#!/usr/bin/env python3
"""SessionStart hook — generates session ID, injects pinned lessons, starts daemon, extracts lessons."""

import json
import subprocess
import sys
import os
import uuid

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

VENV_PYTHON = os.path.join(ENGRAMMAR_HOME, "venv", "bin", "python")
CLI_PATH = os.path.join(ENGRAMMAR_HOME, "cli.py")
LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".daemon.log")


def main():
    from engrammar.hook_utils import log_error, write_session_id, format_lessons_block, make_hook_output

    try:
        # Generate session ID
        session_id = str(uuid.uuid4())
        write_session_id(session_id)

        # Start daemon in background
        try:
            from engrammar.client import _start_daemon_background
            _start_daemon_background()
        except Exception as e:
            log_error("SessionStart", "start daemon", e)

        # Kick off lesson extraction in background
        try:
            with open(LOG_PATH, "a") as log:
                subprocess.Popen(
                    [VENV_PYTHON, CLI_PATH, "extract"],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        except Exception as e:
            log_error("SessionStart", "start extraction", e)

        # Kick off evaluation of previous sessions in background
        try:
            with open(LOG_PATH, "a") as log:
                subprocess.Popen(
                    [VENV_PYTHON, CLI_PATH, "evaluate"],
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        except Exception as e:
            log_error("SessionStart", "start evaluation", e)

        # Get pinned lessons
        from engrammar.config import load_config
        from engrammar.db import get_pinned_lessons
        from engrammar.environment import check_prerequisites, detect_environment

        config = load_config()
        env = detect_environment()
        pinned = get_pinned_lessons()

        show_categories = config["display"]["show_categories"]
        matching = []
        for p in pinned:
            if check_prerequisites(p.get("prerequisites"), env):
                matching.append(p)

        if not matching:
            return

        context = format_lessons_block(matching, show_categories=show_categories)
        output = make_hook_output("SessionStart", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("SessionStart", "main execution", e)


if __name__ == "__main__":
    main()
