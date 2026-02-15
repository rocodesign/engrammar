#!/usr/bin/env python3
"""SessionStart hook — generates session ID, injects pinned lessons, and queues maintenance."""

import json
import sys
import os
import uuid

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def main():
    from engrammar.hook_utils import log_error, write_session_id, format_lessons_block, make_hook_output

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

        # Generate session ID
        session_id = str(uuid.uuid4())
        write_session_id(session_id)

        # Start daemon (if needed) and trigger maintenance jobs with single-flight behavior
        try:
            from engrammar.client import send_request
            send_request({"type": "run_maintenance"})
        except Exception as e:
            log_error("SessionStart", "start daemon/maintenance", e)

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
