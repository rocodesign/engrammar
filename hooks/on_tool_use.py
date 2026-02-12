#!/usr/bin/env python3
"""PreToolUse hook — searches lessons relevant to the tool being called.

Uses the daemon for fast search (~20ms). Falls back to direct search if daemon unavailable.
Shares session-shown tracking with on_prompt.py to avoid repeating lessons.
"""

import json
import sys
import os
import traceback
from datetime import datetime

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SHOWN_PATH = os.path.join(ENGRAMMAR_HOME, ".session-shown.json")
ERROR_LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".hook-errors.log")


def _log_error(context, error):
    """Log errors to .hook-errors.log for debugging."""
    try:
        with open(ERROR_LOG_PATH, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"\n[{timestamp}] PreToolUse - {context}\n")
            f.write(f"Error: {error}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass  # Can't log the logging error


def _load_shown():
    try:
        if os.path.exists(SHOWN_PATH):
            with open(SHOWN_PATH, "r") as f:
                return set(json.load(f))
    except Exception as e:
        _log_error("load shown lessons", e)
    return set()


def _save_shown(shown_ids):
    try:
        with open(SHOWN_PATH, "w") as f:
            json.dump(list(shown_ids), f)
    except Exception as e:
        _log_error("save shown lessons", e)


def _search_via_daemon(tool_name, tool_input):
    """Try daemon first, return results or None."""
    try:
        from engrammar.client import send_request

        response = send_request({
            "type": "tool_context",
            "tool_name": tool_name,
            "tool_input": tool_input,
        })
        if response and "results" in response:
            return response["results"]
    except Exception as e:
        _log_error(f"daemon search for tool: {tool_name}", e)
    return None


def _search_direct(tool_name, tool_input):
    """Fallback: direct search (cold start ~300ms)."""
    try:
        from engrammar.search import search_for_tool_context

        return search_for_tool_context(tool_name, tool_input)
    except Exception as e:
        _log_error(f"direct search for tool: {tool_name}", e)
    return None


def main():
    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return

        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if not tool_name:
            return

        from engrammar.config import load_config

        config = load_config()
        if not config["hooks"]["tool_use_enabled"]:
            return

        skip_tools = config["hooks"]["skip_tools"]
        if tool_name in skip_tools:
            return

        # Try daemon, fall back to direct
        results = _search_via_daemon(tool_name, tool_input)
        if results is None:
            results = _search_direct(tool_name, tool_input)

        if not results:
            return

        # Filter out already-shown lessons
        shown = _load_shown()
        new_results = [r for r in results if r["id"] not in shown]

        if not new_results:
            return

        # Mark as shown and update match stats (only for lessons Claude actually sees)
        shown.update(r["id"] for r in new_results)
        _save_shown(shown)

        # Update match stats for shown lessons only
        from engrammar.db import update_match_stats
        from engrammar.environment import detect_environment
        env = detect_environment()
        repo = env.get("repo")
        for r in new_results:
            update_match_stats(r["id"], repo=repo)

        # Format
        show_categories = config["display"]["show_categories"]
        lines = ["Relevant lessons:"]
        for r in new_results:
            prefix = f"[{r['category']}] " if show_categories and r.get("category") else ""
            lines.append(f"- {prefix}{r['text']}")

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": "\n".join(lines),
            }
        }
        print(json.dumps(output))

    except Exception as e:
        _log_error("main execution", e)


if __name__ == "__main__":
    main()
