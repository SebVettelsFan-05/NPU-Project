# Makefile -- repo-level entry point: runs every verification area.
#
#   make regress          every verif/<group>/<area>/Makefile
#   make -j4 regress      areas in parallel
#
# Uses the pinned toolchain automatically once set up:  sh dependencies/setup.sh
include config.mk

AREAS := $(patsubst %/Makefile,%,$(wildcard $(VERIF)/*/*/Makefile))

.PHONY: all regress $(AREAS)
all: regress

regress: $(AREAS)
	$(call banner,$(words $(AREAS)) verif area(s) passed)

$(AREAS):
	$(call require-tool,$(VERILATOR),run sh dependencies/setup.sh)
	$(call require-tool,g++,verilator --binary needs a C++ compiler -- run sh dependencies/setup.sh)
	@$(MAKE) -C $@ regress
