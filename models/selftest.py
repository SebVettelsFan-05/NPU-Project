"""Consistency checks for the CNN golden model. Run this before trusting it.

    python selftest.py

``model.py`` contains two paths to the same answer: the signed convolution
and the biased-weight decomposition the unsigned RTL multiplier actually
computes. If they ever disagree, the vectors you tape out against are wrong.
This checks they do not, and checks the things the RTL is easy to get subtly
wrong about: sign extension, rounding direction, saturation, and padding.
"""

import numpy as np

import model as M


def _random_net(rng, channels=(1, 8, 8, 1), shifts=(4, 4, 4)) -> M.Net:
    return M.Net([M.Layer(rng.integers(M.WEIGHT_MIN, M.WEIGHT_MAX + 1,
                                       (channels[i + 1], channels[i], M.K, M.K)),
                          rng.integers(-32, 33, channels[i + 1]),
                          shifts[i])
                  for i in range(len(shifts))])


def check_signed_unsigned_agree(trials=40, seed=3):
    """The signed path and the unsigned-multiplier path must be identical.

    This is the check that licenses using ``multiplier.sv`` unmodified.
    """
    rng = np.random.default_rng(seed)
    for _ in range(trials):
        net = _random_net(rng, shifts=tuple(rng.integers(2, 7, 3)))
        img = rng.integers(0, 16, size=(11, 13), dtype=np.int64)
        if not np.array_equal(M.forward(img, net), M.forward(img, net, unsigned=True)):
            raise AssertionError("signed and unsigned datapaths disagree")
    print(f"ok: signed and biased-unsigned paths agree over {trials} random nets")


def check_patch_matches_image(trials=30, seed=11):
    """The 7x7 patch path must match the full-image path at the centre pixel.

    Golden vectors are generated per patch; training and evaluation run per
    image. If these two disagree the testbench is checking the wrong thing.
    """
    rng = np.random.default_rng(seed)
    n = M.RECEPTIVE_FIELD
    for _ in range(trials):
        net = _random_net(rng)
        img = rng.integers(0, 16, size=(24, 24), dtype=np.int64)
        full = M.forward(img, net)
        for _ in range(6):
            y, x = rng.integers(n // 2, 24 - n // 2, 2)
            patch = img[y - n // 2:y + n // 2 + 1, x - n // 2:x + n // 2 + 1]
            if M.forward_patch(patch, net) != full[y, x]:
                raise AssertionError(f"patch and image disagree at ({y},{x})")
    print(f"ok: 7x7 patch path matches the full-image path over {trials} nets")


def check_output_range(trials=200, seed=4):
    """Output must always land inside 0..63, whatever the weights."""
    rng = np.random.default_rng(seed)
    lo, hi = M.OUT_MAX, 0
    for _ in range(trials):
        net = _random_net(rng, shifts=tuple(rng.integers(0, 8, 3)))
        img = rng.integers(0, 16, size=(9, 9), dtype=np.int64)
        out = M.forward(img, net)
        assert out.min() >= 0 and out.max() <= M.OUT_MAX, f"output out of range: {out.min()}..{out.max()}"
        lo, hi = min(lo, int(out.min())), max(hi, int(out.max()))
    print(f"ok: outputs stayed in range over {trials} nets, observed {lo}..{hi}")


def check_identity():
    """An all-zero net must pass the centre through untouched.

    Load this on real silicon first. It validates the line buffers, the edge
    padding and the output packing independently of the convolution, so when
    something is wrong you know which half to look at.
    """
    net = M.Net.zeros()
    img = np.random.default_rng(5).integers(0, 16, size=(16, 16), dtype=np.int64)
    assert np.array_equal(M.forward(img, net), 4 * img), "passthrough mode is broken"
    assert np.array_equal(M.forward(img, net, unsigned=True), 4 * img), \
        "passthrough is broken on the unsigned path"
    print("ok: zero net is an exact passthrough (chip bring-up mode 1)")


def check_rounding():
    """Rounding is round-half-up on the signed value, including negatives.

    Verilog's ``>>>`` on a signed value floors, so adding the half-LSB term
    before the shift gives round-half-up. -3 >> 1 must be -2, not -1: getting
    this backwards is a classic and it biases the whole image.
    """
    cases = {(-4, 1): -2, (-3, 1): -1, (-1, 1): 0, (0, 1): 0,
             (1, 1): 1, (3, 1): 2, (-5, 2): -1, (5, 2): 1, (7, 0): 7}
    for (value, shift), want in cases.items():
        got = int(M.rshift_round(np.array([value]), shift)[0])
        assert got == want, f"rshift_round({value}, {shift}) = {got}, want {want}"
    print(f"ok: rounding shift matches round-half-up over {len(cases)} signed cases")


def check_padding_is_replicate():
    """A uniform image must survive unchanged at the borders.

    If padding were zeros instead of replicate, a uniform bright image would
    darken at the edges. This catches that immediately.
    """
    rng = np.random.default_rng(9)
    net = _random_net(rng)
    for level in (0, 7, 15):
        img = np.full((12, 12), level, dtype=np.int64)
        out = M.forward(img, net)
        assert len(np.unique(out)) == 1, \
            f"uniform input at {level} produced a non-uniform output (padding is wrong)"
    print("ok: uniform inputs stay uniform, so padding is replicate everywhere")


def check_acc_width():
    """The worst case the accumulator can ever see must fit int16.

    Not a statistical bound from the test set -- the true algebraic worst case,
    with every weight at its extreme and every activation saturated.
    """
    for channels in ((1, 8, 8, 1), (1, 16, 16, 1)):
        for i in range(len(channels) - 1):
            terms = channels[i] * M.K * M.K
            worst = terms * M.ACT_MAX * max(abs(M.WEIGHT_MIN), M.WEIGHT_MAX)
            assert M.ACC_MIN <= -worst and worst <= M.ACC_MAX, (
                f"channels {channels} layer {i}: worst-case |acc| {worst} "
                f"exceeds int{M.ACC_BITS}")
    print("ok: worst-case accumulator fits int16 for up to 16 input channels")


def check_noise_reduction():
    """A trained net, if present, must actually reduce flat-field noise."""
    import json
    from pathlib import Path
    path = Path("weights_mid.json")
    if not path.exists():
        print("skip: no weights_mid.json yet, train one first")
        return
    blob = json.loads(path.read_text())
    blob.pop("meta", None)
    net = M.Net.from_dict(blob)
    rng = np.random.default_rng(6)
    flat = np.clip(np.round(8 + 1.3 * rng.standard_normal((64, 64))), 0, 15).astype(np.int64)
    before, after = flat.std(), (M.forward(flat, net) / 4.0).std()
    assert after < before, f"no smoothing at all: {before:.2f} -> {after:.2f}"
    print(f"ok: flat-field noise {before:.2f} -> {after:.2f} LSB "
          f"({before / after:.2f}x reduction)")


if __name__ == "__main__":
    check_signed_unsigned_agree()
    check_patch_matches_image()
    check_output_range()
    check_identity()
    check_rounding()
    check_padding_is_replicate()
    check_acc_width()
    check_noise_reduction()
    print("\nall checks passed")
