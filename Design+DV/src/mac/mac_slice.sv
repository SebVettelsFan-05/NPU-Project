module mac_slice
#(
	parameter ACC_W = 12
)
(
	input logic 			clk,
	input logic			n_rst,

	input logic 			en,
	input logic 			first,
	input logic [3:0]		in,
	input logic [3:0]		weight,
	input logic signed [7:0]	bias,
	input logic [1:0] 		wr_sel,
	input logic [1:0]		rd_sel,

	output logic			overflow,
	output logic signed [ACC_W-1:0] out
);

	//define intermeditates
	logic [7:0] 			mult_result;
	logic [6:0] 			sub_num;
	logic signed [7:0] 		sub_result;
	logic signed [ACC_W-1:0]	mux_result;
	logic signed [ACC_W-1:0]  	prev_result;

	logic signed [ACC_W-1:0]  	acc0_res, acc1_res, acc2_res;
	logic signed [ACC_W:0]		sum;

	//multiply 
	multiplier mult (
		.in_0(in),
		.in_1(weight),
		.out(mult_result)
	);

	//subtract
	assign sub_num = {in, 3'b000};
	assign sub_result = mult_result - sub_num;
	
	//mux 
	assign mux_result = first ? ACC_W'(bias) : prev_result;  

	//assign which accumulator to add
	always_comb begin
		case(wr_sel)
			2'd0: prev_result =  acc0_res;
			2'd1: prev_result =  acc1_res;
			2'd2: prev_result =  acc2_res;
			default: prev_result = 'x;
		endcase
	end

	//do accumulation
	assign sum = ACC_W'(sub_result) + ACC_W'(mux_result);
	
	//calculate overflow
	assign overflow = sum[ACC_W] ^ sum[ACC_W-1];
	
	//add to accumulation registers
	always_ff @(posedge clk) begin	
		if(!n_rst) begin
			acc0_res <= '0;
			acc1_res <= '0;
			acc2_res <= '0;
		end
		else if (en) begin
			case(wr_sel)
				2'd0: acc0_res <=  sum[ACC_W-1:0];
				2'd1: acc1_res <=  sum[ACC_W-1:0];
				2'd2: acc2_res <=  sum[ACC_W-1:0];
				default: ;
			endcase
		end
	end

	//what does it read?
	always_comb begin
		case(rd_sel)
			2'd0: out = acc0_res;
			2'd1: out = acc1_res;
			2'd2: out = acc2_res;
			default: out = 'x;
		endcase 
	end

endmodule
