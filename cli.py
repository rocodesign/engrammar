#!/usr/bin/env python3
"""Engrammar CLI — manage semantic engrams for Claude Code sessions."""

import json
import os
import sys

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def cmd_setup(args):
    """Initialize database + build index."""
    from engrammar.core.config import DB_PATH, ENGRAMMAR_HOME
    from engrammar.core.db import init_db, get_engram_count

    print("Initializing database...")
    init_db()

    count = get_engram_count()
    if count == 0:
        print("Empty database. Run 'engrammar extract' to populate from transcripts.")
    else:
        print(f"Database has {count} engrams.")

    # Build embedding index
    print("Building embedding index...")
    from engrammar.core.db import get_all_active_engrams
    from engrammar.core.embeddings import build_index, build_tag_index, build_tag_vocab_index

    engrams = get_all_active_engrams()
    if engrams:
        n = build_index(engrams)
        print(f"Indexed {n} engrams.")
        nt = build_tag_index(engrams)
        print(f"Cached {nt} tag embeddings.")
        nv = build_tag_vocab_index()
        print(f"Built tag vocabulary: {nv} unique tags.")
    else:
        print("No engrams to index.")

    print("Setup complete.")


def cmd_status(args):
    """Show database stats, index health, hook config."""
    from engrammar.core.config import DB_PATH, INDEX_PATH, IDS_PATH, TAG_INDEX_PATH, CONFIG_PATH, load_config
    from engrammar.core.db import get_engram_count, get_category_stats
    from engrammar.search.environment import _detect_repo

    config = load_config()
    controls = config.get("controls", {})
    repo = _detect_repo()

    print("=== Engrammar Status ===\n")

    # Database
    if os.path.exists(DB_PATH):
        count = get_engram_count()
        print(f"Database:   {DB_PATH}")
        print(f"Engrams:    {count} active")

        stats = get_category_stats()
        if stats:
            print("\nCategories:")
            for cat, cnt in stats:
                print(f"  {cat or 'uncategorized'}: {cnt}")
    else:
        print(f"Database:   NOT FOUND ({DB_PATH})")

    # Index
    print()
    if os.path.exists(INDEX_PATH):
        import numpy as np
        emb = np.load(INDEX_PATH, mmap_mode="r")
        print(f"Index:      {INDEX_PATH}")
        print(f"Embeddings: {emb.shape[0]} vectors" + (f" x {emb.shape[1]} dims" if emb.ndim == 2 else ""))
    else:
        print(f"Index:      NOT FOUND ({INDEX_PATH})")

    # Content tags
    from engrammar.core.db import get_all_content_tags_vocab
    vocab = get_all_content_tags_vocab(min_frequency=1)
    if vocab:
        total_tags = sum(cnt for _, cnt in vocab)
        unique_tags = len(vocab)
        print(f"Content tags: {total_tags} total across {unique_tags} unique tags")
        top_tags = vocab[:8]
        print(f"  Top tags: {', '.join(f'{t}({c})' for t, c in top_tags)}")
    else:
        print(f"Content tags: none (run extraction or backfill to populate)")

    # Tag index
    if os.path.exists(TAG_INDEX_PATH):
        tag_emb = np.load(TAG_INDEX_PATH, mmap_mode="r")
        if tag_emb.size > 0:
            print(f"Tag index:  {tag_emb.shape[0]} cached tag embeddings")
        else:
            print(f"Tag index:  empty")
    else:
        print(f"Tag index:  NOT BUILT (run 'rebuild' to create)")

    # Config
    print()
    print(f"Config:     {CONFIG_PATH}")
    print(f"Prompt hook:  {'enabled' if config['hooks']['prompt_enabled'] else 'disabled'}")
    print(f"Tool hook:    {'enabled' if config['hooks']['tool_use_enabled'] else 'disabled'}")
    print(f"Skip tools:   {', '.join(config['hooks']['skip_tools'])}")
    print()
    print(f"Global disabled: {'yes' if controls.get('global_disabled') else 'no'}")
    print(f"Current repo:    {repo or 'not detected'}")
    if repo:
        print(f"Repo disabled:   {'yes' if repo in controls.get('disabled_repos', []) else 'no'}")
        print(f"Repo isolated:   {'yes' if repo in controls.get('isolated_repos', []) else 'no'}")


def _format_toggle(state):
    return "on" if state else "off"


def _require_current_repo():
    from engrammar.search.environment import _detect_repo

    repo = _detect_repo()
    if not repo:
        print("No git repository detected for the current directory.")
        return None
    return repo


def cmd_isolate(args):
    """Show or toggle isolation for the current repo."""
    from engrammar.core.config import load_config, set_repo_isolated

    repo = _require_current_repo()
    if not repo:
        return

    config = load_config()
    isolated = repo in config.get("controls", {}).get("isolated_repos", [])

    if not args:
        next_state = "off" if isolated else "on"
        print(f"Repo '{repo}' isolation is {_format_toggle(isolated)}.")
        print(f"Toggle with: engrammar isolate {next_state}")
        return

    if len(args) != 1 or args[0] not in ("on", "off"):
        print("Usage: engrammar isolate [on|off]")
        return

    should_isolate = args[0] == "on"
    set_repo_isolated(repo, should_isolate)
    print(f"Repo '{repo}' isolation set to {args[0]}.")


