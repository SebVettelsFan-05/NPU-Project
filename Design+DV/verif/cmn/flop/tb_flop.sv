module tb_flop;
	logic clk = 0;
	always begin
		#1;
		clk <= ~clk;
	end
	
	logic [7:0] in, out;
	logic cout, n_rst;
	int errors = 0;
	int checks = 0;

	flop dut (
		.clk(clk),
		.in(in),
		.out(out),
		.n_rst(n_rst)
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
		n_rst = 0;
		#1;
		in = 8'b10101010; 
		#1;
		n_rst = 1;
		#2;

		if (out !== 8'b10101010)
			errors++;
		checks++;
		#2;

		in = 8'b01010101; 
		#2;
		
		if (out !== 8'b01010101)
			errors++;
		checks++;
		#2;

		//walking ones
		for (int i = 0; i < 8; i++) begin
			in = 1'b1 << i;
			#2;
			if (out !== in) begin
				errors++;
				$display("out should have been %b, was %b", in, out);
			end
			checks++;
		end

		#2;
		n_rst = 1'b0;
		#2;
		n_rst = 1'b1;

		//walking zeros
		for (int i = 0; i < 8; i++) begin
			in = ~(8'b1 << i);
			#2;
			if (out !== in) begin
				errors++;
				$display("out should have been %b, was %b", in, out);
			end
			checks++;
		end

		if (errors == 0) 
			$display("TEST PASS: %m (%0d checks)", checks);
		else
			$display("TEST FAIL: %m (%0d checks)", checks);
		$finish;
	end

endmodule



