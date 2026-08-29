"""Run a trained network on a real image and look at the result.

    python demo.py weights_high.json --image photo.png --noise high --out demo.png

Produces a side-by-side panel -- clean, noisy input, box blur, CNN output --
plus a printed PSNR table, so you can confirm the filter is actually denoising
rather than just blurring or passing through.

This is the *qualitative* check. ``selftest.py`` proves the datapath is
bit-exact and ``train.py`` reports the numbers; this is for looking at it.

Only needs numpy and Pillow. ``model.py`` has no torch dependency, so this runs
anywhere the RTL reference runs.

What you are looking at
-----------------------
The chip sees **4-bit** pixels and emits **6-bit** ones. So the "noisy input"
tile is genuinely 16 grey levels -- it is supposed to look coarse. Every tile is
shown on the 6-bit output scale so they are directly comparable.

By default the input image is treated as the *clean* ground truth and the sensor
noise is simulated on top, exactly as in training. That is the only way to get a
meaningful PSNR. Use ``--already-noisy`` for a real noisy capture, where there
is no ground truth and you only get the picture.

Read the box blur column. If the CNN does not clearly beat it, something is
wrong -- either the training or the image you picked.
"""

import argparse
import json

import numpy as np

import model as M
from data import (COMPAND_MODES, NOISE_PRESETS, compand, noise_sigma_lsb, sense,
                  synthetic_images, _box_downsample, _load_plane)

LABEL_H = 22          # pixels of caption strip above each tile
GAP = 8               # pixels between tiles


def box_blur(x4: np.ndarray) -> np.ndarray:
    """Plain 3x3 average on the 6-bit scale, replicate padded. The thing to beat."""
    p = np.pad(np.asarray(x4, np.float64), 1, mode="edge")
    acc = sum(p[dy:dy + x4.shape[0], dx:dx + x4.shape[1]]
              for dy in range(3) for dx in range(3)) / 9.0
    return np.clip(np.round(acc * 4), 0, M.OUT_MAX)


def to_display(plane6: np.ndarray, scale: int, span=None) -> np.ndarray:
    """6-bit plane to an 8-bit image, nearest-neighbour upscaled.

    Nearest neighbour on purpose: smooth interpolation would hide exactly the
    pixel-level artefacts you are looking for.

    ``span`` is an optional (lo, hi) contrast stretch **for display only**. Dark
    crops -- and everything is dark once you linearise -- are otherwise
    impossible to judge by eye. The same span is applied to every tile so they
    stay comparable, and it never touches the numbers in the PSNR table.
    """
    a = np.asarray(plane6, np.float64)
    if span is None:
        a = a * 255.0 / M.OUT_MAX
    else:
        lo, hi = span
        a = (a - lo) * 255.0 / max(hi - lo, 1e-9)
    img8 = np.clip(np.round(a), 0, 255).astype(np.uint8)
    return np.repeat(np.repeat(img8, scale, axis=0), scale, axis=1)


def build_panel(tiles, scale, span=None):
    """Stitch labelled tiles into one image. tiles is a list of (caption, plane6)."""
    from PIL import Image, ImageDraw

    rendered = [to_display(p, scale, span) for _, p in tiles]
    h, w = rendered[0].shape
    panel = Image.new("L", (len(tiles) * w + (len(tiles) - 1) * GAP, h + LABEL_H), 255)
    draw = ImageDraw.Draw(panel)
    for i, ((caption, _), arr) in enumerate(zip(tiles, rendered)):
        x = i * (w + GAP)
        panel.paste(Image.fromarray(arr), (x, LABEL_H))
        draw.text((x + 2, 6), caption, fill=0)
    return panel


def _busiest_crop(plane, size, grid=12):
    """Pick the crop with the most detail.

    A denoiser is judged on edges and texture, not on blank wall. Scanning a
    coarse grid for the highest-variance window puts the interesting part of the
    frame in the picture instead of leaving it to luck.
    """
    h, w = plane.shape
    ys = np.linspace(0, h - size, grid).astype(int)
    xs = np.linspace(0, w - size, grid).astype(int)
    best, best_v = (0, 0), -1.0
    for y in ys:
        for x in xs:
            v = float(plane[y:y + size, x:x + size].std())
            if v > best_v:
                best, best_v = (int(y), int(x)), v
    return best


