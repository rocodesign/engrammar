#!/usr/bin/env python3
"""UserPromptSubmit hook — searches engrams relevant to the user's prompt.

Uses the daemon for fast search (~20ms). Falls back to direct search if daemon unavailable.
Tracks shown engrams in DB (keyed by session ID) to avoid repeats.
"""

import json
import sys
import os

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def _search_via_daemon(prompt, max_results, cwd=None):
    try:
        from engrammar.infra.client import send_request
        response = send_request({
            "type": "search",
            "query": prompt,
            "top_k": max_results,
            "enforce_prerequisites": True,
            "cwd": cwd,
        })
        if response and "results" in response:
            return response["results"]
    except Exception as e:
        from engrammar.infra.hook_utils import log_error
        log_error("UserPromptSubmit", f"daemon search: {prompt[:50]}", e)
    return None


def _search_direct(prompt, max_results, cwd=None):
    try:
        from engrammar.search.engine import search
        return search(prompt, top_k=max_results, enforce_prerequisites=True, cwd=cwd)
    except Exception as e:
        from engrammar.infra.hook_utils import log_error
        log_error("UserPromptSubmit", f"direct search: {prompt[:50]}", e)
    return None


def _enrich_prompt_query(prompt, config):
    """Apply query enrichment settings to the raw prompt.

    Strips/injects IDE context based on config.query_enrichment.prompt settings.
    Returns the enriched query string.
    """
    import re

    enrich = config.get("query_enrichment", {}).get("prompt", {})
    strip_ide = enrich.get("strip_ide_tags", True)
    inject_file = enrich.get("inject_ide_file", False)
    inject_selection = enrich.get("inject_ide_selection", False)
    max_length = enrich.get("max_query_length", 300)

    ide_file = None
    ide_selection = None

    # Extract IDE context before stripping
    if inject_file or inject_selection:
        file_match = re.search(
            r'<ide_opened_file>The user opened the file ([^<]+?) in the IDE[^<]*</ide_opened_file>',
            prompt, re.DOTALL
        )
        if file_match:
            full_path = file_match.group(1).strip()
            segments = full_path.split("/")
            ide_file = "/".join(segments[-3:]) if len(segments) > 3 else full_path

        sel_match = re.search(
            r'<ide_selection>[^:]+:\n(.*?)\n\nThis may or may not',
            prompt, re.DOTALL
        )
        if sel_match:
            ide_selection = sel_match.group(1).strip()[:100]

    # Strip IDE tags from query
    if strip_ide:
        prompt = re.sub(r'<ide_opened_file>.*?</ide_opened_file>\s*', '', prompt, flags=re.DOTALL)
        prompt = re.sub(r'<ide_selection>.*?</ide_selection>\s*', '', prompt, flags=re.DOTALL)

    # Strip other system tags
    prompt = re.sub(r'<task-notification>.*?</task-notification>\s*', '', prompt, flags=re.DOTALL)
    prompt = re.sub(r'<system-reminder>.*?</system-reminder>\s*', '', prompt, flags=re.DOTALL)

    prompt = prompt.strip()

    # Inject IDE context if configured
    if inject_file and ide_file:
        prompt = f"[file: {ide_file}] {prompt}"
    if inject_selection and ide_selection:
        prompt = f"[selection: {ide_selection}] {prompt}"

    # Truncate to max length
    if max_length and len(prompt) > max_length:
        prompt = prompt[:max_length]

    return prompt


def main():
    from engrammar.infra.hook_utils import log_error, format_engrams_block, make_hook_output

    try:
        if os.environ.get("ENGRAMMAR_INTERNAL_RUN") == "1":
            return

        raw = sys.stdin.read().strip()
        if not raw:
            return

        data = json.loads(raw)
        hook_cwd = data.get("cwd")

        from engrammar.infra.hook_utils import is_mcp_enabled, sync_project_mcp_for_cwd
        sync_project_mcp_for_cwd(cwd=hook_cwd)
        if not is_mcp_enabled(cwd=hook_cwd):
            return

        from engrammar.search.environment import is_engrammar_active
        if not is_engrammar_active(cwd=hook_cwd):
            return

        prompt = data.get("prompt", "")
        if not prompt or len(prompt) < 5:
            return

        from engrammar.core.config import load_config
        config = load_config()
        if not config["hooks"]["prompt_enabled"]:
            return

        # Apply query enrichment
        search_query = _enrich_prompt_query(prompt, config)
        if not search_query or len(search_query) < 5:
            return

        max_results = config["display"]["max_engrams_per_prompt"]
        show_categories = config["display"]["show_categories"]

        # Try daemon, fall back to direct
        results = _search_via_daemon(search_query, max_results, cwd=hook_cwd)
        if results is None:
            results = _search_direct(search_query, max_results, cwd=hook_cwd)

        if not results:
            return

        # Filter by min score
        min_score = config["hooks"].get("min_score_prompt", 0.50)
        results = [r for r in results if r.get("score", 0) >= min_score]
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

        # Detect prompt tags for evaluation attribution
        prompt_tags = None
        try:
            from engrammar.search.prompt_tags import detect_prompt_tags
            pt_config = config.get("scoring", {})
            prompt_tags = detect_prompt_tags(
                search_query,
                top_k=pt_config.get("prompt_tag_top_k", 3),
                threshold=pt_config.get("prompt_tag_threshold", 0.60),
            )
        except Exception:
            pass

        # Record shown engrams in DB and update match stats
        if session_id:
            from engrammar.core.db import update_match_stats
            from engrammar.search.environment import _detect_repo
            hook_repo = _detect_repo(cwd=hook_cwd) if hook_cwd else None
            for r in new_results:
                record_shown_engram(
                    session_id, r["id"], "UserPromptSubmit",
                    prompt_tags=prompt_tags, query_text=search_query,
                )
                update_match_stats(r["id"], repo=hook_repo)

        # Log event
        try:
            from engrammar.core.db import log_hook_event
            ctx = prompt[:80] if prompt else None
            scores = {r["id"]: round(r.get("score", 0), 4) for r in new_results}
            log_hook_event(session_id, "UserPromptSubmit", [r["id"] for r in new_results], context=ctx, scores=scores)
        except Exception:
            pass

        context = format_engrams_block(new_results, show_categories=show_categories)
        output = make_hook_output("UserPromptSubmit", context)
        print(json.dumps(output))

    except Exception as e:
        log_error("UserPromptSubmit", "main execution", e)


if __name__ == "__main__":
    main()
