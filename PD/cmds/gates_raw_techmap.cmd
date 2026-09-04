# Raw gate-level view without ABC logic optimization.
# Uses only techmap (maps to Yosys's internal generic gate primitives).
# Usually messier/less optimized than the "synth" flow, but useful to
# see the unoptimized 1:1 mapping of RTL constructs to gates.

read_verilog tplvl.v
hierarchy -top tplvl

proc
opt

techmap
opt

show -format svg -prefix tplvl_gates_raw

#yosys -s tplvl_gates_raw_techmap.cmd -q
#open tplvl_gates_raw.svg
