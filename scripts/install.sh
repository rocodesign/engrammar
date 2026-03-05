#!/bin/bash
# Engrammar Installer
# One-liner: curl -fsSL https://raw.githubusercontent.com/rocodesign/engrammar/main/scripts/install.sh | bash
set -e

# ─── Colors & helpers ───────────────────────────────────────────────────────
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

ask() {
    local prompt="$1" default="$2" var="$3"
    if [ -n "$default" ]; then
        printf "${BOLD}%s${RESET} ${DIM}[%s]${RESET}: " "$prompt" "$default"
    else
        printf "${BOLD}%s${RESET}: " "$prompt"
    fi
    read -r input
    eval "$var=\"${input:-$default}\""
}

ask_yn() {
    local prompt="$1" default="$2" var="$3"
    local hint="y/n"
    [ "$default" = "y" ] && hint="Y/n"
    [ "$default" = "n" ] && hint="y/N"
    printf "${BOLD}%s${RESET} ${DIM}[%s]${RESET}: " "$prompt" "$hint"
    read -r input
    input="${input:-$default}"
    case "$input" in
        [yY]*) eval "$var=true" ;;
        *)     eval "$var=false" ;;
    esac
}

# ─── Welcome ────────────────────────────────────────────────────────────────
clear 2>/dev/null || true
echo ""
bold "  ╔══════════════════════════════════════════════════╗"
bold "  ║             Engrammar Installer                  ║"
bold "  ║       Semantic Knowledge System for Claude Code  ║"
bold "  ╚══════════════════════════════════════════════════╝"
echo ""

# ─── What is Engrammar? ────────────────────────────────────────────────────
bold "  What is Engrammar?"
echo ""
echo "  Engrammar automatically learns from your Claude Code sessions and"
echo "  surfaces relevant knowledge at the right time. It builds a persistent"
echo "  knowledge base of:"
echo ""
echo "    - Project conventions and architecture decisions"
echo "    - Debugging insights and solutions"
echo "    - Tooling quirks and workarounds"
echo "    - Workflow preferences"
echo ""
echo "  Unlike CLAUDE.md files which require manual curation, Engrammar"
echo "  extracts learnings from friction moments in past conversations"
echo "  (user corrections, repeated struggles, discovered conventions)"
echo "  and learns which contexts each engram belongs in."
echo ""

# ─── How it works ───────────────────────────────────────────────────────────
bold "  How does it work?"
echo ""
echo "  1. ${BOLD}Hooks${RESET} inject relevant engrams into your Claude Code sessions"
echo "     at the right moment (session start, each prompt, before tool use)"
echo ""
echo "  2. ${BOLD}Search${RESET} combines vector similarity + BM25 keywords to find"
echo "     the most relevant engrams for your current context"
echo ""
echo "  3. ${BOLD}Environment detection${RESET} auto-detects your project from paths,"
echo "     git remotes, package files, and directory structure"
echo ""
echo "  4. ${BOLD}Extraction${RESET} automatically discovers new engrams from session"
echo "     friction moments (corrections, struggles, conventions)"
echo ""
echo "  5. ${BOLD}Evaluation${RESET} learns which engrams are relevant in which"
echo "     contexts via per-tag relevance scoring"
echo ""
echo "  No API keys needed for core features — embeddings run locally."
echo "  AI extraction/evaluation uses Haiku and is optional (fails open)."
echo ""

# ─── Prerequisites ──────────────────────────────────────────────────────────
bold "  Checking prerequisites..."
echo ""

# Detect OS
OS="$(uname -s)"
case "$OS" in
    MINGW*|MSYS*|CYGWIN*) IS_WINDOWS=true ;;
    *)                     IS_WINDOWS=false ;;
esac

