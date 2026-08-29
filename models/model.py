"""Bit-exact reference model for the TinyTapeout denoising CNN NPU.

This module is the single source of truth. The RTL, the MCU firmware and the
training script must all agree with what happens here, bit for bit. Nothing
here is approximate and nothing here is floating point.

Network
-------
Three 3x3 convolution layers predicting a *residual* correction, so an
all-zero network is an exact passthrough (see ``selftest.check_identity``,
and load it first on real silicon).

    A0 = x4                                  uint4  0..15, 1 channel
    A1 = requant(conv(A0, W0) + B0, sh0)     uint4  0..15, C1 channels
    A2 = requant(conv(A1, W1) + B1, sh1)     uint4  0..15, C2 channels
    r  = rshift(conv(A2, W2) + B2, sh2)      signed, 1 channel
    y6 = clip(4*x4 + r, 0, 63)               uint6  0..63

Arithmetic
----------
    weights      int4      -8..7      (signed)
    activations  uint4      0..15     (unsigned, ReLU output)
    bias         int, folded into the accumulator
    accumulator  int16     signed, checked for overflow
    requant      arithmetic rounding right shift, then clip

``requantise`` clips to 0..15, and clipping at 0 *is* the ReLU -- they are the
same operation, so the hardware pays for one, not two.

The shift is per layer and a power of two on purpose. A general fixed-point
rescale needs a multiplier in the requantise path; a shift needs wiring. On a
TinyTapeout tile that difference matters more than the accuracy it costs.

Padding is replicate at every layer, matching what the MCU streams to the chip.

Signed weights on an unsigned multiplier
----------------------------------------
``Design+DV/src/cmn/multiplier.sv`` is unsigned. Rather than widen it, store
weights biased as ``u = w + 8`` in 0..15 and use

    sum_i w_i * a_i  ==  sum_i u_i * a_i  -  8 * sum_i a_i

The left term is the unsigned multiplier you already have. The right term is a
sum of the activations shifted left by three -- no multiplier at all.
``conv2d_unsigned`` implements it, and the selftest asserts it is bit-identical
to the signed path. See ``export.py`` for the packing.
"""

from dataclasses import dataclass, field
import numpy as np

WEIGHT_BITS = 4          # int4, -8..7
ACT_BITS = 4             # uint4, 0..15
ACC_BITS = 16            # int16 accumulator in the RTL
OUT_BITS = 6             # final output, 0..63

WEIGHT_MIN = -(1 << (WEIGHT_BITS - 1))          # -8
WEIGHT_MAX = (1 << (WEIGHT_BITS - 1)) - 1       #  7
WEIGHT_ZP = 1 << (WEIGHT_BITS - 1)              #  8, the unsigned-storage offset
ACT_MAX = (1 << ACT_BITS) - 1                   # 15
OUT_MAX = (1 << OUT_BITS) - 1                   # 63
ACC_MIN = -(1 << (ACC_BITS - 1))
ACC_MAX = (1 << (ACC_BITS - 1)) - 1

K = 3                    # kernel edge; 3 layers of 3x3 -> 7x7 receptive field
RECEPTIVE_FIELD = 1 + 3 * (K - 1)


# ---------------------------------------------------------------------------
# Parameters
# ---------------------------------------------------------------------------

@dataclass
class Layer:
    """One quantised 3x3 convolution layer."""

    weight: np.ndarray       # (out_ch, in_ch, 3, 3) int, WEIGHT_MIN..WEIGHT_MAX
    bias: np.ndarray         # (out_ch,) int, folded into the accumulator
    shift: int               # requantise right shift, 0..15

    def __post_init__(self):
        self.weight = np.asarray(self.weight, dtype=np.int64).copy()
        self.bias = np.asarray(self.bias, dtype=np.int64).copy().reshape(-1)
        self.shift = int(self.shift)
        if self.weight.ndim != 4 or self.weight.shape[2:] != (K, K):
            raise ValueError(f"weight must be (out_ch, in_ch, {K}, {K})")
        if self.bias.shape != (self.out_ch,):
            raise ValueError("bias must have one entry per output channel")
        if self.weight.min() < WEIGHT_MIN or self.weight.max() > WEIGHT_MAX:
            raise ValueError(f"weights must be within {WEIGHT_MIN}..{WEIGHT_MAX}")
        if not 0 <= self.shift <= 15:
            raise ValueError("shift must be 0..15")

    @property
    def out_ch(self) -> int:
        return self.weight.shape[0]

    @property
    def in_ch(self) -> int:
        return self.weight.shape[1]

    @property
    def macs_per_pixel(self) -> int:
        return self.out_ch * self.in_ch * K * K

    def as_dict(self) -> dict:
        return {"weight": self.weight.tolist(),
                "bias": self.bias.tolist(),
                "shift": self.shift}

    @classmethod
    def from_dict(cls, d: dict) -> "Layer":
        return cls(np.array(d["weight"]), np.array(d["bias"]), d["shift"])


