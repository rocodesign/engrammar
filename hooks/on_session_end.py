#!/usr/bin/env python3
"""SessionEnd hook — writes audit record of what was shown, clears session state.

Evaluation of lesson relevance is deferred to the next session start via
the evaluator pipeline (Commit C), which has access to the full transcript.
"""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def main():
    from engrammar.hook_utils import log_error, read_session_id, clear_session_id

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

        # Read stdin (session end data) — not used for audit but consumed
        sys.stdin.read()

        session_id = read_session_id()
        if not session_id:
            return

        # Get shown lesson IDs from DB
        from engrammar.db import get_shown_lesson_ids, write_session_audit, clear_session_shown

        shown_ids = get_shown_lesson_ids(session_id)
        if not shown_ids:
            clear_session_id()
            return

        # Write audit record
        from engrammar.environment import detect_environment
        env = detect_environment()
        repo = env.get("repo")
        tags = env.get("tags", [])

        write_session_audit(session_id, list(shown_ids), tags, repo)

        # Clear session state
        clear_session_shown(session_id)
        clear_session_id()

    except Exception as e:
        log_error("SessionEnd", "main execution", e)
        # Clear state anyway to avoid stale data
        clear_session_id()


if __name__ == "__main__":
    main()
