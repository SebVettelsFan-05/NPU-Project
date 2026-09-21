# Running `make regress` on the Cluster

Assumes `SETUP.md` is done and the repo lives in the shared directory
(`/work/NPU-Project`).

---

## The translation

Before:

```bash
cd Design+DV/verif/cmn/sixteen_bit_adder
make regress
```

On the cluster:

```bash
cd /work/NPU-Project/Design+DV/verif/cmn/sixteen_bit_adder
/work/NPU-Project/slurm/submit.sh -c 6 -m 4G make JOBS=6 regress
```

Same directory, same command — it just runs on `chapple` instead of here. The
log lands in that folder as `slurm-<jobid>.out`.

Put the scripts on your PATH to shorten it:

```bash
echo 'export PATH="/work/NPU-Project/slurm:$PATH"' >> ~/.bashrc
source ~/.bashrc

cd /work/NPU-Project/Design+DV/verif/cmn/sixteen_bit_adder
submit.sh -c 6 -m 4G make JOBS=6 regress
```

`make regress` still works normally on your laptop. Nothing here replaces it.

---

## First run: the toolchain

The pinned pixi toolchain is per-machine — `dependencies/toolchain.mk` records
an absolute path into the local rattler cache and is gitignored, so it does not
travel with the repo. Build it once on the server:

```bash
ssh chapple@<ip> 'cd /work/NPU-Project && sh dependencies/setup.sh'
```

That downloads pixi plus verilator/g++/yosys — 10–15 minutes. Or let the job do
it, with a generous time limit:

```bash
cd /work/NPU-Project
./slurm/submit.sh -c 6 -m 4G -t 45 ./slurm/jobs/regress.sh
```

`jobs/regress.sh` detects the missing toolchain and runs setup itself. Later
runs skip it.

Note the toolchain lands in the server user's `~/.cache`, **not** in `/work`, so
it does not interfere with your laptop's copy.

---

## Choosing `-c` and `-m`

**This is CPU work.** Verilator elaboration and the g++ compile of the generated
model are the entire cost. Never pass `-g`.

`chapple` has 12 CPUs and **~6 GB configured for Slurm** — memory binds before
cores do.

| Job | Flags |
|---|---|
| One small area | `-c 4 -m 2G -t 15` |
| One area, first run (toolchain) | `-c 6 -m 4G -t 45` |
| Whole tree | `-c 6 -m 6G -t 60` |

If a job is killed with `oom-kill` or `Exceeded job memory limit`, raise `-m`;
if that hits the node ceiling, lower `-c` instead — concurrent g++ processes are
what eat the RAM.

### The two parallelism knobs are not interchangeable

From the area Makefile's own documentation:

- **`make -j N`** overlaps *whole testbenches*. Only helps when `TBS` lists
  several.
- **`make JOBS=N`** parallelizes verilator's C++ compile of *one* testbench.

`sixteen_bit_adder` has exactly one testbench (`TBS := tb_sixteen_bit_adder`),
so `-j` buys nothing there and `JOBS` is the knob that matters.

Never multiply them. `make -j6 JOBS=6` spawns up to 36 compilers on a 6-core
allocation and will OOM this node.

### Scale to the allocation, not the machine

Inside a job script use `$SLURM_CPUS_PER_TASK`, never `$(nproc)`. `nproc`
reports all 12 host cores even when Slurm allocated 4.

---

## `jobs/regress.sh`

Use it when you want two things plain `submit.sh` doesn't do:

- bootstrap the toolchain on first run
- on failure, tail the failing `run.log` files into the job output

```bash
cd /work/NPU-Project
./slurm/submit.sh -c 6 -m 4G ./slurm/jobs/regress.sh
NPU_AREA=Design+DV/verif/cmn/multiplier ./slurm/submit.sh -c 6 -m 4G ./slurm/jobs/regress.sh
NPU_AREA=all ./slurm/submit.sh -c 6 -m 6G -t 60 ./slurm/jobs/regress.sh
```

For everyday runs in a single area, `submit.sh ... make JOBS=6 regress` is
simpler.

---

## Reading the result

`make regress` exits non-zero when any test fails — the rule ends in
`[ "$$f" -eq 0 ]`. So Slurm's job state agrees with the verdict.

The verdict rule: a test passes only if its log contains `TEST PASS` at the
start of a line. An assertion failure aborts the sim so the banner never prints
— and no `coverage.dat` is written, which is why `make cov` is untrustworthy
until failures are fixed.

Coverage and VCDs land in `Design+DV/verif/build/` on the shared filesystem, so
they're already visible from both machines.

---

## Everyday commands

```bash
squeue                      # the queue
squeue -u $USER             # just yours
scancel <jobid>             # kill one
scancel -u $USER            # kill all of yours
sinfo                       # node state
sinfo -R                    # why a node is down
scontrol show job <id>      # full detail
```

Queue several and walk away:

```bash
cd /work/NPU-Project
for a in cmn/flop cmn/four_bit_adder cmn/full_adder cmn/multiplier cmn/sixteen_bit_adder; do
    NPU_AREA="Design+DV/verif/$a" ./slurm/submit.sh -n -c 4 -m 2G ./slurm/jobs/regress.sh
done
squeue
```

`-n` means don't wait. Slurm runs them as the node frees up.

---

## Is this worth it?

Honestly, for `sixteen_bit_adder` alone: **no.** That regression takes seconds,
and your laptop has 16 cores against `chapple`'s 12.

It pays off for:

- **Whole-tree regressions** you don't want tying up the laptop
- **Queueing several runs** and letting Slurm serialize them
- **Reproducibility** — one pinned toolchain on one machine
- **Practice** for when the design and its runtime grow

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `[fail] ... is not on shared (NFS) storage` | You're outside `/work`. `cd` into the shared copy |
| Job fails instantly, chdir error | Same cause, if you used plain `sbatch` |
| `pinned toolchain missing at ...` | `toolchain.mk` came from another machine. Delete it on the server and re-run |
| `dependencies/pixi.lock changed since setup` | Expected after a lock change. Re-run `sh dependencies/setup.sh` on the server |
| First job times out | Toolchain download is 10–15 min. Use `-t 45` |
| `oom-kill` / `Exceeded job memory limit` | Raise `-m`, or lower `-c` |
| `verilator: command not found` | Toolchain setup didn't run — do it over SSH and read the error |
| Passes locally, fails on the server | Compare `verilator --version` in both places |
| Output file missing after the job | Job failed before starting — `sinfo -R` |
