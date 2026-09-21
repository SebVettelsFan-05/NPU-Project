#!/bin/bash
# regress.sh — run a verification area with toolchain bootstrap and failure logs.
#
# For plain runs you do not need this; just use submit.sh from the area:
#
#     cd Design+DV/verif/cmn/sixteen_bit_adder
#     ../../../../slurm/submit.sh -c 6 -m 4G make JOBS=6 regress
#
# This wrapper adds two things submit.sh alone does not:
#   * builds the pinned pixi toolchain on first use (it is per-machine and
#     gitignored, so it never arrives with the repo)
#   * on failure, tails the failing run.log files into stdout
#
#     cd <repo root>
#     ./slurm/submit.sh -c 6 -m 4G -t 45 ./slurm/jobs/regress.sh
#     NPU_AREA=all ./slurm/submit.sh -c 6 -m 5G -t 60 ./slurm/jobs/regress.sh
#
# Env:
#   NPU_AREA   area path relative to the repo root, or "all" for the whole tree
#              (default: the sixteen_bit_adder area)
#
# This is CPU work. Verilator elaboration and the g++ compile of the generated
# model are the entire cost; there is nothing here for a GPU to do.

set -uo pipefail

AREA="${NPU_AREA:-Design+DV/verif/cmn/sixteen_bit_adder}"
NCPU="${SLURM_CPUS_PER_TASK:-1}"

# submit.sh sets --chdir to where you invoked it, so locate the repo from this
# script rather than assuming the CWD.
REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)

echo "host   : $(hostname)"
echo "job    : ${SLURM_JOB_ID:-interactive}"
echo "cpus   : $NCPU"
echo "repo   : $REPO"
echo "area   : $AREA"
echo "started: $(date)"
echo

cd "$REPO" || { echo "FATAL: cannot enter $REPO"; exit 1; }

# --- toolchain -------------------------------------------------------------
# dependencies/toolchain.mk records the absolute path of the pinned toolchain
# (in-tree under dependencies/.pixi; ~/.cache/rattler for a /mnt/c checkout)
# and is gitignored, so it is per-machine by design.
if [[ ! -f dependencies/toolchain.mk ]]; then
    echo "==> pinned toolchain missing; running dependencies/setup.sh (first run only)"
    echo "    this downloads verilator/g++/yosys and takes 10-15 minutes"
    sh dependencies/setup.sh || { echo "FATAL: toolchain setup failed"; exit 1; }
    echo
fi

# --- run -------------------------------------------------------------------
# Two parallelism knobs, and the wrong one wastes the allocation:
#   make -j N   overlaps whole testbenches  -> only helps with several TBS
#   JOBS=N      parallel C++ compile of ONE -> what a single-testbench area needs
# Never multiply them; -j6 JOBS=6 spawns up to 36 compilers on 6 cores.
if [[ "$AREA" == "all" ]]; then
    echo "==> make -j$NCPU regress (whole tree)"
    make -j"$NCPU" regress
else
    cd "$AREA" || { echo "FATAL: no such area: $AREA"; exit 1; }
    echo "==> make JOBS=$NCPU regress"
    make JOBS="$NCPU" regress
fi
RC=$?

# --- failure detail --------------------------------------------------------
# A bare FAIL line says nothing useful, so surface the actual assertion text.
if (( RC != 0 )); then
    echo
    echo "================ FAILING LOGS ================"
    while IFS= read -r log; do
        echo; echo "--- $log ---"; tail -40 "$log"
    done < <(grep -rlE "^TEST FAIL|Assertion failed" \
                 "$REPO"/Design+DV/verif/build/*/run.log 2>/dev/null | head -5)
    echo "=============================================="
fi

echo
echo "finished: $(date)"
# make regress already exits non-zero when any test fails, so Slurm's job state
# agrees with the verdict in the log.
exit $RC
