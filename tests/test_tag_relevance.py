"""Tests for tag relevance scoring: EMA math, clamping, weighted updates, pin/unpin."""

import json
import tempfile
from pathlib import Path

import pytest

from src.db import (
    init_db,
    add_lesson,
    get_connection,
    update_tag_relevance,
    get_tag_relevance_scores,
    get_avg_tag_relevance,
    check_and_apply_pin_decisions,
    EMA_ALPHA,
    SCORE_CLAMP,
    MIN_EVIDENCE_FOR_PIN,
    PIN_THRESHOLD,
    UNPIN_THRESHOLD,
)


@pytest.fixture
def test_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


class TestEMAMath:
    def test_first_update_applies_alpha(self, test_db):
        """First update should use EMA_ALPHA * weight * raw_score."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        update_tag_relevance(lid, {"typescript": 1.0}, weight=1.0, db_path=test_db)

        scores = get_tag_relevance_scores(lid, db_path=test_db)
        assert abs(scores["typescript"] - EMA_ALPHA * 1.0) < 0.001

    def test_second_update_ema(self, test_db):
        """Second update should blend with existing score."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        update_tag_relevance(lid, {"ts": 1.0}, weight=1.0, db_path=test_db)
        first_score = get_tag_relevance_scores(lid, db_path=test_db)["ts"]

        update_tag_relevance(lid, {"ts": 1.0}, weight=1.0, db_path=test_db)
        second_score = get_tag_relevance_scores(lid, db_path=test_db)["ts"]

        expected = first_score * (1 - EMA_ALPHA) + 1.0 * EMA_ALPHA * 1.0
        assert abs(second_score - expected) < 0.001

    def test_weighted_update(self, test_db):
        """Weight=2.0 should produce larger score change."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        update_tag_relevance(lid, {"ts": 1.0}, weight=2.0, db_path=test_db)
        scores = get_tag_relevance_scores(lid, db_path=test_db)
        assert abs(scores["ts"] - EMA_ALPHA * 1.0 * 2.0) < 0.001

    def test_negative_scores(self, test_db):
        """Negative raw scores should produce negative relevance."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        update_tag_relevance(lid, {"ts": -1.0}, weight=1.0, db_path=test_db)

        scores = get_tag_relevance_scores(lid, db_path=test_db)
        assert scores["ts"] < 0


class TestClamping:
    def test_positive_clamp(self, test_db):
        """Score should never exceed SCORE_CLAMP[1]."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        # Spam positive updates to push past clamp
        for _ in range(100):
            update_tag_relevance(lid, {"ts": 1.0}, weight=2.0, db_path=test_db)

        scores = get_tag_relevance_scores(lid, db_path=test_db)
        assert scores["ts"] <= SCORE_CLAMP[1]

    def test_negative_clamp(self, test_db):
        """Score should never go below SCORE_CLAMP[0]."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        for _ in range(100):
            update_tag_relevance(lid, {"ts": -1.0}, weight=2.0, db_path=test_db)

        scores = get_tag_relevance_scores(lid, db_path=test_db)
        assert scores["ts"] >= SCORE_CLAMP[0]


class TestAvgTagRelevance:
    def test_avg_with_multiple_tags(self, test_db):
        """Should average across multiple tags."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        update_tag_relevance(lid, {"ts": 1.0, "react": -1.0}, weight=1.0, db_path=test_db)

        avg = get_avg_tag_relevance(lid, ["ts", "react"], db_path=test_db)
        # First update: ts = 0.3, react = -0.3, avg = 0.0
        assert abs(avg) < 0.001

    def test_avg_with_no_scores(self, test_db):
        """Should return 0.0 when no scores exist."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        avg = get_avg_tag_relevance(lid, ["ts"], db_path=test_db)
        assert avg == 0.0

    def test_avg_with_empty_tags(self, test_db):
        """Should return 0.0 for empty tag list."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        avg = get_avg_tag_relevance(lid, [], db_path=test_db)
        assert avg == 0.0


class TestEvalCounters:
    def test_positive_eval_counter(self, test_db):
        """Positive scores should increment positive_evals."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        update_tag_relevance(lid, {"ts": 0.5}, weight=1.0, db_path=test_db)
        update_tag_relevance(lid, {"ts": 0.8}, weight=1.0, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT positive_evals, negative_evals FROM lesson_tag_relevance WHERE lesson_id = ? AND tag = 'ts'",
            (lid,),
        ).fetchone()
        conn.close()

        assert row["positive_evals"] == 2
        assert row["negative_evals"] == 0

    def test_negative_eval_counter(self, test_db):
        """Negative scores should increment negative_evals."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)
        update_tag_relevance(lid, {"ts": -0.5}, weight=1.0, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT positive_evals, negative_evals FROM lesson_tag_relevance WHERE lesson_id = ? AND tag = 'ts'",
            (lid,),
        ).fetchone()
        conn.close()

        assert row["positive_evals"] == 0
        assert row["negative_evals"] == 1


class TestAutoPinUnpin:
    def test_auto_pin_with_high_score(self, test_db):
        """Should auto-pin when avg score > PIN_THRESHOLD with enough evidence."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        # Build up enough positive evals to exceed threshold
        for _ in range(MIN_EVIDENCE_FOR_PIN + 2):
            update_tag_relevance(lid, {"ts": 1.0}, weight=2.0, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute("SELECT pinned, prerequisites FROM lessons WHERE id = ?", (lid,)).fetchone()
        conn.close()

        assert row["pinned"] == 1
        prereqs = json.loads(row["prerequisites"])
        assert prereqs.get("auto_pinned") is True

    def test_auto_unpin_with_low_score(self, test_db):
        """Should auto-unpin auto-pinned lessons when score drops below UNPIN_THRESHOLD."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        # First auto-pin it
        conn = get_connection(test_db)
        conn.execute(
            "UPDATE lessons SET pinned = 1, prerequisites = ? WHERE id = ?",
            (json.dumps({"auto_pinned": True}), lid),
        )
        conn.commit()
        conn.close()

        # Add enough negative evals
        for _ in range(MIN_EVIDENCE_FOR_PIN + 2):
            update_tag_relevance(lid, {"ts": -1.0}, weight=2.0, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute("SELECT pinned FROM lessons WHERE id = ?", (lid,)).fetchone()
        conn.close()

        assert row["pinned"] == 0

    def test_manual_pin_protection(self, test_db):
        """Should NOT auto-unpin manually pinned lessons."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        # Manually pin (no auto_pinned flag)
        conn = get_connection(test_db)
        conn.execute("UPDATE lessons SET pinned = 1 WHERE id = ?", (lid,))
        conn.commit()
        conn.close()

        # Add negative evals
        for _ in range(MIN_EVIDENCE_FOR_PIN + 2):
            update_tag_relevance(lid, {"ts": -1.0}, weight=2.0, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute("SELECT pinned FROM lessons WHERE id = ?", (lid,)).fetchone()
        conn.close()

        # Still pinned — manual pins are protected
        assert row["pinned"] == 1

    def test_no_pin_without_enough_evidence(self, test_db):
        """Should not pin with fewer than MIN_EVIDENCE_FOR_PIN evaluations."""
        lid = add_lesson(text="Test", category="test", db_path=test_db)

        # Only a few positive evals (below MIN_EVIDENCE_FOR_PIN)
        for _ in range(2):
            update_tag_relevance(lid, {"ts": 1.0}, weight=2.0, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute("SELECT pinned FROM lessons WHERE id = ?", (lid,)).fetchone()
        conn.close()

        assert row["pinned"] == 0
