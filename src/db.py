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

        -- Replaces .session-shown.json (fixes race condition)
        CREATE TABLE IF NOT EXISTS session_shown_lessons (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            lesson_id INTEGER NOT NULL,
            hook_event TEXT NOT NULL,
            shown_at TEXT NOT NULL,
            UNIQUE(session_id, lesson_id)
        );

        -- Per-tag relevance scoring
        CREATE TABLE IF NOT EXISTS lesson_tag_relevance (
            lesson_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            score REAL DEFAULT 0.0,
            positive_evals INTEGER DEFAULT 0,
            negative_evals INTEGER DEFAULT 0,
            last_evaluated TEXT,
            PRIMARY KEY (lesson_id, tag)
        );

        -- Ground truth for what was shown per session
        CREATE TABLE IF NOT EXISTS session_audit (
            session_id TEXT PRIMARY KEY,
            shown_lesson_ids TEXT NOT NULL,
            env_tags TEXT NOT NULL,
            repo TEXT,
            timestamp TEXT NOT NULL,
            transcript_path TEXT DEFAULT NULL
        );

        -- Evaluation tracking, separate from extraction pipeline
        CREATE TABLE IF NOT EXISTS processed_relevance_sessions (
            session_id TEXT PRIMARY KEY,
            processed_at TEXT,
            retry_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending'
        );
    """)

    # Migrations for existing DBs
    columns = [r[1] for r in conn.execute("PRAGMA table_info(lessons)").fetchall()]
    if "prerequisites" not in columns:
        conn.execute("ALTER TABLE lessons ADD COLUMN prerequisites TEXT DEFAULT NULL")
    if "pinned" not in columns:
        conn.execute("ALTER TABLE lessons ADD COLUMN pinned INTEGER DEFAULT 0")

    # Migration: add transcript_path to session_audit
    audit_columns = [r[1] for r in conn.execute("PRAGMA table_info(session_audit)").fetchall()]
    if audit_columns and "transcript_path" not in audit_columns:
        conn.execute("ALTER TABLE session_audit ADD COLUMN transcript_path TEXT DEFAULT NULL")

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


def add_lesson(text, category="general", categories=None, source="manual", source_sessions=None, occurrence_count=1, prerequisites=None, db_path=None):
    """Insert a new lesson.

    Args:
        text: lesson content
        category: primary category (used for display/level parsing)
        categories: optional list of additional category paths
        source: "auto-extracted" | "manual" | "feedback"
        source_sessions: list of session IDs
        occurrence_count: how many sessions produced this
        prerequisites: optional dict or JSON string of prerequisites (e.g. {"tags": ["acme"]})
    """
    conn = get_connection(db_path)
    level1, level2, level3 = _parse_category(category)
    now = datetime.utcnow().isoformat()
    sessions_json = json.dumps(source_sessions or [])

    # Normalize prerequisites to JSON string
    prereqs_json = None
    if prerequisites is not None:
        if isinstance(prerequisites, dict):
            prereqs_json = json.dumps(prerequisites)
        elif isinstance(prerequisites, str):
            prereqs_json = prerequisites
        # else: leave as None

    cursor = conn.execute(
        """INSERT INTO lessons (text, category, level1, level2, level3, source,
           source_sessions, occurrence_count, prerequisites, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (text, category, level1, level2, level3, source, sessions_json,
         occurrence_count, prereqs_json, now, now),
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


# Topic-to-category mapping for extraction and JSON imports
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
    """Find an existing active lesson with similar text.

    Uses embedding cosine similarity (threshold 0.85) when index is available,
    falls back to word overlap (threshold 0.70).

    Returns the lesson dict if found, None otherwise.
    """
    lessons = get_all_active_lessons(db_path=db_path)
    if not lessons:
        return None

    # Try embedding-based similarity first
    try:
        from .embeddings import embed_text, load_index, vector_search
        embeddings, ids = load_index()
        if embeddings is not None and ids is not None:
            query_emb = embed_text(text)
            results = vector_search(query_emb, embeddings, ids, top_k=3)
            lessons_by_id = {l["id"]: l for l in lessons}
            for lesson_id, score in results:
                if score >= 0.85 and lesson_id in lessons_by_id:
                    return lessons_by_id[lesson_id]
    except Exception:
        pass  # Fall through to word overlap

    # Fallback: word overlap (raised from 0.50 to 0.70)
    text_words = set(text.lower().split())
    if not text_words:
        return None

    for lesson in lessons:
        lesson_words = set(lesson["text"].lower().split())
        if not lesson_words:
            continue
        overlap = len(text_words & lesson_words)
        smaller = min(len(text_words), len(lesson_words))
        if smaller > 0 and overlap / smaller > 0.7:
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


def record_shown_lesson(session_id, lesson_id, hook_event, db_path=None):
    """Record that a lesson was shown during a session (DB-based, replaces file tracking)."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO session_shown_lessons (session_id, lesson_id, hook_event, shown_at)
           VALUES (?, ?, ?, ?)""",
        (session_id, lesson_id, hook_event, now),
    )
    conn.commit()
    conn.close()