def cmd_disable(args):
    """Show or toggle global/current-repo disabled state."""
    from engrammar.core.config import load_config, set_global_disabled, set_repo_disabled
    from engrammar.infra.hook_utils import set_mcp_disabled

    config = load_config()
    controls = config.get("controls", {})
    repo = _require_current_repo() if args[:1] == ["repo"] or not args else None
    global_disabled = bool(controls.get("global_disabled"))
    repo_disabled = bool(repo and repo in controls.get("disabled_repos", []))

    if not args:
        repo = _require_current_repo()
        repo_disabled = bool(repo and repo in controls.get("disabled_repos", []))
        print(f"Global disable is {_format_toggle(global_disabled)}.")
        print(f"Toggle with: engrammar disable global {'off' if global_disabled else 'on'}")
        if repo:
            print(f"Repo '{repo}' disable is {_format_toggle(repo_disabled)}.")
            print(f"Toggle with: engrammar disable repo {'off' if repo_disabled else 'on'}")
        else:
            print("Repo disable is unavailable outside a git repository.")
        return

    if len(args) != 2 or args[0] not in ("global", "repo") or args[1] not in ("on", "off"):
        print("Usage: engrammar disable [global|repo] [on|off]")
        return

    should_disable = args[1] == "on"
    if args[0] == "global":
        set_global_disabled(should_disable)
        set_mcp_disabled(should_disable)
        print(f"Global disable set to {args[1]}.")
        return

    repo = _require_current_repo()
    if not repo:
        return

    set_repo_disabled(repo, should_disable)
    print(f"Repo '{repo}' disable set to {args[1]}.")


def cmd_search(args):
    """Search engrams."""
    if not args:
        print("Usage: engrammar search \"query\" [--category CATEGORY] [--tags tag1,tag2,...]")
        return

    query = args[0]
    category = None
    tags = None
    if "--category" in args:
        idx = args.index("--category")
        if idx + 1 < len(args):
            category = args[idx + 1]
    if "--tags" in args:
        idx = args.index("--tags")
        if idx + 1 < len(args):
            tags = args[idx + 1].split(",")

    from engrammar.search.engine import search

    results = search(query, category_filter=category, tag_filter=tags, top_k=5, skip_prerequisites=True)

    if not results:
        print("No matching engrams found.")
        return

    print(f"Found {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r.get('category', 'general')}] (score: {r.get('score', 0):.4f})")
        print(f"     {r['text']}")
        print(f"     matched: {r.get('times_matched', 0)}x | occurrences: {r.get('occurrence_count', 1)}")
        print()


def cmd_add(args):
    """Add a new engram."""
    if not args:
        print("Usage: engrammar add \"engram text\" --category dev/frontend/styling [--tags tag1,tag2,...]")
        return

    text = args[0]
    category = "general"
    tags = None
    if "--category" in args:
        idx = args.index("--category")
        if idx + 1 < len(args):
            category = args[idx + 1]
    if "--tags" in args:
        idx = args.index("--tags")
        if idx + 1 < len(args):
            tags = args[idx + 1].split(",")

    from engrammar.core.db import add_engram, get_all_active_engrams, add_content_tags
    from engrammar.core.embeddings import build_index, build_tag_index
    from engrammar.search.environment import _detect_repo

    engram_id = add_engram(
        text=text,
        category=category,
        source="manual",
        origin_repo=_detect_repo(),
    )

    # Write tags to engram_tags table (content tags, not prerequisites)
    if tags:
        add_content_tags(engram_id, tags, source="manual")
        print(f"Added engram #{engram_id} in category '{category}' with tags: {', '.join(tags)}")
    else:
        print(f"Added engram #{engram_id} in category '{category}'")

    # Rebuild index
    print("Rebuilding index...")
    engrams = get_all_active_engrams()
    build_index(engrams)
    build_tag_index(engrams)
    print("Done.")


def cmd_import(args):
    """Import engrams from a JSON or markdown file."""
    if not args:
        print("Usage: engrammar import FILE")
        return

    filepath = args[0]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    from engrammar.core.db import import_from_state_file, add_engram, get_all_active_engrams
    from engrammar.core.embeddings import build_index, build_tag_index

    if filepath.endswith(".json"):
        imported = import_from_state_file(filepath)
        print(f"Imported {imported} engrams from {filepath}")
    else:
        # Treat as markdown — each line starting with "- " is a engram
        imported = 0
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("- "):
                    text = line[2:].strip()
                    if text:
                        add_engram(text=text, category="general", source="manual")
                        imported += 1
        print(f"Imported {imported} engrams from {filepath}")

    # Rebuild index
    print("Rebuilding index...")
    engrams = get_all_active_engrams()
    build_index(engrams)
    build_tag_index(engrams)
    print("Done.")


def cmd_export(args):
    """Export all engrams to markdown."""
    from engrammar.core.db import get_all_active_engrams

    engrams = get_all_active_engrams()
    if not engrams:
        print("No engrams to export.")
        return

    # Group by category
    by_category = {}
    for l in engrams:
        cat = l.get("category", "general")
        by_category.setdefault(cat, []).append(l)

    for cat in sorted(by_category.keys()):
        print(f"\n## {cat}\n")
        for l in by_category[cat]:
            print(f"- {l['text']}")


def cmd_extract(args):
    """Extract engrams from conversation transcripts."""
    dry_run = "--dry-run" in args

    # Single-session extraction: extract --session <uuid>
    session_id = None
    if "--session" in args:
        idx = args.index("--session")
        if idx + 1 < len(args):
            session_id = args[idx + 1]

    if session_id:
        from engrammar.pipeline.extractor import extract_from_single_session

        summary = extract_from_single_session(session_id)
        if not dry_run:
            print(f"\nSummary: {summary['extracted']} added, {summary['merged']} merged")
        return

    from engrammar.pipeline.extractor import extract_from_transcripts

    # Parse --limit N
    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        if idx + 1 < len(args):
            try:
                limit = int(args[idx + 1])
            except ValueError:
                pass

    summary = extract_from_transcripts(limit=limit, dry_run=dry_run)

    if not dry_run:
        print(f"\nSummary: {summary['processed']} processed, "
              f"{summary['extracted']} added, {summary['merged']} merged, "
              f"{summary['skipped']} skipped")


