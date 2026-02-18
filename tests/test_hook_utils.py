"""Tests for shared hook utilities."""

import json
from io import StringIO
from unittest.mock import patch

from src.hook_utils import (
    format_lessons_block,
    make_hook_output,
    parse_hook_input,
    read_session_id,
    write_session_id,
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


def test_parse_hook_input_valid_json():
    payload = {"session_id": "abc-123", "transcript_path": "/tmp/transcript.jsonl"}
    with patch("sys.stdin", StringIO(json.dumps(payload))):
        result = parse_hook_input()
    assert result["session_id"] == "abc-123"
    assert result["transcript_path"] == "/tmp/transcript.jsonl"


def test_parse_hook_input_empty_stdin():
    with patch("sys.stdin", StringIO("")):
        result = parse_hook_input()
    assert result == {}


def test_parse_hook_input_invalid_json():
    with patch("sys.stdin", StringIO("not json")):
        result = parse_hook_input()
    assert result == {}


def test_write_and_read_session_id(monkeypatch, tmp_path):
    monkeypatch.setattr("src.hook_utils.ENGRAMMAR_HOME", str(tmp_path))
    session_id = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    write_session_id(session_id)
    assert read_session_id() == session_id


def test_read_session_id_no_file(monkeypatch, tmp_path):
    monkeypatch.setattr("src.hook_utils.ENGRAMMAR_HOME", str(tmp_path))
    assert read_session_id() is None


def test_read_session_id_empty_file(monkeypatch, tmp_path):
    monkeypatch.setattr("src.hook_utils.ENGRAMMAR_HOME", str(tmp_path))
    (tmp_path / ".current_session_id").write_text("")
    assert read_session_id() is None
