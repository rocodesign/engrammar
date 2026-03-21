#!/usr/bin/env python3
"""PostToolUse hook — searches engrams using assistant narration text.

Fires after every tool call. For tools that PreToolUse skips (Read, Glob, Grep),
this hook reads the assistant's narration text from the transcript and uses it
as search context. The narration (e.g. "Let me check the GraphQL query...") is
often a better search signal than the tool input alone.

Key design decisions:
- Only searches when narration text exists (skips tool-only responses)
- Caches last narration to avoid duplicate searches
- Rate-limited to avoid overwhelming long sessions
- Higher min_score threshold than PreToolUse (0.60 vs 0.40)
"""

import json
import sys
import os
import time

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

# State file for rate limiting and narration caching
STATE_FILE = os.path.join(ENGRAMMAR_HOME, ".post_tool_state.json")

# Only search for these tools (the ones PreToolUse skips)
TARGET_TOOLS = {"Read", "Glob", "Grep", "WebFetch", "WebSearch"}

# Rate limit: min seconds between searches
RATE_LIMIT_SECONDS = 10

# Min score threshold — higher than PreToolUse since these fire frequently
MIN_SCORE = 0.40


def _read_state():
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def _write_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception:
        pass


def _extract_narration(transcript_path, session_id):
    """Read the last assistant narration text from the transcript.

    Scans backward through the transcript for the most recent assistant
    message that contains text (not just tool calls). Returns the text
    or None if no narration found.
    """
    try:
        # Read last 50 lines — narration is always recent
        lines = []
        with open(transcript_path, "r") as f:
            lines = f.readlines()

        # Scan backward for assistant text
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


def _build_query(narration, tool_name, tool_input, config=None):
    """Build a search query from narration + tool context.

    Uses config.query_enrichment.post_tool settings to control what gets included.
    """
    enrich = {}
    if config:
        enrich = config.get("query_enrichment", {}).get("post_tool", {})

    inject_narration = enrich.get("inject_narration", True)
    narration_max = enrich.get("narration_max_length", 200)
    inject_tool_ctx = enrich.get("inject_tool_context", True)

    parts = []

    if narration and inject_narration:
        parts.append(narration[:narration_max])

    if inject_tool_ctx:
        if tool_name == "Read":
            path = tool_input.get("file_path", "")
            if path:
                segments = path.split("/")
                relevant = "/".join(segments[-3:]) if len(segments) > 3 else path
                parts.append(relevant)
        elif tool_name == "Grep":
            pattern = tool_input.get("pattern", "")
            if pattern:
                parts.append(pattern)
        elif tool_name == "Glob":
            pattern = tool_input.get("pattern", "")
            if pattern:
                parts.append(pattern)

    return " ".join(parts) if parts else None


def _search_via_daemon(query, max_results, cwd=None):
    try:
        from engrammar.infra.client import send_request
        response = send_request({
            "type": "search",
            "query": query,
            "top_k": max_results,
            "enforce_prerequisites": True,
            "cwd": cwd,
        })
        if response and "results" in response:
            return response["results"]
    except Exception:
        pass
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
        session_id = data.get("session_id")
        transcript_path = data.get("transcript_path")

        # Only target tools that PreToolUse skips
        if tool_name not in TARGET_TOOLS:
            return

        if not transcript_path:
            return

        # Extract narration text from transcript
        narration = _extract_narration(transcript_path, session_id)

        # Skip if no narration — tool-only responses aren't worth searching
        if not narration:
            return

        # Check cache: skip if same narration as last search
        state = _read_state()
        if state.get("session_id") == session_id:
            if state.get("last_narration") == narration:
                return

        # Build search query
        from engrammar.core.config import load_config
        config = load_config()

        query = _build_query(narration, tool_name, tool_input, config=config)
        if not query:
            return

        # Search via daemon
        max_results = config["display"].get("max_engrams_per_tool", 2)
        show_categories = config["display"]["show_categories"]

        hook_cwd = data.get("cwd")
        results = _search_via_daemon(query, max_results, cwd=hook_cwd)
        if not results:
            # Update state even on no results to avoid re-searching same narration
            _write_state({
                "session_id": session_id,
                "last_narration": narration,
                "last_search_time": time.time(),
            })
            return

        # Filter by min score
        results = [r for r in results if r.get("score", 0) >= MIN_SCORE]
        if not results:
            _write_state({
                "session_id": session_id,
                "last_narration": narration,
                "last_search_time": time.time(),
            })
            return

        # Filter out already-shown engrams
        if session_id:
            from engrammar.core.db import get_shown_engram_ids, record_shown_engram
            shown = get_shown_engram_ids(session_id)
            results = [r for r in results if r["id"] not in shown]

        if not results:
            _write_state({
                "session_id": session_id,
                "last_narration": narration,
                "last_search_time": time.time(),
            })
            return

        # Record shown engrams
        if session_id:
            for r in results:
                record_shown_engram(session_id, r["id"], "PostToolUse")

        # Log event
        try:
            from engrammar.core.db import log_hook_event
            ctx = f"{tool_name}: {narration[:60]}"
            scores = {r["id"]: round(r.get("score", 0), 4) for r in results}
            log_hook_event(session_id, "PostToolUse", [r["id"] for r in results], context=ctx, scores=scores)
        except Exception:
            pass

        # Update state
        _write_state({
            "session_id": session_id,
            "last_narration": narration,
            "last_search_time": time.time(),
        })

        context = format_engrams_block(results, show_categories=show_categories)
        output = make_hook_output("PostToolUse", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("PostToolUse", "main execution", e)


if __name__ == "__main__":
    main()
