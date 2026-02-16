"""Tests for hook entry points."""

import json
import sys

import pytest
from io import StringIO
from unittest.mock import patch

from src.db import (
    add_lesson,
    get_connection,
    record_shown_lesson,
    get_shown_lesson_ids,
)

pytestmark = pytest.mark.usefixtures("mock_build_index")

# Default config used across hook tests
_DEFAULT_CONFIG = {
    "hooks": {
        "prompt_enabled": True,
        "tool_use_enabled": True,
        "skip_tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    },
    "display": {
        "max_lessons_per_prompt": 3,
        "max_lessons_per_tool": 2,
        "show_scores": False,
        "show_categories": True,
    },
    "search": {"top_k": 3},
}


def _set_stdin(monkeypatch, data):
    """Set stdin to JSON-encoded data."""
    monkeypatch.setattr("sys.stdin", StringIO(json.dumps(data)))


# ---------- Session Start ----------


class TestSessionStart:
    def test_injects_pinned(self, test_db, monkeypatch, capsys):
        lesson_id = add_lesson(text="Always do X", category="rules", db_path=test_db)
        conn = get_connection(test_db)
        conn.execute("UPDATE lessons SET pinned = 1 WHERE id = ?", (lesson_id,))
        conn.commit()
        conn.close()

        _set_stdin(monkeypatch, {"session_id": "sess-1"})
        with patch("src.client.send_request"), \
             patch("src.environment.detect_environment", return_value={
                 "os": "darwin", "repo": "test", "cwd": "/tmp",
                 "tags": [], "mcp_servers": [],
             }), \
             patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_session_start import main
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "ENGRAMMAR_V1" in ctx
        assert "Always do X" in ctx

    def test_internal_run_guard(self, test_db, monkeypatch, capsys):
        monkeypatch.setenv("ENGRAMMAR_INTERNAL_RUN", "1")
        _set_stdin(monkeypatch, {"session_id": "sess-1"})
        from hooks.on_session_start import main
        main()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_structural_prereq_filter(self, test_db, monkeypatch, capsys):
        """Pinned lesson with non-matching structural prereqs is filtered."""
        lesson_id = add_lesson(
            text="repo-specific",
            category="general",
            prerequisites=json.dumps({"repos": ["other-repo"]}),
            db_path=test_db,
        )
        conn = get_connection(test_db)
        conn.execute("UPDATE lessons SET pinned = 1 WHERE id = ?", (lesson_id,))
        conn.commit()
        conn.close()

        _set_stdin(monkeypatch, {"session_id": "sess-1"})
        with patch("src.client.send_request"), \
             patch("src.environment.detect_environment", return_value={
                 "os": "darwin", "repo": "my-repo", "cwd": "/tmp",
                 "tags": [], "mcp_servers": [],
             }), \
             patch("src.environment.check_structural_prerequisites", return_value=False), \
             patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_session_start import main
            main()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_tag_relevance_filter(self, test_db, monkeypatch, capsys):
        """Pinned lesson with strong negative tag relevance is filtered."""
        lesson_id = add_lesson(text="bad match", category="general", db_path=test_db)
        conn = get_connection(test_db)
        conn.execute("UPDATE lessons SET pinned = 1 WHERE id = ?", (lesson_id,))
        conn.commit()
        conn.close()

        _set_stdin(monkeypatch, {"session_id": "sess-1"})
        with patch("src.client.send_request"), \
             patch("src.environment.detect_environment", return_value={
                 "os": "darwin", "repo": "test", "cwd": "/tmp",
                 "tags": ["python"], "mcp_servers": [],
             }), \
             patch("src.db.get_tag_relevance_with_evidence", return_value=(-0.5, 5)), \
             patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_session_start import main
            main()

        captured = capsys.readouterr()
        assert captured.out == ""


# ---------- Prompt Hook ----------


class TestPrompt:
    def test_returns_lessons(self, test_db, monkeypatch, capsys):
        _set_stdin(monkeypatch, {"prompt": "How to use react hooks?", "session_id": "sess-1"})
        with patch("src.client.send_request", return_value={
                 "results": [{"id": 1, "text": "Use hooks correctly", "category": "dev"}],
             }), \
             patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_prompt import main
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        ctx = output["hookSpecificOutput"]["additionalContext"]
        assert "ENGRAMMAR_V1" in ctx
        assert "Use hooks correctly" in ctx

    def test_disabled_config(self, test_db, monkeypatch, capsys):
        disabled = {
            **_DEFAULT_CONFIG,
            "hooks": {**_DEFAULT_CONFIG["hooks"], "prompt_enabled": False},
        }
        _set_stdin(monkeypatch, {"prompt": "test query", "session_id": "sess-1"})
        with patch("src.config.load_config", return_value=disabled):
            from hooks.on_prompt import main
            main()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_short_prompt_ignored(self, test_db, monkeypatch, capsys):
        _set_stdin(monkeypatch, {"prompt": "hi", "session_id": "sess-1"})
        from hooks.on_prompt import main
        main()

        captured = capsys.readouterr()
        assert captured.out == ""

    def test_dedup_shown(self, test_db, monkeypatch, capsys):
        """Already-shown lesson is filtered out."""
        record_shown_lesson("sess-1", 42, "SessionStart", db_path=test_db)

        _set_stdin(monkeypatch, {"prompt": "show me something", "session_id": "sess-1"})
        with patch("src.client.send_request", return_value={
                 "results": [{"id": 42, "text": "Already shown", "category": "dev"}],
             }), \
             patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_prompt import main
            main()

        captured = capsys.readouterr()
        assert captured.out == ""


# ---------- Tool Use Hook ----------


class TestToolUse:
    def test_returns_lessons(self, test_db, monkeypatch, capsys):
        _set_stdin(monkeypatch, {
            "tool_name": "Bash",
            "tool_input": {"command": "npm test"},
            "session_id": "sess-1",
        })
        with patch("src.client.send_request", return_value={
                 "results": [{"id": 1, "text": "Run tests with --verbose", "category": "dev"}],
             }), \
             patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_tool_use import main
            main()

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "Run tests with --verbose" in output["hookSpecificOutput"]["additionalContext"]

    def test_skip_tool(self, test_db, monkeypatch, capsys):
        _set_stdin(monkeypatch, {
            "tool_name": "Read",
            "tool_input": {"path": "/tmp/file"},
            "session_id": "sess-1",
        })
        with patch("src.config.load_config", return_value=_DEFAULT_CONFIG):
            from hooks.on_tool_use import main
            main()

        captured = capsys.readouterr()
        assert captured.out == ""


# ---------- Session End ----------


class TestSessionEnd:
    def test_writes_audit_clears_shown(self, test_db, monkeypatch, capsys):
        lesson_id = add_lesson(text="shown lesson", category="general", db_path=test_db)
        record_shown_lesson("sess-1", lesson_id, "UserPromptSubmit", db_path=test_db)

        _set_stdin(monkeypatch, {
            "session_id": "sess-1",
            "transcript_path": "/tmp/transcript.jsonl",
        })
        with patch("src.environment.detect_environment", return_value={
                 "os": "darwin", "repo": "test", "cwd": "/tmp",
                 "tags": ["python"], "mcp_servers": [],
             }):
            from hooks.on_session_end import main
            main()

        # Shown lessons should be cleared
        shown = get_shown_lesson_ids("sess-1", db_path=test_db)
        assert len(shown) == 0

        # Audit record should exist
        conn = get_connection(test_db)
        audit = conn.execute(
            "SELECT * FROM session_audit WHERE session_id = ?", ("sess-1",)
        ).fetchone()
        conn.close()
        assert audit is not None
        assert lesson_id in json.loads(audit["shown_lesson_ids"])

    def test_no_session_id(self, test_db, monkeypatch, capsys):
        _set_stdin(monkeypatch, {})
        from hooks.on_session_end import main
        main()

        captured = capsys.readouterr()
        assert captured.out == ""
