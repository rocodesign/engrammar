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


def main():
    if len(sys.argv) < 2:
        print("Engrammar — Semantic knowledge system for Claude Code\n")
        print("Commands:")
        print("  setup      Initialize DB, import lessons, build index")
        print("  status     Show DB stats, index health, hook config")
        print("  search     Search lessons: search \"query\"")
        print("  add        Add lesson: add \"text\" --category cat")
        print("  import     Import from file: import FILE")
        print("  export     Export all lessons to markdown")
        print("  extract    Extract lessons from session facets")
        print("  rebuild    Rebuild embedding index")
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    commands = {
        "setup": cmd_setup,
        "status": cmd_status,
        "search": cmd_search,
        "add": cmd_add,
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
