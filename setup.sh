#!/bin/bash
# Install Engrammar — run: bash setup.sh
set -e

ENGRAMMAR_HOME="$HOME/.engrammar"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Installing Engrammar ==="
echo ""

# 1. Create directory structure
echo "Creating directory structure..."
mkdir -p "$ENGRAMMAR_HOME/hooks"

# 2. Create venv with Python 3.12+ (MCP SDK requires 3.10+)
PYTHON_BIN=""
for py in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$py" &> /dev/null; then
        PYTHON_BIN="$py"
        break
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "ERROR: Python 3.10+ required (for MCP SDK). Install via: brew install python@3.12"
    exit 1
fi

if [ ! -d "$ENGRAMMAR_HOME/venv" ]; then
    echo "Creating Python virtual environment ($PYTHON_BIN)..."
    "$PYTHON_BIN" -m venv "$ENGRAMMAR_HOME/venv"
else
    echo "Virtual environment already exists."
fi

# 3. Install dependencies
echo "Installing dependencies..."
"$ENGRAMMAR_HOME/venv/bin/pip" install -q -r "$SOURCE_DIR/requirements.txt"

# 4. Copy source files
echo "Copying source files..."
rm -rf "$ENGRAMMAR_HOME/engrammar"
cp -r "$SOURCE_DIR/src" "$ENGRAMMAR_HOME/engrammar"
cp "$SOURCE_DIR/hooks/on_session_start.py" "$ENGRAMMAR_HOME/hooks/on_session_start.py"
cp "$SOURCE_DIR/hooks/on_prompt.py" "$ENGRAMMAR_HOME/hooks/on_prompt.py"
cp "$SOURCE_DIR/hooks/on_tool_use.py" "$ENGRAMMAR_HOME/hooks/on_tool_use.py"
cp "$SOURCE_DIR/hooks/on_session_end.py" "$ENGRAMMAR_HOME/hooks/on_session_end.py"
cp "$SOURCE_DIR/cli.py" "$ENGRAMMAR_HOME/cli.py"
cp "$SOURCE_DIR/backfill_stats.py" "$ENGRAMMAR_HOME/backfill_stats.py"
cp "$SOURCE_DIR/engrammar" "$ENGRAMMAR_HOME/engrammar-cli"
chmod +x "$ENGRAMMAR_HOME/engrammar-cli"
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
"$ENGRAMMAR_HOME/venv/bin/python" "$ENGRAMMAR_HOME/cli.py" setup

# 7. Register hooks in Claude Code settings
echo ""
echo "Registering hooks..."
"$ENGRAMMAR_HOME/venv/bin/python" "$ENGRAMMAR_HOME/engrammar/register_hooks.py"

echo ""
echo "=== Engrammar installed ==="
echo "Home:    $ENGRAMMAR_HOME"
echo ""
echo "CLI commands:"
echo "  $ENGRAMMAR_HOME/engrammar-cli status"
echo "  $ENGRAMMAR_HOME/engrammar-cli search \"query\""
echo "  $ENGRAMMAR_HOME/engrammar-cli list"
echo ""
echo "To use 'engrammar' from anywhere, add to your ~/.zshrc:"
echo "  export PATH=\"\$HOME/.engrammar:\$PATH\""
echo "  alias engrammar=\"\$HOME/.engrammar/engrammar-cli\""
echo ""
echo "MCP server + hooks will activate on your next Claude Code session."
