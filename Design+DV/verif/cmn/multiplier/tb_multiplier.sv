module tb_multiplier;
	logic clk = 0;
	always begin
		#1;
		clk <= ~clk;
	end
	
	logic [3:0] in_0, in_1;
	logic [7:0] out;
	int errors = 0;
	int checks = 0;

	multiplier dut (
		.in_0(in_0),
		.in_1(in_1),
		.out(out)
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

		for (int i = 0; i < 16; i++) begin
			for (int j = 0; j < 16; j++) begin
				checks++;

				in_0 = i[3:0];
				in_1 = j[3:0];
				@(posedge clk);
				if (out !== (in_0 * in_1)) begin
					errors++;
					$display("TEST %0d FAILED, %0d * %0d -> %0d, expected %0d", checks, in_0, in_1, out, (in_0 * in_1));					
				end
			end
		end

		if (errors == 0) 
			$display("TEST PASS: %m (%0d checks)", checks);
		else
			$display("TEST FAIL: %m (%0d checks)", checks);
		$finish;
	end

endmodule