def get_shown_lesson_ids(session_id, db_path=None):
    """Get set of lesson IDs shown during a session."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT lesson_id FROM session_shown_lessons WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    conn.close()
    return {r["lesson_id"] for r in rows}


def clear_session_shown(session_id, db_path=None):
    """Clear shown lessons for a session."""
    conn = get_connection(db_path)
    conn.execute(
        "DELETE FROM session_shown_lessons WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def write_session_audit(session_id, shown_lesson_ids, env_tags, repo, transcript_path=None, db_path=None):
    """Write audit record of what was shown in a session."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO session_audit (session_id, shown_lesson_ids, env_tags, repo, timestamp, transcript_path)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, json.dumps(sorted(shown_lesson_ids)), json.dumps(sorted(env_tags)), repo, now, transcript_path),
    )
    conn.commit()
    conn.close()


def get_env_tags_for_sessions(session_ids, db_path=None):
    """Look up env_tags from session_audit for given session IDs.

    Args:
        session_ids: list of session ID strings
        db_path: optional database path

    Returns:
        sorted deduplicated list of tags, or []
    """
    if not session_ids:
        return []

    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(session_ids))
    rows = conn.execute(
        f"SELECT env_tags FROM session_audit WHERE session_id IN ({placeholders})",
        session_ids,
    ).fetchall()
    conn.close()

    tags = set()
    for row in rows:
        try:
            parsed = json.loads(row["env_tags"])
            if isinstance(parsed, list):
                tags.update(parsed)
        except (json.JSONDecodeError, TypeError):
            continue

    return sorted(tags)


