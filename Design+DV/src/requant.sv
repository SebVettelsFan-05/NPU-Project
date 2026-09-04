module requant 
#(
	parameter CLIPPED = 1,
	parameter IN_W = 12,
	parameter SHIFT = 3,
	parameter OUT_W = 4

)
(
	input logic signed [IN_W - 1 : 0] in,
	output logic [OUT_W - 1 : 0] out
	
);

	logic signed [IN_W - 1 : 0] rounded, shifted;
	assign shifted = (in >>> SHIFT) 
	assign rounded = shifted + in[SHIFT-1];

	logic [OUT_W - 1: 0] out_inter;
	
	generate
	if(CLIPPED) begin : clipping 
		always_comb begin
			if(rounded[IN_W-1]) 
				out_inter = '0;
			else if(rounded[(IN_W - 2):OUT_W ])
				out_inter = {OUT_W{1'b1}};
			else
				out_inter = rounded[OUT_W - 1 : 0];
		end
	end
	else begin : non_clipping
		assign out_inter = rounded[OUT_W - 1 : 0];
	end
	endgenerate

	assign out = out_inter;


endmodule
