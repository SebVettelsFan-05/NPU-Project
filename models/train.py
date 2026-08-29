"""Quantisation-aware training for the denoising CNN NPU.

    python train.py --noise mid --out weights_mid.json

Why quantisation-aware and not train-then-quantise
--------------------------------------------------
Weights are int4. Sixteen levels, no per-channel scale factor, and the
requantise is a bare power-of-two shift. Post-training quantisation at that
width does not survive. So the integer datapath is simulated in the forward
pass and the gradients are pushed through it with straight-through estimators.

Everything lives in integer units directly. There is no float weight scale to
fold anywhere: the per-layer shift *is* the scale, and it is trained too.

    w_int = clamp(round(w_raw), -8, 7)          STE on the round
    s     = clamp(round(s_raw),  0, 15)         STE, the requantise shift
    acc   = conv(a, w_int) + round(b_raw)
    a_out = clamp(round(acc / 2^s), 0, 15)      clamp at 0 is the ReLU

The last layer skips the clamp and its output is the signed residual added to
``4 * x``. That residual formulation matters: at initialisation the weights are
near zero, so the network starts as an exact passthrough and training only ever
has to learn the correction. Starting from a blur and unlearning it is much
worse.

After training, ``export_net`` snaps everything to real integers and hands back
a ``model.Net``. The reported PSNR is always measured with the bit-exact
numpy model, never with the torch surrogate, so the headline number is the
number the silicon will produce.
"""

import argparse
import json

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

import model as M
from data import (COMPAND_MODES, NOISE_PRESETS, compand, noise_sigma_lsb, sense,
                  synthetic_images, load_images, split_images)


# ---------------------------------------------------------------------------
# Straight-through estimators
# ---------------------------------------------------------------------------

def round_ste(x: torch.Tensor) -> torch.Tensor:
    """round(x) forwards, identity backwards."""
    return x + (torch.round(x) - x).detach()


def clamp_ste(x: torch.Tensor, lo: float, hi: float) -> torch.Tensor:
    """Clamp forwards, identity backwards.

    Used only for the *shift*, where a hard clamp would strand the parameter
    permanently once it drifted out of range. Activations use a real clamp on
    purpose -- saturation is a genuine part of the datapath and the gradient
    should know about it.
    """
    return x + (torch.clamp(x, lo, hi) - x).detach()


# ---------------------------------------------------------------------------
# The quantised network
# ---------------------------------------------------------------------------

class QuantConv(nn.Module):
    """One 3x3 convolution with int4 weights and a learned power-of-two shift."""

    def __init__(self, in_ch, out_ch, shift_init=4.0, relu=True):
        super().__init__()
        # Weights live in integer units. A small spread keeps the initial
        # residual near zero without collapsing every weight onto 0.
        self.w_raw = nn.Parameter(torch.randn(out_ch, in_ch, M.K, M.K) * 0.8)
        self.b_raw = nn.Parameter(torch.zeros(out_ch))
        self.s_raw = nn.Parameter(torch.tensor(float(shift_init)))
        self.relu = relu

    def quant_weight(self) -> torch.Tensor:
        return clamp_ste(round_ste(self.w_raw), M.WEIGHT_MIN, M.WEIGHT_MAX)

    def shift(self) -> torch.Tensor:
        return clamp_ste(round_ste(self.s_raw), 0.0, 15.0)

    def forward(self, a: torch.Tensor) -> torch.Tensor:
        # Replicate padding, matching model and the MCU stream.
        a = F.pad(a, (1, 1, 1, 1), mode="replicate")
        acc = F.conv2d(a, self.quant_weight(), round_ste(self.b_raw))
        scaled = round_ste(acc * torch.pow(2.0, -self.shift()))
        if not self.relu:
            return scaled                      # signed residual, no clamp
        return torch.clamp(scaled, 0.0, float(M.ACT_MAX))


class QuantNet(nn.Module):
    """Three quantised conv layers predicting a residual on the 6-bit scale."""

    def __init__(self, channels=(1, 8, 8, 1), shift_init=(4.0, 4.0, 4.0)):
        super().__init__()
        n = len(channels) - 1
        self.convs = nn.ModuleList([
            QuantConv(channels[i], channels[i + 1], shift_init[i], relu=(i < n - 1))
            for i in range(n)])

    def forward(self, x4: torch.Tensor) -> torch.Tensor:
        a = x4
        for conv in self.convs:
            a = conv(a)
        return torch.clamp(4.0 * x4 + a, 0.0, float(M.OUT_MAX))

    def export_net(self) -> M.Net:
        """Snap to true integers and return the bit-exact numpy model."""
        layers = []
        for conv in self.convs:
            w = torch.clamp(torch.round(conv.w_raw), M.WEIGHT_MIN, M.WEIGHT_MAX)
            layers.append(M.Layer(w.detach().numpy().astype(np.int64),
                                  torch.round(conv.b_raw).detach().numpy().astype(np.int64),
                                  int(torch.clamp(torch.round(conv.s_raw), 0, 15).item())))
        return M.Net(layers)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def build_pairs(clean_images, shot, read, seed, compand_mode="none"):
    """Noisy 4-bit inputs and clean 6-bit targets, as (N, 1, H, W) tensors.

    The target is the clean image **in the same coded domain as the input**.
    The chip consumes companded 4-bit codes and emits companded 6-bit ones, so
    asking it to output linear light would be asking it to undo the companding
    as well as denoise.
    """
    rng = np.random.default_rng(seed)
    noisy = np.stack([sense(c, shot, read, rng, compand_mode)
                      for c in clean_images])
    target = np.round(compand(np.asarray(clean_images), compand_mode)
                      * float(M.OUT_MAX))
    return (torch.tensor(noisy, dtype=torch.float32).unsqueeze(1),
            torch.tensor(target, dtype=torch.float32).unsqueeze(1))


