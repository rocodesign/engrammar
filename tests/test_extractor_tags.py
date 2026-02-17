"""Tests for session audit tag enrichment in extraction and backfill."""

import json
import tempfile
from pathlib import Path

import pytest

from src.db import (
    add_lesson,
    get_connection,
    get_env_tags_for_sessions,
    init_db,
    write_session_audit,
)
from src.extractor import _enrich_with_session_tags


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


# --- get_env_tags_for_sessions ---


def test_get_env_tags_for_sessions(test_db):
    """Returns deduplicated, sorted tags from audit records."""
    write_session_audit("s1", [1], ["react", "frontend"], "repo", db_path=test_db)
    write_session_audit("s2", [2], ["frontend", "typescript"], "repo", db_path=test_db)

    tags = get_env_tags_for_sessions(["s1", "s2"], db_path=test_db)
    assert tags == ["frontend", "react", "typescript"]


def test_get_env_tags_no_audit(test_db):
    """Returns [] when no audit records exist for given sessions."""
    tags = get_env_tags_for_sessions(["nonexistent"], db_path=test_db)
    assert tags == []


def test_get_env_tags_empty_input(test_db):
    """Returns [] for empty session list."""
    tags = get_env_tags_for_sessions([], db_path=test_db)
    assert tags == []


def test_get_env_tags_partial_match(test_db):
    """Returns tags only from sessions that exist in audit."""
    write_session_audit("s1", [1], ["react"], "repo", db_path=test_db)

    tags = get_env_tags_for_sessions(["s1", "missing"], db_path=test_db)
    assert tags == ["react"]


# --- _enrich_with_session_tags ---


def test_enrich_with_session_tags_new(test_db):
    """Creates prerequisites with tags when none existed."""
    write_session_audit("s1", [], ["python", "backend"], "repo", db_path=test_db)

    result = _enrich_with_session_tags(None, ["s1"], db_path=test_db)
    assert result == {"tags": ["backend", "python"]}


def test_enrich_with_session_tags_merge(test_db):
    """Merges new tags with existing tags (union)."""
    write_session_audit("s1", [], ["react", "typescript"], "repo", db_path=test_db)

    existing = {"tags": ["frontend", "react"]}
    result = _enrich_with_session_tags(existing, ["s1"], db_path=test_db)
    assert result == {"tags": ["frontend", "react", "typescript"]}


def test_enrich_preserves_non_tag_prereqs(test_db):
    """Preserves other prerequisite keys when merging tags."""
    write_session_audit("s1", [], ["react"], "repo", db_path=test_db)

    existing = {"mcp_servers": ["figma"], "tags": ["frontend"]}
    result = _enrich_with_session_tags(existing, ["s1"], db_path=test_db)
    assert result == {"mcp_servers": ["figma"], "tags": ["frontend", "react"]}


def test_enrich_no_audit_returns_original(test_db):
    """Returns original prerequisites when no audit tags found."""
    existing = {"tags": ["frontend"]}
    result = _enrich_with_session_tags(existing, ["missing"], db_path=test_db)
    assert result == {"tags": ["frontend"]}


def test_enrich_no_audit_none_stays_none(test_db):
    """Returns None when no audit tags and no existing prerequisites."""
    result = _enrich_with_session_tags(None, ["missing"], db_path=test_db)
    assert result is None


# --- cmd_backfill_prereqs with audit tags ---


def test_backfill_prereqs_adds_audit_tags(test_db, monkeypatch, capsys):
    """Backfill command picks up session audit tags for lessons."""
    import src.config as config
    import src.db as db_mod

    monkeypatch.setattr(config, "DB_PATH", test_db)
    monkeypatch.setattr(db_mod, "DB_PATH", test_db)

    # Create a lesson with source_sessions
    lesson_id = add_lesson(
        text="Use react hooks for state management",
        category="general",
        source="auto-extracted",
        source_sessions=["sess-abc"],
        db_path=test_db,
    )

    # Create audit record with env_tags
    write_session_audit("sess-abc", [lesson_id], ["react", "frontend"], "app-repo", db_path=test_db)

    # Run backfill-prereqs
    sys_path_backup = __import__("sys").path[:]
    try:
        import cli
        cli.cmd_backfill_prereqs(["--dry-run"])
    finally:
        __import__("sys").path[:] = sys_path_backup

    output = capsys.readouterr().out
    assert "Would set lesson" in output
    assert "react" in output
    assert "frontend" in output


def test_backfill_prereqs_merges_into_existing(test_db, monkeypatch, capsys):
    """Backfill merges audit tags into lessons that already have prerequisites."""
    import src.config as config
    import src.db as db_mod

    monkeypatch.setattr(config, "DB_PATH", test_db)
    monkeypatch.setattr(db_mod, "DB_PATH", test_db)

    # Create a lesson with existing prerequisites
    lesson_id = add_lesson(
        text="Use figma mcp for design tokens",
        category="general",
        source="auto-extracted",
        source_sessions=["sess-xyz"],
        prerequisites={"mcp_servers": ["figma"]},
        db_path=test_db,
    )

    # Create audit record with additional tags
    write_session_audit("sess-xyz", [lesson_id], ["design", "frontend"], "app-repo", db_path=test_db)

    # Run backfill-prereqs (not dry-run)
    import cli
    cli.cmd_backfill_prereqs([])

    # Verify lesson was updated with merged tags
    conn = get_connection(test_db)
    row = conn.execute("SELECT prerequisites FROM lessons WHERE id = ?", (lesson_id,)).fetchone()
    conn.close()

    prereqs = json.loads(row["prerequisites"])
    assert prereqs["mcp_servers"] == ["figma"]
    assert "design" in prereqs["tags"]
    assert "frontend" in prereqs["tags"]


def test_backfill_prereqs_no_change_skips(test_db, monkeypatch, capsys):
    """Backfill skips lessons where audit tags are already present."""
    import src.config as config
    import src.db as db_mod

    monkeypatch.setattr(config, "DB_PATH", test_db)
    monkeypatch.setattr(db_mod, "DB_PATH", test_db)

    # Create a lesson with tags that match the audit
    lesson_id = add_lesson(
        text="Use react hooks",
        category="general",
        source="auto-extracted",
        source_sessions=["sess-same"],
        prerequisites={"tags": ["frontend", "react"]},
        db_path=test_db,
    )

    write_session_audit("sess-same", [lesson_id], ["frontend", "react"], "repo", db_path=test_db)

    import cli
    cli.cmd_backfill_prereqs(["--dry-run"])

    output = capsys.readouterr().out
    assert "Would set lesson" not in output