def get_unprocessed_audit_sessions(limit=10, db_path=None):
    """Get audit sessions that haven't been evaluated yet.

    Returns sessions from session_audit that don't have a completed entry
    in processed_relevance_sessions, with retry_count < 3.
    """
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT sa.session_id, sa.shown_lesson_ids, sa.env_tags, sa.repo, sa.timestamp, sa.transcript_path
           FROM session_audit sa
           LEFT JOIN processed_relevance_sessions prs ON sa.session_id = prs.session_id
           WHERE prs.session_id IS NULL
              OR (prs.status != 'completed' AND prs.retry_count < 3)
           ORDER BY sa.timestamp ASC
           LIMIT ?""",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- Tag relevance scoring constants ---
EMA_ALPHA = 0.3
SCORE_CLAMP = (-3.0, 3.0)
MIN_EVIDENCE_FOR_PIN = 5
PIN_THRESHOLD = 0.6
UNPIN_THRESHOLD = 0.2


def update_tag_relevance(lesson_id, tag_scores, weight=1.0, db_path=None):
    """Update per-tag relevance scores using EMA.

    Formula: new = clamp(old * (1 - EMA_ALPHA) + raw * EMA_ALPHA * weight, -3, 3)

    Args:
        lesson_id: the lesson
        tag_scores: dict mapping tag -> raw score (e.g. {"typescript": 0.9, "frontend": -0.5})
        weight: multiplier for the raw score (2.0 for direct MCP feedback, 1.0 for eval)
        db_path: optional database path
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    for tag, raw_score in tag_scores.items():
        row = conn.execute(
            "SELECT score, positive_evals, negative_evals FROM lesson_tag_relevance WHERE lesson_id = ? AND tag = ?",
            (lesson_id, tag),
        ).fetchone()

        if row:
            old_score = row["score"]
            new_score = old_score * (1 - EMA_ALPHA) + raw_score * EMA_ALPHA * weight
            new_score = max(SCORE_CLAMP[0], min(SCORE_CLAMP[1], new_score))

            pos = row["positive_evals"] + (1 if raw_score > 0 else 0)
            neg = row["negative_evals"] + (1 if raw_score < 0 else 0)

            conn.execute(
                """UPDATE lesson_tag_relevance
                   SET score = ?, positive_evals = ?, negative_evals = ?, last_evaluated = ?
                   WHERE lesson_id = ? AND tag = ?""",
                (new_score, pos, neg, now, lesson_id, tag),
            )
        else:
            initial_score = max(SCORE_CLAMP[0], min(SCORE_CLAMP[1], raw_score * EMA_ALPHA * weight))
            pos = 1 if raw_score > 0 else 0
            neg = 1 if raw_score < 0 else 0

            conn.execute(
                """INSERT INTO lesson_tag_relevance (lesson_id, tag, score, positive_evals, negative_evals, last_evaluated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (lesson_id, tag, initial_score, pos, neg, now),
            )

    conn.commit()
    conn.close()

    # Check pin/unpin decisions after score update
    check_and_apply_pin_decisions(lesson_id, db_path=db_path)


def get_tag_relevance_scores(lesson_id, db_path=None):
    """Get all tag relevance scores for a lesson.

    Returns:
        dict mapping tag -> score
    """
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT tag, score FROM lesson_tag_relevance WHERE lesson_id = ?",
        (lesson_id,),
    ).fetchall()
    conn.close()
    return {r["tag"]: r["score"] for r in rows}


def get_avg_tag_relevance(lesson_id, tags, db_path=None):
    """Get average relevance score for a lesson across given tags.

    Args:
        lesson_id: the lesson
        tags: list of env tags to average over

    Returns:
        float: average score (0.0 if no scores found)
    """
    if not tags:
        return 0.0

    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(tags))
    rows = conn.execute(
        f"SELECT score FROM lesson_tag_relevance WHERE lesson_id = ? AND tag IN ({placeholders})",
        (lesson_id, *tags),
    ).fetchall()
    conn.close()

    if not rows:
        return 0.0
    return sum(r["score"] for r in rows) / len(rows)


def get_tag_relevance_with_evidence(lesson_id, tags, db_path=None):
    """Get average relevance score and total evidence count for a lesson across given tags.

    Unlike get_avg_tag_relevance(), this:
    - Divides by total requested tags (not just matched rows) — treats missing tags as 0.0
    - Returns evidence count (sum of positive + negative evals) for filter threshold decisions

    Args:
        lesson_id: the lesson
        tags: list of env tags to check

    Returns:
        tuple: (avg_score, total_evals) where avg_score divides by len(tags) and
               total_evals is sum of all positive + negative evals across matched tags
    """
    if not tags:
        return (0.0, 0)

    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(tags))
    rows = conn.execute(
        f"SELECT score, positive_evals, negative_evals FROM lesson_tag_relevance WHERE lesson_id = ? AND tag IN ({placeholders})",
        (lesson_id, *tags),
    ).fetchall()
    conn.close()

    total_score = sum(r["score"] for r in rows)
    total_evals = sum(r["positive_evals"] + r["negative_evals"] for r in rows)

    # Divide by total requested tags, not just matched rows
    avg_score = total_score / len(tags)

    return (avg_score, total_evals)


def check_and_apply_pin_decisions(lesson_id, db_path=None):
    """Auto-pin at avg > PIN_THRESHOLD with enough evidence, auto-unpin at avg < UNPIN_THRESHOLD.

    Only auto-unpins if the lesson was auto-pinned (has "auto_pinned": true in prerequisites).
    Manual pins are never auto-unpinned.

    Returns:
        "pinned", "unpinned", or None
    """
    conn = get_connection(db_path)

    # Get all tag relevance data
    rows = conn.execute(
        "SELECT tag, score, positive_evals, negative_evals FROM lesson_tag_relevance WHERE lesson_id = ?",
        (lesson_id,),
    ).fetchall()

    if not rows:
        conn.close()
        return None

    total_evals = sum(r["positive_evals"] + r["negative_evals"] for r in rows)
    avg_score = sum(r["score"] for r in rows) / len(rows)

    lesson = conn.execute(
        "SELECT pinned, prerequisites FROM lessons WHERE id = ?", (lesson_id,)
    ).fetchone()

    if not lesson:
        conn.close()
        return None

    now = datetime.utcnow().isoformat()
    result = None

    if not lesson["pinned"] and avg_score > PIN_THRESHOLD and total_evals >= MIN_EVIDENCE_FOR_PIN:
        # Auto-pin
        existing = {}
        if lesson["prerequisites"]:
            try:
                existing = json.loads(lesson["prerequisites"])
            except (json.JSONDecodeError, TypeError):
                pass

        existing["auto_pinned"] = True
        # Add tags with positive scores as tag prerequisites
        positive_tags = sorted([r["tag"] for r in rows if r["score"] > 0])
        if positive_tags:
            existing["tags"] = positive_tags

        conn.execute(
            "UPDATE lessons SET pinned = 1, prerequisites = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now, lesson_id),
        )
        result = "pinned"

    elif lesson["pinned"] and avg_score < UNPIN_THRESHOLD and total_evals >= MIN_EVIDENCE_FOR_PIN:
        # Only auto-unpin if it was auto-pinned
        existing = {}
        if lesson["prerequisites"]:
            try:
                existing = json.loads(lesson["prerequisites"])
            except (json.JSONDecodeError, TypeError):
                pass

        if existing.get("auto_pinned"):
            conn.execute(
                "UPDATE lessons SET pinned = 0, updated_at = ? WHERE id = ?",
                (now, lesson_id),
            )
            result = "unpinned"

    conn.commit()
    conn.close()
    return result


def import_from_state_file(path, db_path=None):
    """Import lessons from a JSON state file."""
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
