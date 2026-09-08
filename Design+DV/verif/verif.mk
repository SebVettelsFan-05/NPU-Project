# verif/verif.mk -- shared rules for every verification area.
#
# Each verif/<area>/Makefile is three lines:
#
#     DUT := requant.sv          # DUT sources, relative to src/ (globs allowed)
#     TBS := tb_requant          # the testbenches you wrote, by module name
#     include ../verif.mk
#
# Optional, before the include:
#     EXTRA_FLAGS := --trace-depth 3     # area-specific verilator flags
#
# Any other .sv in the area folder -- checkers, coverage modules, bind files --
# is picked up automatically. See SUPPORT below.
#
# Targets: all (= regress) | regress | cov | clean | <tb_name>

include $(dir $(lastword $(MAKEFILE_LIST)))../../config.mk

AREA  := $(notdir $(CURDIR))
BUILD := $(VERIF)/build

# DUT names the RTL. It is both the compile list and, more importantly, the
# rebuild trigger: verilator can find sub-modules on its own through -I, but
# make only rebuilds when a listed prerequisite changes. List everything the
# DUT reaches, or you will silently test a stale binary.
SRCS  := $(wildcard $(addprefix $(SRC)/,$(DUT)))

# Everything in this folder that is not a listed testbench: <dut>_checker.sv,
# <dut>_cov.sv, <dut>_bind.sv. Compiled into every testbench in the area and
# tracked as a dependency, so editing a checker rebuilds. Every tb_*.sv is
# excluded, listed in TBS or not -- a testbench is never a support file.
SUPPORT := $(filter-out $(wildcard tb_*.sv),$(wildcard *.sv))

LOGS  := $(addsuffix /run.log,     $(addprefix $(BUILD)/,$(TBS)))

# `make here` works off what is actually in the folder rather than off TBS, so
# a testbench you wrote but forgot to list still runs.
HERE_TBS  := $(basename $(wildcard tb_*.sv))
HERE_LOGS := $(addsuffix /run.log,$(addprefix $(BUILD)/,$(HERE_TBS)))
COVS  := $(addsuffix /coverage.dat,$(addprefix $(BUILD)/,$(TBS)))
SIMFLAGS += $(EXTRA_FLAGS)
JOBS  ?= 1

ifeq ($(SRCS),)
$(error $(AREA)/Makefile: DUT matched no files under $(SRC))
endif

.PHONY: all regress here cov clean $(TBS)
.PRECIOUS: $(BUILD)/%/sim $(BUILD)/%/run.log
.DELETE_ON_ERROR:

all: regress

# BUILD: elaborate + compile one testbench into its own directory.
# The testbench module name must equal its filename -- --top-module uses the stem.
$(BUILD)/%/sim: %.sv $(SUPPORT) $(SRCS)
	@printf "  [%s] build   %-22s %d rtl + %d support file(s)\n" \
	        "$(AREA)" "$*" "$(words $(SRCS))" "$(words $(SUPPORT))"
	@mkdir -p $(@D)
	@$(VERILATOR) $(SIMFLAGS) -j $(JOBS) --Mdir $(@D) --top-module $* -o sim $< $(SUPPORT) $(SRCS)

# RUN: cd first, so coverage.dat and the VCD land in this test's directory
# rather than on top of the previous test's. || true because a failing test
# must not abort the sweep -- the grep below is what decides the verdict.
$(BUILD)/%/run.log: $(BUILD)/%/sim
	@printf "  [%s] run     %s\n" "$(AREA)" "$*"
	@cd $(@D) && (./sim $(PLUSARGS) > run.log 2>&1 || true)
	@if grep -qE "^TEST PASS" $@; then \
	   printf "  [%s] PASS    %-22s %s\n" "$(AREA)" "$*" "$$(grep -oE '\([0-9]+ checks\)' $@)"; \
	 else \
	   printf "  [%s] FAIL    %-22s log: %s\n" "$(AREA)" "$*" "$@"; \
	   grep -m3 -E "^FAIL|Assertion failed" $@ | sed 's/^/           /' || true; \
	 fi

# Lets you say `make tb_requant` for a single test.
$(TBS): %: $(BUILD)/%/run.log

# REGRESS: depends on the log FILES, not on the phony test names, so an
# unchanged tree re-runs nothing.
regress: $(LOGS)
	@$(VERIF)/report.sh "$(AREA)" "$(BUILD)" $(TBS)
	@f=$$(grep -lE "^TEST FAIL|Assertion failed" $(LOGS) 2>/dev/null | wc -l); \
	 printf "  [%s] %d test(s), %d failing\n" "$(AREA)" "$(words $(TBS))" "$$f"; \
	 [ "$$f" -eq 0 ]

# HERE: build + run every tb_*.sv in THIS folder, listed or not. Bring-up
# convenience; it also tells you which testbenches are missing from TBS.
here: $(HERE_LOGS)
	@$(VERIF)/report.sh "$(AREA)" "$(BUILD)" $(HERE_TBS)
	@u="$(filter-out $(TBS),$(HERE_TBS))"; \
	 [ -z "$$u" ] || printf "  [%s] not listed in TBS: %s\n" "$(AREA)" "$$u"; \
	 f=$$(grep -lE "^TEST FAIL|Assertion failed" $(HERE_LOGS) 2>/dev/null | wc -l); \
	 printf "  [%s] here: %d test(s), %d failing\n" "$(AREA)" "$(words $(HERE_TBS))" "$$f"; \
	 [ "$$f" -eq 0 ]

# COV: an aborted run writes no coverage.dat, so ls rather than a fixed list,
# and warn when the count does not match the number of tests.
cov: regress
	@mkdir -p $(BUILD)/annot
	@n=$$(ls $(COVS) 2>/dev/null | wc -l); \
	 [ "$$n" -eq $(words $(TBS)) ] || \
	   printf "  [%s] warning: %d coverage file(s) for %d test(s)\n" "$(AREA)" "$$n" "$(words $(TBS))"; \
	 printf "  [%s] merging %d coverage file(s)\n" "$(AREA)" "$$n"; \
	 $(VCOV) --write $(BUILD)/$(AREA).dat $$(ls $(COVS) 2>/dev/null)
	@$(VCOV) --annotate $(BUILD)/annot/$(AREA) --annotate-min 1 $(BUILD)/$(AREA).dat
	@printf "  [%s] unhit lines: grep -rl '%%000' %s\n" "$(AREA)" "$(BUILD)/annot/$(AREA)"

# CLEAN: this area only. Other areas share $(BUILD) and are left alone.
clean:
	@printf "  [%s] removing %d build dir(s) and its coverage\n" "$(AREA)" "$(words $(sort $(TBS) $(HERE_TBS)))"
	@rm -rf $(addprefix $(BUILD)/,$(sort $(TBS) $(HERE_TBS))) \
	        $(BUILD)/$(AREA).dat $(BUILD)/annot/$(AREA)
