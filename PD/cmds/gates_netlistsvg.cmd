# Gate-level netlist, exported as JSON for rendering with netlistsvg.
# netlistsvg draws real gate shapes (AND/OR/XOR/mux/D-flip-flop symbols)
# instead of labeled boxes.

read_verilog tplvl.v
hierarchy -top tplvl

synth -top tplvl

# Export netlist as JSON instead of directly rendering
write_json tplvl_gates.json

#yosys -s tplvl_gates_netlistsvg.cmd -q
#netlistsvg tplvl_gates.json -o tplvl_gates_netlistsvg.svg
#open tplvl_gates_netlistsvg.svg