# ---------------------------------------------------------------------------
# Baselines, so the headline number means something
# ---------------------------------------------------------------------------

def baseline_unfiltered(x4, target) -> float:
    return M.psnr(4 * x4.numpy(), target.numpy())


def baseline_box(x4, target) -> float:
    """Plain 3x3 average. Removes noise and detail at about the same rate."""
    a = F.pad(x4, (1, 1, 1, 1), mode="replicate")
    box = F.avg_pool2d(a, 3, stride=1) * 4.0
    return M.psnr(np.clip(np.round(box.numpy()), 0, M.OUT_MAX), target.numpy())


def baseline_linear(train_x, train_y, test_x, test_y) -> float:
    """The best 3x3 linear filter that exists, fitted by least squares.

    One unconstrained full-precision conv layer. Any linear 3x3 filter, however
    cleverly weighted, is bounded by this number.
    """
    def design(x):
        a = F.pad(x, (1, 1, 1, 1), mode="replicate")
        cols = F.unfold(a, 3).transpose(1, 2).reshape(-1, 9).numpy() * 4.0
        return np.hstack([cols, np.ones((cols.shape[0], 1))])

    coef, *_ = np.linalg.lstsq(design(train_x), train_y.reshape(-1).numpy(), rcond=None)
    pred = np.clip(np.round(design(test_x) @ coef), 0, M.OUT_MAX)
    return M.psnr(pred, test_y.reshape(-1).numpy())


