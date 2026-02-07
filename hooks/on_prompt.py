#!/usr/bin/env python3
"""UserPromptSubmit hook — injects pinned lessons + searches relevant ones."""

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

        from engrammar.config import load_config
        config = load_config()
        if not config["hooks"]["prompt_enabled"]:
            return

        show_categories = config["display"]["show_categories"]
        lines = []

        # 1. Always include pinned lessons that match current environment
        from engrammar.db import get_pinned_lessons
        from engrammar.environment import check_prerequisites, detect_environment

        env = detect_environment()
        pinned = get_pinned_lessons()
        pinned_ids = set()
        pinned_lines = []
        for p in pinned:
            if check_prerequisites(p.get("prerequisites"), env):
                pinned_ids.add(p["id"])
                prefix = f"[{p['category']}] " if show_categories and p.get("category") else ""
                pinned_lines.append(f"- {prefix}{p['text']}")

        if pinned_lines:
            lines.append("Active lessons for this project:")
            lines.extend(pinned_lines)

        # 2. Search for relevant lessons (skip if prompt too short)
        if prompt and len(prompt) >= 5:
            from engrammar.search import search
            max_results = config["display"]["max_lessons_per_prompt"]
            results = search(prompt, top_k=max_results)

            # Exclude pinned lessons from search results (already shown)
            results = [r for r in results if r["id"] not in pinned_ids]

            if results:
                if lines:
                    lines.append("")
                lines.append("Relevant lessons from past sessions:")
                for r in results:
                    prefix = f"[{r['category']}] " if show_categories and r.get("category") else ""
                    lines.append(f"- {prefix}{r['text']}")

        if not lines:
            return

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