def cmd_rebuild(args):
    """Rebuild the embedding index."""
    from engrammar.core.db import get_all_active_engrams
    from engrammar.core.embeddings import build_index, build_tag_index, build_tag_vocab_index

    print("Loading engrams...")
    engrams = get_all_active_engrams()

    if not engrams:
        print("No engrams to index.")
        return

    print(f"Building index for {len(engrams)} engrams...")
    n = build_index(engrams)
    nt = build_tag_index(engrams)
    nv = build_tag_vocab_index()
    print(f"Done. Indexed {n} engrams, cached {nt} tag embeddings, {nv} vocab tags.")


def cmd_list(args):
    """List all engrams with optional pagination. Use --verbose for full details."""
    from engrammar.core.db import get_all_active_engrams

    offset = 0
    limit = 20
    category = None
    verbose = "--verbose" in args or "-v" in args
    sort_by = "id"

    # Parse args
    i = 0
    while i < len(args):
        if args[i] == "--offset" and i + 1 < len(args):
            offset = int(args[i + 1])
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            category = args[i + 1]
            i += 2
        elif args[i] == "--sort" and i + 1 < len(args):
            sort_by = args[i + 1]
            i += 2
        elif args[i] in ("--verbose", "-v"):
            i += 1
        else:
            i += 1

    engrams = get_all_active_engrams()

    # Filter by category if specified
    if category:
        if verbose:
            engrams = [l for l in engrams if l.get("category", "").startswith(category)]
        else:
            from engrammar.core.db import get_connection
            conn = get_connection()
            rows = conn.execute(
                "SELECT engram_id FROM engram_categories WHERE category_path LIKE ?",
                (category + "%",)
            ).fetchall()
            conn.close()
            category_ids = {r["engram_id"] for r in rows}
            engrams = [l for l in engrams if l["id"] in category_ids]

    if not engrams:
        print("No engrams found.")
        return

    if verbose:
        _list_verbose(engrams, sort_by, category)
    else:
        total = len(engrams)
        page = engrams[offset:offset + limit]

        print(f"=== Engrams ({offset + 1}-{offset + len(page)} of {total}) ===\n")

        for l in page:
            print(f"ID {l['id']}: [{l.get('category', 'general')}] {l['text'][:80]}...")
            if l.get("pinned"):
                print(f"  PINNED")
            if l.get("prerequisites"):
                prereqs = json.loads(l["prerequisites"]) if isinstance(l["prerequisites"], str) else l["prerequisites"]
                print(f"  Prerequisites: {prereqs}")
            print(f"  Matched: {l.get('times_matched', 0)}x | Occurrences: {l.get('occurrence_count', 1)}")
            print()


def _list_verbose(engrams, sort_by="id", category=None):
    """Show full engram details with tags/scores (git-log style)."""
    from engrammar.core.db import get_connection

    conn = get_connection()

    # Preload all tag relevance scores
    tag_scores = {}
    rows = conn.execute(
        "SELECT engram_id, tag, score, positive_evals, negative_evals "
        "FROM engram_tag_relevance ORDER BY engram_id, score DESC"
    ).fetchall()
    for r in rows:
        tag_scores.setdefault(r["engram_id"], []).append(dict(r))

    # Preload repo stats
    repo_stats = {}
    rows = conn.execute(
        "SELECT engram_id, repo, times_matched FROM engram_repo_stats ORDER BY engram_id"
    ).fetchall()
    for r in rows:
        repo_stats.setdefault(r["engram_id"], []).append(dict(r))

    # Sort
    if sort_by == "score":
        def best_score(l):
            scores = tag_scores.get(l["id"], [])
            return max((s["score"] for s in scores), default=0)
        engrams.sort(key=best_score, reverse=True)
    elif sort_by == "matched":
        engrams.sort(key=lambda l: l.get("times_matched", 0), reverse=True)

    # Print each engram
    for l in engrams:
        lid = l["id"]
        pinned = " PINNED" if l.get("pinned") else ""
        print(f"\033[33mengram {lid}\033[0m{pinned}")
        print(f"Category: {l.get('category', 'general')}")
        print(f"Source:   {l.get('source', 'manual')}")

        # Show transcript paths from source sessions
        source_sessions = l.get("source_sessions")
        if source_sessions:
            if isinstance(source_sessions, str):
                source_sessions = json.loads(source_sessions)
            if source_sessions:
                audit_rows = conn.execute(
                    f"SELECT transcript_path FROM session_audit WHERE session_id IN ({','.join('?' for _ in source_sessions)})",
                    source_sessions,
                ).fetchall()
                paths = [r["transcript_path"] for r in audit_rows if r["transcript_path"]]
                if paths:
                    for p in paths:
                        print(f"Transcript: {p}")

        print(f"Created:  {l.get('created_at', 'unknown')}")
        if l.get("updated_at"):
            print(f"Updated:  {l['updated_at']}")
        print(f"Matched:  {l.get('times_matched', 0)}x | Occurrences: {l.get('occurrence_count', 1)}")

        # Prerequisites
        prereqs = l.get("prerequisites")
        if prereqs:
            if isinstance(prereqs, str):
                prereqs = json.loads(prereqs)
            parts = []
            if prereqs.get("tags"):
                parts.append(f"tags={prereqs['tags']}")
            if prereqs.get("repos"):
                parts.append(f"repos={prereqs['repos']}")
            if prereqs.get("tools"):
                parts.append(f"tools={prereqs['tools']}")
            if parts:
                print(f"Prereqs:  {', '.join(parts)}")

        # Repo stats
        repos = repo_stats.get(lid, [])
        if repos:
            repo_parts = [f"{r['repo']}({r['times_matched']}x)" for r in repos]
            print(f"Repos:    {', '.join(repo_parts)}")

        # Tag relevance scores
        scores = tag_scores.get(lid, [])
        if scores:
            score_parts = []
            for s in scores:
                tag = s["tag"]
                sc = s["score"]
                pos = s["positive_evals"]
                neg = s["negative_evals"]
                if sc > 0.1:
                    color = "\033[32m"  # green
                elif sc < -0.1:
                    color = "\033[31m"  # red
                else:
                    color = "\033[90m"  # gray
                score_parts.append(f"  {color}{tag:12s} {sc:+.3f}  (+{pos}/-{neg})\033[0m")
            print("Tags:")
            print("\n".join(score_parts))

        # Full text
        print()
        print(f"    {l['text']}")
        print()

    conn.close()
    print(f"--- {len(engrams)} engrams ---")


