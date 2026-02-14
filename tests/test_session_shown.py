"""Tests for DB-based session-shown tracking (replaces .session-shown.json)."""

import tempfile
from pathlib import Path

import pytest

from src.db import (
    init_db,
    record_shown_lesson,
    get_shown_lesson_ids,
    clear_session_shown,
    add_lesson,
)


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


def test_record_and_get_shown(test_db):
    """Should record shown lessons and retrieve them."""
    lid1 = add_lesson(text="Lesson 1", category="test", db_path=test_db)
    lid2 = add_lesson(text="Lesson 2", category="test", db_path=test_db)

    record_shown_lesson("sess-1", lid1, "UserPromptSubmit", db_path=test_db)
    record_shown_lesson("sess-1", lid2, "PreToolUse", db_path=test_db)

    shown = get_shown_lesson_ids("sess-1", db_path=test_db)
    assert shown == {lid1, lid2}


def test_dedup_same_lesson(test_db):
    """Should not duplicate if same lesson shown twice in a session."""
    lid = add_lesson(text="Lesson 1", category="test", db_path=test_db)

    record_shown_lesson("sess-1", lid, "UserPromptSubmit", db_path=test_db)
    record_shown_lesson("sess-1", lid, "PreToolUse", db_path=test_db)

    shown = get_shown_lesson_ids("sess-1", db_path=test_db)
    assert shown == {lid}


def test_empty_session(test_db):
    """Should return empty set for unknown session."""
    shown = get_shown_lesson_ids("nonexistent", db_path=test_db)
    assert shown == set()


def test_clear_session(test_db):
    """Should clear all shown records for a session."""
    lid = add_lesson(text="Lesson 1", category="test", db_path=test_db)
    record_shown_lesson("sess-1", lid, "UserPromptSubmit", db_path=test_db)

    clear_session_shown("sess-1", db_path=test_db)

    shown = get_shown_lesson_ids("sess-1", db_path=test_db)
    assert shown == set()


def test_sessions_isolated(test_db):
    """Different sessions should have independent shown sets."""
    lid = add_lesson(text="Lesson 1", category="test", db_path=test_db)

    record_shown_lesson("sess-1", lid, "UserPromptSubmit", db_path=test_db)

    assert get_shown_lesson_ids("sess-1", db_path=test_db) == {lid}
    assert get_shown_lesson_ids("sess-2", db_path=test_db) == set()
