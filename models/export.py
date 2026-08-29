"""Turn trained CNN weights into things the RTL and the firmware can consume.

    python export.py weights_mid.json --verilog weights.vh --header weights.h

This module is the *only* definition of the config bit layout. Both the Verilog
and the C header are generated from it, so firmware and RTL cannot drift apart.
Ordering drift is the most common first-power-up failure and it is entirely
avoidable.

Config bit layout, LSB first, layers in order
---------------------------------------------
For each layer, in order:

    weights, in [out_ch][in_ch][ky][kx] order, 4 bits each, *biased*
    biases,  in [out_ch] order, 8 bits each, two's complement
    shift,   4 bits

Weights are transmitted biased as ``u = w + 8`` so every stored value is an
unsigned nibble in 0..15. That is not a packing convenience -- it is what lets
``Design+DV/src/cmn/multiplier.sv`` stay unsigned:

    sum_i w_i * a_i  =  sum_i u_i * a_i  -  8 * sum_i a_i

The correction term is a sum of activations shifted left by three. See
``model.conv2d_unsigned``, which the selftest asserts is bit-identical to
the signed path.

The layout carries no header. The architecture (layer count, channel counts) is
compile-time in the RTL and must match the JSON; ``config_bits`` is given the
net it is packing and the RTL is generated from that same net, so the two
cannot disagree.

Stream word layout, 16 bits, as driven by one PIO ``out pins, 16``
-------------------------------------------------------------------
    bits 11..0    12-bit payload word
    bits 15..12   control nibble

Control nibble bits: 0 = cfg_en, 1 = valid_in, 2 = shift_en, 3 = reserved.

If the demo board does not place ui_in[7:0] and uio[7:0] on sixteen consecutive
GPIOs in that order, the firmware must permute before writing to the PIO FIFO.
Check that early.
"""

import argparse
import json

import numpy as np

import model as M

BIAS_BITS = 8            # two's complement, -128..127
SHIFT_BITS = 4           # 0..15
WORD_BITS = 12           # payload width of one streamed config word

CTRL_CFG = 0x1           # cfg_en
CTRL_PIXEL = 0x6         # valid_in | shift_en

BIAS_MIN = -(1 << (BIAS_BITS - 1))
BIAS_MAX = (1 << (BIAS_BITS - 1)) - 1


def weight_order(layer: M.Layer):
    """Yield (oc, ic, ky, kx) in canonical transmission order.

    This generator is the single definition of weight ordering. Anything that
    needs to iterate weights -- packing, unpacking, the Verilog array, the C
    array -- goes through here so they cannot disagree.
    """
    for oc in range(layer.out_ch):
        for ic in range(layer.in_ch):
            for ky in range(M.K):
                for kx in range(M.K):
                    yield oc, ic, ky, kx


def config_bits(net: M.Net) -> tuple:
    """Pack the whole network into one integer payload.

    Returns:
        (value, width) where value is the payload as a Python int, LSB first,
        and width is the number of significant bits.
    """
    value = 0
    pos = 0
    for layer in net.layers:
        for oc, ic, ky, kx in weight_order(layer):
            u = int(layer.weight[oc, ic, ky, kx]) + M.WEIGHT_ZP     # 0..15
            value |= u << pos
            pos += M.WEIGHT_BITS
        for oc in range(layer.out_ch):
            b = int(layer.bias[oc])
            if not BIAS_MIN <= b <= BIAS_MAX:
                raise ValueError(f"bias {b} does not fit int{BIAS_BITS}")
            value |= (b & ((1 << BIAS_BITS) - 1)) << pos            # two's complement
            pos += BIAS_BITS
        value |= (layer.shift & ((1 << SHIFT_BITS) - 1)) << pos
        pos += SHIFT_BITS
    return value, pos


def config_words(net: M.Net) -> list:
    """Split the payload into 12-bit words, LSB first."""
    value, width = config_bits(net)
    count = (width + WORD_BITS - 1) // WORD_BITS
    return [(value >> (WORD_BITS * k)) & ((1 << WORD_BITS) - 1) for k in range(count)]


