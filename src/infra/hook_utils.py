"""Shared hook utilities — replaces copy-pasted code across hooks."""

import json
import os
import subprocess
import sys
import traceback
from datetime import datetime

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
ERROR_LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".hook-errors.log")


def _load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {}


def _read_mcp_entry(path):
    if not path or not os.path.exists(path):
        return None
    data = _load_json_file(path)
    entry = data.get("mcpServers", {}).get("engrammar")
    if isinstance(entry, dict):
        return entry
    return None


def _detect_repo_root(cwd=None):
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
    except Exception:
        pass
    return None


def _project_mcp_path(cwd=None):
    repo_root = _detect_repo_root(cwd=cwd)
    if not repo_root:
        return None
    return os.path.join(repo_root, ".mcp.json")


def _write_json_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


def is_mcp_enabled(cwd=None):
    """Check if the engrammar MCP server is enabled in Claude config.

    Returns False if the user-level entry is missing or has disabled=true.
    """
    try:
        claude_config = os.path.expanduser("~/.claude.json")
        entry = _read_mcp_entry(claude_config)
        if entry is None:
            return False
        if bool(entry.get("disabled")):
            return False

        project_config = _project_mcp_path(cwd=cwd)
        project_entry = _read_mcp_entry(project_config)
        if project_entry is None:
            return True
        return not bool(project_entry.get("disabled"))
    except Exception:
        return False


def set_mcp_disabled(disabled):
    """Update the engrammar MCP server disabled flag in Claude config."""
    claude_config_path = os.path.expanduser("~/.claude.json")
    claude_config = {}

    if os.path.exists(claude_config_path):
        with open(claude_config_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            claude_config = loaded

    mcp_servers = claude_config.setdefault("mcpServers", {})
    engrammar = mcp_servers.setdefault("engrammar", {})
    if disabled:
        engrammar["disabled"] = True
    else:
        engrammar.pop("disabled", None)

    os.makedirs(os.path.dirname(claude_config_path), exist_ok=True)
    _write_json_file(claude_config_path, claude_config)


def sync_project_mcp_for_cwd(cwd=None):
    """Mirror repo-disabled scope into the repo-local .mcp.json file."""
    project_config_path = _project_mcp_path(cwd=cwd)
    if not project_config_path:
        return

    from engrammar.search.environment import is_repo_disabled

    project_config = _load_json_file(project_config_path)
    mcp_servers = project_config.setdefault("mcpServers", {})
    engrammar = mcp_servers.setdefault("engrammar", {})

    if is_repo_disabled(cwd=cwd):
        engrammar["disabled"] = True
    else:
        engrammar.pop("disabled", None)
        if not engrammar:
            mcp_servers.pop("engrammar", None)

    if not mcp_servers:
        project_config.pop("mcpServers", None)

    if project_config:
        _write_json_file(project_config_path, project_config)
    elif os.path.exists(project_config_path):
        os.remove(project_config_path)

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
        "call engrammar_feedback(engram_id, applicable=false, reason=\"...\"). "
        "If one is relevant but vague or incomplete, call engrammar_update to improve it."
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
