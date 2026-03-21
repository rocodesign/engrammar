#!/usr/bin/env python3
"""PreToolUse hook — searches engrams relevant to the tool being called.

Uses the daemon for fast search (~20ms). Falls back to direct search if daemon unavailable.
Tracks shown engrams in DB (keyed by session ID) to avoid repeats.
"""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def _extract_narration(transcript_path):
    """Read the last assistant narration text from the transcript.

    Scans backward for the most recent assistant text block.
    Returns the text or None if no narration found.
    """
    try:
        with open(transcript_path, "r") as f:
            lines = f.readlines()

        for line in reversed(lines[-50:]):
            try:
                obj = json.loads(line)
                msg = obj.get("message", {})
                if msg.get("role") != "assistant":
                    continue
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text = block.get("text", "").strip()
                        if text and len(text) > 10:
                            return text
            except (json.JSONDecodeError, Exception):
                continue
    except Exception:
        pass
    return None


def _search_via_daemon(tool_name, tool_input, cwd=None):
    try:
        from engrammar.infra.client import send_request
        response = send_request({
            "type": "tool_context",
            "tool_name": tool_name,
            "tool_input": tool_input,
            "enforce_prerequisites": True,
            "cwd": cwd,
        })
        if response and "results" in response:
            return response["results"]
    except Exception as e:
        from engrammar.infra.hook_utils import log_error
        log_error("PreToolUse", f"daemon search for tool: {tool_name}", e)
    return None


def _search_direct(tool_name, tool_input, cwd=None):
    try:
        from engrammar.search.engine import search_for_tool_context
        return search_for_tool_context(
            tool_name,
            tool_input,
            enforce_prerequisites=True,
            cwd=cwd,
        )
    except Exception as e:
        from engrammar.infra.hook_utils import log_error
        log_error("PreToolUse", f"direct search for tool: {tool_name}", e)
    return None


def main():
    from engrammar.infra.hook_utils import log_error, format_engrams_block, make_hook_output

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

        from engrammar.infra.hook_utils import is_mcp_enabled
        if not is_mcp_enabled():
            return

        raw = sys.stdin.read().strip()
        if not raw:
            return

        data = json.loads(raw)
        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", {})

        if not tool_name:
            return

        # Inject instructions on first tool call in a subagent
        agent_id = data.get("agent_id")
        if agent_id:
            state_file = os.path.join(ENGRAMMAR_HOME, ".subagent_injected.json")
            injected = set()
            try:
                if os.path.exists(state_file):
                    with open(state_file, "r") as f:
                        injected = set(json.load(f))
            except Exception:
                pass
            if agent_id not in injected:
                injected.add(agent_id)
                # Keep only last 20 to avoid unbounded growth
                if len(injected) > 20:
                    injected = set(list(injected)[-20:])
                try:
                    with open(state_file, "w") as f:
                        json.dump(list(injected), f)
                except Exception:
                    pass
                context = (
                    "[ENGRAMMAR_INSTRUCTIONS]\n"
                    "When exploring or planning, call engrammar_search for each area "
                    "you touch — conventions, pitfalls, and past learnings should "
                    "shape your approach. Search by technology, component, pattern, "
                    "or file area involved.\n"
                    "[/ENGRAMMAR_INSTRUCTIONS]"
                )
                output = make_hook_output("PreToolUse", context)
                print(json.dumps(output))
                return

        # Inject planning instruction when entering plan mode
        if tool_name == "EnterPlanMode":
            context = (
                "[ENGRAMMAR_INSTRUCTIONS]\n"
                "Before finalizing your plan, call engrammar_search for each area "
                "your plan touches — conventions, pitfalls, and past learnings should "
                "shape your approach, not just your execution. Search by technology, "
                "pattern, file area, or workflow involved in each step.\n"
                "[/ENGRAMMAR_INSTRUCTIONS]"
            )
            output = make_hook_output("PreToolUse", context)
            print(json.dumps(output))
            return

        from engrammar.core.config import load_config
        config = load_config()
        if not config["hooks"]["tool_use_enabled"]:
            return

        skip_tools = config["hooks"]["skip_tools"]
        if tool_name in skip_tools:
            return

        show_categories = config["display"]["show_categories"]

        # Optionally enrich tool query with narration from transcript
        enrich = config.get("query_enrichment", {}).get("pre_tool", {})
        if enrich.get("inject_narration"):
            transcript_path = data.get("transcript_path")
            if transcript_path:
                narration = _extract_narration(transcript_path)
                if narration:
                    max_len = enrich.get("narration_max_length", 150)
                    narration = narration[:max_len]
                    tool_input = dict(tool_input) if isinstance(tool_input, dict) else {}
                    tool_input["_narration"] = narration

        # Try daemon, fall back to direct
        hook_cwd = data.get("cwd")
        results = _search_via_daemon(tool_name, tool_input, cwd=hook_cwd)
        if results is None:
            results = _search_direct(tool_name, tool_input, cwd=hook_cwd)

        if not results:
            return

        # Filter out already-shown engrams (DB-based)
        session_id = data.get("session_id")
        if session_id:
            from engrammar.core.db import get_shown_engram_ids, record_shown_engram
            shown = get_shown_engram_ids(session_id)
            new_results = [r for r in results if r["id"] not in shown]
        else:
            new_results = results

        if not new_results:
            return

        # Record shown engrams in DB
        if session_id:
            for r in new_results:
                record_shown_engram(session_id, r["id"], "PreToolUse")

        # Log event
        try:
            from engrammar.core.db import log_hook_event
            scores = {r["id"]: round(r.get("score", 0), 4) for r in new_results}
            log_hook_event(session_id, "PreToolUse", [r["id"] for r in new_results], context=tool_name, scores=scores)
        except Exception:
            pass

        context = format_engrams_block(new_results, show_categories=show_categories)
        output = make_hook_output("PreToolUse", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("PreToolUse", "main execution", e)


if __name__ == "__main__":
    main()
