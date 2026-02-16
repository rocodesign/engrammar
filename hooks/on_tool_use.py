#!/usr/bin/env python3
"""PreToolUse hook — searches lessons relevant to the tool being called.

Uses the daemon for fast search (~20ms). Falls back to direct search if daemon unavailable.
Tracks shown lessons in DB (keyed by session ID) to avoid repeats.
"""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def _search_via_daemon(tool_name, tool_input):
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
        from engrammar.hook_utils import log_error
        log_error("PreToolUse", f"daemon search for tool: {tool_name}", e)
    return None


def _search_direct(tool_name, tool_input):
    try:
        from engrammar.search import search_for_tool_context
        return search_for_tool_context(tool_name, tool_input)
    except Exception as e:
        from engrammar.hook_utils import log_error
        log_error("PreToolUse", f"direct search for tool: {tool_name}", e)
    return None


def main():
    from engrammar.hook_utils import log_error, format_lessons_block, make_hook_output

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

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

        show_categories = config["display"]["show_categories"]

        # Try daemon, fall back to direct
        results = _search_via_daemon(tool_name, tool_input)
        if results is None:
            results = _search_direct(tool_name, tool_input)

        if not results:
            return

        # Filter out already-shown lessons (DB-based)
        session_id = data.get("session_id")
        if session_id:
            from engrammar.db import get_shown_lesson_ids, record_shown_lesson
            shown = get_shown_lesson_ids(session_id)
            new_results = [r for r in results if r["id"] not in shown]
        else:
            new_results = results

        if not new_results:
            return

        # Record shown lessons in DB
        if session_id:
            for r in new_results:
                record_shown_lesson(session_id, r["id"], "PreToolUse")

        context = format_lessons_block(new_results, show_categories=show_categories)
        output = make_hook_output("PreToolUse", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("PreToolUse", "main execution", e)


if __name__ == "__main__":
    main()
