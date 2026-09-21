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

### Step 1 — Your own server account (admin, one time)

**One login per person. Never share one.** Two people on the same login are the
same user to the server: `scancel -u $USER` cancels the other person's jobs,
`chmod` cannot keep you apart (you both own everything), and Slurm fairshare
counts you as one user.

Pick a UID that is free on the server *and* on every laptop that mounts `/work`
(`getent passwd <uid>` prints nothing on each). Avoid 1000 — it is what every
fresh Ubuntu/WSL install hands out, so it is the one that collides. Then ask
whoever administers `chapple` to run:

```bash
sudo adduser --uid <uid> <you>
sudo mkdir -p /work/<you> && sudo chown -R <uid>:<uid> /work/<you>
```

Install your key so every later command stops asking for a password:

```bash
ssh-copy-id <you>@<server-ip>
```

A remote command that uses `sudo` needs `ssh -t`, or sudo fails with
`a terminal is required to read the password`.

### Step 2 — Match your laptop UID to it

**Your laptop UID must equal your server UID.** NFS checks permissions by
number, not name. Compare `id -u` on your laptop with `ssh <you>@<server-ip> id -u`.
If they differ you get `Permission denied` writing to your own `/work/<you>`,
and `ls -lan /work` shows the owner as a bare number.

Do this **after** Step 1, never before: if you renumber your laptop while still
submitting jobs through someone else's login, those jobs run under the old UID
and can no longer write into your tree.

`usermod` refuses while any of your processes are running, so the change is
made from a root shell. First, in WSL:

```bash
sudo find / -xdev -uid $(id -u) -not -path "$HOME/*"   # stragglers outside home; usually none
sudo umount /work                                      # keep the chown well away from NFS
```

Then from Windows cmd or PowerShell:

```
wsl --shutdown
wsl -u root
```

In that root shell (`<old>` is the UID you had, usually 1000):

```bash
usermod -u <uid> <you> && groupmod -g <uid> <you> && find / -xdev \( -uid <old> -o -gid <old> \) -exec chown -h <uid>:<uid> {} + ; id <you>
```

Back in Windows: `wsl --shutdown`, then `wsl`. Verify:

```bash
id -u                                               # <uid>
sudo mount -a && findmnt -t nfs4                    # /work back
echo ok > /work/<you>/.probe && rm /work/<you>/.probe && echo "WRITE OK"
```

- `usermod -u` re-chowns your home directory itself; the `find` only sweeps up
  files elsewhere. `-xdev` stops it crossing into `/work` or `/mnt/c`.
- Nothing on `/mnt/c` needs chowning — Windows drives are drvfs and synthesize
  ownership, which is why everything there shows as 777.
- `sudo` still works afterward; group membership is by name.
- If anything goes wrong, `wsl -u root` gets you a root shell regardless.
- `/work` directories carry ACLs (the `+` in `ls -l`). `chown` does not rewrite
  named ACL entries, so have the admin check `getfacl /work/<you>` afterward.
- On native Linux the same `usermod`/`groupmod`/`find` applies; run it from a
  root console with your own account fully logged out.

### Step 3 — Get your copy into `/work`

Run the clone **on the server, as yourself**:

```bash
ssh <you>@<server-ip> 'git clone git@github.com:SebVettelsFan-05/NPU-Project.git /work/<you>/NPU-Project'
```

That needs a GitHub key *on the server*. Without one it fails with
`Host key verification failed`. The repo is public, so clone over HTTPS instead
and then point the remote back at SSH — pushes happen from your laptop, with
your laptop's key:

```bash
ssh <you>@<server-ip> 'git clone https://github.com/SebVettelsFan-05/NPU-Project.git /work/<you>/NPU-Project && git -C /work/<you>/NPU-Project remote set-url origin git@github.com:SebVettelsFan-05/NPU-Project.git'
```

**Or copy a tree you already have.** Only ~4 MB of a working tree is worth
copying; the rest is build output and a per-machine toolchain:

```bash
rsync -a --chmod=D755,F644 --exclude='Design+DV/verif/build/' --exclude='dependencies/.pixi/' --exclude='dependencies/bin/' --exclude='dependencies/toolchain.mk' --exclude='.*.sw[po]' --exclude='__pycache__/' /path/to/NPU-Project/ <you>@<server-ip>:/work/<you>/NPU-Project/
ssh <you>@<server-ip> 'cd /work/<you>/NPU-Project && git checkout -- models/__pycache__ && git status --short'
```

