# Slurm Cluster Setup — Server and Client

Sets up a Slurm cluster with an NFS shared directory, so submitting a job works
the way it does on an LSF cluster: **you `sbatch` from a folder and the job runs
in that folder.**

```
chapple  — Slurm controller + compute node + NFS server
   /work                        real disk, exported
      |
      |  NFS v4 over the LAN (port 2049)
      v
laptop (WSL)  — submit host
   /work                        SAME absolute path, mounted
```

| Script | Where | Purpose |
|---|---|---|
| `setup-server.sh` | server | Slurm controller + compute node + NFS export |
| `setup-client.sh` | client | Slurm client tools + NFS mount |
| `submit.sh` | client or server | run a command as a job in the current directory |
| `jobs/regress.sh` | — | regression wrapper (toolchain bootstrap + failure logs) |

---

## The one rule

**The shared path must be byte-identical on both machines.** Not equivalent —
the same string.

Slurm records your working directory at submit time and hands it to the compute
node verbatim. If `/work/NPU-Project` exists on both, the job just works. If you
export `/home/chapple` and mount it at `/home/daniel`, the paths differ and the
job dies with a chdir error.

That is the entire mechanism behind LSF's behavior: those clusters NFS-mount
your home directory on every node, so "the same folder" exists everywhere.

Everything outside the shared directory is invisible to the compute node.

---

## What you need

| Requirement | Notes |
|---|---|
| Server: Ubuntu 22.04/24.04, sudo | Not Windows. |
| Server: a LAN IP | The script rejects a host that only resolves to `127.0.1.1`. |
| Client: Linux or WSL | No native Windows Slurm client. |
| Network route between them | Same LAN or VPN. |
| SSH from client to server | Used to copy the munge key and config. |
| **Matching numeric UID** | Slurm *and* NFS key on UID, not username. |

A GPU is **optional**. RTL simulation and builds are CPU work; the scripts
detect zero GPUs and configure a CPU-only cluster without complaint.

---

## Server setup

```bash
cd /path/to/NPU-Project/slurm
chmod +x setup-server.sh
./setup-server.sh
```

Options:

```bash
SHARED_DIR=/work ./setup-server.sh      # exported path (default /work)
GPU_TYPE=w6400 ./setup-server.sh        # label GPUs -> --gres=gpu:w6400:1
MEM_MARGIN=4000 ./setup-server.sh       # hold back more RAM from Slurm
NO_NFS=1 ./setup-server.sh              # Slurm only, no export
```

Idempotent — re-run after adding a GPU or changing RAM. Your previous
`slurm.conf` is saved to `slurm.conf.bak`.

It prints the **server IP** at the end. The client needs it.

### Then move the repo into the shared directory

This is the step that makes everything else work:

```bash
git clone <url> /work/NPU-Project
# or move an existing copy:
mv ~/NPU-Project /work/
```

### What the server script does

1. **Hostname** — ensures it resolves to a LAN IP, stripping `127.0.1.1`.
2. **Munge** — installs it and forces the exact permissions it demands
   (`0700` dirs, `0400` key). It silently refuses to start otherwise.
3. **Slurm** — installs `slurm-wlm`, plus `libpmix2` to silence harmless
   "cannot load PMIx library" errors.
4. **GPU detection** — counts `/dev/dri/renderD*` and configures exactly that
   many. Zero is a supported outcome.
5. **Hardware** — takes the authoritative node line from `slurmd -C`, then
   subtracts a memory margin.
6. **Config** — writes `slurm.conf`, `gres.conf`, `cgroup.conf`.
7. **NFS** — exports `SHARED_DIR` to the local `/24`, starts `nfs-server`.
8. **Firewall, start, verify** — opens 6817/6818/2049, starts both daemons,
   runs a test job.

---

## Client setup

Get the server's IP first (`hostname -I` on the server), then:

```bash
chmod +x setup-client.sh submit.sh
SERVER_HOST=192.168.2.245 SERVER_USER=chapple ./setup-client.sh
```

You'll be prompted for the server's SSH password, and once for its sudo
password — the munge key is `0400 munge:munge` and unreadable otherwise.

Options:

```bash
SHARED_DIR=/work ./setup-client.sh   # must match the server exactly
NO_NFS=1 ./setup-client.sh           # Slurm client only, no mount
```

### What the client script does

1. **Reachability** — fails fast on a wrong IP instead of hanging in a later scp.
2. **WSL** — disables `/etc/hosts` regeneration, which otherwise drops the
   server entry on every boot.
3. **Packages** — `slurm-client`, not `slurm-wlm`: no `slurmd`, so the laptop
   never advertises itself as a compute node.
4. **Munge key** — stages it with sudo on the server, copies it, verifies the
   md5 matches.
