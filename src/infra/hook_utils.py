"""Shared hook utilities — replaces copy-pasted code across hooks."""

import json
import os
import sys
import traceback
from datetime import datetime

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
ERROR_LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".hook-errors.log")


def is_mcp_enabled():
    """Check if the engrammar MCP server is enabled in Claude config.

    Returns False if the entry is missing or has disabled=true,
    meaning hooks should no-op and the daemon should not start.
    """
    try:
        claude_config = os.path.expanduser("~/.claude.json")
        if not os.path.exists(claude_config):
            return False
        with open(claude_config, "r") as f:
            data = json.load(f)
        entry = data.get("mcpServers", {}).get("engrammar")
        if entry is None:
            return False
        if isinstance(entry, dict) and entry.get("disabled"):
            return False
        return True
    except Exception:
        return False


def log_error(hook_name, context, error):
    """Write error to .hook-errors.log."""
    try:
        with open(ERROR_LOG_PATH, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"\n[{timestamp}] {hook_name} - {context}\n")
            f.write(f"Error: {error}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def write_session_id(session_id):
    """Persist session_id to a file so the MCP server can auto-capture it.

    Called by SessionStart hook. The MCP engrammar_add handler reads this
    to populate source_sessions without requiring the model to pass it.
    """
    try:
        session_file = os.path.join(ENGRAMMAR_HOME, ".current_session_id")
        with open(session_file, "w") as f:
            f.write(session_id)
    except Exception as e:
        log_error("write_session_id", "write file", e)


def read_session_id():
    """Read the current session_id persisted by the SessionStart hook.

    Returns:
        str or None: The session ID if available, None otherwise.
    """
    try:
        session_file = os.path.join(ENGRAMMAR_HOME, ".current_session_id")
        if os.path.exists(session_file):
            with open(session_file, "r") as f:
                return f.read().strip() or None
    except Exception:
        pass
    return None


def parse_hook_input():
    """Read and parse the JSON payload from stdin (provided by Claude's hook system).

    Returns:
        dict with keys like session_id, transcript_path, etc., or empty dict on failure.
    """
    try:
        raw = sys.stdin.read().strip()
        if raw:
            return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        pass
    return {}


def format_engrams_block(engrams, show_categories=True):
    """Format engrams in [ENGRAMMAR_V1] block with EG#ID markers.

    Args:
        engrams: list of engram dicts (must have 'id', 'text', optionally 'category')
        show_categories: whether to include [category] prefix

    Returns:
        str: formatted block, or empty string if no engrams
    """
    if not engrams:
        return ""

    lines = ["[ENGRAMMAR_V1]"]
    for engram in engrams:
        cat = f"[{engram.get('category', 'general')}] " if show_categories and engram.get("category") else ""
        lines.append(f"- [EG#{engram['id']}]{cat}{engram['text']}")
    lines.append(
        "Treat these as soft constraints. If one doesn't apply here, "
        "call engrammar_feedback(engram_id, applicable=false, reason=\"...\")."
    )
    lines.append("[/ENGRAMMAR_V1]")
    return "\n".join(lines)


def make_hook_output(hook_event_name, context_text):
    """Build the standard hook output dict."""
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": context_text,
        }
    }
