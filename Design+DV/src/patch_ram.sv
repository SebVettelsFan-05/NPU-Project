module patch_ram
(
	input logic 		clk,

	//write defines
	input logic		wr_en,
	input logic [2:0]	wr_row,
	input logic [2:0]       wr_col,
	input logic [3:0]       pix_in,
	//output logic
	input logic [2:0] 	rd_row,
	input logic [2:0] 	rd_col,
	output logic [3:0] 	pix_out,
	output logic [3:0] 	mid
);

	logic [3:0] array[0:6][0:6];
	always_ff @(posedge clk) begin
		if(wr_en) begin
			array[wr_row][wr_col] <= pix_in;
		end
	end
	assign pix_out = array[rd_row][rd_col];
	assign mid = array[3][3];

endmodule
