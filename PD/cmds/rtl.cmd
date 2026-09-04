# RTL-level schematic: shows abstracted arithmetic/mux/register blocks
# rather than individual logic gates. Good for understanding design intent.

read_verilog tplvl.v
hierarchy -top tplvl

# Convert always blocks into internal RTL representation
proc

# Basic cleanup/optimization
opt

# Render as SVG using graphviz backend
show -format svg -prefix tplvl_rtl

#yosys -s tplvl_rtl.cmd -q
#open tplvl_rtl.svg
