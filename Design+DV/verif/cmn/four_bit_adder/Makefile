# verif/cmn/four_bit_adder -- verification of src/cmn/four_bit_adder.sv
#
# COMMANDS
#   make                     build + run every testbench in TBS, print the verdict
#   make regress             the same thing; `all` is an alias for it
#   make cov                 run, then merge + annotate this folder's coverage
#   make clean               remove this folder's build dirs and its coverage
#   make here                build + run every tb_*.sv in this folder, whether
#                            or not it is listed in TBS, and name the ones that
#                            are missing from TBS
#
#   make tb_four_bit_adder   build + run just that one testbench
#   make -j12                overlap whole testbenches across cores
#   make JOBS=12 tb_four_bit_adder
#                            parallel C++ compile of ONE test instead
#   make PLUSARGS=+trace     re-run with VCD dumping (the tb must gate
#                            $dumpvars on $test$plusargs("trace"))
#   make -n                  show what make WOULD do, without doing it
#
# THERE IS NO `make assertion` OR `make coverage`.
#   The checker, coverage and bind files in this folder are compiled into every
#   testbench automatically (see SUPPORT in verif.mk), so assertions are always
#   active and cover points are always sampled. `make cov` does not enable
#   coverage -- it only reports what the run already collected.
#
# VERDICT
#   A test passes only if its log contains "TEST PASS" at the start of a line.
#   An assertion failure aborts the simulation, so the banner never prints and
#   the test is reported FAIL. An aborted run also writes no coverage.dat, so
#   fix failures before trusting `make cov`.
#
# FILES IN THIS FOLDER
#   tb_four_bit_adder.sv        stimulus + the TEST PASS/FAIL banner
#   four_bit_adder_checker.sv   assertions, bound into the DUT
#   four_bit_adder_cov.sv       cover properties, bound into the testbench
#   four_bit_adder_bind.sv      the bind statements
#
# OUTPUT LINES
#   [four_bit_adder] build   tb_...   N rtl + M support file(s)
#        ^ if M is 0 your checker/cov/bind files are NOT being compiled and
#          every assertion in them is silently absent.

# DUT sources, relative to src/. This is both the compile list and the rebuild
# trigger. Verilator finds half_adder/full_adder on its own through -I, but
# make will not rebuild when they change unless they are listed here:
#   DUT := cmn/four_bit_adder.sv cmn/half_adder.sv cmn/full_adder.sv
DUT := cmn/four_bit_adder.sv

# The testbenches you wrote, by module name (= filename without .sv).
TBS := tb_four_bit_adder

include ../../verif.mk
