module tb_full_adder;
	logic clk = 0;
	always begin
		#1;
		clk <= ~clk;
	end
	
	logic cout, out, in_0, in_1, cin;
	int errors = 0;
	int checks = 0;

	full_adder dut (
		.out(out),
		.in_0(in_0),
		.in_1(in_1),
		.cin(cin),
		.cout(cout)
	);

	// VCD dumping, gated so normal regressions stay fast:
	//   make PLUSARGS=+trace tb_four_bit_adder
	// The VCD lands in this test's build dir (verif.mk cds there first).
	initial begin
		if ($test$plusargs("trace")) begin
			$dumpfile("tb_flop.vcd");
			$dumpvars(0, tb_flop);
		end
	end

	initial begin

		for (int i = 0; i < 8; i++) begin
			#1;
			{in_0, in_1, cin} = i[2:0];
			#1;
			checks++;
			if ({cout, out} !==  in_0 + in_1 + cin) begin
				errors++;
				$display("MISMATCH: in_0=%b in_1=%b cin=%b -> cout=%b out=%b",
				         in_0, in_1, cin, cout, out);
			end
		end

		if (errors == 0) 
			$display("TEST PASS: %m (%0d checks)", checks);
		else
			$display("TEST FAIL: %m (%0d checks)", checks);
		$finish;
	end

endmodule



