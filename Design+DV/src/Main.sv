module Main 
(
	input 	logic [7:0] ui_in,
	output 	logic [7:0] uo_out,
	input 	logic [7:0] uio_in,
	output 	logic [7:0] uio_out,
	output 	logic [7:0] uio_oe,
	input	logic 	    ena,
	input 	logic 	    clk,
	input 	logic 	    rst_n
);

	logic [7:0] ui_in_b;
	logic [7:0] uio_in_b;
	logic 	    ena_b;
	
	//input parameters
	logic [3:0] pix_in;	 //nibble of pixel value
	logic 	    in_valid;    //nibble is valid
	logic 	    patch_start; //first nibble of patch, because of how model was done
	logic 	    mode;        //bypass = 1, normal = 0

	//output parameters
	logic [5:0] pix_out; 	//output pixel, 6 bit as specified in models.py
	logic 	    out_valid;  //valid flag 
	logic 	    busy;	//busy flag, still computing
	

	//assign based on pinout
	assign pix_in 	   = ui_in_b[3:0]; 	
	assign in_valid	   = ui_in_b[4]; 	
	assign patch_start = ui_in_b[5]; 
	assign mode 	   = ui_in_b[6];	
	
	assign uo_out_b[5:0] = pix_out;
	assign uo_out_b[6]   = out_valid;
	assign uo_out_b[7]   = busy; 

	flop flop_uin
	(
		.in(ui_in)
		.clk(clk)
		.n_rst(rst_n)
		.out(ui_in_b)
	);

	flop flop_uout
	(
		.in(uo_out)
		.clk(clk)
		.n_rst(rst_n)
		.out(uo_out_b)
	);

	flop flop_ena
	(
		.in(ena)
		.clk(clk)
		.n_rst(rst_n)
		.out(ena_b)
	);




endmodule


