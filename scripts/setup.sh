#!/bin/bash
# Install Engrammar — run: bash scripts/setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SOURCE_DIR="$(get_repo_root)"

ENGRAMMAR_HOME="$HOME/.engrammar"

echo "=== Installing Engrammar ==="
echo ""

# 1. Create directory structure
echo "Creating directory structure..."
mkdir -p "$ENGRAMMAR_HOME/hooks"
mkdir -p "$ENGRAMMAR_HOME/bin"

# 2. Detect OS + find Python 3.10+
detect_os
find_python || exit 1

if [ ! -d "$ENGRAMMAR_HOME/venv" ]; then
    echo "Creating Python virtual environment ($PYTHON_BIN)..."
    "$PYTHON_BIN" -m venv "$ENGRAMMAR_HOME/venv"
else
    echo "Virtual environment already exists."
fi

VENV_BIN="$(get_venv_bin "$ENGRAMMAR_HOME/venv")"

# 3. Install dependencies
echo "Installing dependencies..."
"$VENV_BIN/pip" install -q -r "$SOURCE_DIR/requirements.txt"

# 4. Copy source files
echo "Copying source files..."
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

# 5. Copy config (only if not exists — don't overwrite user customizations)
if [ ! -f "$ENGRAMMAR_HOME/config.json" ]; then
    cp "$SOURCE_DIR/config.json" "$ENGRAMMAR_HOME/config.json"
    echo "Created default config.json"
else
    echo "Config already exists, keeping user customizations."
fi

# 6. Initialize DB + import existing engrams + build index
echo ""
echo "Running setup..."
"$VENV_BIN/python" "$ENGRAMMAR_HOME/cli.py" setup

# 7. Register hooks in Claude Code settings
echo ""
if command -v claude &> /dev/null; then
    echo "Registering hooks..."
    "$VENV_BIN/python" "$ENGRAMMAR_HOME/engrammar/infra/register_hooks.py"
else
    echo "Claude Code not found — skipping hook registration."
    echo "Run 'engrammar register claude' after installing Claude Code."
fi

# 8. Add CLI to ~/.local/bin
mkdir -p "$HOME/.local/bin"
ln -sf "$ENGRAMMAR_HOME/bin/engrammar" "$HOME/.local/bin/engrammar" 2>/dev/null || \
    cp "$ENGRAMMAR_HOME/bin/engrammar" "$HOME/.local/bin/engrammar"

echo ""
echo "=== Engrammar installed ==="
echo "Home:    $ENGRAMMAR_HOME"
echo "CLI:     ~/.local/bin/engrammar"
echo ""
echo "CLI commands:"
echo "  engrammar status"
echo "  engrammar search \"query\""
echo "  engrammar list"
echo ""
if ! echo "$PATH" | tr ':' '\n' | grep -qx "$HOME/.local/bin"; then
    echo "Note: ~/.local/bin is not on your PATH. Add to your shell config:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi
echo "MCP server + hooks will activate on your next Claude Code session."
