module flop #(parameter WIDTH = 8)
(
	input logic [WIDTH-1:0] in,
	input logic clk,
	input logic n_rst,
	output logic [WIDTH-1:0] out
);


	always_ff @(posedge clk) begin
		if(!n_rst)
			out <= {WIDTH{1'b0}};
		else 
			out <= in;
	end



endmodule