# Check Python — try versioned names first, then generic python3/python with version check
PYTHON_BIN=""
for py in python3.13 python3.12 python3.11 python3.10 python3 python; do
    if command -v "$py" &> /dev/null; then
        PY_VER=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
        PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
        if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ] 2>/dev/null; then
            PYTHON_BIN="$py"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    warn "  Python 3.10+ is required but not found."
    echo ""

    # Detect package manager and offer to install
    INSTALL_CMD=""
    SUDO=""
    if [ "$(id -u)" -ne 0 ] && command -v sudo &> /dev/null; then
        SUDO="sudo "
    fi

    if [ "$OS" = "Darwin" ] && command -v brew &> /dev/null; then
        INSTALL_CMD="brew install python@3.12"
    elif command -v apt-get &> /dev/null; then
        INSTALL_CMD="DEBIAN_FRONTEND=noninteractive ${SUDO}apt-get update -qq && DEBIAN_FRONTEND=noninteractive ${SUDO}apt-get install -y python3.12 python3.12-venv"
    elif command -v dnf &> /dev/null; then
        INSTALL_CMD="${SUDO}dnf install -y python3.12"
    elif command -v pacman &> /dev/null; then
        INSTALL_CMD="${SUDO}pacman -S --noconfirm python"
    elif command -v apk &> /dev/null; then
        INSTALL_CMD="${SUDO}apk add python3"
    fi

    if [ -n "$INSTALL_CMD" ]; then
        ask_yn "  Install Python 3.12 now?" "y" INSTALL_PYTHON
        if [ "$INSTALL_PYTHON" = "true" ]; then
            echo ""
            info "  Running: $INSTALL_CMD"
            eval "$INSTALL_CMD"
            echo ""
            # Re-detect Python after install
            for py in python3.13 python3.12 python3.11 python3.10 python3 python; do
                if command -v "$py" &> /dev/null; then
                    PY_VER=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
                    PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
                    PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
                    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ] 2>/dev/null; then
                        PYTHON_BIN="$py"
                        break
                    fi
                fi
            done
        fi
    fi

    if [ -z "$PYTHON_BIN" ]; then
        error "  Python 3.10+ is still not available."
        echo ""
        echo "  Install manually:"
        echo "    macOS:   brew install python@3.12"
        echo "    Ubuntu:  sudo apt install python3.12 python3.12-venv"
        echo "    Fedora:  sudo dnf install python3.12"
        echo "    Windows: https://www.python.org/downloads/"
        echo ""
        exit 1
    fi
fi
PY_VERSION=$("$PYTHON_BIN" --version 2>&1)
success "  Found $PY_VERSION"

# Check git
if ! command -v git &> /dev/null; then
    error "  git is required but not found."
    exit 1
fi
success "  Found git $(git --version | cut -d' ' -f3)"

# Check Claude Code (optional but recommended)
if command -v claude &> /dev/null; then
    success "  Found Claude Code CLI"
else
    warn "  Claude Code CLI not found (engrammar works best with it)"
fi

echo ""

# ─── Configuration ──────────────────────────────────────────────────────────
bold "  Configuration"
echo ""
echo "  Let's configure Engrammar for your workflow."
echo "  Press Enter to accept defaults — you can change these later."
echo ""

# Engrams per prompt
ask "  Max engrams shown per prompt" "3" MAX_PER_PROMPT

# Engrams per tool use
ask "  Max engrams shown per tool use" "2" MAX_PER_TOOL

# Enable prompt hook
ask_yn "  Enable prompt hook? (search engrams on each prompt)" "y" PROMPT_ENABLED

# Enable tool use hook
ask_yn "  Enable tool-use hook? (search engrams before tool calls)" "y" TOOL_ENABLED

# Show scores
ask_yn "  Show relevance scores in results?" "n" SHOW_SCORES

# Add to PATH
ask_yn "  Add 'engrammar' command to your PATH?" "y" ADD_TO_PATH

echo ""

# ─── Confirm ────────────────────────────────────────────────────────────────
bold "  Summary"
echo ""
echo "  Install location:     ~/.engrammar"
echo "  Engrams per prompt:   $MAX_PER_PROMPT"
echo "  Engrams per tool:     $MAX_PER_TOOL"
echo "  Prompt hook:          $PROMPT_ENABLED"
echo "  Tool-use hook:        $TOOL_ENABLED"
echo "  Show scores:          $SHOW_SCORES"
echo "  Add to PATH:          $ADD_TO_PATH"
echo ""

