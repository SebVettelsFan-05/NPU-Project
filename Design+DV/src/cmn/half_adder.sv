module half_adder
(
        input logic in_0,
        input logic in_1,
	output logic out,
	output logic cout       
);
	assign out = (~in_0 & in_1) | (in_0 & ~in_1);
	assign cout = in_0 & in_1;

endmodule


