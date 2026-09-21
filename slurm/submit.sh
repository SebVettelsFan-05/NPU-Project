#!/usr/bin/env bash
#
# submit.sh — run a command as a Slurm job in the CURRENT directory.
#
# The LSF `bsub` shape. Requires the shared (NFS) directory, so the path you
# submit from exists on the compute node too.
#
#   ./submit.sh make regress                     defaults: 4 cpus, 2G, 30 min
#   ./submit.sh -c 6 -m 4G make JOBS=6 regress
#   ./submit.sh -c 6 -m 6G -t 60 make -j6 regress
#   ./submit.sh -n make regress                  don't wait, just queue it
#   ./submit.sh -o build.log make regress        name the log file
#
#   -c N     cpus       (default 4)
#   -m SIZE  memory     (default 2G)
#   -t MIN   time limit (default 30)
#   -g N     GPUs       (default none — RTL work does not use them)
#   -J NAME  job name   (default the command)
#   -o FILE  output file (default slurm-<jobid>.out, in this directory)
#   -n       submit and return immediately
#
set -uo pipefail

CPUS=4 MEM=2G TIME=30 GPUS="" JOBNAME="" OUTFILE="" WAIT=1

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while getopts ":c:m:t:g:J:o:nh" opt; do
    case $opt in
        c) CPUS=$OPTARG ;;   m) MEM=$OPTARG ;;    t) TIME=$OPTARG ;;
        g) GPUS=$OPTARG ;;   J) JOBNAME=$OPTARG ;; o) OUTFILE=$OPTARG ;;
        n) WAIT=0 ;;         h) usage 0 ;;
        *) echo "Unknown option -$OPTARG" >&2; usage 1 ;;
    esac
done
shift $((OPTIND - 1))
(( $# )) || usage 1

command -v sbatch >/dev/null || { echo "sbatch not found — run setup-client.sh" >&2; exit 1; }

# --- the shared-path check -------------------------------------------------
# Slurm hands the compute node your submit-time CWD verbatim. If this path is
# not on shared storage it will not exist over there and the job dies instantly
# with an obscure chdir error. Catch it here with a readable message instead.
CWD=$(pwd -P)
if ! findmnt -T "$CWD" -no FSTYPE 2>/dev/null | grep -q nfs; then
    if [[ "$(hostname)" != "$(sinfo -h -o %n 2>/dev/null | head -1)" ]]; then
        cat >&2 <<EOF
[fail] $CWD is not on shared (NFS) storage.

    The compute node cannot see this directory, so the job would fail with a
    chdir error. Work inside the shared directory instead:

        findmnt -t nfs4          # shows what is shared
EOF
        exit 1
    fi
fi

[[ -z "$JOBNAME" ]] && JOBNAME=$(basename "$1")
[[ -z "$OUTFILE" ]] && OUTFILE="slurm-%j.out"

ARGS=( --parsable --job-name="$JOBNAME" --chdir="$CWD"
       --cpus-per-task="$CPUS" --mem="$MEM" --time="$TIME"
       --output="$OUTFILE" --open-mode=truncate --export=ALL )
[[ -n "$GPUS" ]] && ARGS+=( --gres=gpu:"$GPUS" )

# --wrap runs the command through a shell on the node. Quote the whole thing so
# 'make JOBS=6 regress' arrives intact.
CMD=$(printf '%q ' "$@")

JOBID=$(sbatch "${ARGS[@]}" --wrap="$CMD") || {
    echo "sbatch failed — check 'sinfo'." >&2; exit 1; }

RESOLVED="${OUTFILE//%j/$JOBID}"
printf '\033[1;34m==>\033[0m job %s  (%s cpus, %s, %s min)\n' "$JOBID" "$CPUS" "$MEM" "$TIME"
echo "    $*"
echo "    log: $CWD/$RESOLVED"

if (( ! WAIT )); then
    echo "    queued; check with: squeue -j $JOBID"
    exit 0
fi

# --- wait ------------------------------------------------------------------
# squeue drops the job when it leaves the queue; that is the completion signal.
# (sacct would be richer but needs slurmdbd, which this cluster does not run.)
echo "    waiting (Ctrl-C detaches; the job keeps running)"
LAST=""
while true; do
    LINE=$(squeue -j "$JOBID" -h -o '%T %R' 2>/dev/null || true)
    [[ -z "$LINE" ]] && break
    [[ "$LINE" != "$LAST" ]] && { printf '    %s\n' "$LINE"; LAST="$LINE"; }
    sleep 2
done

# No copying back: the log was written straight into this directory over NFS.
echo
if [[ -f "$RESOLVED" ]]; then
    cat "$RESOLVED"
else
    echo "(no output file — the job may have failed before starting; try 'sinfo -R')"
fi
