"""Tests for session audit write/read and unprocessed filtering."""

import json
import tempfile
from pathlib import Path

import pytest

from src.db import (
    init_db,
    write_session_audit,
    get_unprocessed_audit_sessions,
    get_connection,
)


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


def test_write_and_read_audit(test_db):
    """Should write audit record and retrieve it as unprocessed."""
    write_session_audit("sess-1", [1, 2, 3], ["frontend", "react"], "app-repo", db_path=test_db)

    unprocessed = get_unprocessed_audit_sessions(db_path=test_db)
    assert len(unprocessed) == 1
    assert unprocessed[0]["session_id"] == "sess-1"
    assert json.loads(unprocessed[0]["shown_lesson_ids"]) == [1, 2, 3]
    assert json.loads(unprocessed[0]["env_tags"]) == ["frontend", "react"]
    assert unprocessed[0]["repo"] == "app-repo"


def test_write_audit_with_transcript_path(test_db):
    """Should persist transcript_path when provided."""
    write_session_audit(
        "sess-tp", [1], ["test"], "repo",
        transcript_path="/home/user/.claude/projects/proj/abc.jsonl",
        db_path=test_db,
    )

    unprocessed = get_unprocessed_audit_sessions(db_path=test_db)
    assert len(unprocessed) == 1
    assert unprocessed[0]["transcript_path"] == "/home/user/.claude/projects/proj/abc.jsonl"


def test_write_audit_without_transcript_path(test_db):
    """Should default transcript_path to None when not provided."""
    write_session_audit("sess-no-tp", [1], ["test"], "repo", db_path=test_db)

    unprocessed = get_unprocessed_audit_sessions(db_path=test_db)
    assert len(unprocessed) == 1
    assert unprocessed[0]["transcript_path"] is None


def test_completed_sessions_excluded(test_db):
    """Completed sessions should not appear in unprocessed list."""
    write_session_audit("sess-1", [1], ["test"], "repo", db_path=test_db)

    # Mark as completed
    conn = get_connection(test_db)
    conn.execute(
        "INSERT INTO processed_relevance_sessions (session_id, status) VALUES (?, 'completed')",
        ("sess-1",),
    )
    conn.commit()
    conn.close()

    unprocessed = get_unprocessed_audit_sessions(db_path=test_db)
    assert len(unprocessed) == 0


def test_failed_sessions_retried(test_db):
    """Failed sessions with retry_count < 3 should still appear."""
    write_session_audit("sess-1", [1], ["test"], "repo", db_path=test_db)

    conn = get_connection(test_db)
    conn.execute(
        "INSERT INTO processed_relevance_sessions (session_id, status, retry_count) VALUES (?, 'failed', 2)",
        ("sess-1",),
    )
    conn.commit()
    conn.close()

    unprocessed = get_unprocessed_audit_sessions(db_path=test_db)
    assert len(unprocessed) == 1


def test_max_retries_excluded(test_db):
    """Sessions with retry_count >= 3 should not appear."""
    write_session_audit("sess-1", [1], ["test"], "repo", db_path=test_db)

    conn = get_connection(test_db)
    conn.execute(
        "INSERT INTO processed_relevance_sessions (session_id, status, retry_count) VALUES (?, 'failed', 3)",
        ("sess-1",),
    )
    conn.commit()
    conn.close()

    unprocessed = get_unprocessed_audit_sessions(db_path=test_db)
    assert len(unprocessed) == 0


def test_limit_respected(test_db):
    """Should respect the limit parameter."""
    for i in range(5):
        write_session_audit(f"sess-{i}", [1], ["test"], "repo", db_path=test_db)

    unprocessed = get_unprocessed_audit_sessions(limit=2, db_path=test_db)
    assert len(unprocessed) == 2