def cmd_update(args):
    """Update a engram's text, category, or prerequisites."""
    if len(args) < 2:
        print("Usage: engrammar update LESSON_ID [--text \"new text\"] [--category cat] [--prereqs '{\"repos\": [\"foo\"]}']")
        return

    engram_id = int(args[0])
    text = None
    category = None
    prereqs = None

    i = 1
    while i < len(args):
        if args[i] == "--text" and i + 1 < len(args):
            text = args[i + 1]
            i += 2
        elif args[i] == "--category" and i + 1 < len(args):
            category = args[i + 1]
            i += 2
        elif args[i] == "--prereqs" and i + 1 < len(args):
            prereqs = json.loads(args[i + 1])
            i += 2
        else:
            i += 1

    from engrammar.core.db import (
        _parse_category,
        add_engram_category,
        get_all_active_engrams,
        get_connection,
        remove_engram_category,
    )
    from engrammar.core.embeddings import build_index, build_tag_index

    conn = get_connection()

    # Check if engram exists
    row = conn.execute("SELECT * FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    if not row:
        print(f"Engram {engram_id} not found.")
        conn.close()
        return

    updates = []
    params = []

    if text is not None:
        updates.append("text = ?")
        params.append(text)

    if category is not None:
        # Sync junction table
        old_category = row["category"]
        if old_category:
            remove_engram_category(engram_id, old_category)
        add_engram_category(engram_id, category)
        level1, level2, level3 = _parse_category(category)

        updates.append("category = ?")
        params.append(category)
        updates.append("level1 = ?")
        params.append(level1)
        updates.append("level2 = ?")
        params.append(level2)
        updates.append("level3 = ?")
        params.append(level3)

    if prereqs is not None:
        prereqs_json = json.dumps(prereqs) if isinstance(prereqs, dict) else prereqs
        updates.append("prerequisites = ?")
        params.append(prereqs_json)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(engram_id)
        conn.execute(
            f"UPDATE engrams SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

    conn.close()

    print(f"Updated engram {engram_id}")

    # Rebuild index if text changed
    if text is not None:
        print("Rebuilding index...")
        engrams = get_all_active_engrams()
        build_index(engrams)
        build_tag_index(engrams)
        print("Done.")

    # Rebuild tag index if prerequisites changed
    if prereqs is not None and text is None:
        print("Rebuilding tag index...")
        engrams = get_all_active_engrams()
        build_tag_index(engrams)
        print("Done.")


def cmd_deprecate(args):
    """Deprecate (soft-delete) a engram."""
    if not args:
        print("Usage: engrammar deprecate LESSON_ID")
        return

    engram_id = int(args[0])

    from engrammar.core.db import deprecate_engram

    deprecate_engram(engram_id)
    print(f"Deprecated engram {engram_id}")


def cmd_pin(args):
    """Pin a engram (always shown at session start)."""
    if not args:
        print("Usage: engrammar pin LESSON_ID")
        return

    engram_id = int(args[0])

    from engrammar.core.db import get_connection

    conn = get_connection()
    conn.execute("UPDATE engrams SET pinned = 1 WHERE id = ?", (engram_id,))
    conn.commit()
    conn.close()

    print(f"Pinned engram {engram_id}")


def cmd_unpin(args):
    """Unpin a engram."""
    if not args:
        print("Usage: engrammar unpin LESSON_ID")
        return

    engram_id = int(args[0])

    from engrammar.core.db import get_connection

    conn = get_connection()
    conn.execute("UPDATE engrams SET pinned = 0 WHERE id = ?", (engram_id,))
    conn.commit()
    conn.close()

    print(f"Unpinned engram {engram_id}")


def cmd_categorize(args):
    """Add or remove categories from a engram."""
    if len(args) < 3 or args[1] not in ("add", "remove"):
        print("Usage: engrammar categorize LESSON_ID add|remove CATEGORY")
        return

    engram_id = int(args[0])
    action = args[1]
    category = args[2]

    from engrammar.core.db import add_engram_category, remove_engram_category

    if action == "add":
        add_engram_category(engram_id, category)
        print(f"Added category '{category}' to engram {engram_id}")
    else:
        remove_engram_category(engram_id, category)
        print(f"Removed category '{category}' from engram {engram_id}")


def cmd_reset_stats(args):
    """Reset all match statistics and pins to start fresh."""
    confirm = "--confirm" in args

    if not confirm:
        print("This will reset all engrams:")
        print("  - Unpin all engrams (pinned = 0)")
        print("  - Reset match counts (times_matched = 0)")
        print("  - Clear per-repo match tracking")
        print("  - Preserve engram text, categories, and manual prerequisites")
        print()
        print("Run with --confirm to proceed: engrammar reset-stats --confirm")
        return

    from engrammar.core.db import get_connection

    conn = get_connection()

    # Reset all engram stats
    conn.execute("""
        UPDATE engrams
        SET pinned = 0,
            times_matched = 0,
            last_matched = NULL
    """)

    # Clear per-repo stats
    conn.execute("DELETE FROM engram_repo_stats")

    conn.commit()

    # Get count for confirmation
    count = conn.execute("SELECT COUNT(*) FROM engrams WHERE deprecated = 0").fetchone()[0]
    conn.close()

    print(f"✅ Reset complete:")
    print(f"   - Unpinned all engrams")
    print(f"   - Reset match counts to 0 for {count} active engrams")
    print(f"   - Cleared per-repo tracking")
    print()
    print("Match counts will rebuild with intelligent tracking as you use Claude Code.")


def cmd_backfill(args):
    """Create audit records from past sessions for the evaluator pipeline."""
    import subprocess

    backfill_script = os.path.join(ENGRAMMAR_HOME, "backfill_stats.py")
    venv_python = os.path.join(ENGRAMMAR_HOME, "venv", "bin", "python")

    # Forward all args to backfill script
    result = subprocess.run([venv_python, backfill_script] + args)
    sys.exit(result.returncode)


def cmd_evaluate(args):
    """Run relevance evaluations for a specific session or pending sessions."""
    limit = 5
    session_id = None
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        else:
            i += 1

    from engrammar.pipeline.evaluator import run_evaluation_for_session, run_pending_evaluations

    if session_id:
        print(f"Evaluating session {session_id[:12]}...")
        success = run_evaluation_for_session(session_id)
        print(f"  {'Completed' if success else 'Failed'}")
    else:
        print(f"Running pending evaluations (limit: {limit})...")
        results = run_pending_evaluations(limit=limit)
        print(f"  Completed: {results['completed']}")
        print(f"  Failed:    {results['failed']}")
        print(f"  Total:     {results['total']}")


def cmd_backfill_prereqs(args):
    """Retroactively set prerequisites on existing engrams using keyword inference + session audit tags."""
    dry_run = "--dry-run" in args

    from engrammar.core.db import get_all_active_engrams, get_connection, get_env_tags_for_sessions
    from engrammar.pipeline.extractor import _infer_prerequisites

    engrams = get_all_active_engrams()
    if not engrams:
        print("No active engrams found.")
        return

    updated = 0
    skipped = 0
    for engram in engrams:
        existing_prereqs = None
        if engram.get("prerequisites"):
            try:
                existing_prereqs = json.loads(engram["prerequisites"]) if isinstance(engram["prerequisites"], str) else engram["prerequisites"]
            except (json.JSONDecodeError, TypeError):
                existing_prereqs = None

        # Always look up session audit tags
        source_sessions = json.loads(engram.get("source_sessions") or "[]")
        audit_tags = get_env_tags_for_sessions(source_sessions) if source_sessions else []

        # Only run keyword inference if no existing prerequisites
        keyword_prereqs = None
        if not existing_prereqs:
            keyword_prereqs = _infer_prerequisites(engram["text"])

        # Merge audit tags into prerequisites
        merged = existing_prereqs or keyword_prereqs or {}
        if audit_tags:
            existing_tags = set(merged.get("tags", []))
            existing_tags.update(audit_tags)
            merged["tags"] = sorted(existing_tags)

        if not merged:
            skipped += 1
            continue

        # Check if anything actually changed
        old_json = engram.get("prerequisites") or "{}"
        try:
            old_parsed = json.loads(old_json) if isinstance(old_json, str) else old_json
        except (json.JSONDecodeError, TypeError):
            old_parsed = {}
        if merged == old_parsed:
            skipped += 1
            continue

        if dry_run:
            print(f"  Would set engram #{engram['id']}: {json.dumps(merged)}")
            print(f"    Text: {engram['text'][:80]}...")
            updated += 1
        else:
            from datetime import datetime
            conn = get_connection()
            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE engrams SET prerequisites = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged), now, engram["id"]),
            )
            conn.commit()
            conn.close()
            print(f"  Set engram #{engram['id']}: {json.dumps(merged)}")
            updated += 1

    mode = "Would update" if dry_run else "Updated"
    print(f"\n{mode} {updated} engrams, skipped {skipped}.")

    # Rebuild tag index after prerequisite changes
    if not dry_run and updated > 0:
        from engrammar.core.embeddings import build_tag_index
        print("Rebuilding tag index...")
        engrams = get_all_active_engrams()
        nt = build_tag_index(engrams)
        print(f"Cached {nt} tag embeddings.")


