"""Generate golden vectors so the CNN RTL can be checked bit-for-bit.

    python vectors.py weights_mid.json --count 20000 --out vectors.txt

Each line is fifty hex values: the 49 pixels of a 7x7 patch in raster order,
followed by the expected 6-bit output for the *centre* pixel. Three 3x3 layers
give a 7x7 receptive field, so a 7x7 patch determines one output exactly, with
no padding involved. Feed them to a cocotb testbench and assert equality. Not
"close enough". Equal. Anything that slips through here is permanent once the
chip is fabricated.

Beyond random patches this emits cases random sampling would reach only by
accident, which is exactly where sign-extension, rounding and saturation bugs
live:

- **Uniform patches at every level.** 0..15 flat. With replicate padding these
  must come out uniform; if padding is wrong they will not.
- **Single-hot patches.** One pixel differing from a flat field, at each of the
  49 positions. This is the closest thing to reading the impulse response off
  the silicon, and it catches transposed or mirrored kernel indexing -- a bug
  a symmetric test pattern will never expose.
- **Maximum swing.** Checkerboards and half-planes at both polarities, which
  drive the accumulator hardest.
- **A second pass under a saturating configuration.** The trained weights are
  gentle: the residual stays around +-15, so the output clip at 0 and 63 is
  barely exercised. Since weights load at runtime, a later reload can reach it,
  and untested silicon is not an option. The stress pass forces both clip paths
  and pushes the accumulator toward its int16 limit.

Confirm the summary reports a nonzero count at both floor and ceiling before
you consider the RTL verified.
"""

import argparse
import json

import numpy as np

import model as M

N = M.RECEPTIVE_FIELD            # 7


def random_patches(count: int, seed: int) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 16, size=(count, N, N), dtype=np.int64)


def structured_patches() -> np.ndarray:
    """Patches that exercise padding, kernel indexing, swing and saturation."""
    cases = []

    # Uniform at every level. Must produce a uniform result under replicate
    # padding; a zero-padding bug shows up here immediately.
    for level in range(16):
        cases.append(np.full((N, N), level, np.int64))

    # Single-hot: one pixel differing from a flat field, at every position.
    # Reads out the impulse response and catches transposed kernel indexing.
    for base, hot in ((0, 15), (15, 0), (7, 15), (7, 0), (8, 9), (8, 7)):
        for pos in range(N * N):
            p = np.full((N, N), base, np.int64)
            p[pos // N, pos % N] = hot
            cases.append(p)

    # Maximum swing: hardest cases for the accumulator and the clips.
    yy, xx = np.mgrid[0:N, 0:N]
    cases.append(((yy + xx) % 2 * 15).astype(np.int64))          # checkerboard
    cases.append((1 - (yy + xx) % 2) * 15)                       # inverted
    for axis in range(2):
        for flip in (0, 1):
            half = np.where((yy if axis else xx) < N // 2, 0, 15)
            cases.append((15 - half if flip else half).astype(np.int64))

    # Single row/column spikes: line-buffer ordering bugs.
    for i in range(N):
        p = np.zeros((N, N), np.int64); p[i, :] = 15; cases.append(p)
        p = np.zeros((N, N), np.int64); p[:, i] = 15; cases.append(p)

    return np.stack(cases)


def stress_net(net: M.Net) -> M.Net:
    """A saturating configuration, to force both output clip paths.

    Weights alternate between the extremes so the accumulator swings hard, and
    the shifts are small so the residual is large enough to drive the output
    past 0 and 63. Still a legal configuration: the chip must handle it.
    """
    layers = []
    for i, layer in enumerate(net.layers):
        w = np.where((np.indices(layer.weight.shape).sum(axis=0) % 2) == 0,
                     M.WEIGHT_MAX, M.WEIGHT_MIN).astype(np.int64)
        b = np.zeros(layer.out_ch, np.int64)
        # Enough shift to keep the accumulator inside int16 at the next layer,
        # but small enough that the final residual saturates the output.
        layers.append(M.Layer(w, b, 4 if i < len(net.layers) - 1 else 1))
    return M.Net(layers)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("weights")
    ap.add_argument("--count", type=int, default=20_000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="vectors.txt")
    ap.add_argument("--no-structured", action="store_true",
                    help="omit the structured edge cases (not recommended)")
    ap.add_argument("--no-stress", action="store_true",
                    help="omit the saturating second pass (not recommended)")
    args = ap.parse_args()

    with open(args.weights) as f:
        blob = json.load(f)
    meta = blob.pop("meta", {})
    net = M.Net.from_dict(blob)

    patches = random_patches(args.count, args.seed)
    if not args.no_structured:
        patches = np.vstack([structured_patches(), patches])

    def emit(p_net, tag):
        rows = [f"# {tag}: channels={p_net.channels} "
                f"shifts={[l.shift for l in p_net.layers]}"]
        outs = []
        # Batch through the whole-image path: forward_patch one at a time is
        # correct but slow, and the selftest already proves they agree.
        for patch in patches:
            y = int(M.forward(patch, p_net)[N // 2, N // 2])
            outs.append(y)
            rows.append(" ".join(f"{v:X}" for v in patch.reshape(-1)) + f" {y:02X}")
        return rows, np.array(outs)

    lines = [f"# {N}x{N} patch in raster order, then expected centre y6 (hex)",
             "# each block is preceded by the config it was generated under"]
    main_rows, outputs = emit(net, "trained")
    lines += main_rows
    if not args.no_stress:
        stress_rows, stress_out = emit(stress_net(net), "stress")
        lines += stress_rows
        outputs = np.concatenate([outputs, stress_out])

    with open(args.out, "w") as f:
        f.write("\n".join(lines) + "\n")

    total = len(patches) * (1 if args.no_stress else 2)
    print(f"wrote {total:,} vectors to {args.out}")
    print(f"output range {outputs.min()}..{outputs.max()}  "
          f"({(outputs == 0).sum()} at floor, {(outputs == M.OUT_MAX).sum()} at ceiling)")
    if (outputs == 0).sum() == 0 or (outputs == M.OUT_MAX).sum() == 0:
        print("warning: a clip path is untested; raise --count or keep the stress pass")


if __name__ == "__main__":
    main()
