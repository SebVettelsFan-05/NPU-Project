module four_bit_adder_checker
(
	input logic [3:0] in_0, in_1, out,
	input logic 	  cout
);


	always_comb begin
		a_sum: assert({cout, out} == ({1'b0, in_0} + {1'b0, in_1}))
			else $error("bad sum");
		a_overflow: assert #0 (!(in_0 == 4'hf && in_1 == 4'hf) || cout == 1'b1)
			else $error("cout not asserted on max input");
	end
endmodule