def cmd_process_turn(args):
    """Process a single turn — extract engrams from new transcript content."""
    session_id = None
    transcript_path = None

    i = 0
    while i < len(args):
        if args[i] == "--session" and i + 1 < len(args):
            session_id = args[i + 1]
            i += 2
        elif args[i] == "--transcript" and i + 1 < len(args):
            transcript_path = args[i + 1]
            i += 2
        else:
            i += 1

    if not session_id or not transcript_path:
        print("Usage: engrammar process-turn --session UUID --transcript PATH")
        return

    from engrammar.pipeline.extractor import extract_from_turn

    summary = extract_from_turn(session_id, transcript_path)
    print(f"Turn extraction: {summary.get('extracted', 0)} added, {summary.get('merged', 0)} merged")


def cmd_log(args):
    """Show hook event log — what was injected, when, and by which hook."""
    from engrammar.core.db import get_hook_events, get_connection

    # Parse args
    tail = 20
    session_filter = None
    hook_filter = None
    i = 0
    while i < len(args):
        if args[i] == "--tail" and i + 1 < len(args):
            tail = int(args[i + 1])
            i += 2
        elif args[i] == "--session" and i + 1 < len(args):
            session_filter = args[i + 1]
            i += 2
        elif args[i] == "--hook" and i + 1 < len(args):
            hook_filter = args[i + 1]
            i += 2
        else:
            i += 1

    events = get_hook_events(limit=tail)

    if not events:
        print("No hook events logged yet.")
        print("Events will appear here as engrams are injected during sessions.")
        return

    # Apply filters
    if session_filter:
        events = [e for e in events if e.get("session_id", "").startswith(session_filter)]
    if hook_filter:
        events = [e for e in events if hook_filter.lower() in e.get("hook_event", "").lower()]

    if not events:
        print("No events match the filter.")
        return

    # Preload engram texts for display
    engram_ids_needed = set()
    for e in events:
        ids = json.loads(e["engram_ids"])
        engram_ids_needed.update(ids)

    engram_texts = {}
    if engram_ids_needed:
        conn = get_connection()
        placeholders = ",".join("?" * len(engram_ids_needed))
        rows = conn.execute(
            f"SELECT id, text FROM engrams WHERE id IN ({placeholders})",
            list(engram_ids_needed),
        ).fetchall()
        conn.close()
        engram_texts = {r["id"]: r["text"] for r in rows}

    # Print events (most recent first, already sorted by get_hook_events)
    for e in events:
        ts = e["timestamp"][:19].replace("T", " ")
        hook = e["hook_event"]
        sid = e["session_id"][:8] if e.get("session_id") else "unknown"
        ids = json.loads(e["engram_ids"])
        ctx = e.get("context") or ""

        # Color the hook name
        if hook == "SessionStart":
            color = "\033[34m"  # blue
        elif hook == "UserPromptSubmit":
            color = "\033[32m"  # green
        elif hook == "PreToolUse":
            color = "\033[33m"  # yellow
        else:
            color = "\033[0m"

        id_str = ", ".join(f"#{lid}" for lid in ids)
        print(f"\033[90m{ts}\033[0m  {color}{hook:20s}\033[0m  \033[90m({sid})\033[0m")
        print(f"  Injected: {id_str}")
        if ctx:
            print(f"  Context:  {ctx[:100]}")
        # Show engram text snippets
        for lid in ids:
            text = engram_texts.get(lid, "<deleted>")
            print(f"    #{lid}: {text[:70]}{'...' if len(text) > 70 else ''}")
        print()

    print(f"--- {len(events)} events ---")


