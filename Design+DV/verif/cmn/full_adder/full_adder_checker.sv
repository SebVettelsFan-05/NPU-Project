module full_adder_checker
(
	input logic in_0, in_1, cin, cout, out
);

	a_cout: assert #0 (cout == ((in_0 & in_1) | (in_0 & cin) | (in_1 & cin)))
		else $error("cout was not asserted when it should be");
	a_out: assert #0 (out == (in_0 + in_1 + cin))
		else $error("output is not driven to correct output, out was %b, in_0 was %b, in_1 was %b, cin was %b, out should be %b", out, in_0, in_1, cin, (in_0 + in_1 + cin));
endmodule

