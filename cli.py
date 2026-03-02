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
    from engrammar.config import DB_PATH, ENGRAMMAR_HOME
    from engrammar.db import init_db, get_engram_count

    print("Initializing database...")
    init_db()

    count = get_engram_count()
    if count == 0:
        print("Empty database. Run 'engrammar-cli extract' to populate from transcripts.")
    else:
        print(f"Database has {count} engrams.")

    # Build embedding index
    print("Building embedding index...")
    from engrammar.db import get_all_active_engrams
    from engrammar.embeddings import build_index, build_tag_index

    engrams = get_all_active_engrams()
    if engrams:
        n = build_index(engrams)
        print(f"Indexed {n} engrams.")
        nt = build_tag_index(engrams)
        print(f"Cached {nt} tag embeddings.")
    else:
        print("No engrams to index.")

    print("Setup complete.")


def cmd_status(args):
    """Show database stats, index health, hook config."""
    from engrammar.config import DB_PATH, INDEX_PATH, IDS_PATH, TAG_INDEX_PATH, CONFIG_PATH, load_config
    from engrammar.db import get_engram_count, get_category_stats

    config = load_config()

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

    # Tag index
    if os.path.exists(TAG_INDEX_PATH):
        tag_emb = np.load(TAG_INDEX_PATH, mmap_mode="r")
        if tag_emb.size > 0:
            print(f"Tag index:  {tag_emb.shape[0]} cached tag embeddings")
        else:
            print(f"Tag index:  empty (no engrams with tags)")
    else:
        print(f"Tag index:  NOT BUILT (run 'rebuild' to create)")

    # Config
    print()
    print(f"Config:     {CONFIG_PATH}")
    print(f"Prompt hook:  {'enabled' if config['hooks']['prompt_enabled'] else 'disabled'}")
    print(f"Tool hook:    {'enabled' if config['hooks']['tool_use_enabled'] else 'disabled'}")
    print(f"Skip tools:   {', '.join(config['hooks']['skip_tools'])}")


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

    from engrammar.search import search

    results = search(query, category_filter=category, tag_filter=tags, top_k=5)

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

    from engrammar.db import add_engram, get_all_active_engrams
    from engrammar.embeddings import build_index, build_tag_index

    prereqs = {"tags": sorted(tags)} if tags else None
    engram_id = add_engram(text=text, category=category, source="manual", prerequisites=prereqs)

    if tags:
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

    from engrammar.db import import_from_state_file, add_engram, get_all_active_engrams
    from engrammar.embeddings import build_index, build_tag_index

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
    from engrammar.db import get_all_active_engrams

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
    """Extract engrams from conversation transcripts (or facets with --facets)."""
    dry_run = "--dry-run" in args
    use_facets = "--facets" in args

    # Single-session extraction: extract --session <uuid>
    session_id = None
    if "--session" in args:
        idx = args.index("--session")
        if idx + 1 < len(args):
            session_id = args[idx + 1]

    if session_id:
        from engrammar.extractor import extract_from_single_session

        summary = extract_from_single_session(session_id)
        if not dry_run:
            print(f"\nSummary: {summary['extracted']} added, {summary['merged']} merged")
        return

    if use_facets:
        from engrammar.extractor import extract_from_sessions

        summary = extract_from_sessions(dry_run=dry_run)

        if not dry_run:
            print(f"\nSummary: {summary['new_sessions']} new sessions, "
                  f"{summary['with_friction']} with friction, "
                  f"{summary['extracted']} added, {summary['merged']} merged")
    else:
        from engrammar.extractor import extract_from_transcripts

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
    from engrammar.db import get_all_active_engrams
    from engrammar.embeddings import build_index, build_tag_index

    print("Loading engrams...")
    engrams = get_all_active_engrams()

    if not engrams:
        print("No engrams to index.")
        return

    print(f"Building index for {len(engrams)} engrams...")
    n = build_index(engrams)
    nt = build_tag_index(engrams)
    print(f"Done. Indexed {n} engrams, cached {nt} tag embeddings.")


def cmd_list(args):
    """List all engrams with optional pagination. Use --verbose for full details."""
    from engrammar.db import get_all_active_engrams

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
            from engrammar.db import get_connection
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
    from engrammar.db import get_connection

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

    from engrammar.db import get_connection, get_all_active_engrams, remove_engram_category, add_engram_category
    from engrammar.embeddings import build_index, build_tag_index

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

        updates.append("category = ?")
        params.append(category)

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

    from engrammar.db import deprecate_engram

    deprecate_engram(engram_id)
    print(f"Deprecated engram {engram_id}")


def cmd_pin(args):
    """Pin a engram (always shown at session start)."""
    if not args:
        print("Usage: engrammar pin LESSON_ID")
        return

    engram_id = int(args[0])

    from engrammar.db import get_connection

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

    from engrammar.db import get_connection

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

    from engrammar.db import add_engram_category, remove_engram_category

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

    from engrammar.db import get_connection

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

    from engrammar.evaluator import run_evaluation_for_session, run_pending_evaluations

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

    from engrammar.db import get_all_active_engrams, get_connection, get_env_tags_for_sessions
    from engrammar.extractor import _infer_prerequisites

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
        from engrammar.embeddings import build_tag_index
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

    from engrammar.extractor import extract_from_turn

    summary = extract_from_turn(session_id, transcript_path)
    print(f"Turn extraction: {summary.get('extracted', 0)} added, {summary.get('merged', 0)} merged")


def cmd_log(args):
    """Show hook event log — what was injected, when, and by which hook."""
    from engrammar.db import get_hook_events, get_connection

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
    from engrammar.environment import detect_environment

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


def cmd_restore_db(args):
    """List DB backups and restore a selected one."""
    import glob
    import shutil

    from engrammar.config import DB_PATH, ENGRAMMAR_HOME

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


def cmd_dedup(args):
    """Deduplicate engrams using LLM-assisted similarity analysis."""
    from engrammar.db import init_db
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

    from engrammar.dedup import run_dedup

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
        print("  extract      Extract engrams from transcripts: extract [--limit N] [--session UUID] [--dry-run] [--facets]")
        print("  process-turn Process a single turn: process-turn --session UUID --transcript PATH")
        print("  rebuild      Rebuild embedding index")
        print("  evaluate     Run pending relevance evaluations: evaluate [--limit N]")
        print("  detect-tags  Show detected environment tags for current directory")
        print("  backfill-prereqs  Retroactively set prerequisites on existing engrams [--dry-run]")
        print("  restore      List DB backups and restore a selected one: restore [--list] [N]")
        print("  dedup        Deduplicate engrams: dedup [--scan] [--limit N] [--json] [--id N] [--single-pass]")
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
        "backfill-prereqs": cmd_backfill_prereqs,
        "restore": cmd_restore_db,
        "dedup": cmd_dedup,
    }

    if command in commands:
        commands[command](args)
    else:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
