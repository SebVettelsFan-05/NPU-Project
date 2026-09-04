module full_adder
(
	input logic in_0,
	input logic in_1,
	input logic cin,
	output logic out,
	output logic cout 
);

assign out = in_0 ^ in_1 ^ cin;
assign cout = (in_0 & in_1) | (in_0 & cin) | (in_1 & cin);

endmodule
