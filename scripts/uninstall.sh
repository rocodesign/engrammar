#!/bin/bash
# Uninstall Engrammar
# Usage: bash scripts/uninstall.sh [--keep-data]
#   --keep-data  Keep the database (engrams.db) — only remove code and hooks
set -e

ENGRAMMAR_HOME="$HOME/.engrammar"

# ─── Colors ──────────────────────────────────────────────────────────────────
BOLD='\033[1m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

info()    { printf "${CYAN}%s${RESET}\n" "$1"; }
success() { printf "${GREEN}%s${RESET}\n" "$1"; }
warn()    { printf "${YELLOW}%s${RESET}\n" "$1"; }
error()   { printf "${RED}%s${RESET}\n" "$1"; }

KEEP_DATA=false
if [ "$1" = "--keep-data" ]; then
    KEEP_DATA=true
fi

echo ""
info "Uninstalling Engrammar..."
echo ""

# ─── 1. Remove hooks from ~/.claude/settings.json ───────────────────────────
SETTINGS="$HOME/.claude/settings.json"
if [ -f "$SETTINGS" ]; then
    # Use python to safely edit JSON (available since we have a venv, or system python)
    PYTHON=""
    if [ -f "$ENGRAMMAR_HOME/venv/bin/python" ]; then
        PYTHON="$ENGRAMMAR_HOME/venv/bin/python"
    elif [ -f "$ENGRAMMAR_HOME/venv/Scripts/python.exe" ]; then
        PYTHON="$ENGRAMMAR_HOME/venv/Scripts/python.exe"
    else
        for py in python3 python; do
            if command -v "$py" &>/dev/null; then
                PYTHON="$py"
                break
            fi
        done
    fi

    if [ -n "$PYTHON" ]; then
        "$PYTHON" -c "
import json, sys

path = '$SETTINGS'
with open(path, 'r') as f:
    settings = json.load(f)

changed = False

# Remove engrammar hooks
hooks = settings.get('hooks', {})
for event in list(hooks.keys()):
    original_len = len(hooks[event])
    hooks[event] = [
        hg for hg in hooks[event]
        if not any('.engrammar' in h.get('command', '') for h in hg.get('hooks', []))
    ]
    if len(hooks[event]) != original_len:
        changed = True
    if not hooks[event]:
        del hooks[event]

# Remove mcp__engrammar__* from permissions allow list
permissions = settings.get('permissions', {})
allow_list = permissions.get('allow', [])
new_allow = [p for p in allow_list if 'engrammar' not in p]
if len(new_allow) != len(allow_list):
    permissions['allow'] = new_allow
    changed = True

if changed:
    with open(path, 'w') as f:
        json.dump(settings, f, indent=2)
        f.write('\n')
    print('  Removed hooks from settings.json')
else:
    print('  No engrammar hooks found in settings.json')
" 2>/dev/null || warn "  Could not clean settings.json (edit manually)"
    else
        warn "  No python found — manually remove engrammar hooks from $SETTINGS"
    fi
else
    echo "  No settings.json found"
fi

# ─── 2. Remove MCP server from ~/.claude.json ───────────────────────────────
CLAUDE_JSON="$HOME/.claude.json"
if [ -f "$CLAUDE_JSON" ]; then
    if [ -n "$PYTHON" ]; then
        "$PYTHON" -c "
import json

path = '$CLAUDE_JSON'
with open(path, 'r') as f:
    config = json.load(f)

servers = config.get('mcpServers', {})
if 'engrammar' in servers:
    del servers['engrammar']
    with open(path, 'w') as f:
        json.dump(config, f, indent=2)
        f.write('\n')
    print('  Removed MCP server from ~/.claude.json')
else:
    print('  No engrammar MCP server found in ~/.claude.json')
" 2>/dev/null || warn "  Could not clean ~/.claude.json (edit manually)"
    else
        warn "  No python found — manually remove engrammar from $CLAUDE_JSON"
    fi
else
    echo "  No ~/.claude.json found"
fi

# ─── 3. Remove CLI symlink/binary ───────────────────────────────────────────
if [ -L "$HOME/.local/bin/engrammar" ] || [ -f "$HOME/.local/bin/engrammar" ]; then
    rm -f "$HOME/.local/bin/engrammar"
    echo "  Removed ~/.local/bin/engrammar"
else
    echo "  No CLI symlink found"
fi

# ─── 4. Remove ~/.engrammar directory ───────────────────────────────────────
if [ -d "$ENGRAMMAR_HOME" ]; then
    if [ "$KEEP_DATA" = true ]; then
        # Keep the database, remove everything else
        echo "  Keeping database (--keep-data)"
        # Save DB files
        TMPDIR=$(mktemp -d)
        for f in engrams.db engrams.db-wal engrams.db-shm; do
            [ -f "$ENGRAMMAR_HOME/$f" ] && cp "$ENGRAMMAR_HOME/$f" "$TMPDIR/"
        done
        # Also save backups
        for f in "$ENGRAMMAR_HOME"/engrams.db.backup-*; do
            [ -f "$f" ] && cp "$f" "$TMPDIR/"
        done

        rm -rf "$ENGRAMMAR_HOME"
        mkdir -p "$ENGRAMMAR_HOME"

        # Restore DB files
        for f in "$TMPDIR"/*; do
            [ -f "$f" ] && cp "$f" "$ENGRAMMAR_HOME/"
        done
        rm -rf "$TMPDIR"
        echo "  Removed code, kept database in $ENGRAMMAR_HOME"
    else
        rm -rf "$ENGRAMMAR_HOME"
        echo "  Removed $ENGRAMMAR_HOME"
    fi
else
    echo "  No $ENGRAMMAR_HOME directory found"
fi

echo ""
success "Engrammar uninstalled."
if [ "$KEEP_DATA" = true ]; then
    echo "  Database preserved at $ENGRAMMAR_HOME/engrams.db"
    echo "  Reinstall with: bash scripts/install.sh (or setup.sh)"
fi
echo ""
