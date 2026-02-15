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
)


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


def _setup_session(test_db, session_id="sess-1"):
    """Helper: create a lesson + audit record."""
    lid = add_lesson(text="Never use inline styles", category="development/frontend", db_path=test_db)
    write_session_audit(session_id, [lid], ["frontend", "react"], "app-repo", db_path=test_db)
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
