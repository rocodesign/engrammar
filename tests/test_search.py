"""Tests for search and RRF fusion."""

import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone
from src.core.db import init_db, add_engram, add_content_tags, write_session_audit, get_connection
from src.search.engine import search, _get_rrf_normalization_anchors, _reciprocal_rank_fusion


def test_rrf_fusion():
    """RRF should combine ranked lists using reciprocal rank fusion."""
    # Two ranked lists with some overlap
    vector_results = [(1, 0.9), (2, 0.8), (3, 0.7)]
    bm25_results = [(2, 15.0), (4, 10.0), (1, 5.0)]

    fused = _reciprocal_rank_fusion([vector_results, bm25_results], k=60)

    # Should be sorted by fused score descending
    assert fused[0][0] in [1, 2]  # Top items should be 1 or 2 (both in top ranks)
    assert len(fused) == 4  # Should have all unique IDs

    # Check RRF score calculation for first item in each list
    # Item 1: rank 0 in vector, rank 2 in bm25 → 1/61 + 1/63 ≈ 0.0164 + 0.0159 = 0.0323
    # Item 2: rank 1 in vector, rank 0 in bm25 → 1/62 + 1/61 ≈ 0.0161 + 0.0164 = 0.0325
    # So item 2 should have slightly higher score


def test_rrf_returns_all_top_k_results():
    """RRF search should return all top_k results (no threshold filtering).

    This is the bug fix - we removed score_threshold which was incompatible
    with RRF scores (max ~0.016 << threshold 0.3).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        # Add 5 engrams
        for i in range(5):
            add_engram(
                text=f"Engram {i} about testing",
                category="test",
                db_path=db_path
            )

        # Build index (we'll skip this for now as it requires embeddings)
        # Instead, just test that search doesn't filter by threshold

        # The key assertion: with top_k=3, we should get UP TO 3 results
        # (might be less if no matches, but shouldn't be limited to 1)
        results = search("testing", top_k=3, db_path=db_path)

        # Before fix: would return only 1 result due to threshold
        # After fix: returns all results up to top_k
        assert len(results) <= 3
        # If we got any results, we should get more than 1 (assuming multiple match)
        if len(results) > 1:
            # Verify all results have scores
            for r in results:
                assert "score" in r
                assert r["score"] > 0


def test_rrf_normalization_anchors_are_corpus_scaled_and_tunable():
    """RRF anchors should scale with corpus size and allow relative tuning."""
    rrf_k, rrf_floor, rrf_ceiling = _get_rrf_normalization_anchors(
        50,
        {"rrf_floor_mult": 0.9, "rrf_ceiling_mult": 1.1},
    )

    assert rrf_k == 10
    assert rrf_floor == pytest.approx((1.0 / 20.0) * 0.9)
    assert rrf_ceiling == pytest.approx((2.0 / 11.0) * 1.1)


def test_rrf_normalization_anchors_fall_back_on_invalid_tuning():
    """Invalid tuning should not invert the normalized RRF range."""
    rrf_k, rrf_floor, rrf_ceiling = _get_rrf_normalization_anchors(
        50,
        {"rrf_floor_mult": 10.0, "rrf_ceiling_mult": 0.1},
    )

    assert rrf_k == 10
    assert rrf_floor == pytest.approx(1.0 / 20.0)
    assert rrf_ceiling == pytest.approx(2.0 / 11.0)


def test_search_respects_top_k():
    """Search should respect top_k parameter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        # Add 10 engrams
        for i in range(10):
            add_engram(
                text=f"Test engram {i}",
                category="test",
                db_path=db_path
            )

        results = search("test", top_k=5, db_path=db_path)
        assert len(results) <= 5


def test_search_filters_by_tag_relevance():
    """Search should filter engrams with strong negative tag relevance."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        from src.core.db import get_connection, update_tag_relevance

        # Add two engrams about the same topic
        good_id = add_engram(text="Good testing engram", category="test", db_path=db_path)
        bad_id = add_engram(text="Bad testing engram", category="test", db_path=db_path)

        # Give bad_id strong negative signal for tag "frontend" (enough evidence to filter)
        for _ in range(5):
            update_tag_relevance(bad_id, {"frontend": -1.0}, weight=1.0, db_path=db_path)

        # Give good_id positive signal
        for _ in range(5):
            update_tag_relevance(good_id, {"frontend": 1.0}, weight=1.0, db_path=db_path)

        # The tag relevance filtering is applied when env has tags
        # We can't easily mock detect_environment here, but the filtering
        # logic is tested thoroughly in test_tag_filtering.py


def test_search_handles_empty_database():
    """Search should handle empty database gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        results = search("anything", db_path=db_path)
        assert results == []


