#!/bin/bash
# Deploy Engrammar from repo to ~/.engrammar (development workflow)
# Usage: bash scripts/deploy.sh [--restart]
#   --restart  Also restart the daemon after deploying
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
SOURCE_DIR="$(get_repo_root)"

ENGRAMMAR_HOME="$HOME/.engrammar"

if [ ! -d "$ENGRAMMAR_HOME" ]; then
    error "ERROR: $ENGRAMMAR_HOME not found. Run scripts/setup.sh first for initial install."
    exit 1
fi

echo "Deploying from $SOURCE_DIR -> $ENGRAMMAR_HOME"

# Copy source package
echo "  src/ -> engrammar/"
rm -rf "$ENGRAMMAR_HOME/engrammar"
cp -r "$SOURCE_DIR/src" "$ENGRAMMAR_HOME/engrammar"
find "$ENGRAMMAR_HOME/engrammar" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

# Copy hooks
echo "  hooks/"
for hook in on_session_start.py on_prompt.py on_tool_use.py on_stop.py; do
    if [ -f "$SOURCE_DIR/hooks/$hook" ]; then
        cp "$SOURCE_DIR/hooks/$hook" "$ENGRAMMAR_HOME/hooks/$hook"
    fi
done

# Copy prompts
echo "  prompts/"
mkdir -p "$ENGRAMMAR_HOME/prompts"
cp -r "$SOURCE_DIR"/prompts/* "$ENGRAMMAR_HOME/prompts/"

# Copy CLI + scripts
echo "  cli.py, engrammar, backfill_stats.py"
cp "$SOURCE_DIR/cli.py" "$ENGRAMMAR_HOME/cli.py"
mkdir -p "$ENGRAMMAR_HOME/bin"
cp "$SOURCE_DIR/engrammar" "$ENGRAMMAR_HOME/bin/engrammar"
cp "$SOURCE_DIR/backfill_stats.py" "$ENGRAMMAR_HOME/backfill_stats.py"
chmod +x "$ENGRAMMAR_HOME/bin/engrammar"
chmod +x "$ENGRAMMAR_HOME/backfill_stats.py"

# Restart daemon if requested
if [ "$1" = "--restart" ]; then
    echo ""
    PIDFILE="$ENGRAMMAR_HOME/.daemon.pid"
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "Stopping daemon (PID $PID)..."
            kill "$PID"
            sleep 1
        fi
    fi
    echo "Starting daemon..."
    "$ENGRAMMAR_HOME/venv/bin/python" "$ENGRAMMAR_HOME/engrammar/infra/daemon.py" &
    sleep 1
    if [ -f "$PIDFILE" ]; then
        echo "Daemon started (PID $(cat "$PIDFILE"))"
    else
        echo "WARNING: Daemon may not have started — check .daemon.log"
    fi
else
    echo ""
    echo "Note: daemon will pick up module changes on next import."
    echo "Use --restart to also restart the daemon."
fi

echo ""
echo "Deployed."
