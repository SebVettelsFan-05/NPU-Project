 module multiplier 
(
	input logic [3:0] in_0,
       	input logic [3:0] in_1,
	output logic [7:0] out 	
);

logic [3:0] b0_a, b1_a, b2_a, b3_a;

assign b0_a = {4{in_1[0]}} & in_0;
assign b1_a = {4{in_1[1]}} & in_0;
assign b2_a = {4{in_1[2]}} & in_0;
assign b3_a = {4{in_1[3]}} & in_0;

logic [3:0] out_s1;
logic cout_s1;

logic [3:0] out_s2;
logic cout_s2;

logic [3:0] out_s3;
logic cout_s3;

four_bit_adder stage1 (
	.in_0(b1_a),
	.in_1({1'b0,b0_a[3:1]}),
	.out(out_s1),
	.cout(cout_s1)
);

four_bit_adder stage2 (
	.in_0(b2_a),
	.in_1({cout_s1,out_s1[3:1]}),
	.out(out_s2),
	.cout(cout_s2)

);

four_bit_adder stage3 (
	.in_0(b3_a),
	.in_1({cout_s2,out_s2[3:1]}),
	.out(out_s3),
	.cout(cout_s3)

);

assign out = {cout_s3, out_s3[3:0], out_s2[0], out_s1[0], b0_a[0]};
	
	 

endmodule