5. **slurm.conf** — copies it verbatim; it must be identical cluster-wide.
6. **UID check** — warns loudly on a mismatch.
7. **NFS mount** — mounts `SHARED_DIR` at the same path, adds an fstab entry
   with `nofail`, then writes a probe file and confirms the server sees it.

### Verify

```bash
munge -n | unmunge     # STATUS: Success (0)
sinfo                  # shows the partition and node
findmnt -t nfs4        # shows the shared mount
touch /work/hello && ssh chapple@<ip> 'ls /work/hello'
```

---

## Using it

From anywhere inside the shared directory:

```bash
cd /work/NPU-Project/Design+DV/verif/cmn/sixteen_bit_adder
/work/NPU-Project/slurm/submit.sh -c 6 -m 4G make JOBS=6 regress
```

The job runs in that folder and `slurm-<jobid>.out` lands there — visible from
both machines immediately. No sync, no fetch.

Plain `sbatch` works the same way:

```bash
sbatch --cpus-per-task=6 --mem=4G --wrap="make JOBS=6 regress"
```

See `REGRESSION.md` for running this repo's verification specifically.

---

## Details that matter

**`RealMemory` must be below actual RAM.** If the configured value exceeds what
the node reports at runtime, Slurm marks it DRAIN with "Low RealMemory". The
script reserves 2 GB; raise `MEM_MARGIN` if it drains anyway.

**`cons_tres`, not `cons_res`.** Required to treat a GPU as a consumable
resource; with the older plugin a GPU request locks the whole node.

**`AccountingStorageTRES=gres/gpu` is fatal without slurmdbd.** `slurmctld`
exits with *"slurmdbd is required to run with TRES gres/gpu"*. Omitted
deliberately — you lose historical usage accounting, not scheduling.

**`renderD*`, never `card*`.** `/dev/dri/card*` is the display interface;
`renderD*` is compute. Pointing `gres.conf` at `card*` looks right and isolates
nothing.

**`/dev/kfd` is never a GRES.** One shared device every ROCm process needs;
listing it would let one job lock out all others.

**NFSv4 needs only port 2049** — no rpcbind/portmapper zoo like v3.

**WSL2 NAT changes the client IP.** From the server's view your traffic comes
from the **Windows host's** LAN address, not WSL's internal `172.x` one. That is
why the export allows the whole `/24`. Windows 11 also supports
`networkingMode=mirrored` in `.wslconfig`, which gives WSL the host's IP.

**NFS performance is fine here** because the job runs on `chapple`, which *is*
the NFS server — Verilator's thousands of small writes happen at local disk
speed. Only editing traffic crosses the network. This would be a different
conversation with a third machine as the compute node.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Node `drain`, "Low RealMemory" | Raise `MEM_MARGIN`, re-run |
| `fatal: slurmdbd is required to run with TRES gres/gpu` | Remove `AccountingStorageTRES` |
| `fatal: can't stat gres.conf file /dev/dri/renderDxxx` | Device doesn't exist — `ls /dev/dri/` |
| `Node configuration differs from hardware` | `sudo slurmd -C`, copy its line into slurm.conf |
| munge "Invalid credential" | Keys differ, or clock skew. Compare `sudo md5sum /etc/munge/munge.key` |
| munge fails after laptop sleeps (WSL) | Clock drift: `sudo hwclock -s` |
| `mpi/pmix: can not load PMIx library` | Cosmetic. `sudo apt install libpmix2` |
| `Could not open node state file` | Normal on first start |
| `sinfo` hangs | Port 6817 blocked: `sudo ufw allow 6817/tcp` |
| Job fails instantly, chdir error | Submitted from outside the shared dir |
| NFS mount fails | `sudo exportfs -v` on the server; check port 2049 and the subnet |
| Mount gone after restart | `sudo mount -a` (fstab entry uses `nofail`) |
| Files owned by the wrong user | UID mismatch — `id -u` on both, fix with `usermod -u` |
| `Permission denied` writing to `/etc/...` | `>` runs as *you*. Use `sudo tee` |
| Interactive `srun` hangs | Expected on WSL/NAT. Use `sbatch`/`submit.sh` |

After any manual config edit:

```bash
sudo systemctl restart slurmctld slurmd
sudo scontrol reconfigure
```

---

## Adding a second compute node later

1. Same Ubuntu version, **matching UIDs**.
2. Every node's `/etc/hosts` lists every other node.
3. Copy `/etc/munge/munge.key` — identical bytes, `munge:munge`, `0400`. The #1
   multi-node failure.
4. `slurm.conf` and `cgroup.conf` byte-identical cluster-wide.
5. One `NodeName=` line per node, plus that node's `gres.conf` entries.
6. Workers install `slurm-wlm` and run **`slurmd` only**.
7. Mount the NFS share at the same path there too — now mandatory rather than a
   convenience, since Slurm does not move files between nodes.
