#!/usr/bin/env python3
"""UserPromptSubmit hook — searches lessons relevant to the user's prompt."""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def main():
    try:
        # Read hook input from stdin
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

        # Format lessons for context injection
        show_categories = config["display"]["show_categories"]
        lines = ["Relevant lessons from past sessions:"]
        for r in results:
            prefix = f"[{r['category']}] " if show_categories and r.get("category") else ""
            lines.append(f"- {prefix}{r['text']}")

        context = "\n".join(lines)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))

    except Exception:
        # Silent failure — never block the user's prompt
        pass


if __name__ == "__main__":
    main()
