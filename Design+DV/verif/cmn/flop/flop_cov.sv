module flop_cov #(parameter WIDTH = 8)
(
	input logic [WIDTH-1:0] in, out,
	input logic clk,
	input logic n_rst
);

  c_n_rst_asserted: cover property (@(posedge clk) n_rst == 1'b0);
  c_n_rst_deasserted: cover property (@(posedge clk) n_rst == 1'b1);
  
  data_is_transfered: cover property (@(posedge clk) (n_rst == 1'b1) |-> (out == $past(in)));

endmodule