- **Never copy `dependencies/toolchain.mk`.** It hardcodes the absolute
  toolchain path of the machine that generated it; copied, jobs fail with
  `pinned toolchain missing`.
- `models/__pycache__/*.pyc` are tracked in git even though they are build
  output, so the `__pycache__` exclude makes them show as deleted — the
  `git checkout` restores them. `git status --short` should print nothing.
- Keep the command on one line. Pasting `\` line continuations into some
  terminals turns each into an escaped space, and rsync reports
  `link_stat ".../ " failed` for the phantom arguments.

Everyone works in their own directory and collaborates through git. Don't edit
someone else's directory.

### Step 4 — Build the toolchain (one time, ~10-15 min)

`dependencies/toolchain.mk` records an absolute path to the pinned pixi
toolchain and is gitignored, so it never arrives with a clone. Build it **on the
server**, from inside `/work` — the env then lands in
`/work/<you>/NPU-Project/dependencies/.pixi`, a path that resolves identically
on the compute node and on your laptop:

```bash
ssh -t <you>@<server-ip> 'cd /work/<you>/NPU-Project && sh dependencies/setup.sh'
```

Needs `curl`. If it fails with `curl: not found`, run `sudo apt install -y curl`.
(A checkout on a Windows drive, `/mnt/c/...`, keeps its env in
`~/.cache/rattler` instead — fine for local work, invisible to the node.)

---

## Part 2 — Client setup on your laptop

```bash
cd /work/<you>/NPU-Project/slurm    # or a local clone, if /work is not mounted yet
SHARED_DIR=/work SERVER_HOST=<server-ip> SERVER_USER=<you> ./setup-client.sh
```

This installs `slurm-client` and `munge`, copies the munge key and `slurm.conf`
from the server, and mounts `/work`.

Verify:

```bash
munge -n | unmunge     # STATUS: Success (0)
sinfo                  # shows the partition and node
findmnt -t nfs4        # shows /work mounted
```

If the script dies at the mount step with `Could not get lock
/var/lib/dpkg/lock-frontend`, `unattended-upgrades` is running — not a real
failure. Wait it out and finish by hand:

```bash
while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do sleep 5; done; sudo apt-get install -y nfs-common && sudo mkdir -p /work && sudo mount -t nfs4 <server-ip>:/work /work && findmnt -t nfs4
grep -qF '<server-ip>:/work' /etc/fstab || echo '<server-ip>:/work  /work  nfs4  defaults,_netdev,nofail  0  0' | sudo tee -a /etc/fstab
```

### If `sinfo` fails with `Zero Bytes were transmitted or received`

Your Slurm client and the server's slurmctld are too far apart in version. `apt`
installs whatever your Ubuntu release ships: the server (24.04) runs **23.11**,
while Ubuntu 26.04 ships **25.11** — four releases apart, beyond Slurm's
~two-release compatibility window. The TCP connection opens and is dropped, so
port 6817 tests open and munge still reports `Success (0)`. Compare:

```bash
sinfo --version ; ssh <you>@<server-ip> sinfo --version
```

If they are too far apart, skip the local client and submit on the server. The
files are the same through `/work`, and `slurm-<jobid>.out` lands in your tree
where you can `tail -f` it locally:

```bash
ssh <you>@<server-ip> 'cd /work/<you>/NPU-Project && sbatch -c 6 --mem=4G --time=45 --wrap="make JOBS=6 regress"'
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
scancel -u $USER            # all of yours (only safe on your own login)
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
| Toolchain | `/work/<you>/NPU-Project/dependencies/.pixi` (a `/mnt/c` checkout uses `~/.cache/rattler`) |

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
| `Zero Bytes were transmitted or received` | Client/server Slurm versions too far apart. Compare `sinfo --version`; submit over SSH (Part 2) |
| `Permission denied` writing to your own `/work/<you>` | Laptop UID differs from server UID — Part 1, Step 2 |
| `sudo: a terminal is required` over SSH | Use `ssh -t` |
| `Could not get lock /var/lib/dpkg/lock-frontend` | `unattended-upgrades` is running. Wait, then finish by hand (Part 2) |
| `git clone` on the server: `Host key verification failed` | Server has no GitHub key. Clone over HTTPS (Part 1, Step 3) |
| rsync `link_stat ".../ " failed` | Pasted `\` continuations became escaped spaces. Use one line |
| Jobs vanish that you didn't cancel | Someone shares your login and ran `scancel -u`. Get separate accounts (Part 1, Step 1) |
