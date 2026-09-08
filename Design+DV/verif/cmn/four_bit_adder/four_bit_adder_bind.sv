// four_bit_adder_bind.sv -- attaches the checker and the coverage module to the
// design. Neither is instantiated anywhere else; without this file both compile
// and emit nothing, and every assertion in the checker is silently absent.

// Assertions go into the DUT. The checker's ports are named exactly like
// four_bit_adder's, so .* connects them. It is an immediate assertion inside
// always_comb, so it needs no clock -- which means it stays live in every build
// that instantiates four_bit_adder, including tb_mac_slice, where the adder
// sits under multiplier.
bind four_bit_adder four_bit_adder_checker u_chk (.*);

// Coverage needs a sampling edge and four_bit_adder has no clock, so this one
// binds into the testbench instead, where clk exists. A bind whose target
// module is not in the build is ignored, so this line is harmless in every
// other testbench's build.
bind tb_four_bit_adder four_bit_adder_cov u_cov (.*);