def cmd_detect_tags(args):
    """Show detected environment tags for the current directory."""
    from engrammar.search.environment import detect_environment

    env = detect_environment()
    tags = env.get("tags", [])

    print("Detected environment tags:")
    if tags:
        for tag in tags:
            print(f"  - {tag}")
    else:
        print("  (no tags detected)")

    print(f"\nCurrent directory: {env.get('cwd', 'unknown')}")
    print(f"Repository: {env.get('repo', 'unknown')}")


def cmd_backfill_repo_tags(args):
    """Backfill missing repo:X tags from source session env_tags.

    Extracted lessons don't have repo tags if they were extracted before the repo tag
    feature was added to the extraction pipeline. This command fills in missing repo tags
    from the source session's environment tags recorded in session_audit.

    Returns:
        Number of engrams updated and total tags added.
    """
    from engrammar.core.db import backfill_repo_tags

    print("Backfilling missing repo tags from source sessions...")
    updated, added = backfill_repo_tags()
    print(f"Updated {updated} engrams with {added} repo tags")


def cmd_restore_db(args):
    """List DB backups and restore a selected one."""
    import glob
    import shutil

    from engrammar.core.config import DB_PATH, ENGRAMMAR_HOME

    pattern = os.path.join(ENGRAMMAR_HOME, "engrams.db.backup-*")
    backups = sorted(glob.glob(pattern))

    if not backups:
        print("No backups found.")
        return

    if args and args[0] == "--list":
        print(f"Found {len(backups)} backup(s):\n")
        for i, b in enumerate(backups, 1):
            size_kb = os.path.getsize(b) / 1024
            name = os.path.basename(b)
            print(f"  {i}. {name}  ({size_kb:.0f} KB)")
        return

    # Show backups with index
    print(f"Found {len(backups)} backup(s):\n")
    for i, b in enumerate(backups, 1):
        size_kb = os.path.getsize(b) / 1024
        name = os.path.basename(b)
        print(f"  {i}. {name}  ({size_kb:.0f} KB)")

    print()

    # Accept index from args or prompt
    choice = None
    if args:
        choice = args[0]
    else:
        try:
            choice = input("Enter backup number to restore (or 'q' to cancel): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return

    if not choice or choice.lower() == "q":
        print("Cancelled.")
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(backups):
            print(f"Invalid selection. Choose 1-{len(backups)}.")
            return
    except ValueError:
        print(f"Invalid input: {choice}")
        return

    selected = backups[idx]
    print(f"\nRestoring from: {os.path.basename(selected)}")
    shutil.copy2(selected, DB_PATH)
    print(f"Done. Database restored.")


def cmd_reextract(args):
    """Re-extract from source sessions to identify low-quality engrams."""
    category = None
    limit = None
    prune = "--prune" in args
    dry_run = "--dry-run" in args

    i = 0
    while i < len(args):
        if args[i] == "--category" and i + 1 < len(args):
            category = args[i + 1]
            i += 2
        elif args[i] == "--limit" and i + 1 < len(args):
            try:
                limit = int(args[i + 1])
            except ValueError:
                pass
            i += 2
        elif args[i] in ("--prune", "--dry-run"):
            i += 1
        else:
            i += 1

    from engrammar.pipeline.extractor import reextract_engrams

    summary = reextract_engrams(
        category=category, limit=limit, prune=prune, dry_run=dry_run
    )

    if not dry_run:
        print(f"\nSummary: {summary['confirmed']} confirmed, "
              f"{summary['unconfirmed']} unconfirmed, "
              f"{summary['skipped']} skipped")


def cmd_register(args):
    """Register engrammar with a tool. Usage: engrammar register claude"""
    if not args:
        print("Usage: engrammar register <tool>")
        print("  claude    Register hooks and MCP server with Claude Code")
        return

    target = args[0]
    if target == "claude":
        from engrammar.infra.register_hooks import register_hooks
        register_hooks()
    else:
        print(f"Unknown target: {target}")
        print("Available: claude")


def cmd_dedup(args):
    """Deduplicate engrams using LLM-assisted similarity analysis."""
    from engrammar.core.db import init_db
    init_db()
    scan_only = "--scan" in args
    json_output = "--json" in args
    single_pass = "--single-pass" in args
    limit = None
    batch_size = None
    max_candidates = 8
    min_sim = 0.50
    engram_id = None
    max_passes = 10

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--batch-size" and i + 1 < len(args):
            batch_size = int(args[i + 1])
            i += 2
        elif args[i] == "--max-candidates" and i + 1 < len(args):
            max_candidates = int(args[i + 1])
            i += 2
        elif args[i] == "--min-sim" and i + 1 < len(args):
            min_sim = float(args[i + 1])
            i += 2
        elif args[i] == "--id" and i + 1 < len(args):
            engram_id = int(args[i + 1])
            i += 2
        elif args[i] == "--max-passes" and i + 1 < len(args):
            max_passes = int(args[i + 1])
            i += 2
        elif args[i] in ("--scan", "--json", "--single-pass"):
            i += 1
        else:
            i += 1

    from engrammar.pipeline.dedup import run_dedup

    summary = run_dedup(
        scan_only=scan_only,
        limit=limit,
        batch_size=batch_size,
        max_candidates=max_candidates,
        min_sim=min_sim,
        max_passes=max_passes,
        single_pass=single_pass,
        engram_id=engram_id,
        json_output=json_output,
    )

    if json_output:
        print(json.dumps(summary, indent=2))
    elif not scan_only:
        print(f"\n=== Dedup Summary ===")
        print(f"Passes:   {summary['passes']}")
        print(f"Processed: {summary['processed']}")
        print(f"Merged:    {summary['merged']}")
        print(f"Verified:  {summary['verified']}")
        print(f"Skipped:   {summary['skipped']}")
        print(f"Failed:    {summary['failed']}")


def _llm_generate_tags_batch(engrams_batch):
    """Call LLM to generate content tags for a batch of engrams.

    Returns:
        dict mapping engram_id -> list of tag strings
    """
    import subprocess
    from engrammar.core.config import load_config

    items = [{"id": e["id"], "text": e["text"], "category": e.get("category", "general")} for e in engrams_batch]
    prompt = f"""For each engram below, output 1-3 short lowercase topic tags describing what it's about.
Tags should be specific topics (e.g. "forms", "git", "testing", "react", "docker"), not generic terms like "development" or "best-practices".

Output strict JSON: {{"tags": {{"<id>": ["tag1", "tag2"], ...}}}}

Engrams:
{json.dumps(items, indent=2)}"""

    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env["ENGRAMMAR_INTERNAL_RUN"] = "1"
        model = load_config().get("models", {}).get("extraction", "haiku")
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model,
             "--output-format", "text", "--no-session-persistence"],
            capture_output=True, text=True, timeout=120, env=env, stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            return {}
        text = result.stdout.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text.rsplit("\n", 1)[0]
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            tags_map = parsed.get("tags", parsed)
            return {int(k): [t.strip().lower() for t in v] for k, v in tags_map.items()}
    except Exception as e:
        print(f"  LLM batch failed: {e}", file=sys.stderr)
    return {}


