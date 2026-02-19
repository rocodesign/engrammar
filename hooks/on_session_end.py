#!/usr/bin/env python3
"""SessionEnd hook — writes audit record and triggers background evaluation."""

import json
import subprocess
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def main():
    from engrammar.hook_utils import log_error, parse_hook_input

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

        # Read session_id and transcript_path from Claude's hook payload
        data = parse_hook_input()
        session_id = data.get("session_id")
        transcript_path = data.get("transcript_path")

        if not session_id:
            return

        # Get shown lesson IDs from DB
        from engrammar.db import get_shown_lesson_ids, write_session_audit, clear_session_shown

        shown_ids = get_shown_lesson_ids(session_id)
        if not shown_ids:
            return

        # Write audit record
        from engrammar.environment import detect_environment
        env = detect_environment()
        repo = env.get("repo")
        tags = env.get("tags", [])

        write_session_audit(session_id, list(shown_ids), tags, repo, transcript_path=transcript_path)

        # Clear session state
        clear_session_shown(session_id)

        # Trigger background evaluation for this session
        cli_path = os.path.join(ENGRAMMAR_HOME, "engrammar-cli")
        subprocess.Popen(
            [cli_path, "evaluate", "--session", session_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

    except Exception as e:
        log_error("SessionEnd", "main execution", e)


if __name__ == "__main__":
    main()
