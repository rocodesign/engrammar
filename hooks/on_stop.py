#!/usr/bin/env python3
"""Stop hook — triggers per-turn extraction + writes session audit.

Fires after every assistant response. Must exit fast (never block Claude).
Delegates extraction to the daemon which runs it in the background.
"""

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

        # Skip subagent sessions — short task runs, not real conversations
        if transcript_path and "/subagents/" in transcript_path:
            return

        # Write session audit (shown engrams + env tags) for evaluation
        try:
            from engrammar.db import get_shown_engram_ids, write_session_audit

            shown_ids = get_shown_engram_ids(session_id)
            if shown_ids:
                from engrammar.environment import detect_environment
                env = detect_environment()
                write_session_audit(
                    session_id, list(shown_ids),
                    env.get("tags", []), env.get("repo", ""),
                    transcript_path=transcript_path,
                )
        except Exception as e:
            log_error("Stop", "write_session_audit", e)

        # Send extraction request to daemon (non-blocking)
        if transcript_path:
            try:
                from engrammar.client import send_request

                send_request({
                    "type": "process_turn",
                    "session_id": session_id,
                    "transcript_path": transcript_path,
                }, timeout=2.0)
            except Exception:
                # Fallback: spawn CLI directly if daemon unavailable
                try:
                    cli_path = os.path.join(ENGRAMMAR_HOME, "engrammar-cli")
                    subprocess.Popen(
                        [cli_path, "process-turn",
                         "--session", session_id,
                         "--transcript", transcript_path],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                    )
                except Exception as e:
                    log_error("Stop", "fallback spawn", e)

    except Exception as e:
        log_error("Stop", "main execution", e)


if __name__ == "__main__":
    main()