def cmd_backfill_tags(args):
    """Generate content tags for engrams that don't have any.

    Two strategies:
    1. Vector retrieval from tag vocab (fast, promotes convergence)
    2. LLM generation for engrams where retrieval finds nothing (cold start)

    Options:
        --limit N       Process at most N engrams (default: all)
        --dry-run       Show what would be tagged without writing
        --threshold F   Min cosine similarity for tag retrieval (default 0.4)
        --llm           Use LLM for engrams where vector retrieval finds nothing
    """
    from engrammar.core.db import (
        get_all_active_engrams, get_content_tags, add_content_tags,
        get_all_content_tags_vocab,
    )
    from engrammar.core.embeddings import build_tag_vocab_index
    from engrammar.search.prompt_tags import detect_prompt_tags

    limit = None
    dry_run = "--dry-run" in args
    use_llm = "--llm" in args
    threshold = 0.4
    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] == "--threshold" and i + 1 < len(args):
            threshold = float(args[i + 1])
            i += 2
        else:
            i += 1

    # Build vocab index from whatever tags exist
    print("Building tag vocab index...")
    nv = build_tag_vocab_index(min_frequency=1)
    print(f"  {nv} tags in vocabulary")

    engrams = get_all_active_engrams()
    to_process = [e for e in engrams if not get_content_tags(e["id"])]

    if limit:
        to_process = to_process[:limit]

    if not to_process:
        print("All engrams already have content tags.")
        return

    print(f"Processing {len(to_process)} engrams without content tags...\n")

    tagged_vector = 0
    tagged_llm = 0
    skipped = 0
    llm_queue = []

    for idx, e in enumerate(to_process, 1):
        text = e["text"]
        # Try vector retrieval from vocab
        retrieved = detect_prompt_tags(text, top_k=5, threshold=threshold)
        tags = [tag for tag, _score in retrieved]

        if tags:
            if dry_run:
                print(f"  [{idx}/{len(to_process)}] #{e['id']} (vector): {tags}")
            else:
                add_content_tags(e["id"], tags, source="backfill")
                tagged_vector += 1
                if idx <= 10 or idx % 50 == 0:
                    print(f"  [{idx}/{len(to_process)}] #{e['id']} (vector): {tags}")
        else:
            llm_queue.append(e)
            if not use_llm and dry_run:
                print(f"  [{idx}/{len(to_process)}] #{e['id']}: (no vector match, would need --llm)")

        # Rebuild vocab periodically
        if not dry_run and tagged_vector > 0 and tagged_vector % 50 == 0:
            nv = build_tag_vocab_index(min_frequency=1)
            print(f"  ... rebuilt vocab ({nv} tags), retrying {len(llm_queue)} unmatched")
            # Retry LLM queue with updated vocab
            still_unmatched = []
            for qe in llm_queue:
                retrieved = detect_prompt_tags(qe["text"], top_k=5, threshold=threshold)
                tags = [tag for tag, _score in retrieved]
                if tags:
                    add_content_tags(qe["id"], tags, source="backfill")
                    tagged_vector += 1
                else:
                    still_unmatched.append(qe)
            llm_queue = still_unmatched

    # LLM fallback for remaining unmatched
    if use_llm and llm_queue and not dry_run:
        print(f"\nRunning LLM on {len(llm_queue)} unmatched engrams...")
        BATCH_SIZE = 20
        for batch_start in range(0, len(llm_queue), BATCH_SIZE):
            batch = llm_queue[batch_start:batch_start + BATCH_SIZE]
            print(f"  LLM batch {batch_start // BATCH_SIZE + 1} ({len(batch)} engrams)...")
            result = _llm_generate_tags_batch(batch)
            for e in batch:
                tags = result.get(e["id"], [])
                if tags:
                    add_content_tags(e["id"], tags, source="backfill-llm")
                    tagged_llm += 1
                else:
                    skipped += 1
            # Rebuild vocab after each LLM batch
            nv = build_tag_vocab_index(min_frequency=1)
    elif llm_queue:
        skipped = len(llm_queue)

    print(f"\nDone. Vector-tagged: {tagged_vector}, LLM-tagged: {tagged_llm}, Skipped: {skipped}"
          + (" (dry run)" if dry_run else ""))

    # Final rebuild
    if not dry_run and (tagged_vector + tagged_llm) > 0:
        print("Rebuilding tag vocab index...")
        nv = build_tag_vocab_index(min_frequency=1)
        print(f"  {nv} unique tags in vocabulary")

        vocab = get_all_content_tags_vocab(min_frequency=1)
        top = vocab[:15]
        print(f"  Top tags: {', '.join(f'{t}({c})' for t, c in top)}")


