## Maps to Yosys's generic simulation standard-cell library (cells.lib),
# giving a netlist that looks like a real ASIC cell-based design
# (basic gates + DFF) rather than internal $_AND_/$_XOR_ primitives.
read_verilog tplvl.v
hierarchy -top tplvl
synth -top tplvl
# Map flip-flops only to the standard cell library (cells.lib has no combinational gates)
dfflibmap -liberty /usr/share/yosys/cells.lib
# Map combinational logic using ABC's built-in default library
abc
show -format svg -prefix tpvlvl_stdcell
#yosys -s stdcell.cmd -q
#open tplvl_stdcell.svg
