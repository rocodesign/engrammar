"""Tests for shared hook utilities."""

import os
import tempfile

from src.hook_utils import (
    format_lessons_block,
    make_hook_output,
    read_session_id,
    write_session_id,
    clear_session_id,
)


def test_format_lessons_block_with_categories():
    lessons = [
        {"id": 42, "text": "Never use inline styles", "category": "development/frontend"},
        {"id": 17, "text": "Branch naming: taps-NUMBER", "category": "development/git"},
    ]
    result = format_lessons_block(lessons, show_categories=True)

    assert "[ENGRAMMAR_V1]" in result
    assert "[/ENGRAMMAR_V1]" in result
    assert "[EG#42]" in result
    assert "[EG#17]" in result
    assert "[development/frontend]" in result
    assert "engrammar_feedback" in result


def test_format_lessons_block_without_categories():
    lessons = [{"id": 1, "text": "Test lesson", "category": "test"}]
    result = format_lessons_block(lessons, show_categories=False)

    assert "[EG#1]" in result
    assert "[test]" not in result


def test_format_lessons_block_empty():
    result = format_lessons_block([], show_categories=True)
    assert result == ""


def test_make_hook_output():
    output = make_hook_output("SessionStart", "some context")
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert output["hookSpecificOutput"]["additionalContext"] == "some context"


def test_session_id_roundtrip(tmp_path, monkeypatch):
    sid_path = str(tmp_path / ".current-session-id")
    monkeypatch.setattr("src.hook_utils.SESSION_ID_PATH", sid_path)

    assert read_session_id() is None

    write_session_id("test-session-123")
    assert read_session_id() == "test-session-123"

    clear_session_id()
    assert read_session_id() is None
