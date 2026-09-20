module multiplier_cov
(
  input logic clk,
	input logic [3:0] in_0, in_1,
	input logic [7:0] out 	
);

  c_in0_max: cover property (@(posedge clk) in_0 == 4'hf);
  c_in1_max: cover property (@(posedge clk) in_1 == 4'hf);

  c_out_max: cover property (@(posedge clk) out == 8'he1); // max is e1 not ff for 4bit unsigned multiplier
  
  c_out_whenMultipliedByZero: cover property (@(posedge clk) (in_0 == 4'h0 || in_1 == 4'h0) & (out == 8'h0));
  c_out_whenOverflow: cover property (@(posedge clk) (in_0 == 4'hf && in_1 == 4'hf) & (out == 8'he1));

endmodule
