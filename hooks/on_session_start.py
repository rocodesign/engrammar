#!/usr/bin/env python3
"""SessionStart hook — injects pinned lessons and starts the search daemon."""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SHOWN_PATH = os.path.join(ENGRAMMAR_HOME, ".session-shown.json")


def main():
    try:
        # Clear session-shown tracking (new session = fresh slate)
        try:
            with open(SHOWN_PATH, "w") as f:
                json.dump([], f)
        except Exception:
            pass

        # Start daemon in background (don't block — it warms up while user types)
        from engrammar.client import _start_daemon_background

        _start_daemon_background()

        # Get pinned lessons directly (fast — just DB query, no model needed)
        from engrammar.config import load_config
        from engrammar.db import get_pinned_lessons
        from engrammar.environment import check_prerequisites, detect_environment

        config = load_config()
        env = detect_environment()
        pinned = get_pinned_lessons()

        show_categories = config["display"]["show_categories"]
        lines = []
        for p in pinned:
            if check_prerequisites(p.get("prerequisites"), env):
                prefix = f"[{p['category']}] " if show_categories and p.get("category") else ""
                lines.append(f"- {prefix}{p['text']}")

        if not lines:
            return

        context = "Active lessons for this project:\n" + "\n".join(lines)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))

    except Exception:
        pass


if __name__ == "__main__":
    main()
