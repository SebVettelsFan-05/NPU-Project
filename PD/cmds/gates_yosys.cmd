# Gate-level netlist using Yosys's full generic synthesis flow (synth),
# rendered with Yosys's built-in graphviz-based viewer.
# Note: gates appear as labeled boxes ($_AND_, $_XOR_, etc.), not
# classic gate symbols.

read_verilog tplvl.v
hierarchy -top tplvl

# Full generic synth flow: proc + opt + techmap + abc optimization
synth -top tplvl

show -format svg -prefix tplvl_gates_yosys


#yosys -s tplvl_gates_yosys.cmd -q
#open tplvl_gates_yosys.svg
