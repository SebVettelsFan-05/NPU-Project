# New User Guide — Getting Onto the Cluster

For someone joining the `chapple` cluster. Assumes the server is already set up
(see `SETUP.md`); this covers your own account, your own work directory, and the
commands you will actually use.

---

## Part 1 — Your work directory

Everyone gets a subdirectory under `/work`, the NFS share. Keep your tree
inside it: anything outside `/work` is invisible to the compute node, and jobs
submitted from elsewhere die with a chdir error.

```
/work/daniel/NPU-Project      <- yours
/work/alice/NPU-Project       <- theirs
```

### On the server (one time)

Ask whoever administers `chapple` to run:

```bash
sudo mkdir -p /work/<you>
sudo chown <you>:<you> /work/<you>
```

**UIDs must match between your laptop and the server.** NFS maps by numeric UID,
not username — if two people are both uid 1000, they will see and overwrite each
other's files. Check with `id -u` on both machines and have the admin assign
distinct UIDs.

### Clone your copy

```bash
git clone git@github.com:SebVettelsFan-05/NPU-Project.git /work/<you>/NPU-Project
```

Everyone works in their own clone and collaborates through git. Don't edit
someone else's directory.

### Build the toolchain (one time, ~10-15 min)

The pinned pixi toolchain is per-machine — `dependencies/toolchain.mk` records
an absolute path into a local cache and is gitignored, so it never arrives with
a clone.

```bash
cd /work/<you>/NPU-Project
sh dependencies/setup.sh
```

Needs `curl`. If it fails with `curl: not found`, run `sudo apt install -y curl`.

---

## Part 2 — Client setup on your laptop

```bash
cd /work/<you>/NPU-Project/slurm    # or a local clone, if /work is not mounted yet
SHARED_DIR=/work SERVER_HOST=<server-ip> SERVER_USER=<server-login> ./setup-client.sh
```

This installs `slurm-client` and `munge`, copies the munge key and `slurm.conf`
from the server, and mounts `/work`.

Verify:

```bash
munge -n | unmunge     # STATUS: Success (0)
sinfo                  # shows the partition and node
findmnt -t nfs4        # shows /work mounted
```

---

## Part 3 — The symlink (optional, WSL/Linux)

Your files now live in `/work/<you>/NPU-Project`. If you would rather keep using
a familiar path — an existing project folder, say — put a symlink there:

```bash
cd /path/to/your/old/location
mv NPU-Project NPU-Project.bak            # keep the original as a backup
ln -s /work/<you>/NPU-Project NPU-Project
cd NPU-Project && pwd -P                  # MUST print /work/<you>/NPU-Project
```

That `pwd -P` check is the important one. `cd` through a symlink and the kernel
reports the resolved path, so `sbatch` records `/work/<you>/NPU-Project/...` —
which exists on the compute node. That is what makes submitting from the old
path work.

### What the symlink does and does not do

- It **does** let you keep your old path and muscle memory.
- It **does not** keep two copies in sync. The files live in `/work`; the old
  path is a signpost. There is no configuration where files sit on a local disk
  *and* the server sees them live.

### If your old path is on a Windows drive (WSL)

Works for WSL tools — terminal, git, VS Code Remote-WSL. **Windows-native tools
break**, because Explorer and Windows-side VS Code cannot resolve a symlink
pointing at a Linux path. Use `\\wsl.localhost\<distro>\work\<you>\NPU-Project`
from Windows instead.

Two gotchas:

- **`mv` fails with "Permission denied"** — a Windows process has the folder
  open. Close VS Code and any Explorer window there, then retry. Pause OneDrive
  if it still refuses.
- **Keep `NPU-Project.bak`** until you have successfully run `git push` from the
  new path.

### Git still works

```bash
cd /path/to/your/old/location/NPU-Project   # resolves to /work/<you>/NPU-Project
git status && git add -A && git commit -m "..." && git push
```

Git runs on your laptop, reads the files over NFS, and uses your normal SSH key.
Run it from WSL, not from a Windows git client. The mount must be up.

---

## Part 4 — Basic Slurm commands

### Submitting

```bash
# run a command as a job, in the current directory
sbatch --cpus-per-task=6 --mem=4G --time=30 --wrap="make JOBS=6 regress"

# run a job script
sbatch myjob.sh

# the wrapper: submit, wait, print the log
/work/<you>/NPU-Project/slurm/submit.sh -c 6 -m 4G make JOBS=6 regress
```

The job runs in the directory you submitted from, and output lands there as
`slurm-<jobid>.out`. That only holds inside `/work`.

A job script with its resources baked in:

```bash
#!/bin/bash
#SBATCH --job-name=regress
#SBATCH --cpus-per-task=6
#SBATCH --mem=4G
#SBATCH --time=30

make JOBS=$SLURM_CPUS_PER_TASK regress
```

