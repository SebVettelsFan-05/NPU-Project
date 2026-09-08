#!/usr/bin/env bash
# verif/report.sh <area> <build_dir> <tb_name>...
#
# Lists, by name, every assertion and cover point declared in the current
# folder and whether it was exercised.
#
# Verilator has no assertion coverage -- --coverage covers line, toggle and
# `cover` statements only -- so assertion names are read from the source and
# their status comes from the run log. A failing assertion aborts the
# simulation, so "held" means it never failed on a sampled cycle. It does NOT
# prove the assertion was ever reached: an implication whose antecedent never
# occurs passes vacuously. Pair one with a cover point on its antecedent when
# that matters.

set -u
area=$1; build=$2; shift 2

# --- assertions -------------------------------------------------------------
asserts=$(grep -hoE '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*:[[:space:]]*assert' *.sv 2>/dev/null \
          | sed -E 's/[[:space:]]*:.*//; s/^[[:space:]]*//' | sort -u)

# A label declared in a source file is not necessarily in the DESIGN: if no
# bind statement instantiates its module, verilator compiles the file and emits
# nothing. Verilator writes each assertion's scope name into the generated C++,
# so searching for it there distinguishes "bound in" from "silently absent".
in_design() {   # in_design <label>
  for tb in "$@"; do :; done
  for tb in $TBS_ALL; do
    grep -qh "\.$1\"" "$build/$tb/"*.cpp "$build/$tb/"*.h 2>/dev/null && return 0
  done
  return 1
}
TBS_ALL="$*"

if [ -n "$asserts" ]; then
  printf "  [%s] assertions\n" "$area"
  unbound=0
  for a in $asserts; do
    if ! in_design "$a"; then
      printf "      %-26s NOT BOUND -- no bind statement instantiates it\n" "$a"
      unbound=1
      continue
    fi
    fired=""
    for tb in $TBS_ALL; do
      log="$build/$tb/run.log"
      [ -f "$log" ] && grep -q "Assertion failed.*[.: ]$a\b" "$log" && fired="$fired $tb"
    done
    if [ -n "$fired" ]; then printf "      %-26s FIRED in%s\n" "$a" "$fired"
    else                     printf "      %-26s held\n"       "$a"; fi
  done
  [ "$unbound" -eq 0 ] || printf "      ^ add a *_bind.sv with: bind <dut> <module> u_chk (.*);\n"
else
  printf "  [%s] assertions: none declared in this folder\n" "$area"
fi

# --- cover points -----------------------------------------------------------
# coverage.dat separates fields with \001<key>\002<value>; the hierarchical
# name is the "h" field, the hit count follows the closing quote.
files=""
for tb in "$@"; do [ -f "$build/$tb/coverage.dat" ] && files="$files $build/$tb/coverage.dat"; done

if [ -z "$files" ]; then
  printf "  [%s] cover points: no coverage.dat yet (run the tests first)\n" "$area"
  exit 0
fi

grep -h "v_user" $files 2>/dev/null | awk -v area="$area" '
  { n = ""
    if (match($0, /\001h\002[^\047]*/)) n = substr($0, RSTART + 3, RLENGTH - 3)
    c = $0; sub(/.*\047 /, "", c)
    sub(/.*\./, "", n)
    cnt[n] += c
  }
  END {
    tot = 0; hit = 0
    for (k in cnt) { tot++; if (cnt[k] > 0) hit++ }
    if (tot == 0) printf "  [%s] cover points: none in the design (declared but not bound?)\n", area
    else printf "  [%s] cover points: %d/%d hit\n", area, hit, tot
    for (k in cnt) printf "      %-26s %6d%s\n", k, cnt[k], (cnt[k] ? "" : "   MISS")
  }' | { IFS= read -r hdr; printf "%s\n" "$hdr"; sort -k2 -rn; }
