#!/usr/bin/env bash
#
# setup-client.sh — submit host: Slurm client tools + the NFS mount.
#
# Run ON the client (laptop / WSL). Jobs EXECUTE on the server; this box only
# submits. With NFS mounted at the same path on both machines, `sbatch` from a
# shared directory behaves exactly like LSF's `bsub`: the job runs in the
# folder you submitted from.
#
#   SERVER_HOST=192.168.2.245 SERVER_USER=<you> ./setup-client.sh
#
# The client's Slurm must be close to the server's version (server: 23.11).
# A newer Ubuntu's slurm-client fails with "Zero Bytes were transmitted or
# received"; build a matching client instead -- see NEW-USER.md Part 2.
#
# Options:
#   SHARED_DIR=/work   must match the server's export exactly
#   NO_NFS=1           Slurm client only, skip the mount
#
set -euo pipefail

SERVER_HOST="${SERVER_HOST:-}"
SERVER_USER="${SERVER_USER:-}"
SERVER_NAME="${SERVER_NAME:-}"
SHARED_DIR="${SHARED_DIR:-/work}"
NO_NFS="${NO_NFS:-0}"

say()  { printf '\n\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

[[ -z "$SERVER_HOST" ]] && die "Set SERVER_HOST=<ip>  ('hostname -I' on the server)."
[[ -z "$SERVER_USER" ]] && die "Set SERVER_USER=<login>."
sudo -v || die "sudo required."

SSH="ssh -o ConnectTimeout=10 ${SERVER_USER}@${SERVER_HOST}"

# ------------------------------------------------------- 1. reachability first
# Fail loudly here: a wrong IP otherwise surfaces as a multi-minute hang inside
# a later scp, which is miserable to diagnose.
say "Testing connectivity to $SERVER_HOST"
ping -c 2 -W 3 "$SERVER_HOST" >/dev/null 2>&1 || warn "ping failed (may be firewalled) — continuing"
$SSH true 2>/dev/null || die "Cannot SSH to ${SERVER_USER}@${SERVER_HOST}.
    Check the IP ('hostname -I' on the server), that sshd is running there,
    and that you can reach it. On a first connection run '$SSH hostname' once
    and accept the host key prompt interactively."
[[ -z "$SERVER_NAME" ]] && SERVER_NAME=$($SSH hostname)
echo "    connected; server node name is '$SERVER_NAME'"

# ------------------------------------------------------------- 2. WSL handling
IS_WSL=0
if grep -qi microsoft /proc/version 2>/dev/null; then
    IS_WSL=1
    say "WSL detected"
    # WSL2 regenerates /etc/hosts every boot, silently dropping our entry.
    if ! grep -q 'generateHosts' /etc/wsl.conf 2>/dev/null; then
        printf '[network]\ngenerateHosts = false\n' | sudo tee -a /etc/wsl.conf >/dev/null
        echo "    disabled /etc/hosts regeneration (effective after 'wsl --shutdown')"
    fi
fi

# --------------------------------------------------------- 3. name resolution
say "Adding '$SERVER_NAME' to /etc/hosts"
sudo sed -i "/[[:space:]]${SERVER_NAME}\$/d" /etc/hosts
echo "${SERVER_HOST}    ${SERVER_NAME}" | sudo tee -a /etc/hosts >/dev/null
getent hosts "$SERVER_NAME" | sed 's/^/    /'

# ---------------------------------------------------------------- 4. packages
# slurm-client, NOT slurm-wlm: no slurmd, so this laptop never advertises
# itself as a compute node.
say "Installing slurm-client and munge"
sudo apt-get update -qq
sudo apt-get install -y -qq slurm-client munge

# -------------------------------------------------------------- 5. munge key
# Must be byte-identical everywhere. It is 0400 munge:munge on the server, so
# plain scp cannot read it — stage it with sudo, then copy the staged file.
# (Piping 'ssh -t ... | ...' would need CR stripping; staging avoids that.)
say "Copying munge key from server"
echo "    (you may be prompted for the server's sudo password)"
TMP_REMOTE="/tmp/.mungekey.$$.b64"
TMP_LOCAL=$(mktemp)
trap 'rm -f "$TMP_LOCAL"; $SSH "rm -f $TMP_REMOTE" 2>/dev/null || true' EXIT

ssh -t "${SERVER_USER}@${SERVER_HOST}" \
    "sudo base64 /etc/munge/munge.key > $TMP_REMOTE && chmod 600 $TMP_REMOTE" \
    || die "Could not stage the munge key on the server."
scp -q "${SERVER_USER}@${SERVER_HOST}:$TMP_REMOTE" "$TMP_LOCAL" || die "Could not copy the staged key."
[[ -s "$TMP_LOCAL" ]] || die "Staged key came back empty."

sudo base64 -d "$TMP_LOCAL" | sudo tee /etc/munge/munge.key >/dev/null
sudo chown munge:munge /etc/munge/munge.key
sudo chmod 0400 /etc/munge/munge.key
LOCAL_MD5=$(sudo md5sum /etc/munge/munge.key | awk '{print $1}')
REMOTE_MD5=$($SSH 'sudo -n md5sum /etc/munge/munge.key 2>/dev/null' | awk '{print $1}' || true)
[[ -n "$REMOTE_MD5" && "$LOCAL_MD5" != "$REMOTE_MD5" ]] \
    && die "munge key MISMATCH (local $LOCAL_MD5 vs remote $REMOTE_MD5). Re-run."
echo "    key installed, md5 $LOCAL_MD5"

sudo systemctl enable --now munge
sudo systemctl restart munge
sleep 1
munge -n | unmunge >/dev/null 2>&1 \
    || die "munge self-test failed. On WSL check the clock first: sudo hwclock -s"
echo "    munge OK"

# -------------------------------------------------------------- 6. slurm.conf
# Must be IDENTICAL cluster-wide, not merely similar. Never hand-edit locally.
say "Copying slurm.conf from server"
sudo mkdir -p /etc/slurm
scp -q "${SERVER_USER}@${SERVER_HOST}:/etc/slurm/slurm.conf" "$TMP_LOCAL"
sudo cp "$TMP_LOCAL" /etc/slurm/slurm.conf
sudo chmod 644 /etc/slurm/slurm.conf
echo "    installed"

# -------------------------------------------------------------- 7. UID check
# Slurm and NFS both key on the NUMERIC UID, not the username.
say "Checking UID alignment"
LOCAL_UID=$(id -u); REMOTE_UID=$($SSH 'id -u')
echo "    local  $USER = $LOCAL_UID"
echo "    remote $SERVER_USER = $REMOTE_UID"
if [[ "$LOCAL_UID" != "$REMOTE_UID" ]]; then
    warn "UID MISMATCH — jobs will be rejected and NFS files will have wrong ownership."
    warn "Fix on one side: sudo usermod -u <uid> <user>   (then chown their files)"
elif [[ "$USER" != "$SERVER_USER" ]]; then
    warn "Same UID, different names ('$USER' vs '$SERVER_USER'). Harmless here;"
    warn "files show as '$USER' locally and '$SERVER_USER' on the server."
fi

# ------------------------------------------------------------------- 8. NFS
if [[ "$NO_NFS" != "1" ]]; then
    say "Mounting $SHARED_DIR from $SERVER_HOST"
    # THE RULE: identical absolute path on both machines. Slurm hands the
    # compute node your submit-time CWD verbatim; a different path there means
    # an instant chdir failure. This is exactly what LSF clusters give you via
    # NFS-mounted homes.
    sudo apt-get install -y -qq nfs-common
    sudo mkdir -p "$SHARED_DIR"

    if mountpoint -q "$SHARED_DIR"; then
        echo "    already mounted"
    else
        sudo mount -t nfs4 "${SERVER_HOST}:${SHARED_DIR}" "$SHARED_DIR" \
            || die "Mount failed.
    Check on the server: sudo exportfs -v ; sudo systemctl status nfs-server
    Check the firewall:   sudo ufw allow from <subnet> to any port 2049 proto tcp
    Note WSL2 NAT: the server sees your WINDOWS host IP, not WSL's 172.x address,
    which is why the export allows the whole /24."
        echo "    mounted"
    fi

    # nofail/_netdev so the client still boots when the server is off.
    FSTAB="${SERVER_HOST}:${SHARED_DIR}  ${SHARED_DIR}  nfs4  defaults,_netdev,nofail  0  0"
    if ! grep -qF "${SERVER_HOST}:${SHARED_DIR}" /etc/fstab 2>/dev/null; then
        echo "$FSTAB" | sudo tee -a /etc/fstab >/dev/null
        echo "    added to /etc/fstab"
    fi

    say "Testing shared write"
    PROBE="$SHARED_DIR/.probe.$$"
    if echo ok > "$PROBE" 2>/dev/null; then
        $SSH "test -f '$PROBE'" \
            && echo "    OK — the server sees files written here" \
            || warn "wrote locally but the server cannot see it; check the export"
        rm -f "$PROBE"
    else
        warn "cannot write to $SHARED_DIR — check ownership (should be UID $LOCAL_UID)"
    fi
fi

# ---------------------------------------------------------------- 9. verify
say "Verifying cluster access"
sinfo || die "sinfo failed.
    Check: slurmctld running on the server, port 6817 open, munge keys match."

cat <<EOF

$(printf '\033[1;32m==> Client ready\033[0m')

Work inside $SHARED_DIR and submit like LSF — the job runs in the
directory you submit from, and output lands right there:

    cd $SHARED_DIR/NPU-Project/Design+DV/verif/cmn/sixteen_bit_adder
    ../../../../slurm/submit.sh -c 6 -m 4G make JOBS=6 regress

Anything OUTSIDE $SHARED_DIR is not visible to the server and will
fail with a chdir error.
EOF

if (( IS_WSL )); then
cat <<'EOF'

WSL notes:
  * Interactive 'srun' will likely hang — WSL2 is behind NAT, so the compute
    node cannot connect back. Use sbatch / submit.sh.
  * If munge starts failing after the laptop sleeps, the clock drifted:
    sudo hwclock -s
  * If the NFS mount is missing after a restart: sudo mount -a
EOF
fi