def stream_words(net: M.Net) -> list:
    """The full 16-bit words to push, control nibble included."""
    return [(CTRL_CFG << 12) | w for w in config_words(net)]


def unpack(value: int, net: M.Net) -> M.Net:
    """Unpack a payload back into a Net, using ``net`` only for its shape.

    Exists so ``roundtrip_check`` can verify the layout by actually inverting
    it rather than by re-reading the packing code.
    """
    pos = 0
    layers = []
    for layer in net.layers:
        w = np.zeros_like(layer.weight)
        for oc, ic, ky, kx in weight_order(layer):
            u = (value >> pos) & ((1 << M.WEIGHT_BITS) - 1)
            w[oc, ic, ky, kx] = u - M.WEIGHT_ZP
            pos += M.WEIGHT_BITS
        b = np.zeros_like(layer.bias)
        for oc in range(layer.out_ch):
            raw = (value >> pos) & ((1 << BIAS_BITS) - 1)
            b[oc] = raw - (1 << BIAS_BITS) if raw >> (BIAS_BITS - 1) else raw
            pos += BIAS_BITS
        shift = (value >> pos) & ((1 << SHIFT_BITS) - 1)
        pos += SHIFT_BITS
        layers.append(M.Layer(w, b, shift))
    return M.Net(layers)


def roundtrip_check(net: M.Net) -> None:
    """Unpack what we packed and confirm it matches. Cheap insurance."""
    value, _ = config_bits(net)
    got = unpack(value, net)
    for i, (a, b) in enumerate(zip(net.layers, got.layers)):
        assert np.array_equal(a.weight, b.weight), f"layer {i} weights packed wrong"
        assert np.array_equal(a.bias, b.bias), f"layer {i} biases packed wrong"
        assert a.shift == b.shift, f"layer {i} shift packed wrong"


# ---------------------------------------------------------------------------
# Generated files
# ---------------------------------------------------------------------------

def to_verilog(net: M.Net) -> str:
    value, width = config_bits(net)
    words = config_words(net)
    chans = net.channels

    blocks = []
    for i, layer in enumerate(net.layers):
        flat = [int(layer.weight[oc, ic, ky, kx]) + M.WEIGHT_ZP
                for oc, ic, ky, kx in weight_order(layer)]
        rows = ", ".join(f"4'd{v}" for v in flat)
        wrapped = "\n".join("    " + rows[j:j + 88] for j in range(0, len(rows), 88))
        biases = ", ".join(f"-8'sd{-int(v)}" if int(v) < 0 else f"8'sd{int(v)}"
                           for v in layer.bias)
        blocks.append(
            f"// Layer {i}: {layer.in_ch} -> {layer.out_ch} channels, "
            f"{layer.macs_per_pixel} MACs/pixel, shift {layer.shift}\n"
            f"localparam integer L{i}_IN = {layer.in_ch};\n"
            f"localparam integer L{i}_OUT = {layer.out_ch};\n"
            f"localparam [3:0] L{i}_SHIFT = 4'd{layer.shift};\n"
            f"// Weights are BIASED: stored u = w + {M.WEIGHT_ZP}, so 0..15 unsigned.\n"
            f"// Recover the signed weight as (u - {M.WEIGHT_ZP}), or use the\n"
            f"// decomposition sum(w*a) = sum(u*a) - {M.WEIGHT_ZP}*sum(a).\n"
            f"localparam [3:0] L{i}_W [0:{layer.weight.size - 1}] = '{{\n{wrapped}\n}};\n"
            f"localparam signed [{BIAS_BITS - 1}:0] L{i}_B [0:{layer.out_ch - 1}] = "
            f"'{{{biases}}};\n")

    word_rows = ", ".join(f"12'h{w:03X}" for w in words)
    word_wrapped = "\n".join("    " + word_rows[j:j + 88]
                             for j in range(0, len(word_rows), 88))

    return f"""// Generated by export.py. Do not edit by hand.
// Regenerate with: python export.py <weights.json> --verilog weights.vh

`ifndef CNN_WEIGHTS_VH
`define CNN_WEIGHTS_VH

localparam integer WEIGHT_BITS = {M.WEIGHT_BITS};   // int4, stored biased by {M.WEIGHT_ZP}
localparam integer ACT_BITS    = {M.ACT_BITS};   // uint4, 0..{M.ACT_MAX}
localparam integer ACC_BITS    = {M.ACC_BITS};  // signed accumulator
localparam integer OUT_BITS    = {M.OUT_BITS};   // 0..{M.OUT_MAX}
localparam integer BIAS_BITS   = {BIAS_BITS};
localparam integer KERNEL      = {M.K};
localparam integer NUM_LAYERS  = {len(net.layers)};
localparam integer MAX_CH      = {max(chans)};
localparam integer RECEPTIVE   = {M.RECEPTIVE_FIELD};  // 7x7, for the line buffers

{"".join(blocks)}
// The whole payload as {len(words)} x {WORD_BITS}-bit config words, LSB first.
// {width} significant bits.
localparam integer CFG_WORDS = {len(words)};
localparam [11:0] DEF_CFG_WORDS [0:{len(words) - 1}] = '{{
{word_wrapped}
}};

`endif
"""