ask_yn "  Proceed with installation?" "y" PROCEED
echo ""

if [ "$PROCEED" != "true" ]; then
    info "  Installation cancelled."
    exit 0
fi

# ─── Download ───────────────────────────────────────────────────────────────
ENGRAMMAR_HOME="$HOME/.engrammar"
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

info "  Downloading Engrammar..."
git clone --depth 1 https://github.com/rocodesign/engrammar.git "$TMPDIR/engrammar" 2>&1 | while read -r line; do
    dim "    $line"
done
echo ""

SOURCE_DIR="$TMPDIR/engrammar"

# ─── Install ────────────────────────────────────────────────────────────────
info "  Installing..."
echo ""

# Create directory structure
echo "  Creating directory structure..."
mkdir -p "$ENGRAMMAR_HOME/hooks"
mkdir -p "$ENGRAMMAR_HOME/bin"

# OS-aware venv paths
if [ "$IS_WINDOWS" = true ]; then
    VENV_BIN="$ENGRAMMAR_HOME/venv/Scripts"
else
    VENV_BIN="$ENGRAMMAR_HOME/venv/bin"
fi

# Create venv
if [ ! -d "$ENGRAMMAR_HOME/venv" ]; then
    echo "  Creating Python virtual environment ($PYTHON_BIN)..."
    "$PYTHON_BIN" -m venv "$ENGRAMMAR_HOME/venv"
else
    echo "  Virtual environment already exists."
fi

# Install dependencies
echo "  Installing dependencies..."
"$VENV_BIN/pip" install -q -r "$SOURCE_DIR/requirements.txt"

# Copy source files
echo "  Copying source files..."
rm -rf "$ENGRAMMAR_HOME/engrammar"
cp -r "$SOURCE_DIR/src" "$ENGRAMMAR_HOME/engrammar"
cp "$SOURCE_DIR/hooks/on_session_start.py" "$ENGRAMMAR_HOME/hooks/on_session_start.py"
cp "$SOURCE_DIR/hooks/on_prompt.py" "$ENGRAMMAR_HOME/hooks/on_prompt.py"
cp "$SOURCE_DIR/hooks/on_tool_use.py" "$ENGRAMMAR_HOME/hooks/on_tool_use.py"
cp "$SOURCE_DIR/hooks/on_stop.py" "$ENGRAMMAR_HOME/hooks/on_stop.py"
cp "$SOURCE_DIR/cli.py" "$ENGRAMMAR_HOME/cli.py"
cp "$SOURCE_DIR/backfill_stats.py" "$ENGRAMMAR_HOME/backfill_stats.py"
cp "$SOURCE_DIR/engrammar" "$ENGRAMMAR_HOME/bin/engrammar"
chmod +x "$ENGRAMMAR_HOME/bin/engrammar"
chmod +x "$ENGRAMMAR_HOME/backfill_stats.py"

