"""SQLite database for lesson storage."""

import json
import os
import sqlite3
from datetime import datetime

from .config import DB_PATH


def get_connection(db_path=None):
    """Get a SQLite connection."""
    path = db_path or DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path=None):
    """Create tables if they don't exist."""
    conn = get_connection(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS lessons (
            id INTEGER PRIMARY KEY,
            text TEXT NOT NULL,
            category TEXT NOT NULL DEFAULT 'general',
            level1 TEXT,
            level2 TEXT,
            level3 TEXT,
            source TEXT DEFAULT 'manual',
            source_sessions TEXT DEFAULT '[]',
            occurrence_count INTEGER DEFAULT 1,
            times_matched INTEGER DEFAULT 0,
            last_matched TEXT,
            created_at TEXT,
            updated_at TEXT,
            deprecated INTEGER DEFAULT 0,
            prerequisites TEXT DEFAULT NULL,
            pinned INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS categories (
            path TEXT PRIMARY KEY,
            description TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_lessons_category ON lessons(category);
        CREATE INDEX IF NOT EXISTS idx_lessons_level1 ON lessons(level1);
        CREATE INDEX IF NOT EXISTS idx_lessons_deprecated ON lessons(deprecated);

        CREATE TABLE IF NOT EXISTS lesson_categories (
            lesson_id INTEGER NOT NULL,
            category_path TEXT NOT NULL,
            PRIMARY KEY (lesson_id, category_path),
            FOREIGN KEY (lesson_id) REFERENCES lessons(id)
        );

        CREATE TABLE IF NOT EXISTS lesson_repo_stats (
            lesson_id INTEGER NOT NULL,
            repo TEXT NOT NULL,
            times_matched INTEGER DEFAULT 0,
            last_matched TEXT,
            PRIMARY KEY (lesson_id, repo),
            FOREIGN KEY (lesson_id) REFERENCES lessons(id)
        );

        CREATE TABLE IF NOT EXISTS lesson_tag_stats (
            lesson_id INTEGER NOT NULL,
            tag_set TEXT NOT NULL,
            times_matched INTEGER DEFAULT 0,
            last_matched TEXT,
            PRIMARY KEY (lesson_id, tag_set),
            FOREIGN KEY (lesson_id) REFERENCES lessons(id)
        );

        CREATE TABLE IF NOT EXISTS processed_sessions (
            session_id TEXT PRIMARY KEY,
            processed_at TEXT,
            had_friction INTEGER DEFAULT 0,
            lessons_extracted INTEGER DEFAULT 0
        );
    """)

    # Migrations for existing DBs
    columns = [r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()]
    if "prerequisites" not in columns:
        conn.execute("ALTER TABLE lessons ADD COLUMN prerequisites TEXT DEFAULT NULL")
    if "pinned" not in columns:
        conn.execute("ALTER TABLE lessons ADD COLUMN pinned INTEGER DEFAULT 0")

    conn.commit()
    conn.close()


def _parse_category(category):
    """Parse 'development/frontend/styling' into level1, level2, level3."""
    parts = category.strip("/").split("/")
    return (
        parts[0] if len(parts) > 0 else None,
        parts[1] if len(parts) > 1 else None,
        parts[2] if len(parts) > 2 else None,
    )


def add_lesson(text, category="general", categories=None, source="manual", source_sessions=None, occurrence_count=1, db_path=None):
    """Insert a new lesson.

    Args:
        text: lesson content
        category: primary category (used for display/level parsing)
        categories: optional list of additional category paths
        source: "auto-extracted" | "manual" | "feedback"
        source_sessions: list of session IDs
        occurrence_count: how many sessions produced this
    """
    conn = get_connection(db_path)
    level1, level2, level3 = _parse_category(category)
    now = datetime.utcnow().isoformat()
    sessions_json = json.dumps(source_sessions or [])

    cursor = conn.execute(
        """INSERT INTO lessons (text, category, level1, level2, level3, source,
           source_sessions, occurrence_count, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (text, category, level1, level2, level3, source, sessions_json,
         occurrence_count, now, now),
    )
    lesson_id = cursor.lastrowid

    # Ensure primary category path exists and add to junction table
    _ensure_category(conn, category)
    conn.execute(
        "INSERT OR IGNORE INTO lesson_categories (lesson_id, category_path) VALUES (?, ?)",
        (lesson_id, category),
    )

    # Add additional categories
    if categories:
        for cat in categories:
            _ensure_category(conn, cat)
            conn.execute(
                "INSERT OR IGNORE INTO lesson_categories (lesson_id, category_path) VALUES (?, ?)",
                (lesson_id, cat),
            )

    conn.commit()
    conn.close()
    return lesson_id


def _ensure_category(conn, category):
    """Insert category path if not exists."""
    parts = category.strip("/").split("/")
    for i in range(len(parts)):
        path = "/".join(parts[: i + 1])
        conn.execute(
            "INSERT OR IGNORE INTO categories (path) VALUES (?)", (path,)
        )


def get_all_active_lessons(db_path=None):
    """Get all non-deprecated lessons."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM lessons WHERE deprecated = 0 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_lessons_by_category(level1, level2=None, level3=None, db_path=None):
    """Get lessons filtered by category levels."""
    conn = get_connection(db_path)
    query = "SELECT * FROM lessons WHERE deprecated = 0 AND level1 = ?"
    params = [level1]

    if level2 is not None:
        query += " AND level2 = ?"
        params.append(level2)
    if level3 is not None:
        query += " AND level3 = ?"
        params.append(level3)

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


AUTO_PIN_THRESHOLD = 15


def find_auto_pin_tag_subsets(lesson_id, threshold=AUTO_PIN_THRESHOLD, db_path=None):
    """Find minimal common tag subset with threshold+ matches.

    Algorithm:
    1. Get all tag_sets where lesson matched
    2. Generate powerset of all unique tags (limit size=4 for performance)
    3. Count matches for each subset across all tag_sets
    4. Find minimal subsets (no proper subset also meets threshold)
    5. Return smallest minimal subset

    Args:
        lesson_id: the lesson to check
        threshold: minimum matches required (default 15)
        db_path: optional database path

    Returns:
        Sorted list of tags for auto-pin, or None if no subset meets threshold
    """
    conn = get_connection(db_path)

    # Get all tag sets for this lesson
    rows = conn.execute(
        """SELECT tag_set, times_matched
           FROM lesson_tag_stats
           WHERE lesson_id = ?""",
        (lesson_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return None

    # Parse and collect all unique tags
    tag_sets = []
    for row in rows:
        try:
            tags = set(json.loads(row["tag_set"]))
            tag_sets.append((tags, row["times_matched"]))
        except (json.JSONDecodeError, TypeError):
            continue

    if not tag_sets:
        return None

    all_tags = set().union(*[ts for ts, _ in tag_sets])

    # Generate powerset (limit size to 4 for performance)
    from itertools import combinations
    candidates = []
    for r in range(1, min(len(all_tags), 4) + 1):
        candidates.extend([set(c) for c in combinations(sorted(all_tags), r)])

    # Count matches for each subset
    subset_counts = {}
    for candidate in candidates:
        total = sum(count for tag_set, count in tag_sets if candidate.issubset(tag_set))
        if total >= threshold:
            subset_counts[frozenset(candidate)] = total

    if not subset_counts:
        return None

    # Find minimal subsets (no proper subset also meets threshold)
    sorted_subsets = sorted(subset_counts.keys(), key=len)
    minimal = []
    for subset in sorted_subsets:
        # Check if any subset already in minimal is a proper subset of this one
        if not any(other < subset for other in minimal):
            minimal.append(subset)

    if not minimal:
        return None

    # Return smallest minimal subset
    smallest = min(minimal, key=len)
    return sorted(list(smallest))


def update_match_stats(lesson_id, repo=None, tags=None, db_path=None):
    """Increment times_matched (global + per-repo + per-tag-set) and auto-pin if threshold reached.

    Args:
        lesson_id: the lesson that matched
        repo: current repo name (for per-repo tracking)
        tags: list of environment tags (for per-tag-set tracking)
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    # Global counter
    conn.execute(
        """UPDATE lessons SET times_matched = times_matched + 1,
           last_matched = ?, updated_at = ? WHERE id = ?""",
        (now, now, lesson_id),
    )

    # Per-repo counter
    if repo:
        conn.execute(
            """INSERT INTO lesson_repo_stats (lesson_id, repo, times_matched, last_matched)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(lesson_id, repo) DO UPDATE SET
               times_matched = times_matched + 1, last_matched = ?""",
            (lesson_id, repo, now, now),
        )

        # Check repo-based auto-pin threshold
        row = conn.execute(
            "SELECT times_matched FROM lesson_repo_stats WHERE lesson_id = ? AND repo = ?",
            (lesson_id, repo),
        ).fetchone()

        if row and row["times_matched"] >= AUTO_PIN_THRESHOLD:
            lesson = conn.execute(
                "SELECT pinned, prerequisites FROM lessons WHERE id = ?", (lesson_id,)
            ).fetchone()

            if lesson and not lesson["pinned"]:
                # Auto-pin with repo prerequisite
                existing = {}
                if lesson["prerequisites"]:
                    try:
                        existing = json.loads(lesson["prerequisites"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                repos = set(existing.get("repos", []))
                repos.add(repo)
                existing["repos"] = list(repos)

                conn.execute(
                    "UPDATE lessons SET pinned = 1, prerequisites = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(existing), now, lesson_id),
                )

    # Per-tag-set counter (NEW)
    if tags:
        tag_set_json = json.dumps(sorted(tags))
        conn.execute(
            """INSERT INTO lesson_tag_stats (lesson_id, tag_set, times_matched, last_matched)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(lesson_id, tag_set) DO UPDATE SET
               times_matched = times_matched + 1, last_matched = ?""",
            (lesson_id, tag_set_json, now, now),
        )

        # Check for tag-based auto-pin
        conn.commit()  # Commit first to make stats visible to find_auto_pin_tag_subsets
        auto_pin_tags = find_auto_pin_tag_subsets(lesson_id, db_path=db_path)
        if auto_pin_tags:
            # Check if lesson is already pinned
            lesson = conn.execute(
                "SELECT pinned, prerequisites FROM lessons WHERE id = ?", (lesson_id,)
            ).fetchone()

            if lesson and not lesson["pinned"]:
                # Auto-pin with tag prerequisite
                existing = {}
                if lesson["prerequisites"]:
                    try:
                        existing = json.loads(lesson["prerequisites"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                existing["tags"] = auto_pin_tags

                conn.execute(
                    "UPDATE lessons SET pinned = 1, prerequisites = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(existing), now, lesson_id),
                )

    conn.commit()
    conn.close()


def get_lesson_categories(lesson_id, db_path=None):
    """Get all categories for a lesson."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT category_path FROM lesson_categories WHERE lesson_id = ?", (lesson_id,)
    ).fetchall()
    conn.close()
    return [r["category_path"] for r in rows]


def add_lesson_category(lesson_id, category_path, db_path=None):
    """Add a category to an existing lesson."""
    conn = get_connection(db_path)
    _ensure_category(conn, category_path)
    conn.execute(
        "INSERT OR IGNORE INTO lesson_categories (lesson_id, category_path) VALUES (?, ?)",
        (lesson_id, category_path),
    )
    conn.commit()
    conn.close()


def remove_lesson_category(lesson_id, category_path, db_path=None):
    """Remove a category from a lesson."""
    conn = get_connection(db_path)
    conn.execute(
        "DELETE FROM lesson_categories WHERE lesson_id = ? AND category_path = ?",
        (lesson_id, category_path),
    )
    conn.commit()
    conn.close()


def deprecate_lesson(lesson_id, db_path=None):
    """Soft delete a lesson."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE lessons SET deprecated = 1, updated_at = ? WHERE id = ?",
        (now, lesson_id),
    )
    conn.commit()
    conn.close()


def get_lesson_count(db_path=None):
    """Get count of active lessons."""
    conn = get_connection(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM lessons WHERE deprecated = 0"
    ).fetchone()[0]
    conn.close()
    return count


def get_pinned_lessons(db_path=None):
    """Get all pinned, non-deprecated lessons."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM lessons WHERE deprecated = 0 AND pinned = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_category_stats(db_path=None):
    """Get lesson counts per top-level category."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT level1, COUNT(*) as count FROM lessons
           WHERE deprecated = 0 GROUP BY level1 ORDER BY count DESC"""
    ).fetchall()
    conn.close()
    return [(r["level1"], r["count"]) for r in rows]


# Topic-to-category mapping for importing from .lessons-state.json
TOPIC_CATEGORY_MAP = {
    "tool-usage": "tools/figma",
    "git-workflow": "development/git",
    "styling": "development/frontend/styling",
    "project-structure": "development/architecture",
    "code-patterns": "development/frontend/components",
    "jira-integration": "tools/jira",
    "pr-creation": "development/git/pr",
    "debugging": "development/debugging",
    "permissions": "tools/claude-code",
    "request-clarification": "workflow/communication",
    "instructions": "workflow/setup",
}


def get_processed_session_ids(db_path=None):
    """Get set of already-processed session IDs."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT session_id FROM processed_sessions").fetchall()
    conn.close()
    return {r["session_id"] for r in rows}


def mark_sessions_processed(sessions, db_path=None):
    """Bulk mark sessions as processed.

    Args:
        sessions: list of dicts with session_id, had_friction, lessons_extracted
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    for s in sessions:
        conn.execute(
            """INSERT OR IGNORE INTO processed_sessions
               (session_id, processed_at, had_friction, lessons_extracted)
               VALUES (?, ?, ?, ?)""",
            (s["session_id"], now, s.get("had_friction", 0), s.get("lessons_extracted", 0)),
        )
    conn.commit()
    conn.close()


def find_similar_lesson(text, db_path=None):
    """Find an existing active lesson with similar text (word overlap > 50%).

    Returns the lesson dict if found, None otherwise.
    """
    lessons = get_all_active_lessons(db_path=db_path)
    text_words = set(text.lower().split())
    if not text_words:
        return None

    for lesson in lessons:
        lesson_words = set(lesson["text"].lower().split())
        if not lesson_words:
            continue
        overlap = len(text_words & lesson_words)
        smaller = min(len(text_words), len(lesson_words))
        if overlap / smaller > 0.5:
            return lesson

    return None


def increment_lesson_occurrence(lesson_id, new_sessions=None, db_path=None):
    """Merge source sessions and bump occurrence count for an existing lesson."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    row = conn.execute(
        "SELECT source_sessions, occurrence_count FROM lessons WHERE id = ?",
        (lesson_id,),
    ).fetchone()

    if row:
        existing_sessions = json.loads(row["source_sessions"] or "[]")
        if new_sessions:
            for s in new_sessions:
                if s not in existing_sessions:
                    existing_sessions.append(s)

        conn.execute(
            """UPDATE lessons SET source_sessions = ?, occurrence_count = ?,
               updated_at = ? WHERE id = ?""",
            (json.dumps(existing_sessions), len(existing_sessions), now, lesson_id),
        )

    conn.commit()
    conn.close()


def import_from_state_file(path, db_path=None):
    """Import lessons from .lessons-state.json."""
    if not os.path.exists(path):
        return 0

    with open(path, "r") as f:
        data = json.load(f)

    lessons = data.get("lessons", [])
    imported = 0

    for lesson in lessons:
        topic = lesson.get("topic", "general")
        category = TOPIC_CATEGORY_MAP.get(topic, "general/" + topic)
        text = lesson.get("lesson", "")
        source_sessions = lesson.get("source_sessions", [])
        occurrence_count = lesson.get("occurrence_count", 1)

        if text:
            add_lesson(
                text=text,
                category=category,
                source="auto-extracted",
                source_sessions=source_sessions,
                occurrence_count=occurrence_count,
                db_path=db_path,
            )
            imported += 1

    return imported
