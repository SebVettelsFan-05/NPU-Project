module four_bit_adder_cov
(
	input logic clk,
	input logic [3:0] in_0, in_1, out,
	input logic cout
);


  c_a_min: cover property (@(posedge clk) in_0 == 4'h0);

endmodule
