module four_bit_adder
(
	input logic [3:0] in_0,
	input logic [3:0] in_1,
	output logic [3:0] out,
	output logic cout
);

logic [3:0]cout_inter;
genvar i;

half_adder ha (
	.in_0(in_0[0]),
	.in_1(in_1[0]),
	.out(out[0]),
	.cout(cout_inter[0])
);

generate for (i = 1; i < 4; i++) begin : serial_adders
	full_adder fa (
		.in_0(in_0[i]),
		.in_1(in_1[i]),
		.cin(cout_inter[i-1]),
		.cout(cout_inter[i]),
		.out(out[i])
	);

end endgenerate 

assign cout = cout_inter[3];
endmodule
