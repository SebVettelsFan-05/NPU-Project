module flop_checker #(parameter WIDTH = 8)
(
	input logic [WIDTH-1:0] in, out,
	input logic clk,
	input logic n_rst
);


	a_n_rst: assert property (@(posedge clk) (n_rst == 1'b0) |=> out == 0)
		else $error("out was not forced to 0 on reset, is %b", out);
	a_transfer: assert property (@(posedge clk) disable iff (n_rst == 1'b0) $past(n_rst == 1'b1) |-> out == $past(in))
		else $error("data was not transferred through the flop, in was %b and out is %b", $past(in), out);
endmodule

