#!/bin/bash
# Deploy Engrammar from repo to ~/.engrammar (development workflow)
# Usage: bash deploy.sh [--restart]
#   --restart  Also restart the daemon after deploying
set -e

ENGRAMMAR_HOME="$HOME/.engrammar"
SOURCE_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$ENGRAMMAR_HOME" ]; then
    echo "ERROR: $ENGRAMMAR_HOME not found. Run setup.sh first for initial install."
    exit 1
fi

echo "Deploying from $SOURCE_DIR -> $ENGRAMMAR_HOME"

# Copy source package
echo "  src/ -> engrammar/"
rm -rf "$ENGRAMMAR_HOME/engrammar/__pycache__"
cp "$SOURCE_DIR"/src/*.py "$ENGRAMMAR_HOME/engrammar/"

# Copy hooks
echo "  hooks/"
for hook in on_session_start.py on_prompt.py on_tool_use.py on_stop.py; do
    if [ -f "$SOURCE_DIR/hooks/$hook" ]; then
        cp "$SOURCE_DIR/hooks/$hook" "$ENGRAMMAR_HOME/hooks/$hook"
    fi
done

# Copy CLI + scripts
echo "  cli.py, engrammar-cli, backfill_stats.py"
cp "$SOURCE_DIR/cli.py" "$ENGRAMMAR_HOME/cli.py"
cp "$SOURCE_DIR/engrammar" "$ENGRAMMAR_HOME/engrammar-cli"
cp "$SOURCE_DIR/backfill_stats.py" "$ENGRAMMAR_HOME/backfill_stats.py"
chmod +x "$ENGRAMMAR_HOME/engrammar-cli"
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
    "$ENGRAMMAR_HOME/venv/bin/python" "$ENGRAMMAR_HOME/engrammar/daemon.py" &
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
