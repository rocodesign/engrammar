#!/usr/bin/env python3
"""SessionStart hook — injects pinned lessons that match the current environment."""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def main():
    try:
        from engrammar.config import load_config
        config = load_config()

        from engrammar.db import get_pinned_lessons
        from engrammar.environment import check_prerequisites, detect_environment

        # Clear session-shown tracking (new session = fresh slate)
        from engrammar.config import ENGRAMMAR_HOME as home
        shown_path = os.path.join(home, ".session-shown.json")
        try:
            with open(shown_path, "w") as f:
                json.dump([], f)
        except Exception:
            pass

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
