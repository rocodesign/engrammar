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
            prerequisites TEXT DEFAULT NULL
        );

        CREATE TABLE IF NOT EXISTS categories (
            path TEXT PRIMARY KEY,
            description TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_lessons_category ON lessons(category);
        CREATE INDEX IF NOT EXISTS idx_lessons_level1 ON lessons(level1);
        CREATE INDEX IF NOT EXISTS idx_lessons_deprecated ON lessons(deprecated);
    """)

    # Migration: add prerequisites column if missing (for existing DBs)
    columns = [r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()]
    if "prerequisites" not in columns:
        conn.execute("ALTER TABLE lessons ADD COLUMN prerequisites TEXT DEFAULT NULL")

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


def add_lesson(text, category="general", source="manual", source_sessions=None, occurrence_count=1, db_path=None):
    """Insert a new lesson."""
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

    # Ensure category path exists
    _ensure_category(conn, category)

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


def update_match_stats(lesson_id, db_path=None):
    """Increment times_matched and update last_matched."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """UPDATE lessons SET times_matched = times_matched + 1,
           last_matched = ?, updated_at = ? WHERE id = ?""",
        (now, now, lesson_id),
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