@dataclass
class Net:
    """The complete trained network: three layers, last one single-channel."""

    layers: list = field(default_factory=list)

    def __post_init__(self):
        if not self.layers:
            raise ValueError("net must have at least one layer")
        if self.layers[0].in_ch != 1:
            raise ValueError("first layer must take a single input channel")
        if self.layers[-1].out_ch != 1:
            raise ValueError("last layer must produce a single residual channel")
        for a, b in zip(self.layers, self.layers[1:]):
            if a.out_ch != b.in_ch:
                raise ValueError(f"channel mismatch: {a.out_ch} -> {b.in_ch}")

    @property
    def channels(self) -> list:
        return [self.layers[0].in_ch] + [l.out_ch for l in self.layers]

    @property
    def macs_per_pixel(self) -> int:
        """Total multiplies for one output pixel, ignoring any reuse."""
        return sum(l.macs_per_pixel for l in self.layers)

    @property
    def num_weights(self) -> int:
        return sum(l.weight.size for l in self.layers)

    def as_dict(self) -> dict:
        return {"layers": [l.as_dict() for l in self.layers],
                "weight_bits": WEIGHT_BITS, "act_bits": ACT_BITS,
                "acc_bits": ACC_BITS}

    @classmethod
    def from_dict(cls, d: dict) -> "Net":
        return cls([Layer.from_dict(x) for x in d["layers"]])

    @classmethod
    def zeros(cls, channels=(1, 8, 8, 1), shifts=(4, 4, 4)) -> "Net":
        """An all-zero net. Exact passthrough; the chip bring-up configuration."""
        return cls([Layer(np.zeros((channels[i + 1], channels[i], K, K), np.int64),
                          np.zeros(channels[i + 1], np.int64), shifts[i])
                    for i in range(len(shifts))])


# ---------------------------------------------------------------------------
# Datapath primitives
# ---------------------------------------------------------------------------

def _pad_replicate(a: np.ndarray) -> np.ndarray:
    """Replicate-pad the spatial dims of a (C, H, W) array by one pixel."""
    return np.pad(a, ((0, 0), (1, 1), (1, 1)), mode="edge")


