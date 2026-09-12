module tb_sixteen_bit_adder;
	logic clk = 0;
	always begin
		#1;
		clk <= ~clk;
	end
	
	logic [15:0] in_0, in_1, out;
	logic	    cout;
	int errors = 0;
	int checks = 0;

	sixteen_bit_adder dut (
		.in_0(in_0),
		.in_1(in_1),
		.out(out),
		.cout(cout)
	);

	// VCD dumping, gated so normal regressions stay fast:
	//   make PLUSARGS=+trace tb_four_bit_adder
	// The VCD lands in this test's build dir (verif.mk cds there first).
	initial begin
		if ($test$plusargs("trace")) begin
			$dumpfile("tb_four_bit_adder.vcd");
			$dumpvars(0, tb_four_bit_adder);
		end
	end

	initial begin
		for(int i = 0; i < 256; i++) begin
			for(int j = 0; j < 256; j++) begin
				in_0 = i[15:0];
				in_1 = j[15:0];
				@(posedge clk);
				checks++;
				if({cout,out} !== ({1'b0,in_0} +{1'b0, in_1})) begin
					errors++;
					$display("TEST %0d FAILED, %0d + %0d -> %0d, expected %0d", checks, in_0, in_1, {cout,out}, ({1'b0,in_0} +{1'b0, in_1}));
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