# Copy prompts
mkdir -p "$ENGRAMMAR_HOME/prompts"
if [ -d "$SOURCE_DIR/prompts" ]; then
    cp -r "$SOURCE_DIR"/prompts/* "$ENGRAMMAR_HOME/prompts/"
fi

# ─── Write config ───────────────────────────────────────────────────────────
# Convert booleans for JSON
json_bool() { [ "$1" = "true" ] && echo "true" || echo "false"; }

if [ -f "$ENGRAMMAR_HOME/config.json" ]; then
    echo "  Config already exists, keeping user customizations."
else
    echo "  Writing configuration..."
    cat > "$ENGRAMMAR_HOME/config.json" << EOF
{
  "search": {
    "top_k": $MAX_PER_PROMPT
  },
  "hooks": {
    "prompt_enabled": $(json_bool "$PROMPT_ENABLED"),
    "tool_use_enabled": $(json_bool "$TOOL_ENABLED"),
    "skip_tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"]
  },
  "display": {
    "max_engrams_per_prompt": $MAX_PER_PROMPT,
    "max_engrams_per_tool": $MAX_PER_TOOL,
    "show_scores": $(json_bool "$SHOW_SCORES"),
    "show_categories": true
  }
}
EOF
fi

# ─── Initialize DB + build index ────────────────────────────────────────────
echo ""
echo "  Initializing database and building embedding index..."
"$VENV_BIN/python" "$ENGRAMMAR_HOME/cli.py" setup

# ─── Register hooks ─────────────────────────────────────────────────────────
echo ""
if command -v claude &> /dev/null; then
    echo "  Registering hooks with Claude Code..."
    "$VENV_BIN/python" "$ENGRAMMAR_HOME/engrammar/infra/register_hooks.py"
else
    echo "  Claude Code not found — skipping hook registration."
    echo "  Run 'engrammar register claude' after installing Claude Code."
fi

# ─── Add to PATH ────────────────────────────────────────────────────────────
if [ "$ADD_TO_PATH" = "true" ]; then
    echo ""
    echo "  Adding to PATH..."

    # Try symlink into ~/.local/bin (standard on macOS/Linux, usually already on PATH)
    mkdir -p "$HOME/.local/bin"
    if ln -sf "$ENGRAMMAR_HOME/bin/engrammar" "$HOME/.local/bin/engrammar" 2>/dev/null; then
        # Symlink succeeded (macOS/Linux)
        if echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
            success "  Symlinked to ~/.local/bin/engrammar (already on PATH)"
        else
            # ~/.local/bin not on PATH — add it to shell config
            SHELL_CONFIG=""
            if [ -f "$HOME/.zshrc" ]; then
                SHELL_CONFIG="$HOME/.zshrc"
            elif [ -f "$HOME/.bashrc" ]; then
                SHELL_CONFIG="$HOME/.bashrc"
            elif [ -f "$HOME/.bash_profile" ]; then
                SHELL_CONFIG="$HOME/.bash_profile"
            fi

            if [ -n "$SHELL_CONFIG" ]; then
                if ! grep -q '\.local/bin' "$SHELL_CONFIG" 2>/dev/null; then
                    echo "" >> "$SHELL_CONFIG"
                    echo '# local bin' >> "$SHELL_CONFIG"
                    echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_CONFIG"
                    success "  Symlinked to ~/.local/bin/engrammar"
                    warn "  Added ~/.local/bin to PATH in $SHELL_CONFIG (restart your terminal)"
                else
                    success "  Symlinked to ~/.local/bin/engrammar"
                fi
            else
                success "  Symlinked to ~/.local/bin/engrammar"
                warn "  ~/.local/bin may not be on PATH. Add to your shell config:"
                echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
            fi
        fi
    else
        # Symlink failed (Windows Git Bash without dev mode) — copy instead
        cp "$ENGRAMMAR_HOME/bin/engrammar" "$HOME/.local/bin/engrammar" 2>/dev/null && \
            chmod +x "$HOME/.local/bin/engrammar" 2>/dev/null

        if echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
            success "  Copied to ~/.local/bin/engrammar (already on PATH)"
        else
            success "  Copied to ~/.local/bin/engrammar"
            warn "  ~/.local/bin may not be on PATH. Add to your shell profile:"
            echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        fi
    fi
fi

# ─── Done ───────────────────────────────────────────────────────────────────
echo ""
echo ""
success "  ══════════════════════════════════════════════════"
success "           Engrammar installed successfully!"
success "  ══════════════════════════════════════════════════"
echo ""
echo "  ${BOLD}Quick start:${RESET}"
echo ""
echo "    engrammar status        Check system health"
echo "    engrammar detect-tags   See detected environment tags"
echo "    engrammar search \"...\"  Search your knowledge base"
echo "    engrammar list          List all engrams"
echo ""
echo "  ${BOLD}What happens next:${RESET}"
echo ""
echo "    1. Start a new Claude Code session"
echo "    2. Engrammar hooks will activate automatically"
echo "    3. As you work, engrams are extracted from friction moments"
echo "    4. Over time, Claude gets smarter about your projects"
echo ""
if [ "$ADD_TO_PATH" = "true" ] && [ -n "$SHELL_CONFIG" ]; then
    dim "  Run 'source $SHELL_CONFIG' or open a new terminal to use the engrammar command."
fi
echo ""
