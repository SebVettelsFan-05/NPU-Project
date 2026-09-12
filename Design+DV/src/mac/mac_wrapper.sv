module mac
#(
	parameter MAC_SLICES 	    = 8
	parameter ACC_W	    	    = 12

)
(
	input logic 	      			clk,
	input logic           			n_rst,

	input logic [3:0]     			i_val,

	input logic [1:0]     			layer,
	input logic [6:0]     			tap,
	input logic 	      			first,
	input logic 				en,
	input logic [1:0]      			wr_sel,
	input logic [1:0]			rd_sel,	

	input logic [$clog2(MAC_SLICES] -1 :0] 	act_sel,
	input logic 				act_shift_sel,	
	
	output logic [ACC_W - 1:0]		o_val
 
);

//Signal defines
	logic [MAC_SLICES -1 : 0] 			overflow;
	logic [: 0] 		  			slice_in;
	//bias and weights
	logic signed [8*MAC_SLICES - 1:0] 		bias;
	logic [4*MAC_SLICES - 1 : 0] 		  	weight;
	//slice in and out defs
	logic [3:0] 					slice_in [0:MAC_SLICES-1];
	logic signed [ACC_W-1 :0] 			slice_out[0:MAC_SLICES-1];
	//activation variables
	logic [4*MAC_SLICES - 1:0] 			act_bus;

	
//Weight ROM
	weight_rom u_rom (
		.layer(layer),
		.t(tap),
		.w(weight),
		.bias(bias),
	);
//MAC Slice, Requant Instantiations (8)
	genvar i;
	
	
	generate
		for(i = 0; i < MAC_SLICES; i++) begin : gen_mac_slice_modules
			assign slice_in[i] = (layer == 2'd0) ? i_val : 
					     (layer == 2'd1) ? :
						
			
			mac_slice u_mac_slice (
				.clk(clk),
				.n_rst(n_rst),
				.en(en),
				.first(first),
				.in(slice_in[i]),
				.weight(weight[4*i +: 4]),
				.bias(bias[8*i +: 8]),
				.wr_sel(wr_sel),
				.rd_sel(rd_sel),
				.overflow(overflow[i]),
				.out(slice_out[i])
			);
			
			requant u_requant(
				.in(slice_out[i]),
				.out(act_bus[4*i +: 4]),
				.shift_sel(act_shift_sel)
			); 	
	
		end
	endgenerate
	
	
	
	endmodule
