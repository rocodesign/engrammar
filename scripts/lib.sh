#!/bin/bash
# Shared helpers for Engrammar repo scripts
# Usage: source "$SCRIPT_DIR/lib.sh"

# ─── Repo root ────────────────────────────────────────────────────────────────
get_repo_root() {
    cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd
}

# ─── OS detection ─────────────────────────────────────────────────────────────
detect_os() {
    local os
    os="$(uname -s)"
    case "$os" in
        MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=true ;;
        *)                     IS_WINDOWS=false ;;
    esac
}

# ─── Python 3.10+ finder ─────────────────────────────────────────────────────
find_python() {
    PYTHON_BIN=""
    for py in python3.13 python3.12 python3.11 python3.10 python3 python; do
        if command -v "$py" &> /dev/null; then
            local ver major minor
            ver=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ] 2>/dev/null; then
                PYTHON_BIN="$py"
                return 0
            fi
        fi
    done
    echo "ERROR: Python 3.10+ required. Install via:"
    echo "  macOS:   brew install python@3.12"
    echo "  Linux:   sudo apt install python3.12"
    echo "  Windows: https://www.python.org/downloads/"
    return 1
}

# ─── Venv bin path (OS-aware) ─────────────────────────────────────────────────
get_venv_bin() {
    local venv_dir="${1:-$HOME/.engrammar/venv}"
    if [ "$IS_WINDOWS" = true ]; then
        echo "$venv_dir/Scripts"
    else
        echo "$venv_dir/bin"
    fi
}

# ─── Colors & output helpers ─────────────────────────────────────────────────
BOLD='\033[1m'
DIM='\033[2m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

info()    { printf "${CYAN}%s${RESET}\n" "$1"; }
success() { printf "${GREEN}%s${RESET}\n" "$1"; }
warn()    { printf "${YELLOW}%s${RESET}\n" "$1"; }
error()   { printf "${RED}%s${RESET}\n" "$1"; }
bold()    { printf "${BOLD}%s${RESET}\n" "$1"; }
dim()     { printf "${DIM}%s${RESET}\n" "$1"; }
