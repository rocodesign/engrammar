"""SQLite database for engram storage."""

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
        CREATE TABLE IF NOT EXISTS engrams (
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

        CREATE INDEX IF NOT EXISTS idx_engrams_category ON engrams(category);
        CREATE INDEX IF NOT EXISTS idx_engrams_level1 ON engrams(level1);
        CREATE INDEX IF NOT EXISTS idx_engrams_deprecated ON engrams(deprecated);

        CREATE TABLE IF NOT EXISTS engram_categories (
            engram_id INTEGER NOT NULL,
            category_path TEXT NOT NULL,
            PRIMARY KEY (engram_id, category_path),
            FOREIGN KEY (engram_id) REFERENCES engrams(id)
        );

        CREATE TABLE IF NOT EXISTS engram_repo_stats (
            engram_id INTEGER NOT NULL,
            repo TEXT NOT NULL,
            times_matched INTEGER DEFAULT 0,
            last_matched TEXT,
            PRIMARY KEY (engram_id, repo),
            FOREIGN KEY (engram_id) REFERENCES engrams(id)
        );

        CREATE TABLE IF NOT EXISTS engram_tag_stats (
            engram_id INTEGER NOT NULL,
            tag_set TEXT NOT NULL,
            times_matched INTEGER DEFAULT 0,
            last_matched TEXT,
            PRIMARY KEY (engram_id, tag_set),
            FOREIGN KEY (engram_id) REFERENCES engrams(id)
        );

        CREATE TABLE IF NOT EXISTS processed_sessions (
            session_id TEXT PRIMARY KEY,
            processed_at TEXT,
            had_friction INTEGER DEFAULT 0,
            engrams_extracted INTEGER DEFAULT 0
        );

        -- Replaces .session-shown.json (fixes race condition)
        CREATE TABLE IF NOT EXISTS session_shown_engrams (
            id INTEGER PRIMARY KEY,
            session_id TEXT NOT NULL,
            engram_id INTEGER NOT NULL,
            hook_event TEXT NOT NULL,
            shown_at TEXT NOT NULL,
            UNIQUE(session_id, engram_id)
        );

        -- Per-tag relevance scoring
        CREATE TABLE IF NOT EXISTS engram_tag_relevance (
            engram_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            score REAL DEFAULT 0.0,
            positive_evals INTEGER DEFAULT 0,
            negative_evals INTEGER DEFAULT 0,
            last_evaluated TEXT,
            PRIMARY KEY (engram_id, tag)
        );

        -- Ground truth for what was shown per session
        CREATE TABLE IF NOT EXISTS session_audit (
            session_id TEXT PRIMARY KEY,
            shown_engram_ids TEXT NOT NULL,
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

        -- Persistent event log for hook activity
        CREATE TABLE IF NOT EXISTS hook_event_log (
            id INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            session_id TEXT,
            hook_event TEXT NOT NULL,
            engram_ids TEXT NOT NULL,
            context TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_hook_event_log_ts ON hook_event_log(timestamp);
    """)

    # Migrations for existing DBs
    columns = [r[1] for r in conn.execute("PRAGMA table_info(engrams)").fetchall()]
    if "prerequisites" not in columns:
        conn.execute("ALTER TABLE engrams ADD COLUMN prerequisites TEXT DEFAULT NULL")
    if "pinned" not in columns:
        conn.execute("ALTER TABLE engrams ADD COLUMN pinned INTEGER DEFAULT 0")

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


def add_engram(text, category="general", categories=None, source="manual", source_sessions=None, occurrence_count=1, prerequisites=None, db_path=None):
    """Insert a new engram.

    Args:
        text: engram content
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
        """INSERT INTO engrams (text, category, level1, level2, level3, source,
           source_sessions, occurrence_count, prerequisites, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (text, category, level1, level2, level3, source, sessions_json,
         occurrence_count, prereqs_json, now, now),
    )
    engram_id = cursor.lastrowid

    # Ensure primary category path exists and add to junction table
    _ensure_category(conn, category)
    conn.execute(
        "INSERT OR IGNORE INTO engram_categories (engram_id, category_path) VALUES (?, ?)",
        (engram_id, category),
    )

    # Add additional categories
    if categories:
        for cat in categories:
            _ensure_category(conn, cat)
            conn.execute(
                "INSERT OR IGNORE INTO engram_categories (engram_id, category_path) VALUES (?, ?)",
                (engram_id, cat),
            )

    conn.commit()
    conn.close()
    return engram_id


def _ensure_category(conn, category):
    """Insert category path if not exists."""
    parts = category.strip("/").split("/")
    for i in range(len(parts)):
        path = "/".join(parts[: i + 1])
        conn.execute(
            "INSERT OR IGNORE INTO categories (path) VALUES (?)", (path,)
        )


def get_all_active_engrams(db_path=None):
    """Get all non-deprecated engrams."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM engrams WHERE deprecated = 0 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_engrams_by_category(level1, level2=None, level3=None, db_path=None):
    """Get engrams filtered by category levels."""
    conn = get_connection(db_path)
    query = "SELECT * FROM engrams WHERE deprecated = 0 AND level1 = ?"
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


def find_auto_pin_tag_subsets(engram_id, threshold=AUTO_PIN_THRESHOLD, db_path=None):
    """Find minimal common tag subset with threshold+ matches.

    Algorithm:
    1. Get all tag_sets where engram matched
    2. Generate powerset of all unique tags (limit size=4 for performance)
    3. Count matches for each subset across all tag_sets
    4. Find minimal subsets (no proper subset also meets threshold)
    5. Return smallest minimal subset

    Args:
        engram_id: the engram to check
        threshold: minimum matches required (default 15)
        db_path: optional database path

    Returns:
        Sorted list of tags for auto-pin, or None if no subset meets threshold
    """
    conn = get_connection(db_path)

    # Get all tag sets for this engram
    rows = conn.execute(
        """SELECT tag_set, times_matched
           FROM engram_tag_stats
           WHERE engram_id = ?""",
        (engram_id,)
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


def update_match_stats(engram_id, repo=None, tags=None, db_path=None):
    """Increment times_matched (global + per-repo + per-tag-set) and auto-pin if threshold reached.

    Args:
        engram_id: the engram that matched
        repo: current repo name (for per-repo tracking)
        tags: list of environment tags (for per-tag-set tracking)
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    # Global counter
    conn.execute(
        """UPDATE engrams SET times_matched = times_matched + 1,
           last_matched = ?, updated_at = ? WHERE id = ?""",
        (now, now, engram_id),
    )

    # Per-repo counter
    if repo:
        conn.execute(
            """INSERT INTO engram_repo_stats (engram_id, repo, times_matched, last_matched)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(engram_id, repo) DO UPDATE SET
               times_matched = times_matched + 1, last_matched = ?""",
            (engram_id, repo, now, now),
        )

        # Check repo-based auto-pin threshold
        row = conn.execute(
            "SELECT times_matched FROM engram_repo_stats WHERE engram_id = ? AND repo = ?",
            (engram_id, repo),
        ).fetchone()

        if row and row["times_matched"] >= AUTO_PIN_THRESHOLD:
            engram = conn.execute(
                "SELECT pinned, prerequisites FROM engrams WHERE id = ?", (engram_id,)
            ).fetchone()

            if engram and not engram["pinned"]:
                # Auto-pin with repo prerequisite
                existing = {}
                if engram["prerequisites"]:
                    try:
                        existing = json.loads(engram["prerequisites"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                repos = set(existing.get("repos", []))
                repos.add(repo)
                existing["repos"] = list(repos)

                conn.execute(
                    "UPDATE engrams SET pinned = 1, prerequisites = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(existing), now, engram_id),
                )

    # Per-tag-set counter (NEW)
    if tags:
        tag_set_json = json.dumps(sorted(tags))
        conn.execute(
            """INSERT INTO engram_tag_stats (engram_id, tag_set, times_matched, last_matched)
               VALUES (?, ?, 1, ?)
               ON CONFLICT(engram_id, tag_set) DO UPDATE SET
               times_matched = times_matched + 1, last_matched = ?""",
            (engram_id, tag_set_json, now, now),
        )

        # Check for tag-based auto-pin
        conn.commit()  # Commit first to make stats visible to find_auto_pin_tag_subsets
        auto_pin_tags = find_auto_pin_tag_subsets(engram_id, db_path=db_path)
        if auto_pin_tags:
            # Check if engram is already pinned
            engram = conn.execute(
                "SELECT pinned, prerequisites FROM engrams WHERE id = ?", (engram_id,)
            ).fetchone()

            if engram and not engram["pinned"]:
                # Auto-pin with tag prerequisite
                existing = {}
                if engram["prerequisites"]:
                    try:
                        existing = json.loads(engram["prerequisites"])
                    except (json.JSONDecodeError, TypeError):
                        pass

                existing["tags"] = auto_pin_tags

                conn.execute(
                    "UPDATE engrams SET pinned = 1, prerequisites = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(existing), now, engram_id),
                )

    conn.commit()
    conn.close()


def get_engram_categories(engram_id, db_path=None):
    """Get all categories for a engram."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT category_path FROM engram_categories WHERE engram_id = ?", (engram_id,)
    ).fetchall()
    conn.close()
    return [r["category_path"] for r in rows]


def add_engram_category(engram_id, category_path, db_path=None):
    """Add a category to an existing engram."""
    conn = get_connection(db_path)
    _ensure_category(conn, category_path)
    conn.execute(
        "INSERT OR IGNORE INTO engram_categories (engram_id, category_path) VALUES (?, ?)",
        (engram_id, category_path),
    )
    conn.commit()
    conn.close()


def remove_engram_category(engram_id, category_path, db_path=None):
    """Remove a category from a engram."""
    conn = get_connection(db_path)
    conn.execute(
        "DELETE FROM engram_categories WHERE engram_id = ? AND category_path = ?",
        (engram_id, category_path),
    )
    conn.commit()
    conn.close()


def deprecate_engram(engram_id, db_path=None):
    """Soft delete a engram."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        "UPDATE engrams SET deprecated = 1, updated_at = ? WHERE id = ?",
        (now, engram_id),
    )
    conn.commit()
    conn.close()


def get_engram_count(db_path=None):
    """Get count of active engrams."""
    conn = get_connection(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM engrams WHERE deprecated = 0"
    ).fetchone()[0]
    conn.close()
    return count


def get_pinned_engrams(db_path=None):
    """Get all pinned, non-deprecated engrams."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM engrams WHERE deprecated = 0 AND pinned = 1 ORDER BY id"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_category_stats(db_path=None):
    """Get engram counts per top-level category."""
    conn = get_connection(db_path)
    rows = conn.execute(
        """SELECT level1, COUNT(*) as count FROM engrams
           WHERE deprecated = 0 GROUP BY level1 ORDER BY count DESC"""
    ).fetchall()
    conn.close()
    return [(r["level1"], r["count"]) for r in rows]


def get_processed_session_ids(db_path=None):
    """Get set of already-processed session IDs."""
    conn = get_connection(db_path)
    rows = conn.execute("SELECT session_id FROM processed_sessions").fetchall()
    conn.close()
    return {r["session_id"] for r in rows}


def mark_sessions_processed(sessions, db_path=None):
    """Bulk mark sessions as processed.

    Args:
        sessions: list of dicts with session_id, had_friction, engrams_extracted
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    for s in sessions:
        conn.execute(
            """INSERT OR IGNORE INTO processed_sessions
               (session_id, processed_at, had_friction, engrams_extracted)
               VALUES (?, ?, ?, ?)""",
            (s["session_id"], now, s.get("had_friction", 0), s.get("engrams_extracted", 0)),
        )
    conn.commit()
    conn.close()


def find_similar_engram(text, db_path=None):
    """Find an existing active engram with similar text.

    Uses embedding cosine similarity (threshold 0.85) when index is available,
    falls back to word overlap (threshold 0.70).

    Returns the engram dict if found, None otherwise.
    """
    engrams = get_all_active_engrams(db_path=db_path)
    if not engrams:
        return None

    # Try embedding-based similarity first
    try:
        from .embeddings import embed_text, load_index, vector_search
        embeddings, ids = load_index()
        if embeddings is not None and ids is not None:
            query_emb = embed_text(text)
            results = vector_search(query_emb, embeddings, ids, top_k=3)
            engrams_by_id = {l["id"]: l for l in engrams}
            for engram_id, score in results:
                if score >= 0.85 and engram_id in engrams_by_id:
                    return engrams_by_id[engram_id]
    except Exception:
        pass  # Fall through to word overlap

    # Fallback: word overlap (raised from 0.50 to 0.70)
    text_words = set(text.lower().split())
    if not text_words:
        return None

    for engram in engrams:
        engram_words = set(engram["text"].lower().split())
        if not engram_words:
            continue
        overlap = len(text_words & engram_words)
        smaller = min(len(text_words), len(engram_words))
        if smaller > 0 and overlap / smaller > 0.7:
            return engram

    return None


def increment_engram_occurrence(engram_id, new_sessions=None, db_path=None):
    """Merge source sessions and bump occurrence count for an existing engram."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    row = conn.execute(
        "SELECT source_sessions, occurrence_count FROM engrams WHERE id = ?",
        (engram_id,),
    ).fetchone()

    if row:
        existing_sessions = json.loads(row["source_sessions"] or "[]")
        if new_sessions:
            for s in new_sessions:
                if s not in existing_sessions:
                    existing_sessions.append(s)

        conn.execute(
            """UPDATE engrams SET source_sessions = ?, occurrence_count = ?,
               updated_at = ? WHERE id = ?""",
            (json.dumps(existing_sessions), len(existing_sessions), now, engram_id),
        )

    conn.commit()
    conn.close()


def record_shown_engram(session_id, engram_id, hook_event, db_path=None):
    """Record that a engram was shown during a session (DB-based, replaces file tracking)."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO session_shown_engrams (session_id, engram_id, hook_event, shown_at)
           VALUES (?, ?, ?, ?)""",
        (session_id, engram_id, hook_event, now),
    )
    conn.commit()
    conn.close()


def get_shown_engram_ids(session_id, db_path=None):
    """Get set of engram IDs shown during a session."""
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT engram_id FROM session_shown_engrams WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    conn.close()
    return {r["engram_id"] for r in rows}


def clear_session_shown(session_id, db_path=None):
    """Clear shown engrams for a session."""
    conn = get_connection(db_path)
    conn.execute(
        "DELETE FROM session_shown_engrams WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()


def write_session_audit(session_id, shown_engram_ids, env_tags, repo, transcript_path=None, db_path=None):
    """Write audit record of what was shown in a session."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR REPLACE INTO session_audit (session_id, shown_engram_ids, env_tags, repo, timestamp, transcript_path)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, json.dumps(sorted(shown_engram_ids)), json.dumps(sorted(env_tags)), repo, now, transcript_path),
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
        """SELECT sa.session_id, sa.shown_engram_ids, sa.env_tags, sa.repo, sa.timestamp, sa.transcript_path
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


def update_tag_relevance(engram_id, tag_scores, weight=1.0, db_path=None):
    """Update per-tag relevance scores using EMA.

    Formula: new = clamp(old * (1 - EMA_ALPHA) + raw * EMA_ALPHA * weight, -3, 3)

    Args:
        engram_id: the engram
        tag_scores: dict mapping tag -> raw score (e.g. {"typescript": 0.9, "frontend": -0.5})
        weight: multiplier for the raw score (2.0 for direct MCP feedback, 1.0 for eval)
        db_path: optional database path
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    for tag, raw_score in tag_scores.items():
        row = conn.execute(
            "SELECT score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ? AND tag = ?",
            (engram_id, tag),
        ).fetchone()

        if row:
            old_score = row["score"]
            new_score = old_score * (1 - EMA_ALPHA) + raw_score * EMA_ALPHA * weight
            new_score = max(SCORE_CLAMP[0], min(SCORE_CLAMP[1], new_score))

            pos = row["positive_evals"] + (1 if raw_score > 0 else 0)
            neg = row["negative_evals"] + (1 if raw_score < 0 else 0)

            conn.execute(
                """UPDATE engram_tag_relevance
                   SET score = ?, positive_evals = ?, negative_evals = ?, last_evaluated = ?
                   WHERE engram_id = ? AND tag = ?""",
                (new_score, pos, neg, now, engram_id, tag),
            )
        else:
            initial_score = max(SCORE_CLAMP[0], min(SCORE_CLAMP[1], raw_score * EMA_ALPHA * weight))
            pos = 1 if raw_score > 0 else 0
            neg = 1 if raw_score < 0 else 0

            conn.execute(
                """INSERT INTO engram_tag_relevance (engram_id, tag, score, positive_evals, negative_evals, last_evaluated)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (engram_id, tag, initial_score, pos, neg, now),
            )

    conn.commit()
    conn.close()

    # Check pin/unpin decisions after score update
    check_and_apply_pin_decisions(engram_id, db_path=db_path)


def get_tag_relevance_scores(engram_id, db_path=None):
    """Get all tag relevance scores for a engram.

    Returns:
        dict mapping tag -> score
    """
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT tag, score FROM engram_tag_relevance WHERE engram_id = ?",
        (engram_id,),
    ).fetchall()
    conn.close()
    return {r["tag"]: r["score"] for r in rows}


