module requant 
#(
	parameter CLIPPED = 1, //clip enable (true for L0, L1, false for L2)
	parameter IN_W = 12, //Input Width
	parameter SHIFT = 3, //Shift based on model generation
	parameter OUT_W = 4  //Output Width

)
(
	input logic signed [IN_W - 1 : 0] in, //input
	output logic [OUT_W - 1 : 0] out //requantised output
	
);

	logic signed [IN_W - 1 : 0] rounded, shifted;
	assign shifted = (in >>> SHIFT)  //shift by specified
	assign rounded = shifted + in[SHIFT-1]; //add for rounding

	logic [OUT_W - 1: 0] out_inter; 
	
	generate
	if(CLIPPED) begin : clipping  //if clipping
		always_comb begin
			if(rounded[IN_W-1]) //if num is negative round to 0
				out_inter = '0;
			else if(rounded[(IN_W - 2):OUT_W ]) //if num is more than max, make it max
				out_inter = {OUT_W{1'b1}};
			else
				out_inter = rounded[OUT_W - 1 : 0];
		end
	end
	else begin : non_clipping //for L2
		assign out_inter = rounded[OUT_W - 1 : 0];
	end
	endgenerate

	assign out = out_inter;


endmodule
