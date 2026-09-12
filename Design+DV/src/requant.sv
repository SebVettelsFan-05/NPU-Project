module requant 
#(
	parameter CLIPPED = 1, //clip enable (true for L0, L1, false for L2)
	parameter IN_W = 12, //Input Width
	parameter SHIFT = 3, //base shift; shift_sel picks SHIFT or SHIFT+1
	parameter OUT_W = 4  //Output Width

)
(
	input logic signed [IN_W - 1 : 0] in, //input
	input logic shift_sel, //0 -> shift by SHIFT, 1 -> shift by SHIFT+1
	output logic [OUT_W - 1 : 0] out //requantised output
	
);

	//Both shift amounts are elaboration constants, so this is a 2:1 mux
	//between two bundles of wires, not a barrel shifter.
	logic signed [IN_W - 1 : 0] rounded, shifted, round_ext;
	logic round_bit;

	assign shifted   = shift_sel ? (in >>> (SHIFT + 1)) : (in >>> SHIFT);
	assign round_bit = shift_sel ? in[SHIFT] : in[SHIFT - 1];
	assign round_ext = IN_W'(round_bit); //signed, so the add below stays signed
	assign rounded   = shifted + round_ext; //add for rounding

	logic [OUT_W - 1: 0] out_inter; 
	
	generate
	if(CLIPPED) begin : clipping  //if clipping
		always_comb begin
			if(rounded[IN_W-1]) //if num is negative round to 0
				out_inter = '0;
			else if(|rounded[(IN_W - 2):OUT_W ]) //if num is more than max, make it max
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