def evaluate_exact(net: M.Net, x4, target):
    """PSNR from the bit-exact numpy model. This is the number that ships."""
    imgs = x4.squeeze(1).numpy().astype(np.int64)
    trace = {}
    pred = np.stack([M.forward(im, net, trace=trace) for im in imgs])
    return M.psnr(pred, target.squeeze(1).numpy()), trace


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train(model, train_x, train_y, epochs, batch, lr, seed, verbose=True):
    opt = torch.optim.Adam(model.parameters(), lr=lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, epochs)
    g = torch.Generator().manual_seed(seed)
    n = train_x.shape[0]

    for epoch in range(epochs):
        perm = torch.randperm(n, generator=g)
        total = 0.0
        for i in range(0, n, batch):
            idx = perm[i:i + batch]
            loss = F.mse_loss(model(train_x[idx]), train_y[idx])
            opt.zero_grad()
            loss.backward()
            opt.step()
            total += float(loss.detach()) * idx.numel()
        sched.step()
        if verbose and (epoch % 10 == 0 or epoch == epochs - 1):
            mse = total / n
            shifts = [int(c.shift().item()) for c in model.convs]
            print(f"  epoch {epoch:4d}  train PSNR {10 * np.log10(63.0 ** 2 / max(mse, 1e-9)):5.2f} dB"
                  f"   shifts {shifts}")
    return model


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--noise", choices=sorted(NOISE_PRESETS), default="mid")
    ap.add_argument("--shot", type=float, help="override shot noise coefficient")
    ap.add_argument("--read", type=float, help="override read noise coefficient")
    ap.add_argument("--channels", default="1,8,8,1",
                    help="channels per layer, comma separated (default 1,8,8,1)")
    ap.add_argument("--epochs", type=int, default=150)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--train-images", type=int, default=60)
    ap.add_argument("--test-images", type=int, default=20)
    ap.add_argument("--size", type=int, default=64, help="image edge in pixels")
    ap.add_argument("--images", help="directory of real photos to use instead "
                                     "(searched recursively)")
    ap.add_argument("--downscale", type=int, default=2,
                    help="box-downsample photos by this factor before cropping, "
                         "which averages away the noise already in them (default 2)")
    ap.add_argument("--linearise", action="store_true",
                    help="undo the sRGB gamma so the noise model is applied in "
                         "linear light, where it is physically meaningful")
    ap.add_argument("--compand", choices=COMPAND_MODES, default=None,
                    help="transfer curve applied after the noise and before the "
                         "4-bit quantisation. Defaults to 'srgb' when "
                         "--linearise is set and 'none' otherwise. Quantising "
                         "linear light straight to 4 bits wastes most of the 16 "
                         "codes, so do not turn this off while linearising")
    ap.add_argument("--holdout", type=float, default=0.25,
                    help="fraction of photos reserved for the test set (default 0.25)")
    ap.add_argument("--image-pattern",
                    help="case-insensitive filename glob, e.g. '*GT_SRGB*'. "
                         "Denoising datasets keep clean and noisy shots in the "
                         "same folder -- filter, or you train on the noisy ones")
    ap.add_argument("--restarts", type=int, default=3,
                    help="independent inits; the best exact-integer result wins")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="weights.json")
    args = ap.parse_args()

    channels = tuple(int(c) for c in args.channels.split(","))
    if channels[0] != 1 or channels[-1] != 1:
        raise SystemExit("channels must start and end at 1")

    preset = NOISE_PRESETS[args.noise]
    shot = args.shot if args.shot is not None else preset["shot"]
    read = args.read if args.read is not None else preset["read"]
    # Linearised data is in linear light, so it must be companded before the
    # 4-bit quantisation or nearly every pixel lands in the bottom two codes.
    compand_mode = args.compand if args.compand else ("srgb" if args.linearise
                                                      else "none")

    if args.images:
        # Split by photograph, not by crop. Cropping one photo into both sets
        # leaks lighting, focus and content, and flatters the test PSNR.
        train_paths, test_paths = split_images(args.images, args.holdout,
                                               args.seed, args.image_pattern)
        print(f"photos: {len(train_paths)} train / {len(test_paths)} held out"
              f"   downscale /{args.downscale}"
              f"{'   sRGB-linearised' if args.linearise else ''}")
        train_clean = load_images(train_paths, args.train_images, args.size,
                                  args.seed, args.linearise, args.downscale)
        test_clean = load_images(test_paths, args.test_images, args.size,
                                 args.seed + 1, args.linearise, args.downscale)
    else:
        train_clean = synthetic_images(args.train_images, args.size, args.seed)
        test_clean = synthetic_images(args.test_images, args.size, args.seed + 1000)

    train_x, train_y = build_pairs(train_clean, shot, read, args.seed + 100,
                                   compand_mode)
    test_x, test_y = build_pairs(test_clean, shot, read, args.seed + 900,
                                 compand_mode)

    print(f"noise '{args.noise}': shot={shot:.4f} read={read:.5f}  "
          f"~{noise_sigma_lsb(shot, read):.1f} LSB at mid grey")
    codes = len(np.unique(train_x.numpy().astype(int)))
    print(f"compand '{compand_mode}': {codes}/16 four-bit codes used by the "
          f"training set")
    print(f"train {train_x.numel():,} px   test {test_x.numel():,} px")
    print(f"channels {list(channels)}   int{M.WEIGHT_BITS} weights   "
          f"uint{M.ACT_BITS} activations   int{M.ACC_BITS} accumulator\n")

    best = None
    for r in range(args.restarts):
        print(f"restart {r + 1}/{args.restarts}:")
        torch.manual_seed(args.seed + 31 * r)
        model = QuantNet(channels)
        train(model, train_x, train_y, args.epochs, args.batch, args.lr, args.seed + r)
        net = model.export_net()
        db, trace = evaluate_exact(net, test_x, test_y)
        print(f"  exact-integer test PSNR {db:5.2f} dB\n")
        if best is None or db > best[0]:
            best = (db, net, trace)

    db, net, trace = best

    print("results on held-out test set")
    print(f"  unfiltered input        {baseline_unfiltered(test_x, test_y):5.2f} dB")
    print(f"  3x3 box blur            {baseline_box(test_x, test_y):5.2f} dB")
    print(f"  best linear 3x3         "
          f"{baseline_linear(train_x, train_y, test_x, test_y):5.2f} dB")
    print(f"  this CNN                {db:5.2f} dB")

    print(f"\nnetwork: channels {net.channels}  "
          f"{net.num_weights} weights  {net.macs_per_pixel} MACs/pixel")
    print(f"  shifts        {[l.shift for l in net.layers]}")
    print("  accumulator ranges observed on the test set:")
    for k, v in trace.items():
        print(f"    {k:14s} {v[0]:7d} .. {v[1]:6d}")
    print(f"  int{M.ACC_BITS} headroom: {M.ACC_MIN} .. {M.ACC_MAX}")

    meta = {"noise": args.noise, "shot": shot, "read": read,
            "compand": compand_mode, "linearise": bool(args.linearise),
            "sigma_lsb": round(noise_sigma_lsb(shot, read), 2),
            "test_psnr_db": round(db, 2),
            "channels": list(net.channels),
            "macs_per_pixel": net.macs_per_pixel,
            "acc_range": {k: list(v) for k, v in trace.items()}}
    with open(args.out, "w") as f:
        json.dump({**net.as_dict(), "meta": meta}, f, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
