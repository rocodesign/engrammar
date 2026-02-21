#!/usr/bin/env python3
"""Engrammar CLI — manage semantic lessons for Claude Code sessions."""

import json
import os
import sys

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def cmd_setup(args):
    """Initialize database + build index."""
    from engrammar.config import DB_PATH, ENGRAMMAR_HOME
    from engrammar.db import init_db, get_lesson_count

    print("Initializing database...")
    init_db()

    count = get_lesson_count()
    if count == 0:
        print("Empty database. Run 'engrammar-cli extract' to populate from transcripts.")
    else:
        print(f"Database has {count} lessons.")

    # Build embedding index
    print("Building embedding index...")
    from engrammar.db import get_all_active_lessons
    from engrammar.embeddings import build_index

    lessons = get_all_active_lessons()
    if lessons:
        n = build_index(lessons)
        print(f"Indexed {n} lessons.")
    else:
        print("No lessons to index.")

    print("Setup complete.")


def cmd_status(args):
    """Show database stats, index health, hook config."""
    from engrammar.config import DB_PATH, INDEX_PATH, IDS_PATH, CONFIG_PATH, load_config
    from engrammar.db import get_lesson_count, get_category_stats

    config = load_config()

    print("=== Engrammar Status ===\n")

    # Database
    if os.path.exists(DB_PATH):
        count = get_lesson_count()
        print(f"Database:   {DB_PATH}")
        print(f"Lessons:    {count} active")

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

    # Config
    print()
    print(f"Config:     {CONFIG_PATH}")
    print(f"Prompt hook:  {'enabled' if config['hooks']['prompt_enabled'] else 'disabled'}")
    print(f"Tool hook:    {'enabled' if config['hooks']['tool_use_enabled'] else 'disabled'}")
    print(f"Skip tools:   {', '.join(config['hooks']['skip_tools'])}")


def cmd_search(args):
    """Search lessons."""
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
        print("No matching lessons found.")
        return

    print(f"Found {len(results)} results:\n")
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r.get('category', 'general')}] (score: {r.get('score', 0):.4f})")
        print(f"     {r['text']}")
        print(f"     matched: {r.get('times_matched', 0)}x | occurrences: {r.get('occurrence_count', 1)}")
        print()


def cmd_add(args):
    """Add a new lesson."""
    if not args:
        print("Usage: engrammar add \"lesson text\" --category dev/frontend/styling [--tags tag1,tag2,...]")
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

    from engrammar.db import add_lesson, get_all_active_lessons
    from engrammar.embeddings import build_index

    prereqs = {"tags": sorted(tags)} if tags else None
    lesson_id = add_lesson(text=text, category=category, source="manual", prerequisites=prereqs)

    if tags:
        print(f"Added lesson #{lesson_id} in category '{category}' with tags: {', '.join(tags)}")
    else:
        print(f"Added lesson #{lesson_id} in category '{category}'")

    # Rebuild index
    print("Rebuilding index...")
    lessons = get_all_active_lessons()
    build_index(lessons)
    print("Done.")