def forward_strips(x4, net, strip=384):
    """Run the network over a large image in horizontal strips.

    A full SIDD frame is ~2700x1500 even after downscaling by 2, and the int64
    accumulators for eight channels run to hundreds of megabytes. Strips keep
    the peak bounded.

    Each strip is cut with a ``RECEPTIVE_FIELD // 2`` margin of *real* pixels
    above and below, which is then discarded. Interior strip boundaries
    therefore see their true neighbours rather than replicated edge pixels, so
    the result is identical to running the whole image at once. At the genuine
    top and bottom no margin exists and replicate padding applies, which is what
    the whole-image path does anyway.
    """
    x4 = np.asarray(x4, dtype=np.int64)
    h = x4.shape[0]
    if h <= strip:
        return M.forward(x4, net)

    margin = M.RECEPTIVE_FIELD // 2
    out = np.empty_like(x4)
    for top in range(0, h, strip):
        bot = min(top + strip, h)
        lo, hi = max(0, top - margin), min(h, bot + margin)
        piece = M.forward(x4[lo:hi], net)
        out[top:bot] = piece[top - lo:top - lo + (bot - top)]
    return out


def load_source(args):
    """Return a clean float plane in [0, 1], preprocessed as in training."""
    if args.image:
        plane = _load_plane(args.image, args.linearise)
        plane = _box_downsample(plane, args.downscale)
        if args.full:
            print(f"full image: {plane.shape[1]}x{plane.shape[0]} "
                  f"after downscaling by {args.downscale}")
            return plane
        if min(plane.shape) < args.size:
            raise SystemExit(
                f"image is {plane.shape[1]}x{plane.shape[0]} after downscaling by "
                f"{args.downscale}, smaller than --size {args.size}")
        rng = np.random.default_rng(args.seed)
        if args.at:
            y, x = (int(v) for v in args.at.split(","))
        elif args.auto_crop:
            y, x = _busiest_crop(plane, args.size)
            print("auto-crop: picked the highest-variance region", end="  ")
        else:
            y = int(rng.integers(0, plane.shape[0] - args.size + 1))
            x = int(rng.integers(0, plane.shape[1] - args.size + 1))
        print(f"crop {args.size}x{args.size} at (y={y}, x={x})")
        return plane[y:y + args.size, x:x + args.size]

    print(f"no --image given, using synthetic test image {args.size}x{args.size}")
    return synthetic_images(1, args.size, args.seed)[0]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("weights", help="weights JSON written by train.py")
    ap.add_argument("--image", help="input image; omit for a synthetic test pattern")
    ap.add_argument("--noise", choices=sorted(NOISE_PRESETS), default="mid",
                    help="sensor noise preset to simulate (default: mid)")
    ap.add_argument("--shot", type=float, help="override shot noise coefficient")
    ap.add_argument("--read", type=float, help="override read noise coefficient")
    ap.add_argument("--already-noisy", action="store_true",
                    help="input is a real noisy capture, not clean ground truth: "
                         "skip noise simulation and report no PSNR")
    ap.add_argument("--size", type=int, default=192, help="crop edge (default 192)")
    ap.add_argument("--full", action="store_true",
                    help="process the whole image instead of a crop. Forces "
                         "--scale 1; combine with --separate unless you want a "
                         "very wide four-up panel")
    ap.add_argument("--separate", action="store_true",
                    help="write one file per tile (demo_clean.png, _input, "
                         "_box, _cnn) instead of a single panel. The sane way "
                         "to look at a full frame")
    ap.add_argument("--at", help="crop position as 'y,x'; default is random")
    ap.add_argument("--auto-crop", action="store_true",
                    help="pick the highest-variance region instead of a random "
                         "one, so the panel shows edges and texture rather than "
                         "whatever the seed landed on")
    ap.add_argument("--stretch", action="store_true",
                    help="contrast-stretch the panel for display only. Dark "
                         "crops, and anything linearised, are otherwise "
                         "impossible to judge by eye. Does not affect the PSNRs")
    ap.add_argument("--downscale", type=int, default=2,
                    help="match what you trained with (default 2)")
    ap.add_argument("--linearise", action="store_true",
                    help="match what you trained with")
    ap.add_argument("--compand", choices=COMPAND_MODES, default=None,
                    help="match what you trained with; defaults to 'srgb' when "
                         "--linearise is set, else 'none'")
    ap.add_argument("--scale", type=int, default=3,
                    help="nearest-neighbour zoom for the output panel (default 3)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", default="demo.png")
    args = ap.parse_args()

    with open(args.weights) as f:
        blob = json.load(f)
    meta = blob.pop("meta", {})
    net = M.Net.from_dict(blob)

    preset = NOISE_PRESETS[args.noise]
    shot = args.shot if args.shot is not None else preset["shot"]
    read = args.read if args.read is not None else preset["read"]

    print(f"network: channels {net.channels}  shifts {[l.shift for l in net.layers]}"
          f"  trained on '{meta.get('noise', '?')}' "
          f"({meta.get('test_psnr_db', '?')} dB)")

    if args.full and args.scale != 1:
        print("--full: forcing --scale 1 (a zoomed full frame would be enormous)")
        args.scale = 1

    clean = load_source(args)

    compand_mode = args.compand if args.compand else ("srgb" if args.linearise
                                                      else "none")
    if args.already_noisy:
        # No ground truth. Quantise to what the chip actually sees and stop.
        x4 = np.clip(np.round(compand(clean, compand_mode) * 15.0),
                     0, 15).astype(np.int64)
        target6 = None
        print("input treated as already noisy: no PSNR available")
    else:
        rng = np.random.default_rng(args.seed + 1)
        x4 = sense(clean, shot, read, rng, compand_mode)
        target6 = np.round(compand(clean, compand_mode) * float(M.OUT_MAX))
        print(f"simulated '{args.noise}' noise: shot={shot:.4f} read={read:.5f}  "
              f"~{noise_sigma_lsb(shot, read):.1f} LSB at mid grey")
    trained_with = meta.get("compand")
    if trained_with is not None and trained_with != compand_mode:
        print(f"  warning: these weights were trained with compand="
              f"'{trained_with}' but you are running compand='{compand_mode}'")
    print(f"compand '{compand_mode}': {len(np.unique(x4))}/16 four-bit codes "
          f"present in this crop")

    trace = {}
    if args.full:
        out6 = forward_strips(x4, net)
        # The unsigned cross-check is O(image); on a full frame do it on a
        # representative window rather than twice over millions of pixels.
        probe = x4[:256, :256]
        if not np.array_equal(M.forward(probe, net),
                              M.forward(probe, net, unsigned=True)):
            raise SystemExit("signed and unsigned datapaths disagree -- model is broken")
        M.forward(probe, net, trace=trace)      # accumulator ranges, from the probe
    else:
        out6 = M.forward(x4, net, trace=trace)
        # The unsigned decomposition is what the RTL computes. Free check, so take it.
        if not np.array_equal(out6, M.forward(x4, net, unsigned=True)):
            raise SystemExit("signed and unsigned datapaths disagree -- model is broken")
    box6 = box_blur(x4)
    input6 = 4 * x4

    tiles = []
    if target6 is not None:
        tiles.append(("clean (ground truth)", target6))
    tiles.append((f"noisy input (4-bit)", input6))
    tiles.append(("3x3 box blur", box6))
    tiles.append(("CNN output", out6))

    if target6 is not None:
        print("\n                        PSNR")
        rows = [("noisy input", input6), ("3x3 box blur", box6), ("CNN output", out6)]
        best = max(M.psnr(p, target6) for _, p in rows)
        for name, plane in rows:
            db = M.psnr(plane, target6)
            print(f"  {name:22s} {db:5.2f} dB{'   <-- best' if db == best else ''}")
        gain = M.psnr(out6, target6) - M.psnr(input6, target6)
        print(f"\n  CNN improvement over the raw input: {gain:+.2f} dB")
        if M.psnr(out6, target6) <= M.psnr(box6, target6):
            print("  warning: a plain box blur matched or beat the CNN here. Either "
                  "this crop is too smooth to\n           be a fair test, or the "
                  "weights do not suit this noise level.")

        # Retitle the tiles with their scores now that we have them.
        tiles = [tiles[0]] + [(f"{c}  {M.psnr(p, target6):.2f} dB", p)
                              for c, p in tiles[1:]]

    print("\naccumulator ranges" + (" (from a 256x256 probe window):"
                                    if args.full else " on this image:"))
    for k, v in trace.items():
        print(f"  {k:14s} {v[0]:7d} .. {v[1]:6d}")

    span = None
    if args.stretch:
        ref = target6 if target6 is not None else input6
        lo, hi = np.percentile(ref, [0.5, 99.5])
        span = (float(lo), float(hi))
        print(f"\ndisplay stretched to 6-bit range {lo:.1f}..{hi:.1f} "
              f"(display only, PSNRs above are unaffected)")

    if args.separate:
        from PIL import Image
        stem = args.out.rsplit(".", 1)[0]
        slugs = {"clean (ground truth)": "clean", "noisy input (4-bit)": "input",
                 "3x3 box blur": "box", "CNN output": "cnn"}
        print()
        for caption, plane in tiles:
            # Captions may carry an appended PSNR; match on the leading name.
            slug = next((v for k, v in slugs.items() if caption.startswith(k)),
                        "tile")
            path = f"{stem}_{slug}.png"
            Image.fromarray(to_display(plane, args.scale, span)).save(path)
            print(f"wrote {path}")
    else:
        panel = build_panel(tiles, args.scale, span)
        panel.save(args.out)
        print(f"\nwrote {args.out}  ({panel.width}x{panel.height})")


if __name__ == "__main__":
    main()
