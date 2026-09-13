// weight_rom.sv -- all trained constants for the 3-layer int4 denoiser.
//
// This is the ONLY module that may `include "weights.vh".  The header has an
// `ifndef CNN_WEIGHTS_VH guard, which expands once per compilation unit, so a
// second include anywhere in the build silently yields nothing.  Everything
// else reaches the weights and biases through these ports.
//
// The shift outputs were REMOVED: every requant needs the shift of the layer
// BEHIND it (rd_sel = layer - 1), not the current one, so addr_gen supplies
// act_shift_sel instead.  L0_SHIFT/L1_SHIFT/L2_SHIFT are therefore unreferenced
// here, and the values are hardcoded as requant #(.SHIFT(3)) in mac_wrapper and
// #(.SHIFT(5)) in out_stage.  A retrain that changes them will NOT be caught.
//
// Weights are stored BIASED: u = w + 8, unsigned 0..15.  Recover the signed
// weight as (u - 8), or use  sum(w*a) = sum(u*a) - 8*sum(a).
//
// Each slice owns a contiguous 90-entry slab, because export.py flattens the
// weights as [oc][ic][ky][kx] with oc outermost:
//
//     layer 0 :  L0_W[s*9  + t]   t = 0..8    s = output channel
//     layer 1 :  L1_W[s*72 + t]   t = 0..71   s = output channel
//     layer 2 :  L2_W[s*9  + t]   t = 0..8    s = INPUT channel
//
// Layer 2 has one output channel, so the eight slices divide the *input*
// channels and their partial sums are added downstream.  The bias must be
// applied once, not eight times: slice 0 gets L2_B[0], the rest get zero.

module weight_rom (
    input  logic [1:0]  layer,   // 0 = L0, 1 = L1, 2 = L2
    input  logic [6:0]  t,       // tap counter: 0..71 in L1, 0..8 in L0/L2

    output logic [31:0] w,       // w[4*s +: 4]    = slice s weight, biased u
    output logic [63:0] bias     // bias[8*s +: 8] = slice s bias, signed
);

    /* verilator lint_off UNUSEDPARAM */
    `include "weights.vh"
    /* verilator lint_on UNUSEDPARAM */

    // One address decode shared by all 32 weight bits: this builds a single
    // 90 x 32 ROM, not eight 90 x 4 ROMs.
    genvar s;
    generate
        for (s = 0; s < 8; s++) begin : slice
            always_comb begin
                unique case (layer)
                    2'd0:    w[4*s +: 4] = L0_W[s*9  + t];
                    2'd1:    w[4*s +: 4] = L1_W[s*72 + t];
                    2'd2:    w[4*s +: 4] = L2_W[s*9  + t];
                    // layer 3 never occurs; 'x lets the synthesiser treat the
                    // 38 unused addresses in the 128-entry space as don't-care.
                    default: w[4*s +: 4] = 4'bx;
                endcase

                unique case (layer)
                    2'd0:    bias[8*s +: 8] = L0_B[s];
                    2'd1:    bias[8*s +: 8] = L1_B[s];
                    2'd2:    bias[8*s +: 8] = (s == 0) ? L2_B[0] : 8'sd0;
                    default: bias[8*s +: 8] = 8'bx;
                endcase
            end
        end
    endgenerate

    // The L0/L2 index expressions can run past the end of their 72-entry arrays
    // if t is ever driven above 8 (7*9 + 71 = 134).  Left unguarded on purpose:
    // clamping costs a comparator and mux per slice for a case that cannot
    // happen, and synthesis is free to use it as don't-care.  Caught here
    // instead, because it will NOT show up in simulation -- Verilator is
    // 2-state and returns a plausible wrong value, not x.
`ifndef SYNTHESIS
    always_comb begin
        if (layer != 2'd1 && layer != 2'd3 && t > 7'd8)
            $error("weight_rom: tap %0d out of range for layer %0d (max 8)", t, layer);
        if (layer == 2'd1 && t > 7'd71)
            $error("weight_rom: tap %0d out of range for layer 1 (max 71)", t);
    end
`endif

endmodule