def get_avg_tag_relevance(engram_id, tags, db_path=None):
    """Get average relevance score for a engram across given tags.

    Args:
        engram_id: the engram
        tags: list of env tags to average over

    Returns:
        float: average score (0.0 if no scores found)
    """
    if not tags:
        return 0.0

    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(tags))
    rows = conn.execute(
        f"SELECT score FROM engram_tag_relevance WHERE engram_id = ? AND tag IN ({placeholders})",
        (engram_id, *tags),
    ).fetchall()
    conn.close()

    if not rows:
        return 0.0
    return sum(r["score"] for r in rows) / len(rows)


def get_tag_relevance_with_evidence(engram_id, tags, db_path=None):
    """Get average relevance score and total evidence count for a engram across given tags.

    Unlike get_avg_tag_relevance(), this:
    - Divides by total requested tags (not just matched rows) — treats missing tags as 0.0
    - Returns evidence count (sum of positive + negative evals) for filter threshold decisions

    Args:
        engram_id: the engram
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
        f"SELECT score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ? AND tag IN ({placeholders})",
        (engram_id, *tags),
    ).fetchall()
    conn.close()

    total_score = sum(r["score"] for r in rows)
    total_evals = sum(r["positive_evals"] + r["negative_evals"] for r in rows)

    # Divide by total requested tags, not just matched rows
    avg_score = total_score / len(tags)

    return (avg_score, total_evals)


def check_and_apply_pin_decisions(engram_id, db_path=None):
    """Auto-pin at avg > PIN_THRESHOLD with enough evidence, auto-unpin at avg < UNPIN_THRESHOLD.

    Only auto-unpins if the engram was auto-pinned (has "auto_pinned": true in prerequisites).
    Manual pins are never auto-unpinned.

    Returns:
        "pinned", "unpinned", or None
    """
    conn = get_connection(db_path)

    # Get all tag relevance data
    rows = conn.execute(
        "SELECT tag, score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ?",
        (engram_id,),
    ).fetchall()

    if not rows:
        conn.close()
        return None

    total_evals = sum(r["positive_evals"] + r["negative_evals"] for r in rows)
    avg_score = sum(r["score"] for r in rows) / len(rows)

    engram = conn.execute(
        "SELECT pinned, prerequisites FROM engrams WHERE id = ?", (engram_id,)
    ).fetchone()

    if not engram:
        conn.close()
        return None

    now = datetime.utcnow().isoformat()
    result = None

    if not engram["pinned"] and avg_score > PIN_THRESHOLD and total_evals >= MIN_EVIDENCE_FOR_PIN:
        # Auto-pin
        existing = {}
        if engram["prerequisites"]:
            try:
                existing = json.loads(engram["prerequisites"])
            except (json.JSONDecodeError, TypeError):
                pass

        existing["auto_pinned"] = True
        # Add tags with positive scores as tag prerequisites
        positive_tags = sorted([r["tag"] for r in rows if r["score"] > 0])
        if positive_tags:
            existing["tags"] = positive_tags

        conn.execute(
            "UPDATE engrams SET pinned = 1, prerequisites = ?, updated_at = ? WHERE id = ?",
            (json.dumps(existing), now, engram_id),
        )
        result = "pinned"

    elif engram["pinned"] and avg_score < UNPIN_THRESHOLD and total_evals >= MIN_EVIDENCE_FOR_PIN:
        # Only auto-unpin if it was auto-pinned
        existing = {}
        if engram["prerequisites"]:
            try:
                existing = json.loads(engram["prerequisites"])
            except (json.JSONDecodeError, TypeError):
                pass

        if existing.get("auto_pinned"):
            conn.execute(
                "UPDATE engrams SET pinned = 0, updated_at = ? WHERE id = ?",
                (now, engram_id),
            )
            result = "unpinned"

    conn.commit()
    conn.close()
    return result


def import_from_state_file(path, db_path=None):
    """Import engrams from a JSON state file."""
    if not os.path.exists(path):
        return 0

    with open(path, "r") as f:
        data = json.load(f)

    engrams = data.get("engrams", [])
    imported = 0

    for engram in engrams:
        category = engram.get("category") or engram.get("topic", "general")
        if "/" not in category:
            category = "general/" + category
        text = engram.get("engram", "")
        source_sessions = engram.get("source_sessions", [])
        occurrence_count = engram.get("occurrence_count", 1)

        if text:
            add_engram(
                text=text,
                category=category,
                source="auto-extracted",
                source_sessions=source_sessions,
                occurrence_count=occurrence_count,
                db_path=db_path,
            )
            imported += 1

    return imported


def log_hook_event(session_id, hook_event, engram_ids, context=None, db_path=None):
    """Write a persistent event log entry for a hook injection.

    Args:
        session_id: current session ID (may be None)
        hook_event: e.g. "SessionStart", "UserPromptSubmit", "PreToolUse"
        engram_ids: list of engram IDs that were injected
        context: optional string (query snippet, tool name, etc.)
    """
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT INTO hook_event_log (timestamp, session_id, hook_event, engram_ids, context)
           VALUES (?, ?, ?, ?, ?)""",
        (now, session_id, hook_event, json.dumps(engram_ids), context),
    )
    conn.commit()
    conn.close()


def get_hook_events(limit=50, offset=0, db_path=None):
    """Get hook event log entries, most recent first.

    Returns:
        list of dicts with id, timestamp, session_id, hook_event, engram_ids, context
    """
    conn = get_connection(db_path)
    rows = conn.execute(
        "SELECT * FROM hook_event_log ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
