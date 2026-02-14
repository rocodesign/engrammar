#!/usr/bin/env python3
"""Engrammar CLI — manage semantic lessons for Claude Code sessions."""

import json
import os
import sys

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)


def cmd_setup(args):
    """Initialize database + import existing lessons + build index."""
    from engrammar.config import DB_PATH, ENGRAMMAR_HOME
    from engrammar.db import init_db, import_from_state_file, get_lesson_count

    print("Initializing database...")
    init_db()

    # Import existing lessons if DB is empty
    count = get_lesson_count()
    if count == 0:
        state_file = os.path.expanduser("~/.shared-cli-agents/.lessons-state.json")
        if os.path.exists(state_file):
            imported = import_from_state_file(state_file)
            print(f"Imported {imported} lessons from {state_file}")
        else:
            print("No existing lessons file found, starting fresh.")
    else:
        print(f"Database already has {count} lessons, skipping import.")

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
        print("Usage: engrammar search \"query\" [--category CATEGORY]")
        return

    query = args[0]
    category = None
    if "--category" in args:
        idx = args.index("--category")
        if idx + 1 < len(args):
            category = args[idx + 1]

    from engrammar.search import search

    results = search(query, category_filter=category, top_k=5)

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
        print("Usage: engrammar add \"lesson text\" --category dev/frontend/styling")
        return

    text = args[0]
    category = "general"
    if "--category" in args:
        idx = args.index("--category")
        if idx + 1 < len(args):
            category = args[idx + 1]

    from engrammar.db import add_lesson, get_all_active_lessons
    from engrammar.embeddings import build_index

    lesson_id = add_lesson(text=text, category=category, source="manual")
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
    """Extract lessons from Claude Code session facets."""
    dry_run = "--dry-run" in args

    from engrammar.extractor import extract_from_sessions

    summary = extract_from_sessions(dry_run=dry_run)

    if not dry_run:
        print(f"\nSummary: {summary['new_sessions']} new sessions, "
              f"{summary['with_friction']} with friction, "
              f"{summary['extracted']} added, {summary['merged']} merged")


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
    """List all lessons with optional pagination."""
    from engrammar.db import get_all_active_lessons

    offset = 0
    limit = 20
    category = None

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
        else:
            i += 1

    lessons = get_all_active_lessons()

    # Filter by category if specified
    if category:
        from engrammar.db import get_connection
        conn = get_connection()
        rows = conn.execute(
            "SELECT lesson_id FROM lesson_categories WHERE category_path LIKE ?",
            (category + "%",)
        ).fetchall()
        conn.close()
        category_ids = {r["lesson_id"] for r in rows}
        lessons = [l for l in lessons if l["id"] in category_ids]

    total = len(lessons)
    page = lessons[offset:offset + limit]

    print(f"=== Lessons ({offset + 1}-{offset + len(page)} of {total}) ===\n")

    for l in page:
        print(f"ID {l['id']}: [{l.get('category', 'general')}] {l['text'][:80]}...")
        if l.get("pinned"):
            print(f"  📌 PINNED")
        if l.get("prerequisites"):
            prereqs = json.loads(l["prerequisites"]) if isinstance(l["prerequisites"], str) else l["prerequisites"]
            print(f"  Prerequisites: {prereqs}")
        print(f"  Matched: {l.get('times_matched', 0)}x | Occurrences: {l.get('occurrence_count', 1)}")
        print()


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
    """Backfill match statistics from past sessions."""
    import subprocess

    backfill_script = os.path.join(ENGRAMMAR_HOME, "backfill_stats.py")
    venv_python = os.path.join(ENGRAMMAR_HOME, "venv", "bin", "python")

    # Forward all args to backfill script
    result = subprocess.run([venv_python, backfill_script] + args)
    sys.exit(result.returncode)


def main():
    if len(sys.argv) < 2:
        print("Engrammar — Semantic knowledge system for Claude Code\n")
        print("Commands:")
        print("  setup        Initialize DB, import lessons, build index")
        print("  status       Show DB stats, index health, hook config")
        print("  search       Search lessons: search \"query\"")
        print("  list         List all lessons (--offset N --limit N --category cat)")
        print("  add          Add lesson: add \"text\" --category cat")
        print("  update       Update lesson: update ID --text \"new\" --category cat")
        print("  deprecate    Soft-delete lesson: deprecate ID")
        print("  pin          Pin lesson for session start: pin ID")
        print("  unpin        Unpin lesson: unpin ID")
        print("  categorize   Add/remove categories: categorize ID add|remove CATEGORY")
        print("  reset-stats  Reset all match counts and pins: reset-stats --confirm")
        print("  backfill     Backfill stats from past sessions: backfill [--dry-run] [--limit N]")
        print("  import       Import from file: import FILE")
        print("  export       Export all lessons to markdown")
        print("  extract      Extract lessons from session facets")
        print("  rebuild      Rebuild embedding index")
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "setup": cmd_setup,
        "status": cmd_status,
        "search": cmd_search,
        "list": cmd_list,
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
    }

    if command in commands:
        commands[command](args)
    else:
        print(f"Unknown command: {command}")
        print(f"Available: {', '.join(commands.keys())}")


if __name__ == "__main__":
    main()