def cmd_import(args):
    """Import lessons from a JSON or markdown file."""
    if not args:
        print("Usage: engrammar import FILE")
        return

    filepath = args[0]
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return

    from engrammar.db import import_from_state_file, add_lesson, get_all_active_lessons
    from engrammar.embeddings import build_index

    if filepath.endswith(".json"):
        imported = import_from_state_file(filepath)
        print(f"Imported {imported} lessons from {filepath}")
    else:
        # Treat as markdown — each line starting with "- " is a lesson
        imported = 0
        with open(filepath, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith("- "):
                    text = line[2:].strip()
                    if text:
                        add_lesson(text=text, category="general", source="manual")
                        imported += 1
        print(f"Imported {imported} lessons from {filepath}")

    # Rebuild index
    print("Rebuilding index...")
    lessons = get_all_active_lessons()
    build_index(lessons)
    print("Done.")


def cmd_export(args):
    """Export all lessons to markdown."""
    from engrammar.db import get_all_active_lessons

    lessons = get_all_active_lessons()
    if not lessons:
        print("No lessons to export.")
        return

    # Group by category
    by_category = {}
    for l in lessons:
        cat = l.get("category", "general")
        by_category.setdefault(cat, []).append(l)

    for cat in sorted(by_category.keys()):
        print(f"\n## {cat}\n")
        for l in by_category[cat]:
            print(f"- {l['text']}")


def cmd_extract(args):
    """Extract lessons from conversation transcripts (or facets with --facets)."""
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
    from engrammar.db import get_all_active_lessons
    from engrammar.embeddings import build_index

    print("Loading lessons...")
    lessons = get_all_active_lessons()

    if not lessons:
        print("No lessons to index.")
        return

    print(f"Building index for {len(lessons)} lessons...")
    n = build_index(lessons)
    print(f"Done. Indexed {n} lessons.")


def cmd_list(args):
    """List all lessons with optional pagination. Use --verbose for full details."""
    from engrammar.db import get_all_active_lessons

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

    lessons = get_all_active_lessons()

    # Filter by category if specified
    if category:
        if verbose:
            lessons = [l for l in lessons if l.get("category", "").startswith(category)]
        else:
            from engrammar.db import get_connection
            conn = get_connection()
            rows = conn.execute(
                "SELECT lesson_id FROM lesson_categories WHERE category_path LIKE ?",
                (category + "%",)
            ).fetchall()
            conn.close()
            category_ids = {r["lesson_id"] for r in rows}
            lessons = [l for l in lessons if l["id"] in category_ids]

    if not lessons:
        print("No lessons found.")
        return

    if verbose:
        _list_verbose(lessons, sort_by, category)
    else:
        total = len(lessons)
        page = lessons[offset:offset + limit]

        print(f"=== Lessons ({offset + 1}-{offset + len(page)} of {total}) ===\n")

        for l in page:
            print(f"ID {l['id']}: [{l.get('category', 'general')}] {l['text'][:80]}...")
            if l.get("pinned"):
                print(f"  PINNED")
            if l.get("prerequisites"):
                prereqs = json.loads(l["prerequisites"]) if isinstance(l["prerequisites"], str) else l["prerequisites"]
                print(f"  Prerequisites: {prereqs}")
            print(f"  Matched: {l.get('times_matched', 0)}x | Occurrences: {l.get('occurrence_count', 1)}")
            print()


def _list_verbose(lessons, sort_by="id", category=None):
    """Show full lesson details with tags/scores (git-log style)."""
    from engrammar.db import get_connection

    conn = get_connection()

    # Preload all tag relevance scores
    tag_scores = {}
    rows = conn.execute(
        "SELECT lesson_id, tag, score, positive_evals, negative_evals "
        "FROM lesson_tag_relevance ORDER BY lesson_id, score DESC"
    ).fetchall()
    for r in rows:
        tag_scores.setdefault(r["lesson_id"], []).append(dict(r))

    # Preload repo stats
    repo_stats = {}
    rows = conn.execute(
        "SELECT lesson_id, repo, times_matched FROM lesson_repo_stats ORDER BY lesson_id"
    ).fetchall()
    for r in rows:
        repo_stats.setdefault(r["lesson_id"], []).append(dict(r))

    # Sort
    if sort_by == "score":
        def best_score(l):
            scores = tag_scores.get(l["id"], [])
            return max((s["score"] for s in scores), default=0)
        lessons.sort(key=best_score, reverse=True)
    elif sort_by == "matched":
        lessons.sort(key=lambda l: l.get("times_matched", 0), reverse=True)

    # Print each lesson
    for l in lessons:
        lid = l["id"]
        pinned = " PINNED" if l.get("pinned") else ""
        print(f"\033[33mlesson {lid}\033[0m{pinned}")
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
    print(f"--- {len(lessons)} lessons ---")


def cmd_update(args):
    """Update a lesson's text, category, or prerequisites."""
    if len(args) < 2:
        print("Usage: engrammar update LESSON_ID [--text \"new text\"] [--category cat] [--prereqs '{\"repos\": [\"foo\"]}']")
        return

    lesson_id = int(args[0])
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

    from engrammar.db import get_connection, get_all_active_lessons, remove_lesson_category, add_lesson_category
    from engrammar.embeddings import build_index

    conn = get_connection()

    # Check if lesson exists
    row = conn.execute("SELECT * FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    if not row:
        print(f"Lesson {lesson_id} not found.")
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
            remove_lesson_category(lesson_id, old_category)
        add_lesson_category(lesson_id, category)

        updates.append("category = ?")
        params.append(category)

    if prereqs is not None:
        prereqs_json = json.dumps(prereqs) if isinstance(prereqs, dict) else prereqs
        updates.append("prerequisites = ?")
        params.append(prereqs_json)

    if updates:
        updates.append("updated_at = datetime('now')")
        params.append(lesson_id)
        conn.execute(
            f"UPDATE lessons SET {', '.join(updates)} WHERE id = ?",
            params
        )
        conn.commit()

    conn.close()

    print(f"Updated lesson {lesson_id}")

    # Rebuild index if text changed
    if text is not None:
        print("Rebuilding index...")
        lessons = get_all_active_lessons()
        build_index(lessons)
        print("Done.")


def cmd_deprecate(args):
    """Deprecate (soft-delete) a lesson."""
    if not args:
        print("Usage: engrammar deprecate LESSON_ID")
        return

    lesson_id = int(args[0])

    from engrammar.db import deprecate_lesson

    deprecate_lesson(lesson_id)
    print(f"Deprecated lesson {lesson_id}")


def cmd_pin(args):
    """Pin a lesson (always shown at session start)."""
    if not args:
        print("Usage: engrammar pin LESSON_ID")
        return

    lesson_id = int(args[0])

    from engrammar.db import get_connection

    conn = get_connection()
    conn.execute("UPDATE lessons SET pinned = 1 WHERE id = ?", (lesson_id,))
    conn.commit()
    conn.close()

    print(f"Pinned lesson {lesson_id}")


def cmd_unpin(args):
    """Unpin a lesson."""
    if not args:
        print("Usage: engrammar unpin LESSON_ID")
        return

    lesson_id = int(args[0])

    from engrammar.db import get_connection

    conn = get_connection()
    conn.execute("UPDATE lessons SET pinned = 0 WHERE id = ?", (lesson_id,))
    conn.commit()
    conn.close()

    print(f"Unpinned lesson {lesson_id}")


def cmd_categorize(args):
    """Add or remove categories from a lesson."""
    if len(args) < 3 or args[1] not in ("add", "remove"):
        print("Usage: engrammar categorize LESSON_ID add|remove CATEGORY")
        return

    lesson_id = int(args[0])
    action = args[1]
    category = args[2]

    from engrammar.db import add_lesson_category, remove_lesson_category

    if action == "add":
        add_lesson_category(lesson_id, category)
        print(f"Added category '{category}' to lesson {lesson_id}")
    else:
        remove_lesson_category(lesson_id, category)
        print(f"Removed category '{category}' from lesson {lesson_id}")


def cmd_reset_stats(args):
    """Reset all match statistics and pins to start fresh."""
    confirm = "--confirm" in args

    if not confirm:
        print("This will reset all lessons:")
        print("  - Unpin all lessons (pinned = 0)")
        print("  - Reset match counts (times_matched = 0)")
        print("  - Clear per-repo match tracking")
        print("  - Preserve lesson text, categories, and manual prerequisites")
        print()
        print("Run with --confirm to proceed: engrammar reset-stats --confirm")
        return

    from engrammar.db import get_connection

    conn = get_connection()

    # Reset all lesson stats
    conn.execute("""
        UPDATE lessons
        SET pinned = 0,
            times_matched = 0,
            last_matched = NULL
    """)

    # Clear per-repo stats
    conn.execute("DELETE FROM lesson_repo_stats")

    conn.commit()

    # Get count for confirmation
    count = conn.execute("SELECT COUNT(*) FROM lessons WHERE deprecated = 0").fetchone()[0]
    conn.close()

    print(f"✅ Reset complete:")
    print(f"   - Unpinned all lessons")
    print(f"   - Reset match counts to 0 for {count} active lessons")
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
    """Retroactively set prerequisites on existing lessons using keyword inference + session audit tags."""
    dry_run = "--dry-run" in args

    from engrammar.db import get_all_active_lessons, get_connection, get_env_tags_for_sessions
    from engrammar.extractor import _infer_prerequisites

    lessons = get_all_active_lessons()
    if not lessons:
        print("No active lessons found.")
        return

    updated = 0
    skipped = 0
    for lesson in lessons:
        existing_prereqs = None
        if lesson.get("prerequisites"):
            try:
                existing_prereqs = json.loads(lesson["prerequisites"]) if isinstance(lesson["prerequisites"], str) else lesson["prerequisites"]
            except (json.JSONDecodeError, TypeError):
                existing_prereqs = None

        # Always look up session audit tags
        source_sessions = json.loads(lesson.get("source_sessions") or "[]")
        audit_tags = get_env_tags_for_sessions(source_sessions) if source_sessions else []

        # Only run keyword inference if no existing prerequisites
        keyword_prereqs = None
        if not existing_prereqs:
            keyword_prereqs = _infer_prerequisites(lesson["text"])

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
        old_json = lesson.get("prerequisites") or "{}"
        try:
            old_parsed = json.loads(old_json) if isinstance(old_json, str) else old_json
        except (json.JSONDecodeError, TypeError):
            old_parsed = {}
        if merged == old_parsed:
            skipped += 1
            continue

        if dry_run:
            print(f"  Would set lesson #{lesson['id']}: {json.dumps(merged)}")
            print(f"    Text: {lesson['text'][:80]}...")
            updated += 1
        else:
            from datetime import datetime
            conn = get_connection()
            now = datetime.utcnow().isoformat()
            conn.execute(
                "UPDATE lessons SET prerequisites = ?, updated_at = ? WHERE id = ?",
                (json.dumps(merged), now, lesson["id"]),
            )
            conn.commit()
            conn.close()
            print(f"  Set lesson #{lesson['id']}: {json.dumps(merged)}")
            updated += 1

    mode = "Would update" if dry_run else "Updated"
    print(f"\n{mode} {updated} lessons, skipped {skipped}.")


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
        print("Events will appear here as lessons are injected during sessions.")
        return

    # Apply filters
    if session_filter:
        events = [e for e in events if e.get("session_id", "").startswith(session_filter)]
    if hook_filter:
        events = [e for e in events if hook_filter.lower() in e.get("hook_event", "").lower()]

    if not events:
        print("No events match the filter.")
        return

    # Preload lesson texts for display
    lesson_ids_needed = set()
    for e in events:
        ids = json.loads(e["lesson_ids"])
        lesson_ids_needed.update(ids)

    lesson_texts = {}
    if lesson_ids_needed:
        conn = get_connection()
        placeholders = ",".join("?" * len(lesson_ids_needed))
        rows = conn.execute(
            f"SELECT id, text FROM lessons WHERE id IN ({placeholders})",
            list(lesson_ids_needed),
        ).fetchall()
        conn.close()
        lesson_texts = {r["id"]: r["text"] for r in rows}

    # Print events (most recent first, already sorted by get_hook_events)
    for e in events:
        ts = e["timestamp"][:19].replace("T", " ")
        hook = e["hook_event"]
        sid = e["session_id"][:8] if e.get("session_id") else "unknown"
        ids = json.loads(e["lesson_ids"])
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
        # Show lesson text snippets
        for lid in ids:
            text = lesson_texts.get(lid, "<deleted>")
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

    pattern = os.path.join(ENGRAMMAR_HOME, "lessons.db.backup-*")
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


def main():
    if len(sys.argv) < 2:
        print("Engrammar — Semantic knowledge system for Claude Code\n")
        print("Commands:")
        print("  setup        Initialize DB, import lessons, build index")
        print("  status       Show DB stats, index health, hook config")
        print("  search       Search lessons: search \"query\"")
        print("  list         List all lessons (--offset N --limit N --category cat --verbose --sort id|score|matched)")
        print("  log          Show hook event log (--tail N --session ID --hook HOOK)")
        print("  add          Add lesson: add \"text\" --category cat")
        print("  update       Update lesson: update ID --text \"new\" --category cat")
        print("  deprecate    Soft-delete lesson: deprecate ID")
        print("  pin          Pin lesson for session start: pin ID")
        print("  unpin        Unpin lesson: unpin ID")
        print("  categorize   Add/remove categories: categorize ID add|remove CATEGORY")
        print("  reset-stats  Reset all match counts and pins: reset-stats --confirm")
        print("  backfill     Create audit records from past sessions: backfill [--dry-run] [--limit N] [--evaluate]")
        print("  import       Import from file: import FILE")
        print("  export       Export all lessons to markdown")
        print("  extract      Extract lessons from transcripts: extract [--limit N] [--session UUID] [--dry-run] [--facets]")
        print("  rebuild      Rebuild embedding index")
        print("  evaluate     Run pending relevance evaluations: evaluate [--limit N]")
        print("  detect-tags  Show detected environment tags for current directory")
        print("  backfill-prereqs  Retroactively set prerequisites on existing lessons [--dry-run]")
        print("  restore      List DB backups and restore a selected one: restore [--list] [N]")
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
        "rebuild": cmd_rebuild,
        "evaluate": cmd_evaluate,
        "detect-tags": cmd_detect_tags,
        "backfill-prereqs": cmd_backfill_prereqs,
        "restore": cmd_restore_db,
    }

    if command in commands:
        commands[command](args)
    else:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
