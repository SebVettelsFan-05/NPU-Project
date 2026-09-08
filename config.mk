# config.mk -- shared configuration, included by every Makefile in the tree.
#
# Include it from anywhere; it locates itself, so no ../.. counting is needed:
#
#     include ../../config.mk          # from Design+DV/src or Design+DV/verif
#     include ../config.mk             # from PD or models
#
# The include guard below makes double-inclusion harmless, which matters
# because recursive make reads this file more than once per tree walk.

ifndef CONFIG_MK
CONFIG_MK := 1

# --- where things are -------------------------------------------------------
# MAKEFILE_LIST's last entry, while this file is being parsed, is this file.
ROOT   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
DVDIR  := $(ROOT)/Design+DV
SRC    := $(DVDIR)/src
VERIF  := $(DVDIR)/verif
MODELS := $(ROOT)/models
PDDIR  := $(ROOT)/PD

# --- the design, defined once -----------------------------------------------
# One list, so verif, src and PD cannot disagree about what the design is.
RTL     := $(wildcard $(SRC)/cmn/*.sv) $(wildcard $(SRC)/mac/*.sv) $(SRC)/requant.sv
RTL_TOP := $(SRC)/Main.sv
TOP     := Main
INCS    := -I$(SRC) -I$(SRC)/cmn -I$(SRC)/mac -I$(MODELS)

# --- tools ------------------------------------------------------------------
# ?= so a single run can override: make VERILATOR=/opt/verilator-5.040/bin/verilator
VERILATOR ?= verilator
VCOV      ?= verilator_coverage
YOSYS     ?= yosys
PYTHON    ?= python3

LINTFLAGS := --lint-only -sv -Wall -Wno-DECLFILENAME $(INCS)

# --assert is what makes assertions a project-wide guarantee. Without it a
# failing SVA is parsed, ignored, and the testbench still prints TEST PASS.
# -MAKEFLAGS silences verilator's own sub-make; --quiet does not reach it.
SIMFLAGS  := --binary --quiet --quiet-stats -MAKEFLAGS "-s --no-print-directory" \
             --timing --assert --coverage --trace \
             -Wno-DECLFILENAME -Wno-BLKSEQ $(INCS)

# --- helpers ----------------------------------------------------------------
define banner
@printf "\n\033[1m== %s ==\033[0m\n" "$(1)"
endef

define require-tool
@command -v $(1) >/dev/null 2>&1 || { \
  printf "\n  MISSING TOOL: %s\n  %s\n\n" "$(1)" "$(2)" >&2; exit 1; }
endef

define require-py
@$(PYTHON) -c "import $(1)" 2>/dev/null || { \
  printf "\n  MISSING PYTHON MODULE: %s\n  %s\n\n" "$(1)" "$(2)" >&2; exit 1; }
endef

MAKEFLAGS += --no-print-directory
endif
