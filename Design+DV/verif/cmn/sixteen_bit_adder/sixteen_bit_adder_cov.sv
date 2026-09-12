module sixteen_bit_adder_cov
(
	input logic clk,
	input logic [15:0] in_0, in_1, out,
	input logic cout
);

  // check the individual parameters
  c_a_min: cover property (@(posedge clk) in_0 == 16'h0);
  c_b_min: cover property (@(posedge clk) in_1 == 16'h0);
  c_a_max: cover property (@(posedge clk) in_0 == 16'hff);
  c_b_max: cover property (@(posedge clk) in_1 == 16'hff);
  cout_is_zero: cover property (@(posedge clk) cout == 1'b0);
  cout_is_one: cover property (@(posedge clk) cout == 1'b1);

  // check the inputs to the adder
  input_max_coutIsZero: cover property (@(posedge clk) in_0 == 4'hff && in_1 == 4'hff && cout == 1'b0);
  input_min_coutIsZero: cover property (@(posedge clk) in_0 == 4'h0 && in_1 == 4'h0 && cout == 1'b0);
  input_max_coutIsOne: cover property (@(posedge clk) in_0 == 4'hff && in_1 == 4'hff && cout == 1'b1);
  input_min_coutIsOne: cover property (@(posedge clk) in_0 == 4'h0 && in_1 == 4'h0 && cout == 1'b1);

  // check the outputs
  out_min: cover property (@(posedge clk) out == 4'h0);
  out_max: cover property (@(posedge clk) out == 4'hff);
  
  // combinations?
  overflow_coutIsOne: cover property (@(posedge clk) in_0 == 4'hff && in_1 == 4'hff && cout == 1'b1 && out == 4'h0); 
endmodule
