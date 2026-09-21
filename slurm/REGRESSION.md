# Running `make regress` on the Cluster

Assumes `NEW-USER.md` is done: your tree lives at `/work/<you>/NPU-Project`
(or your old path, if you made the symlink in Part 3), and `sinfo` on your
laptop lists the `chapple` node. If `sinfo` fails with `Zero Bytes were
transmitted or received`, your Slurm client is the wrong version — see
`NEW-USER.md` Part 2. Nothing below works until that is fixed.

---

## The translation

Before:

```bash
cd Design+DV/verif/cmn/sixteen_bit_adder
make regress
```

On the cluster:

```bash
cd /work/<you>/NPU-Project/Design+DV/verif/cmn/sixteen_bit_adder
/work/<you>/NPU-Project/slurm/submit.sh -c 6 -m 4G make JOBS=6 regress
```

Same directory, same command — it just runs on `chapple` instead of here. The
log lands in that folder as `slurm-<jobid>.out`.

Put the scripts on your PATH to shorten it:

```bash
echo 'export PATH="/work/<you>/NPU-Project/slurm:$PATH"' >> ~/.bashrc
source ~/.bashrc

cd /work/<you>/NPU-Project/Design+DV/verif/cmn/sixteen_bit_adder
submit.sh -c 6 -m 4G make JOBS=6 regress
```

`make regress` still works normally on your laptop. Nothing here replaces it.

---

## First run: the toolchain

`dependencies/toolchain.mk` records an absolute path to the pinned pixi
toolchain and is gitignored, so it does not travel with the repo. Build it once
on the server:

```bash
ssh -t <you>@<ip> 'cd /work/<you>/NPU-Project && sh dependencies/setup.sh'
```

That downloads pixi plus verilator/g++/yosys — 10–15 minutes. Or let the job do
it, with a generous time limit:

```bash
cd /work/<you>/NPU-Project
./slurm/submit.sh -c 6 -m 4G -t 45 ./slurm/jobs/regress.sh
```

`jobs/regress.sh` detects the missing toolchain and runs setup itself. Later
runs skip it.

The toolchain lands inside your tree, in
`/work/<you>/NPU-Project/dependencies/.pixi`, so the same path works on the
compute node and on your laptop. (Only a checkout on a Windows drive, `/mnt/c`,
keeps its env in `~/.cache/rattler` instead.) Never copy a `toolchain.mk` from
another machine — delete it and re-run setup.

---

## Choosing `-c` and `-m`

**This is CPU work.** Verilator elaboration and the g++ compile of the generated
model are the entire cost. Never pass `-g`.

`chapple` has 12 CPUs and **5857 MB configured for Slurm** (`RealMemory`) —
memory binds before cores do. `-m 6G` is 6144 MB, more than the node has, and
is rejected with `Requested node configuration is not available`.

| Job | Flags |
|---|---|
| One small area | `-c 4 -m 2G -t 15` |
| One area, first run (toolchain) | `-c 6 -m 4G -t 45` |
| Whole tree | `-c 6 -m 5G -t 60` |

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
cd /work/<you>/NPU-Project
./slurm/submit.sh -c 6 -m 4G ./slurm/jobs/regress.sh
NPU_AREA=Design+DV/verif/cmn/multiplier ./slurm/submit.sh -c 6 -m 4G ./slurm/jobs/regress.sh
NPU_AREA=all ./slurm/submit.sh -c 6 -m 5G -t 60 ./slurm/jobs/regress.sh
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
scancel -u $USER            # kill all of yours (only safe on your own login)
sinfo                       # node state
sinfo -R                    # why a node is down
scontrol show job <id>      # full detail
```

Queue several and walk away:

```bash
cd /work/<you>/NPU-Project
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
| `Zero Bytes were transmitted or received` | Laptop Slurm client too far from the server's 23.11. Build a matching one (`NEW-USER.md` Part 2) |
| `Requested node configuration is not available` | Asked for more than the node has — `-m` above 5857 MB or `-c` above 12 |
| `submit.sh: Permission denied` | Lost its execute bit (git does not track it here). `chmod +x slurm/*.sh slurm/jobs/*.sh` |
| `[fail] ... is not on shared (NFS) storage` | You're outside `/work`. `cd` into the shared copy |
| Job fails instantly, chdir error | Same cause, if you used plain `sbatch` |
| `pinned toolchain missing at ...` | `toolchain.mk` came from another machine. Delete it on the server and re-run |
| `dependencies/pixi.lock changed since setup` | Expected after a lock change. Re-run `sh dependencies/setup.sh` on the server |
| First job times out | Toolchain download is 10–15 min. Use `-t 45` |
| `oom-kill` / `Exceeded job memory limit` | Raise `-m`, or lower `-c` |
| `verilator: command not found` | Toolchain setup didn't run — do it over SSH and read the error |
| Passes locally, fails on the server | Compare `verilator --version` in both places |
| Output file missing after the job | Job failed before starting — `sinfo -R` |