def conv2d(a: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """Signed 3x3 convolution, replicate padding. Exact integer arithmetic.

    Args:
        a:      (in_ch, H, W) int64 activations.
        weight: (out_ch, in_ch, 3, 3) int64 signed weights.
        bias:   (out_ch,) int64.

    Returns:
        (out_ch, H, W) int64 accumulators, before any shift or clip.
    """
    a = np.asarray(a, dtype=np.int64)
    _, h, w = a.shape
    padded = _pad_replicate(a)
    acc = np.broadcast_to(np.asarray(bias, np.int64).reshape(-1, 1, 1),
                          (len(bias), h, w)).copy()
    for ky in range(K):
        for kx in range(K):
            tile = padded[:, ky:ky + h, kx:kx + w]              # (in_ch, H, W)
            acc += np.tensordot(weight[:, :, ky, kx], tile, axes=([1], [0]))
    return acc


def conv2d_unsigned(a: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    """The same convolution, computed the way the unsigned RTL multiplier does.

    Weights are stored biased as ``u = w + 8`` so every multiply operand is in
    0..15, then the offset is removed in one lump:

        sum_i w_i * a_i  =  sum_i u_i * a_i  -  8 * sum_i a_i

    Bit-identical to :func:`conv2d`; the selftest asserts it. Kept as a
    separate function so the RTL has something to be checked against directly.
    """
    a = np.asarray(a, dtype=np.int64)
    _, h, w = a.shape
    padded = _pad_replicate(a)
    biased = np.asarray(weight, np.int64) + WEIGHT_ZP        # 0..15, unsigned
    out_ch = biased.shape[0]

    prod = np.zeros((out_ch, h, w), np.int64)                # unsigned multiplies
    act_sum = np.zeros((h, w), np.int64)                     # correction term
    for ky in range(K):
        for kx in range(K):
            tile = padded[:, ky:ky + h, kx:kx + w]
            prod += np.tensordot(biased[:, :, ky, kx], tile, axes=([1], [0]))
            act_sum += tile.sum(axis=0)
    correction = act_sum * WEIGHT_ZP                         # i.e. act_sum << 3
    return prod - correction[None, :, :] + np.asarray(bias, np.int64).reshape(-1, 1, 1)


def rshift_round(acc: np.ndarray, shift: int) -> np.ndarray:
    """Arithmetic right shift with round-half-up. Matches Verilog ``>>>``.

    A shift of zero is a pass-through, with no rounding term to add.
    """
    if shift == 0:
        return np.asarray(acc, np.int64)
    return (np.asarray(acc, np.int64) + (1 << (shift - 1))) >> shift


def requantise(acc: np.ndarray, shift: int) -> np.ndarray:
    """Rounding shift, then clip to the activation range.

    Clipping at zero is the ReLU. The hardware does not have a separate one.
    """
    return np.clip(rshift_round(acc, shift), 0, ACT_MAX)


def check_acc_range(acc: np.ndarray, where: str) -> None:
    """Fail loudly if the accumulator would not fit the RTL's width."""
    lo, hi = int(acc.min()), int(acc.max())
    if lo < ACC_MIN or hi > ACC_MAX:
        raise OverflowError(
            f"{where}: accumulator range {lo}..{hi} does not fit "
            f"int{ACC_BITS} ({ACC_MIN}..{ACC_MAX})")


# ---------------------------------------------------------------------------
# Forward pass
# ---------------------------------------------------------------------------

def forward(x4: np.ndarray, net: Net, unsigned: bool = False,
            trace: dict = None) -> np.ndarray:
    """Filter a whole 2-D image. Input 4-bit, output 6-bit, same shape.

    Args:
        x4:       (H, W) array of 4-bit pixels, 0..15.
        net:      the trained network.
        unsigned: use the biased-weight decomposition instead of signed
                  multiplies. Must give identical results.
        trace:    optional dict, filled with per-layer accumulator ranges.
                  This is how the RTL's accumulator width gets justified.
    """
    x4 = np.asarray(x4, dtype=np.int64)
    if x4.min() < 0 or x4.max() > ACT_MAX:
        raise ValueError(f"input pixels must be 0..{ACT_MAX}")
    conv = conv2d_unsigned if unsigned else conv2d

    a = x4[None, :, :]                                   # (1, H, W)
    for i, layer in enumerate(net.layers):
        acc = conv(a, layer.weight, layer.bias)
        check_acc_range(acc, f"layer {i}")
        if trace is not None:
            trace[f"layer{i}_acc"] = (int(acc.min()), int(acc.max()))
        a = (rshift_round(acc, layer.shift) if i == len(net.layers) - 1
             else requantise(acc, layer.shift))

    residual = a[0]                                      # signed correction
    if trace is not None:
        trace["residual"] = (int(residual.min()), int(residual.max()))
    return np.clip(4 * x4 + residual, 0, OUT_MAX)


def forward_patch(patch: np.ndarray, net: Net, unsigned: bool = False) -> int:
    """Filter one 7x7 patch and return the single centre output pixel.

    Three 3x3 layers give a 7x7 receptive field, so this is the smallest input
    that determines an output exactly. Used to generate golden vectors: the
    testbench drives 49 pixels and checks one, with no padding involved.
    """
    patch = np.asarray(patch, dtype=np.int64)
    n = RECEPTIVE_FIELD
    if patch.shape != (n, n):
        raise ValueError(f"patch must be {n}x{n}")
    # Interior pixels never touch the replicate padding, so filtering the whole
    # patch and taking the centre is exactly the streamed result.
    return int(forward(patch, net, unsigned)[n // 2, n // 2])


def psnr(pred: np.ndarray, target: np.ndarray) -> float:
    """PSNR in dB on the 6-bit scale (peak 63)."""
    mse = float(np.mean((np.asarray(pred, float) - np.asarray(target, float)) ** 2))
    return 10.0 * np.log10(float(OUT_MAX) ** 2 / max(mse, 1e-12))
