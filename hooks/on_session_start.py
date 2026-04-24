#!/usr/bin/env python3
"""SessionStart hook — injects pinned engrams and queues maintenance."""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def main():
    from engrammar.infra.hook_utils import log_error, parse_hook_input, format_engrams_block, make_hook_output

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

        from engrammar.infra.hook_utils import is_mcp_enabled
        if not is_mcp_enabled():
            return

        # Read session_id from Claude's hook payload
        data = parse_hook_input()
        hook_cwd = data.get("cwd")

        from engrammar.search.environment import is_engrammar_active
        if not is_engrammar_active(cwd=hook_cwd):
            return

        session_id = data.get("session_id")

        # Persist session_id so MCP server can auto-capture it for self-extracted engrams
        if session_id:
            from engrammar.infra.hook_utils import write_session_id
            write_session_id(session_id)

        # Clean up stale turn offset files (older than 24h)
        try:
            from engrammar.pipeline.extractor import cleanup_old_turn_offsets
            cleanup_old_turn_offsets()
        except Exception:
            pass

        # Start daemon (if needed) and trigger maintenance jobs with single-flight behavior
        try:
            from engrammar.infra.client import send_request
            send_request({"type": "run_maintenance"})
        except Exception as e:
            log_error("SessionStart", "start daemon/maintenance", e)

        # Get pinned engrams
        from engrammar.core.config import load_config
        from engrammar.core.db import get_pinned_engrams, get_tag_relevance_with_evidence
        from engrammar.search.environment import (
            check_structural_prerequisites,
            detect_environment,
            filter_engrams_for_repo_scope,
        )

        config = load_config()
        env = detect_environment()
        pinned = filter_engrams_for_repo_scope(
            get_pinned_engrams(),
            repo=env.get("repo"),
            config=config,
        )
        env_tags = env.get("tags", [])

        show_categories = config["display"]["show_categories"]
        matching = []
        for p in pinned:
            # Hard-gate on structural prerequisites (os, repo, paths, mcp_servers)
            if not check_structural_prerequisites(p.get("prerequisites"), env):
                continue
            # Soft-gate: overall content tag relevance (no prompt context at session start)
            from engrammar.core.db import get_content_tags
            content_tags = get_content_tags(p["id"])
            if content_tags:
                avg_score, total_evals = get_tag_relevance_with_evidence(p["id"], content_tags)
                if total_evals >= 3 and avg_score < -0.1:
                    continue
            matching.append(p)

        # Build context parts
        parts = []

        # Always inject system instruction from prompt template
        prompt_path = os.path.join(ENGRAMMAR_HOME, "prompts", "injection", "session_start.md")
        try:
            with open(prompt_path, "r") as f:
                content = f.read()
            # Strip YAML frontmatter (between --- markers)
            if content.startswith("---"):
                end = content.index("---", 3)
                content = content[end + 3:].strip()
            parts.append(content)
        except Exception:
            # Fallback to inline if prompt file missing
            parts.append(
                "[ENGRAMMAR_INSTRUCTIONS]\n"
                "When planning or working autonomously, call engrammar_search for each area "
                "you touch — past learnings about conventions, pitfalls, and patterns should "
                "shape your plan, not just your execution. Hooks surface engrams on user "
                "prompts and some tool calls, but during autonomous work you must actively "
                "search. Query by technology, pattern, file area, or workflow involved.\n"
                "[/ENGRAMMAR_INSTRUCTIONS]"
            )

        # Add pinned engrams if any matched
        if matching:
            if session_id:
                from engrammar.core.db import record_shown_engram, update_match_stats
                hook_repo = env.get("repo")
                for p in matching:
                    record_shown_engram(session_id, p["id"], "SessionStart")
                    update_match_stats(p["id"], repo=hook_repo)

            try:
                from engrammar.core.db import log_hook_event
                log_hook_event(session_id, "SessionStart", [p["id"] for p in matching])
            except Exception:
                pass

            parts.append(format_engrams_block(matching, show_categories=show_categories))

        context = "\n".join(parts)
        output = make_hook_output("SessionStart", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("SessionStart", "main execution", e)


if __name__ == "__main__":
    main()
