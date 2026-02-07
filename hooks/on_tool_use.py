#!/usr/bin/env python3
"""PreToolUse hook — searches lessons relevant to the tool being called."""

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
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if not tool_name:
            return

        from engrammar.config import load_config
        config = load_config()
        if not config["hooks"]["tool_use_enabled"]:
            return

        # Short-circuit for read-only tools
        skip_tools = config["hooks"]["skip_tools"]
        if tool_name in skip_tools:
            return

        from engrammar.search import search_for_tool_context
        results = search_for_tool_context(tool_name, tool_input)

        if not results:
            return

        # Format lessons for context injection
        show_categories = config["display"]["show_categories"]
        lines = ["Relevant lessons:"]
        for r in results:
            prefix = f"[{r['category']}] " if show_categories and r.get("category") else ""
            lines.append(f"- {prefix}{r['text']}")

        context = "\n".join(lines)

        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": context,
            }
        }
        print(json.dumps(output))

    except Exception:
        # Silent failure — never block tool use
        pass


if __name__ == "__main__":
    main()
