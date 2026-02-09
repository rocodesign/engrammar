#!/usr/bin/env python3
"""SessionStart hook — injects pinned lessons, starts daemon, and extracts new lessons."""

import json
import subprocess
import sys
import os
import traceback
from datetime import datetime

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SHOWN_PATH = os.path.join(ENGRAMMAR_HOME, ".session-shown.json")
VENV_PYTHON = os.path.join(ENGRAMMAR_HOME, "venv", "bin", "python")
CLI_PATH = os.path.join(ENGRAMMAR_HOME, "cli.py")
LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.log")
ERROR_LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".hook-errors.log")


def _log_error(context, error):
    """Log errors to .hook-errors.log for debugging."""
    try:
        with open(ERROR_LOG_PATH, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"\n[{timestamp}] SessionStart - {context}\n")
            f.write(f"Error: {error}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass  # Can't log the logging error


def main():
    try:
        # Clear session-shown tracking (new session = fresh slate)
        try:
            with open(SHOWN_PATH, "w") as f:
                json.dump([], f)
        except Exception as e:
            _log_error("clear session-shown", e)

        # Start daemon in background (don't block — it warms up while user types)
        try:
            from engrammar.client import _start_daemon_background
            _start_daemon_background()
        except Exception as e:
            _log_error("start daemon", e)

        # Kick off lesson extraction in background (always run — learns from past sessions)
        try:
            with open(LOG_PATH, "a") as log:
                subprocess.Popen(
                    [VENV_PYTHON, CLI_PATH, "extract"],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        except Exception as e:
            _log_error("start extraction", e)

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

    except Exception as e:
        _log_error("main execution", e)


if __name__ == "__main__":
    main()