def cmd_curate(args):
    """Run curation pipeline — quality review + dedup on uncurated engrams.

    Options:
        --limit N       Process at most N uncurated engrams
        --dry-run       Show batches without calling LLM
        --force         Run even if below threshold
    """
    from engrammar.core.db import init_db
    init_db()

    dry_run = "--dry-run" in args
    force = "--force" in args
    limit = None

    i = 0
    while i < len(args):
        if args[i] == "--limit" and i + 1 < len(args):
            limit = int(args[i + 1])
            i += 2
        elif args[i] in ("--dry-run", "--force"):
            i += 1
        else:
            i += 1

    from engrammar.pipeline.curator import should_curate, run_curation

    ready, count = should_curate()
    if not ready and not force:
        print(f"Only {count} uncurated engrams (below threshold). Use --force to run anyway.")
        return

    summary = run_curation(limit=limit, dry_run=dry_run)
    if not dry_run:
        print(f"\nSummary: {summary['kept']} kept, {summary['rejected']} rejected, "
              f"{summary['merged']} merged")


def main():
    if len(sys.argv) < 2:
        print("Engrammar — Semantic knowledge system for Claude Code\n")
        print("Commands:")
        print("  setup        Initialize DB, import engrams, build index")
        print("  status       Show DB stats, index health, hook config")
        print("  search       Search engrams: search \"query\"")
        print("  list         List all engrams (--offset N --limit N --category cat --verbose --sort id|score|matched)")
        print("  log          Show hook event log (--tail N --session ID --hook HOOK)")
        print("  add          Add engram: add \"text\" --category cat")
        print("  update       Update engram: update ID --text \"new\" --category cat")
        print("  deprecate    Soft-delete engram: deprecate ID")
        print("  pin          Pin engram for session start: pin ID")
        print("  unpin        Unpin engram: unpin ID")
        print("  categorize   Add/remove categories: categorize ID add|remove CATEGORY")
        print("  reset-stats  Reset all match counts and pins: reset-stats --confirm")
        print("  backfill     Create audit records from past sessions: backfill [--dry-run] [--limit N] [--evaluate]")
        print("  import       Import from file: import FILE")
        print("  export       Export all engrams to markdown")
        print("  extract      Extract engrams from transcripts: extract [--limit N] [--session UUID] [--dry-run]")
        print("  process-turn Process a single turn: process-turn --session UUID --transcript PATH")
        print("  rebuild      Rebuild embedding index")
        print("  evaluate     Run pending relevance evaluations: evaluate [--limit N]")
        print("  detect-tags  Show detected environment tags for current directory")
        print("  isolate      Show or toggle current repo isolation: isolate [on|off]")
        print("  disable      Show or toggle disable state: disable [global|repo] [on|off]")
        print("  backfill-prereqs  Retroactively set prerequisites on existing engrams [--dry-run]")
        print("  restore      List DB backups and restore a selected one: restore [--list] [N]")
        print("  reextract    Re-check engrams against current prompt: reextract [--category CAT] [--limit N] [--prune] [--dry-run]")
        print("  register     Register with a tool: register claude")
        print("  dedup        Deduplicate engrams: dedup [--scan] [--limit N] [--json] [--id N] [--single-pass]")
        print("  backfill-tags  Generate content tags for untagged engrams: backfill-tags [--limit N] [--dry-run] [--rebuild]")
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "setup": cmd_setup,
        "status": cmd_status,
        "search": cmd_search,
        "list": cmd_list,
        "log": cmd_log,
        "add": cmd_add,
        "update": cmd_update,
        "deprecate": cmd_deprecate,
        "pin": cmd_pin,
        "unpin": cmd_unpin,
        "categorize": cmd_categorize,
        "reset-stats": cmd_reset_stats,
        "backfill": cmd_backfill,
        "import": cmd_import,
        "export": cmd_export,
        "extract": cmd_extract,
        "process-turn": cmd_process_turn,
        "rebuild": cmd_rebuild,
        "evaluate": cmd_evaluate,
        "detect-tags": cmd_detect_tags,
        "isolate": cmd_isolate,
        "disable": cmd_disable,
        "backfill-prereqs": cmd_backfill_prereqs,
        "backfill-repo-tags": cmd_backfill_repo_tags,
        "restore": cmd_restore_db,
        "reextract": cmd_reextract,
        "register": cmd_register,
        "dedup": cmd_dedup,
        "backfill-tags": cmd_backfill_tags,
        "curate": cmd_curate,
    }

    if command in commands:
        commands[command](args)
    else:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
