#!/usr/bin/env bash
#
# harden_locally.sh
#
# Sets up and runs the Tiny Tapeout local hardening flow (LibreLane) for a
# SKY130 project. Based on: https://tinytapeout.com/guides/local-hardening/
#
# Usage:
#   Run this from anywhere. It will operate on the project directory you
#   point PROJECT_DIR at below (defaults to the current directory).
#
#   First run:   ./harden_locally.sh setup    # one-time environment setup
#   Then:        ./harden_locally.sh harden   # run/re-run hardening
#   Also:        ./harden_locally.sh warnings # print synthesis/clock warnings
#                ./harden_locally.sh klayout  # open result in KLayout
#                ./harden_locally.sh openroad # open result in OpenROAD GUI
#                ./harden_locally.sh png      # export gds_render.png
#
set -euo pipefail
 
# ---- Config -----------------------------------------------------------
PROJECT_DIR="${PROJECT_DIR:-$(pwd)}"
TTSETUP_DIR="${TTSETUP_DIR:-$HOME/ttsetup}"
VENV_DIR="$TTSETUP_DIR/venv"
PDK_ROOT_DIR="$TTSETUP_DIR/pdk"
 
export PDK_ROOT="$PDK_ROOT_DIR"
export PDK="sky130A"
export LIBRELANE_TAG="3.0.3"   # check TinyTapeout/tt-gds-action action.yml for the latest
 
# ---- Helpers ------------------------------------------------------------
log() { echo -e "\033[1;32m==>\033[0m $*"; }
err() { echo -e "\033[1;31mERROR:\033[0m $*" >&2; }
 
check_prereqs() {
    log "Checking prerequisites..."
 
    if ! command -v python3 &>/dev/null; then
        err "python3 not found. Install Python 3.11+ first."
        exit 1
    fi
 
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 11) )); then
        err "Python $PY_VER found, but 3.11+ is required. Consider using 'uv' instead."
        exit 1
    fi
    log "Python $PY_VER OK"
 
    if ! command -v docker &>/dev/null; then
        err "Docker not found. Install and start Docker before hardening."
        exit 1
    fi
    if ! docker info &>/dev/null; then
        err "Docker is installed but not running (or you lack permissions). Start it and try again."
        exit 1
    fi
    log "Docker OK"
 
    if [ ! -f "$PROJECT_DIR/info.yaml" ]; then
        err "No info.yaml found in $PROJECT_DIR. Set PROJECT_DIR to your project's root."
        exit 1
    fi
    log "Project directory OK: $PROJECT_DIR"
}
 
do_setup() {
    check_prereqs
 
    log "Cloning tt-support-tools into project as ./tt ..."
    if [ -d "$PROJECT_DIR/tt" ]; then
        log "  ./tt already exists, pulling latest instead of re-cloning"
        git -C "$PROJECT_DIR/tt" pull
    else
        git clone https://github.com/TinyTapeout/tt-support-tools "$PROJECT_DIR/tt"
    fi
 
    log "Creating Python virtual environment at $VENV_DIR ..."
    mkdir -p "$TTSETUP_DIR"
    python3 -m venv "$VENV_DIR"
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
 
    log "Installing tt-support-tools requirements..."
    pip install --upgrade pip
    pip install -r "$PROJECT_DIR/tt/requirements.txt"
 
    log "Installing LibreLane ($LIBRELANE_TAG)..."
    pip install "librelane==$LIBRELANE_TAG"
 
    log "Setup complete."
    log "PDK_ROOT=$PDK_ROOT  PDK=$PDK  LIBRELANE_TAG=$LIBRELANE_TAG"
    log "Next: ./harden_locally.sh harden"
}
 
activate_venv() {
    if [ ! -f "$VENV_DIR/bin/activate" ]; then
        err "Virtual environment not found at $VENV_DIR. Run: ./harden_locally.sh setup"
        exit 1
    fi
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
}
 
do_harden() {
    check_prereqs
    activate_venv
 
    cd "$PROJECT_DIR"
 
    log "Generating LibreLane user config..."
    ./tt/tt_tool.py --create-user-config
 
    log "Hardening project (this can take a while, ~10 min for a small design)..."
    ./tt/tt_tool.py --harden
 
    log "Hardening complete. Results are under $PROJECT_DIR/runs/"
    log "Tip: run './harden_locally.sh warnings' to check for synthesis/clock warnings."
}
 
do_warnings() {
    activate_venv
    cd "$PROJECT_DIR"
    ./tt/tt_tool.py --print-warnings
}
 
do_klayout() {
    activate_venv
    cd "$PROJECT_DIR"
    log "If the GUI fails with a display error, run: xhost +local:docker"
    ./tt/tt_tool.py --open-in-klayout
}
 
do_openroad() {
    activate_venv
    cd "$PROJECT_DIR"
    log "If the GUI fails with a display error, run: xhost +local:docker"
    ./tt/tt_tool.py --open-in-openroad
}
 
do_png() {
    activate_venv
    cd "$PROJECT_DIR"
 
    if ! dpkg -s librsvg2-bin &>/dev/null || ! dpkg -s pngquant &>/dev/null; then
        log "Installing required packages (librsvg2-bin, pngquant)..."
        sudo apt install -y librsvg2-bin pngquant
    fi
 
    ./tt/tt_tool.py --create-png
    log "Render exported to $PROJECT_DIR/gds_render.png"
}
 
# ---- Main -----------------------------------------------------------
CMD="${1:-}"
 
case "$CMD" in
    setup)
        do_setup
        ;;
    harden)
        do_harden
        ;;
    warnings)
        do_warnings
        ;;
    klayout)
        do_klayout
        ;;
    openroad)
        do_openroad
        ;;
    png)
        do_png
        ;;
    *)
        echo "Usage: $0 {setup|harden|warnings|klayout|openroad|png}"
        echo ""
        echo "  setup     One-time environment setup (venv, tt-support-tools, LibreLane)"
        echo "  harden    Generate config and run the hardening flow (synthesis -> GDS)"
        echo "  warnings  Print synthesis/clock warnings from the last hardening run"
        echo "  klayout   Open the hardened design in KLayout"
        echo "  openroad  Open the hardened design in the OpenROAD GUI"
        echo "  png       Export a PNG render of the hardened GDS"
        echo ""
        echo "Environment overrides:"
        echo "  PROJECT_DIR   Path to your Tiny Tapeout project (default: current directory)"
        echo "  TTSETUP_DIR   Path to store venv/PDK (default: \$HOME/ttsetup)"
        exit 1
        ;;
esac
 

