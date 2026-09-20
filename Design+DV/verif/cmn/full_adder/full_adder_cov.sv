module full_adder_cov
(
	input logic in_0, in_1, out, clk, cin, cout
);

  c_in0_0: cover property(@(posedge clk) in_0 == 1'b0);
  c_in1_0: cover property(@(posedge clk) in_1 == 1'b0);

  c_in0_1: cover property(@(posedge clk) in_0 == 1'b1);
  c_in1_1: cover property(@(posedge clk) in_1 == 1'b1);

  c_cin_0: cover property(@(posedge clk) cin == 1'b0);
  c_cin_1: cover property(@(posedge clk) cin == 1'b1);

  c_cout_0: cover property(@(posedge clk) cout == 1'b0);
  c_cout_1: cover property(@(posedge clk) cout == 1'b1);

  c_out_0: cover property(@(posedge clk) out == 1'b0);
  c_out_1: cover property(@(posedge clk) out == 1'b1);

endmodule
