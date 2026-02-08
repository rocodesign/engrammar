#!/usr/bin/env python3
"""UserPromptSubmit hook — searches lessons relevant to the user's prompt.

Skips lessons already shown in this session (tracked in .session-shown.json).
"""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SHOWN_PATH = os.path.join(ENGRAMMAR_HOME, ".session-shown.json")


def _load_shown():
    """Load set of lesson IDs already shown this session."""
    try:
        if os.path.exists(SHOWN_PATH):
            with open(SHOWN_PATH, "r") as f:
                return set(json.load(f))
    except Exception:
        pass
    return set()


def _save_shown(shown_ids):
    """Save shown lesson IDs."""
    try:
        with open(SHOWN_PATH, "w") as f:
            json.dump(list(shown_ids), f)
    except Exception:
        pass


def main():
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

        from engrammar.search import search
        max_results = config["display"]["max_lessons_per_prompt"]
        results = search(prompt, top_k=max_results)

        if not results:
            return

        # Filter out already-shown lessons
        shown = _load_shown()
        new_results = [r for r in results if r["id"] not in shown]

        if not new_results:
            return

        # Mark as shown
        shown.update(r["id"] for r in new_results)
        _save_shown(shown)

        # Format
        show_categories = config["display"]["show_categories"]
        lines = ["Relevant lessons from past sessions:"]
        for r in new_results:
            prefix = f"[{r['category']}] " if show_categories and r.get("category") else ""
            lines.append(f"- {prefix}{r['text']}")

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": "\n".join(lines),
            }
        }
        print(json.dumps(output))

    except Exception:
        pass


if __name__ == "__main__":
    main()