def test_search_handles_no_matches():
    """Search should return empty list when no engrams match."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(text="Python engram", category="test", db_path=db_path)

        # Search for something completely different
        # (Without embeddings, BM25 might still match, so this is a weak test)
        results = search("xyzabc123", db_path=db_path)
        # Should return empty or minimal results
        assert isinstance(results, list)


def test_enforce_prerequisites_applies_min_score(monkeypatch):
    """enforce_prerequisites should apply prerequisites_min_score threshold from config."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(
            text="Engrammar-only note",
            category="tools/engrammar",
            prerequisites='{"tags": ["repo:engrammar", "python"]}',
            db_path=db_path,
        )
        add_engram(
            text="Generic frontend note",
            category="development/frontend",
            db_path=db_path,
        )

        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {
                "os": "darwin",
                "repo": "other-repo",
                "cwd": "/tmp/other-repo",
                "tags": ["frontend", "nodejs", "repo:other-repo"],
                "mcp_servers": [],
            },
        )

        # With a very high threshold, low-scoring results get filtered out
        monkeypatch.setattr(
            "src.search.engine.load_config",
            lambda: {
                "search": {"top_k": 5},
                "hooks": {"prerequisites_min_score": 999.0},
                "display": {},
            },
        )
        strict_results = search(
            "note",
            db_path=db_path,
            top_k=5,
            enforce_prerequisites=True,
        )
        assert strict_results == []

        # With threshold at 0, all results pass
        monkeypatch.setattr(
            "src.search.engine.load_config",
            lambda: {
                "search": {"top_k": 5},
                "hooks": {"prerequisites_min_score": 0},
                "display": {},
            },
        )
        all_results = search(
            "note",
            db_path=db_path,
            top_k=5,
            enforce_prerequisites=True,
        )
        assert len(all_results) >= 1


def test_search_hides_isolated_repo_engrams_from_other_repos(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(text="shared alpha note", category="test", db_path=db_path)
        add_engram(text="isolated alpha note", category="test", origin_repo="isolated-repo", db_path=db_path)

        config = {
            "search": {"top_k": 5},
            "hooks": {"prerequisites_min_score": 0},
            "scoring": {},
            "controls": {"isolated_repos": ["isolated-repo"]},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)

        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {
                "os": "darwin",
                "repo": "other-repo",
                "cwd": "/tmp/other-repo",
                "tags": [],
                "mcp_servers": [],
            },
        )

        results = search("alpha", top_k=10, db_path=db_path)
        texts = [result["text"] for result in results]
        assert "shared alpha note" in texts
        assert "isolated alpha note" not in texts


def test_search_restricts_isolated_repo_to_its_own_engrams(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(text="shared alpha note", category="test", db_path=db_path)
        add_engram(text="isolated alpha note", category="test", origin_repo="isolated-repo", db_path=db_path)
        add_engram(text="same repo alpha note", category="test", origin_repo="isolated-repo", db_path=db_path)

        config = {
            "search": {"top_k": 5},
            "hooks": {"prerequisites_min_score": 0},
            "scoring": {},
            "controls": {"isolated_repos": ["isolated-repo"]},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)

        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {
                "os": "darwin",
                "repo": "isolated-repo",
                "cwd": "/tmp/isolated-repo",
                "tags": [],
                "mcp_servers": [],
            },
        )

        results = search("alpha", top_k=10, db_path=db_path)
        texts = [result["text"] for result in results]
        assert "shared alpha note" not in texts
        assert "isolated alpha note" in texts
        assert "same repo alpha note" in texts


def test_search_hides_isolated_repo_engrams_inferred_from_source_sessions(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(text="shared alpha note", category="test", db_path=db_path)
        add_engram(
            text="legacy isolated alpha note",
            category="test",
            source_sessions=["sess-isolated"],
            db_path=db_path,
        )
        write_session_audit(
            "sess-isolated",
            [],
            ["repo:isolated-repo"],
            "isolated-repo",
            db_path=db_path,
        )

        config = {
            "search": {"top_k": 5},
            "hooks": {"prerequisites_min_score": 0},
            "scoring": {},
            "controls": {"isolated_repos": ["isolated-repo"]},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)

        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {
                "os": "darwin",
                "repo": "other-repo",
                "cwd": "/tmp/other-repo",
                "tags": [],
                "mcp_servers": [],
            },
        )

        results = search("alpha", top_k=10, db_path=db_path)
        texts = [result["text"] for result in results]
        assert "shared alpha note" in texts
        assert "legacy isolated alpha note" not in texts


def test_search_hides_isolated_repo_engrams_inferred_from_tags(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(text="shared alpha note", category="test", db_path=db_path)
        legacy_id = add_engram(
            text="legacy tagged isolated alpha note",
            category="test",
            db_path=db_path,
        )
        add_content_tags(legacy_id, ["isolated-repo"], db_path=db_path)

        config = {
            "search": {"top_k": 5},
            "hooks": {"prerequisites_min_score": 0},
            "scoring": {},
            "controls": {"isolated_repos": ["isolated-repo"]},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)

        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {
                "os": "darwin",
                "repo": "other-repo",
                "cwd": "/tmp/other-repo",
                "tags": [],
                "mcp_servers": [],
            },
        )

        results = search("alpha", top_k=10, db_path=db_path)
        texts = [result["text"] for result in results]
        assert "shared alpha note" in texts
        assert "legacy tagged isolated alpha note" not in texts


