#!/usr/bin/env python3
"""UserPromptSubmit hook — searches lessons relevant to the user's prompt.

Uses the daemon for fast search (~20ms). Falls back to direct search if daemon unavailable.
Tracks shown lessons in DB (keyed by session ID) to avoid repeats.
"""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def _search_via_daemon(prompt, max_results):
    try:
        from engrammar.client import send_request
        response = send_request({"type": "search", "query": prompt, "top_k": max_results})
        if response and "results" in response:
            return response["results"]
    except Exception as e:
        from engrammar.hook_utils import log_error
        log_error("UserPromptSubmit", f"daemon search: {prompt[:50]}", e)
    return None


def _search_direct(prompt, max_results):
    try:
        from engrammar.search import search
        return search(prompt, top_k=max_results)
    except Exception as e:
        from engrammar.hook_utils import log_error
        log_error("UserPromptSubmit", f"direct search: {prompt[:50]}", e)
    return None


def main():
    from engrammar.hook_utils import log_error, read_session_id, format_lessons_block, make_hook_output

    try:
        raw = sys.stdin.read().strip()
        if not raw:
            return

        data = json.loads(raw)
        prompt = data.get("prompt", "")
        if not prompt or len(prompt) < 5:
            return

        from engrammar.config import load_config
        config = load_config()
        if not config["hooks"]["prompt_enabled"]:
            return

        max_results = config["display"]["max_lessons_per_prompt"]
        show_categories = config["display"]["show_categories"]

        # Try daemon, fall back to direct
        results = _search_via_daemon(prompt, max_results)
        if results is None:
            results = _search_direct(prompt, max_results)

        if not results:
            return

        # Filter out already-shown lessons (DB-based)
        session_id = read_session_id()
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
                record_shown_lesson(session_id, r["id"], "UserPromptSubmit")

        context = format_lessons_block(new_results, show_categories=show_categories)
        output = make_hook_output("UserPromptSubmit", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("UserPromptSubmit", "main execution", e)


if __name__ == "__main__":
    main()