def to_c_header(net: M.Net, meta: dict) -> str:
    words = stream_words(net)
    value, width = config_bits(net)
    rows = ", ".join(f"0x{w:04X}" for w in words)
    wrapped = "\n".join("    " + rows[j:j + 84] for j in range(0, len(rows), 84))
    chans = ", ".join(str(c) for c in net.channels)

    return f"""/* Generated by export.py. Do not edit by hand.
 * Regenerate with: python export.py <weights.json> --header weights.h
 *
 * Noise preset: {meta.get("noise", "unknown")}    held-out test PSNR: {meta.get("test_psnr_db", "n/a")} dB
 * Channels: {net.channels}    {net.macs_per_pixel} MACs/pixel
 */
#ifndef CNN_WEIGHTS_H
#define CNN_WEIGHTS_H

#include <stdint.h>

#define CNN_CTRL_CFG    0x1u   /* cfg_en                        */
#define CNN_CTRL_PIXEL  0x6u   /* valid_in | shift_en           */

#define CNN_NUM_LAYERS  {len(net.layers)}
#define CNN_WEIGHT_ZP   {M.WEIGHT_ZP}u  /* weights are stored as w + {M.WEIGHT_ZP} */
#define CNN_CFG_BITS    {width}

static const uint8_t cnn_channels[CNN_NUM_LAYERS + 1] = {{{chans}}};

/* Push these words to the PIO FIFO before streaming any pixels. */
#define CNN_CONFIG_WORD_COUNT {len(words)}
static const uint16_t cnn_config_words[CNN_CONFIG_WORD_COUNT] = {{
{wrapped}
}};

/* Build one 16-bit stream word from a pixel payload. */
static inline uint16_t cnn_pixel_word(uint16_t payload)
{{
    return (uint16_t)((CNN_CTRL_PIXEL << 12) | (payload & 0x0FFFu));
}}

#endif /* CNN_WEIGHTS_H */
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("weights", help="weights JSON written by train.py")
    ap.add_argument("--verilog", help="path for the generated .vh")
    ap.add_argument("--header", help="path for the generated .h")
    args = ap.parse_args()

    with open(args.weights) as f:
        blob = json.load(f)
    meta = blob.pop("meta", {})
    net = M.Net.from_dict(blob)
    roundtrip_check(net)

    value, width = config_bits(net)
    words = config_words(net)
    print(f"channels {net.channels}   {net.num_weights} weights   "
          f"{net.macs_per_pixel} MACs/pixel")
    print(f"shifts   {[l.shift for l in net.layers]}")
    print(f"payload  {width} bits -> {len(words)} words of {WORD_BITS} bits")
    print(f"         first words: " + " ".join(f"0x{w:03X}" for w in words[:6]) + " ...")

    if args.verilog:
        with open(args.verilog, "w") as f:
            f.write(to_verilog(net))
        print(f"wrote {args.verilog}")
    if args.header:
        with open(args.header, "w") as f:
            f.write(to_c_header(net, meta))
        print(f"wrote {args.header}")


if __name__ == "__main__":
    main()
