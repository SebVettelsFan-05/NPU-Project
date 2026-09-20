module multiplier_checker
(
	input logic [3:0] in_0, in_1,
	input logic [7:0] out
);

	always_comb begin
		a_out: assert(out == (in_0 * in_1))
			else $error("multplier does not work, out was %b when it should be %b. in_0 was $b and in_1 was %b", out, (in_0 * in_1), in_0, in_1);
	end
endmodule