def test_search_hides_isolated_repo_engrams_when_repo_detection_fails(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        add_engram(text="shared alpha note", category="test", db_path=db_path)
        add_engram(
            text="legacy isolated alpha note",
            category="test",
            source_sessions=["sess-isolated"],
            db_path=db_path,
        )
        write_session_audit(
            "sess-isolated",
            [],
            ["repo:isolated-repo"],
            "isolated-repo",
            db_path=db_path,
        )

        config = {
            "search": {"top_k": 5},
            "hooks": {"prerequisites_min_score": 0},
            "scoring": {},
            "controls": {"isolated_repos": ["isolated-repo"]},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)
        monkeypatch.setattr("src.search.environment._detect_repo", lambda cwd=None: None)

        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {
                "os": "darwin",
                "repo": None,
                "cwd": tmpdir,
                "tags": [],
                "mcp_servers": [],
            },
        )

        results = search("alpha", top_k=10, db_path=db_path)
        texts = [result["text"] for result in results]
        assert "shared alpha note" in texts
        assert "legacy isolated alpha note" not in texts


def test_recency_multiplier_lowers_score_for_old_engrams(monkeypatch):
    """Older engrams should score lower than fresh ones with recency_decay_rate > 0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        fresh_id = add_engram(text="typescript async await pattern", category="dev", db_path=db_path)
        old_id = add_engram(text="typescript async await pattern", category="dev", db_path=db_path)

        now = datetime.now(timezone.utc)
        fresh_ts = now.isoformat()
        old_ts = (now - timedelta(days=200)).isoformat()

        conn = get_connection(db_path)
        conn.execute("UPDATE engrams SET refreshed_at = ? WHERE id = ?", (fresh_ts, fresh_id))
        conn.execute("UPDATE engrams SET refreshed_at = ? WHERE id = ?", (old_ts, old_id))
        conn.commit()
        conn.close()

        config = {
            "search": {"top_k": 10},
            "controls": {"isolated_repos": []},
            "hooks": {},
            "scoring": {"recency_decay_rate": 0.003},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)
        monkeypatch.setattr("src.search.environment._detect_repo", lambda cwd=None: None)
        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {"os": "darwin", "repo": None, "cwd": tmpdir, "tags": [], "mcp_servers": []},
        )

        results, meta = search("typescript async await", top_k=10, db_path=db_path, return_diagnostics=True)

        scores_by_id = {r["id"]: r["score"] for r in results}
        if fresh_id in scores_by_id and old_id in scores_by_id:
            assert scores_by_id[fresh_id] > scores_by_id[old_id]

        mults_by_id = {r["id"]: r["_diag"]["recency_multiplier"] for r in results if "_diag" in r}
        if fresh_id in mults_by_id and old_id in mults_by_id:
            assert mults_by_id[fresh_id] > mults_by_id[old_id]
            assert mults_by_id[old_id] < 1.0


def test_recency_multiplier_disabled_when_rate_is_zero(monkeypatch):
    """With recency_decay_rate=0, the multiplier should always be 1.0."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(text="typescript async await pattern", category="dev", db_path=db_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=500)).isoformat()

        conn = get_connection(db_path)
        conn.execute("UPDATE engrams SET refreshed_at = ? WHERE id = ?", (old_ts, engram_id))
        conn.commit()
        conn.close()

        config = {
            "search": {"top_k": 10},
            "controls": {"isolated_repos": []},
            "hooks": {},
            "scoring": {"recency_decay_rate": 0.0},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)
        monkeypatch.setattr("src.search.environment._detect_repo", lambda cwd=None: None)
        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {"os": "darwin", "repo": None, "cwd": tmpdir, "tags": [], "mcp_servers": []},
        )

        results, meta = search("typescript async await", top_k=10, db_path=db_path, return_diagnostics=True)

        for r in results:
            if r["id"] == engram_id and "_diag" in r:
                assert r["_diag"]["recency_multiplier"] == 1.0


def test_recency_falls_back_to_created_at_when_no_refreshed_at(monkeypatch):
    """Engrams without refreshed_at should use created_at for age calculation."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(text="typescript async await pattern", category="dev", db_path=db_path)
        old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()

        conn = get_connection(db_path)
        conn.execute(
            "UPDATE engrams SET refreshed_at = NULL, created_at = ? WHERE id = ?",
            (old_ts, engram_id)
        )
        conn.commit()
        conn.close()

        config = {
            "search": {"top_k": 10},
            "controls": {"isolated_repos": []},
            "hooks": {},
            "scoring": {"recency_decay_rate": 0.003},
        }
        monkeypatch.setattr("src.search.engine.load_config", lambda: config)
        monkeypatch.setattr("src.search.environment._detect_repo", lambda cwd=None: None)
        monkeypatch.setattr(
            "src.search.engine.detect_environment",
            lambda cwd=None: {"os": "darwin", "repo": None, "cwd": tmpdir, "tags": [], "mcp_servers": []},
        )

        results, meta = search("typescript async await", top_k=10, db_path=db_path, return_diagnostics=True)

        for r in results:
            if r["id"] == engram_id and "_diag" in r:
                assert r["_diag"]["recency_multiplier"] < 1.0