### Common flags

| Flag | Meaning |
|---|---|
| `--cpus-per-task=N` / `-c N` | CPU cores |
| `--mem=4G` | memory (job is killed if it exceeds this) |
| `--time=30` | minutes; the job is killed at the limit |
| `--job-name=NAME` / `-J` | name shown in `squeue` |
| `--output=FILE` | log file (`%j` = job id, `%x` = job name) |
| `--gres=gpu:1` | request a GPU (not needed for RTL work) |
| `--wrap="CMD"` | run a command instead of a script |

### Watching

```bash
squeue                      # everyone's queue
squeue -u $USER             # just yours
squeue -j 42                # one job
tail -f slurm-42.out        # follow the log live
scontrol show job 42        # full detail: why pending, what it got
```

`ST` column: `R` running, `PD` pending, `CG` completing. The `NODELIST(REASON)`
column says *why* a job is pending — `(Resources)` means it is waiting for a
free CPU/GPU/memory, which is normal.

### Cancelling

```bash
scancel 42                  # one job
scancel -u $USER            # all of yours
scancel --name=regress      # by name
```

### The cluster

```bash
sinfo                       # partitions and node states
sinfo -R                    # WHY a node is down or drained
sinfo -N -l                 # per-node detail: cpus, memory, state
scontrol show node chapple  # everything about a node
```

Node states: `idle` free, `mix` partly used, `alloc` full, `drain`/`down`
unavailable — `sinfo -R` gives the reason.

### Interactive

```bash
srun --pty bash             # a shell on the compute node
srun -c 4 --mem=2G hostname # run one command, output to your terminal
```

`srun` streams output to your terminal, unlike `sbatch`. **It usually hangs from
WSL**, because WSL2 sits behind NAT and the compute node cannot connect back.
Use `sbatch` there.

---

## Part 5 — Choosing resources

This is CPU work. Verilator elaboration and the g++ compile of the generated
model are the whole cost — never request a GPU for it.

`chapple` has 12 CPUs and ~5.8 GB available to Slurm, so **memory binds before
cores do.**

| Job | Flags |
|---|---|
| One small area | `-c 4 --mem=2G --time=15` |
| One area, first run (toolchain) | `-c 6 --mem=4G --time=45` |
| Whole tree | `-c 6 --mem=5G --time=60` |

Killed with `oom-kill` or `Exceeded job memory limit`? Raise `--mem`; if that
hits the node ceiling, lower `-c` instead — concurrent g++ processes are what
eat the RAM.

**Scale to the allocation, not the machine.** Inside a job use
`$SLURM_CPUS_PER_TASK`, never `$(nproc)` — `nproc` reports all 12 host cores
even when Slurm gave you 4.

**The two make knobs are not interchangeable** (see the area Makefile):

- `make -j N` overlaps whole testbenches — only helps when `TBS` lists several
- `make JOBS=N` parallelizes verilator's C++ compile of one testbench

Never multiply them. `-j6 JOBS=6` spawns up to 36 compilers on 6 cores.

---

## Part 6 — Where things are

| What | Where |
|---|---|
| Your tree | `/work/<you>/NPU-Project` |
| Job logs | `slurm-<jobid>.out`, in the directory you submitted from |
| Build output | `Design+DV/verif/build/<tb_name>/` — shared across areas |
| Per-test log | `Design+DV/verif/build/<tb_name>/run.log` |
| Coverage | `Design+DV/verif/build/<tb_name>/coverage.dat` |
| Toolchain | the server user's `~/.cache/rattler`, **not** in `/work` |

A test passes only if `run.log` contains `TEST PASS` at the start of a line. An
assertion failure aborts the sim, so the banner never prints and no
`coverage.dat` is written — which is why `make cov` is untrustworthy until
failures are fixed.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Job fails instantly, chdir error | Submitted from outside `/work` |
| `Invalid credential` | munge key differs, or clock skew. On WSL: `sudo hwclock -s` |
| `sinfo` hangs | Port 6817 blocked, or slurmctld down |
| `/work` empty | Mount dropped: `sudo mount -a` |
| `mount.nfs4: Operation not permitted` | Export needs `insecure` (WSL2 NAT uses a high source port) |
| Job pending, `(Resources)` | Normal — waiting for a free slot |
| Job pending, `(PartitionNodeLimit)` | You asked for more CPU/memory than the node has |
| `oom-kill` | Raise `--mem` or lower `-c` |
| `verilator: command not found` | Toolchain not built: `sh dependencies/setup.sh` |
| `pinned toolchain missing` | `toolchain.mk` came from another machine — delete it and re-run setup |
| `mv: Permission denied` on Windows | VS Code or Explorer holds the folder. Close them |
| `srun` hangs on WSL | Expected (NAT). Use `sbatch` |
