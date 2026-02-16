"""Tests for evaluation pipeline."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.db import (
    init_db,
    add_lesson,
    write_session_audit,
    get_connection,
)
from src.evaluator import (
    run_evaluation_for_session,
    run_pending_evaluations,
    _mark_session_status,
    _read_transcript_file,
)


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


def _setup_session(test_db, session_id="sess-1", transcript_path=None):
    """Helper: create a lesson + audit record."""
    lid = add_lesson(text="Never use inline styles", category="development/frontend", db_path=test_db)
    write_session_audit(session_id, [lid], ["frontend", "react"], "app-repo",
                        transcript_path=transcript_path, db_path=test_db)
    return lid


class TestRunEvaluation:
    def test_completed_on_success(self, test_db):
        """Should mark session as completed when evaluation succeeds."""
        lid = _setup_session(test_db)

        mock_result = [{"lesson_id": lid, "tag_scores": {"frontend": 0.8, "react": 0.5}}]
        with patch("src.evaluator._call_claude_for_evaluation", return_value=mock_result):
            success = run_evaluation_for_session("sess-1", db_path=test_db)

        assert success is True

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT status FROM processed_relevance_sessions WHERE session_id = ?",
            ("sess-1",),
        ).fetchone()
        conn.close()
        assert row["status"] == "completed"

    def test_failed_on_empty_response(self, test_db):
        """Should mark session as failed when claude returns nothing."""
        _setup_session(test_db)

        with patch("src.evaluator._call_claude_for_evaluation", return_value=[]):
            success = run_evaluation_for_session("sess-1", db_path=test_db)

        assert success is False

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT status, retry_count FROM processed_relevance_sessions WHERE session_id = ?",
            ("sess-1",),
        ).fetchone()
        conn.close()
        assert row["status"] == "failed"
        assert row["retry_count"] == 1

    def test_missing_audit_returns_false(self, test_db):
        """Should return False when no audit record exists."""
        success = run_evaluation_for_session("nonexistent", db_path=test_db)
        assert success is False

    def test_empty_shown_returns_true(self, test_db):
        """Should return True (success) when no lessons were shown."""
        write_session_audit("sess-empty", [], ["test"], "repo", db_path=test_db)
        success = run_evaluation_for_session("sess-empty", db_path=test_db)
        assert success is True

    def test_uses_stored_transcript_path(self, test_db, tmp_path):
        """Should read transcript from stored path when available."""
        # Create a fake transcript file
        transcript_file = tmp_path / "session.jsonl"
        transcript_file.write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": "hello"}}) + "\n"
            + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "hi there"}}) + "\n"
        )

        lid = _setup_session(test_db, transcript_path=str(transcript_file))

        mock_result = [{"lesson_id": lid, "tag_scores": {"frontend": 0.9}}]
        with patch("src.evaluator._call_claude_for_evaluation", return_value=mock_result) as mock_call:
            with patch("src.evaluator._find_transcript_excerpt") as mock_glob:
                success = run_evaluation_for_session("sess-1", db_path=test_db)

        assert success is True
        # Should NOT have fallen back to glob search
        mock_glob.assert_not_called()
        # Transcript should have been passed to claude
        call_args = mock_call.call_args
        transcript_arg = call_args[0][4] if len(call_args[0]) > 4 else call_args[1].get("transcript", "")
        assert "hello" in transcript_arg or "hi there" in transcript_arg


class TestReadTranscriptFile:
    def test_reads_messages(self, tmp_path):
        """Should extract user and assistant messages."""
        transcript_file = tmp_path / "test.jsonl"
        transcript_file.write_text(
            json.dumps({"type": "user", "message": {"role": "user", "content": "What is Python?"}}) + "\n"
            + json.dumps({"type": "assistant", "message": {"role": "assistant", "content": "A programming language."}}) + "\n"
        )

        result = _read_transcript_file(str(transcript_file))
        assert "What is Python?" in result
        assert "A programming language." in result

    def test_returns_empty_for_missing_file(self):
        """Should return empty string for nonexistent file."""
        result = _read_transcript_file("/nonexistent/path.jsonl")
        assert result == ""

    def test_truncates_to_max_chars(self, tmp_path):
        """Should truncate to max_chars."""
        transcript_file = tmp_path / "big.jsonl"
        lines = []
        for i in range(100):
            lines.append(json.dumps({"type": "user", "message": {"role": "user", "content": f"Message {i} " + "x" * 200}}))
        transcript_file.write_text("\n".join(lines))

        result = _read_transcript_file(str(transcript_file), max_chars=500)
        assert len(result) <= 500


class TestRetryBehavior:
    def test_retry_increments(self, test_db):
        """Retries should increment retry_count."""
        _setup_session(test_db)

        with patch("src.evaluator._call_claude_for_evaluation", return_value=[]):
            run_evaluation_for_session("sess-1", db_path=test_db)
            run_evaluation_for_session("sess-1", db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT retry_count FROM processed_relevance_sessions WHERE session_id = ?",
            ("sess-1",),
        ).fetchone()
        conn.close()
        assert row["retry_count"] == 2

    def test_skip_at_max_retries(self, test_db):
        """Sessions at retry_count >= 3 should not appear in pending."""
        _setup_session(test_db)

        # Manually set retry count to 3
        conn = get_connection(test_db)
        conn.execute(
            "INSERT INTO processed_relevance_sessions (session_id, status, retry_count) VALUES (?, 'failed', 3)",
            ("sess-1",),
        )
        conn.commit()
        conn.close()

        # Should process 0 sessions
        with patch("src.evaluator._call_claude_for_evaluation") as mock_call:
            results = run_pending_evaluations(db_path=test_db)

        mock_call.assert_not_called()
        assert results["total"] == 0


class TestPendingEvaluations:
    def test_batch_processing(self, test_db):
        """Should process multiple sessions."""
        for i in range(3):
            lid = add_lesson(text=f"Lesson {i}", category="test", db_path=test_db)
            write_session_audit(f"sess-{i}", [lid], ["test"], "repo", db_path=test_db)

        mock_result = [{"lesson_id": 1, "tag_scores": {"test": 0.5}}]
        with patch("src.evaluator._call_claude_for_evaluation", return_value=mock_result):
            results = run_pending_evaluations(limit=5, db_path=test_db)

        assert results["total"] == 3
        assert results["completed"] == 3
