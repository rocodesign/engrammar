"""Tests for LLM-assisted engram deduplication."""

import json
import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from src.db import (
    init_db, add_engram, get_connection, get_all_active_engrams,
    get_unverified_engrams, get_verified_engrams, mark_dedup_verified,
    record_dedup_error, merge_engram_group, write_session_audit,
    log_hook_event, record_shown_engram, update_tag_relevance,
    update_match_stats,
)
from src.dedup import (
    find_candidates_for_unverified,
    find_candidates_bootstrap,
    build_batches,
    validate_dedup_response,
    should_bootstrap,
    select_survivor,
    run_dedup,
    _engram_to_payload,
    BOOTSTRAP_VERIFIED_THRESHOLD,
)


# --- Fixtures ---


@pytest.fixture
def db_path():
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "test.db")
        init_db(path)
        yield path


def _add_engram(db_path, text, category="general", verified=False, occurrence_count=1,
                prerequisites=None, source_sessions=None):
    """Helper to add an engram and optionally mark it verified."""
    eid = add_engram(
        text=text, category=category, occurrence_count=occurrence_count,
        prerequisites=prerequisites, source_sessions=source_sessions,
        db_path=db_path,
    )
    if verified:
        mark_dedup_verified(eid, db_path=db_path)
    return eid


def _make_batch(engrams_list, edges, unverified_ids):
    """Helper to construct a batch dict."""
    return {
        "engrams": engrams_list,
        "candidate_edges": edges,
        "unverified_ids": set(unverified_ids),
    }


# =============================================================================
# Unit tests (no LLM, mock call_dedup_llm)
# =============================================================================


class TestFindCandidates:
    """Tests for candidate finding."""

    def test_find_candidates_verified_only(self, db_path):
        """Verify that find_candidates_for_unverified only returns verified engrams."""
        v1 = _add_engram(db_path, "No migration code for dev projects", verified=True)
        v2 = _add_engram(db_path, "Always write unit tests", verified=True)
        u1 = _add_engram(db_path, "Skip compat layers in dev-only repos")
        u2 = _add_engram(db_path, "Another unrelated engram about CSS styling")

        unverified = get_unverified_engrams(db_path=db_path)
        verified = get_verified_engrams(db_path=db_path)

        candidates = find_candidates_for_unverified(unverified, verified, min_sim=0.0, top_k=8)

        # All candidates should be verified IDs only
        for uid, cands in candidates.items():
            for cid, score in cands:
                assert cid in {v1, v2}, f"Candidate {cid} is not verified"

    def test_find_candidates_respects_min_sim(self, db_path):
        """Verify threshold filtering works."""
        v1 = _add_engram(db_path, "No migration code for dev projects", verified=True)
        u1 = _add_engram(db_path, "Something completely different about cloud infrastructure")

        unverified = get_unverified_engrams(db_path=db_path)
        verified = get_verified_engrams(db_path=db_path)

        # With a very high threshold, should find no candidates
        candidates = find_candidates_for_unverified(unverified, verified, min_sim=0.99, top_k=8)
        assert candidates[u1] == []


class TestBuildBatches:

    def test_build_batches_char_budget(self):
        """Verify batches split at char budget."""
        # Create engrams with known text lengths
        engrams_by_id = {
            1: {"id": 1, "text": "A" * 100, "category": "test", "occurrence_count": 1, "prerequisites": None},
            2: {"id": 2, "text": "B" * 100, "category": "test", "occurrence_count": 1, "prerequisites": None},
            3: {"id": 3, "text": "C" * 100, "category": "test", "occurrence_count": 1, "prerequisites": None},
            10: {"id": 10, "text": "V" * 100, "category": "test", "occurrence_count": 1, "prerequisites": None},
            11: {"id": 11, "text": "W" * 100, "category": "test", "occurrence_count": 1, "prerequisites": None},
        }
        candidate_map = {
            1: [(10, 0.8)],
            2: [(11, 0.7)],
            3: [(10, 0.6)],
        }
        unverified_ids = {1, 2, 3}

        # Budget of 250 chars: each pair is ~200 chars (unverified + candidate)
        batches = build_batches(candidate_map, engrams_by_id, unverified_ids, char_budget=250)

        # Should produce multiple batches
        assert len(batches) >= 2

        # All unverified IDs should be covered
        all_unverified = set()
        for batch in batches:
            all_unverified.update(batch["unverified_ids"])
        assert all_unverified == unverified_ids

    def test_build_batches_shared_candidates(self):
        """Verify deduplication of shared verified candidates."""
        engrams_by_id = {
            1: {"id": 1, "text": "text1", "category": "test", "occurrence_count": 1, "prerequisites": None},
            2: {"id": 2, "text": "text2", "category": "test", "occurrence_count": 1, "prerequisites": None},
            10: {"id": 10, "text": "verified", "category": "test", "occurrence_count": 1, "prerequisites": None},
        }
        # Both unverified share the same candidate
        candidate_map = {
            1: [(10, 0.8)],
            2: [(10, 0.7)],
        }
        unverified_ids = {1, 2}

        batches = build_batches(candidate_map, engrams_by_id, unverified_ids, char_budget=10000)

        # Should produce single batch with shared candidate
        assert len(batches) == 1
        # Candidate 10 should appear once in engrams list
        ids_in_batch = [e["id"] for e in batches[0]["engrams"]]
        assert ids_in_batch.count(10) == 1
        # Both edges should be present
        assert len(batches[0]["candidate_edges"]) == 2


class TestValidateResponse:

    def _make_valid_response(self):
        return {
            "groups": [
                {
                    "ids": [1, 10],
                    "canonical_text": "Merged text.",
                    "confidence": 0.9,
                    "reason": "Same rule."
                }
            ],
            "no_match_ids": [2],
            "notes": [],
        }

    def _make_batch(self):
        return _make_batch(
            engrams_list=[
                {"id": 1, "status": "unverified"},
                {"id": 2, "status": "unverified"},
                {"id": 10, "status": "verified"},
            ],
            edges=[{"source_id": 1, "target_id": 10, "similarity": 0.85}],
            unverified_ids={1, 2},
        )

    def test_validate_response_valid(self):
        """Well-formed response passes validation."""
        response = self._make_valid_response()
        batch = self._make_batch()
        valid_groups, errors = validate_dedup_response(response, batch, mode="incremental")

        assert len(valid_groups) == 1
        assert len(errors) == 0

    def test_validate_response_missing_ids(self):
        """Reject if unverified IDs are not accounted for."""
        response = {
            "groups": [
                {"ids": [1, 10], "canonical_text": "text", "confidence": 0.9, "reason": "test"}
            ],
            "no_match_ids": [],  # Missing ID 2
            "notes": [],
        }
        batch = self._make_batch()
        valid_groups, errors = validate_dedup_response(response, batch, mode="incremental")

        assert any("not accounted" in e for e in errors)

    def test_validate_response_duplicate_ids(self):
        """Reject if ID appears in multiple groups."""
        response = {
            "groups": [
                {"ids": [1, 10], "canonical_text": "text", "confidence": 0.9, "reason": "test"},
                {"ids": [1, 2], "canonical_text": "text2", "confidence": 0.9, "reason": "test2"},
            ],
            "no_match_ids": [],
            "notes": [],
        }
        batch = self._make_batch()
        valid_groups, errors = validate_dedup_response(response, batch, mode="incremental")

        assert any("already in another group" in e for e in errors)

    def test_validate_response_no_unverified(self):
        """Reject incremental group without unverified ID."""
        response = {
            "groups": [
                {"ids": [10, 11], "canonical_text": "text", "confidence": 0.9, "reason": "test"},
            ],
            "no_match_ids": [1, 2],
            "notes": [],
        }
        batch = _make_batch(
            engrams_list=[
                {"id": 1, "status": "unverified"},
                {"id": 2, "status": "unverified"},
                {"id": 10, "status": "verified"},
                {"id": 11, "status": "verified"},
            ],
            edges=[],
            unverified_ids={1, 2},
        )
        valid_groups, errors = validate_dedup_response(response, batch, mode="incremental")

        assert any("no unverified ID" in e for e in errors)

    def test_validate_response_malformed_json(self):
        """Graceful failure on non-dict response."""
        valid_groups, errors = validate_dedup_response("not a dict", {}, mode="incremental")
        assert valid_groups == []
        assert len(errors) > 0


class TestShouldBootstrap:

    def test_should_bootstrap_empty_pool(self, db_path):
        """Returns True when no verified engrams exist."""
        _add_engram(db_path, "unverified engram 1")
        _add_engram(db_path, "unverified engram 2")

        assert should_bootstrap(db_path=db_path) is True

    def test_should_bootstrap_below_threshold(self, db_path):
        """Returns True when verified pool is below threshold."""
        for i in range(BOOTSTRAP_VERIFIED_THRESHOLD - 1):
            _add_engram(db_path, f"verified {i}", verified=True)

        assert should_bootstrap(db_path=db_path) is True

    def test_should_not_bootstrap_above_threshold(self, db_path):
        """Returns False when verified pool is at or above threshold."""
        for i in range(BOOTSTRAP_VERIFIED_THRESHOLD):
            _add_engram(db_path, f"verified {i}", verified=True)

        assert should_bootstrap(db_path=db_path) is False


# =============================================================================
# Merge tests (test DB, mock LLM)
# =============================================================================


class TestMerge:

    def test_merge_updates_survivor_text(self, db_path):
        """Canonical text is applied to survivor."""
        e1 = _add_engram(db_path, "Old text one")
        e2 = _add_engram(db_path, "Old text two")

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "New canonical text", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute("SELECT text FROM engrams WHERE id = ?", (e1,)).fetchone()
        conn.close()
        assert row["text"] == "New canonical text"

    def test_merge_combines_occurrence_count(self, db_path):
        """Occurrence counts are summed."""
        e1 = _add_engram(db_path, "Text one", occurrence_count=3)
        e2 = _add_engram(db_path, "Text two", occurrence_count=5)

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute("SELECT occurrence_count FROM engrams WHERE id = ?", (e1,)).fetchone()
        conn.close()
        assert row["occurrence_count"] == 8

    def test_merge_unions_source_sessions(self, db_path):
        """Source sessions are merged without duplicates."""
        e1 = _add_engram(db_path, "Text one", source_sessions=["s1", "s2"])
        e2 = _add_engram(db_path, "Text two", source_sessions=["s2", "s3"])

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute("SELECT source_sessions FROM engrams WHERE id = ?", (e1,)).fetchone()
        conn.close()
        sessions = json.loads(row["source_sessions"])
        assert set(sessions) == {"s1", "s2", "s3"}
        assert len(sessions) == 3  # no duplicates

    def test_merge_prerequisites_tags_union(self, db_path):
        """Tags use union (engram applies to all contexts where originals were relevant)."""
        e1 = _add_engram(db_path, "Text one", prerequisites={"tags": ["frontend", "react", "acme"]})
        e2 = _add_engram(db_path, "Text two", prerequisites={"tags": ["frontend", "react"]})

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute("SELECT prerequisites FROM engrams WHERE id = ?", (e1,)).fetchone()
        conn.close()
        prereqs = json.loads(row["prerequisites"])
        assert set(prereqs["tags"]) == {"frontend", "react", "acme"}

    def test_merge_prerequisites_repos_union(self, db_path):
        """Repos use union (OR semantics)."""
        e1 = _add_engram(db_path, "Text one", prerequisites={"repos": ["repo-a"]})
        e2 = _add_engram(db_path, "Text two", prerequisites={"repos": ["repo-b"]})

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute("SELECT prerequisites FROM engrams WHERE id = ?", (e1,)).fetchone()
        conn.close()
        prereqs = json.loads(row["prerequisites"])
        assert set(prereqs["repos"]) == {"repo-a", "repo-b"}

    def test_merge_deprecates_absorbed(self, db_path):
        """Absorbed engrams are deprecated and marked verified."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute(
            "SELECT deprecated, dedup_verified FROM engrams WHERE id = ?", (e2,)
        ).fetchone()
        conn.close()
        assert row["deprecated"] == 1
        assert row["dedup_verified"] == 1

    def test_merge_rewrites_session_shown_engrams(self, db_path):
        """Absorbed IDs in session_shown_engrams become survivor."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        record_shown_engram("sess-1", e2, "UserPromptSubmit", db_path=db_path)

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        rows = conn.execute(
            "SELECT engram_id FROM session_shown_engrams WHERE session_id = 'sess-1'"
        ).fetchall()
        conn.close()
        engram_ids = {r["engram_id"] for r in rows}
        assert e1 in engram_ids
        assert e2 not in engram_ids

    def test_merge_rewrites_session_audit_json(self, db_path):
        """Session audit shown_engram_ids JSON is updated."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        write_session_audit("sess-1", [e1, e2], ["tag1"], "repo", db_path=db_path)

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute(
            "SELECT shown_engram_ids FROM session_audit WHERE session_id = 'sess-1'"
        ).fetchone()
        conn.close()
        ids = json.loads(row["shown_engram_ids"])
        assert e1 in ids
        assert e2 not in ids

    def test_merge_rewrites_hook_event_log_json(self, db_path):
        """Hook event log engram_ids JSON is updated."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        log_hook_event("sess-1", "UserPromptSubmit", [e1, e2], db_path=db_path)

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute("SELECT engram_ids FROM hook_event_log LIMIT 1").fetchone()
        conn.close()
        ids = json.loads(row["engram_ids"])
        assert e1 in ids
        assert e2 not in ids

    def test_merge_categories_union(self, db_path):
        """All categories from absorbed are added to survivor."""
        e1 = _add_engram(db_path, "Survivor", category="development/backend")
        e2 = _add_engram(db_path, "Absorbed", category="development/frontend")

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        rows = conn.execute(
            "SELECT category_path FROM engram_categories WHERE engram_id = ?", (e1,)
        ).fetchall()
        conn.close()
        cats = {r["category_path"] for r in rows}
        assert "development/backend" in cats
        assert "development/frontend" in cats

    def test_merge_repo_stats_aggregation(self, db_path):
        """Repo stats counts are summed per repo."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        # Add repo stats for both
        update_match_stats(e1, repo="test-repo", db_path=db_path)
        update_match_stats(e1, repo="test-repo", db_path=db_path)  # 2 matches
        update_match_stats(e2, repo="test-repo", db_path=db_path)  # 1 match

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute(
            "SELECT times_matched FROM engram_repo_stats WHERE engram_id = ? AND repo = 'test-repo'",
            (e1,),
        ).fetchone()
        conn.close()
        assert row["times_matched"] == 3

    def test_merge_tag_relevance_weighted_avg(self, db_path):
        """Tag relevance uses evidence-weighted average."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        # e1: score=0.8 with 4 positive evals
        update_tag_relevance(e1, {"frontend": 2.0}, weight=1.0, db_path=db_path)
        update_tag_relevance(e1, {"frontend": 2.0}, weight=1.0, db_path=db_path)
        update_tag_relevance(e1, {"frontend": 2.0}, weight=1.0, db_path=db_path)
        update_tag_relevance(e1, {"frontend": 2.0}, weight=1.0, db_path=db_path)

        # e2: different score with 2 evals
        update_tag_relevance(e2, {"frontend": -1.0}, weight=1.0, db_path=db_path)
        update_tag_relevance(e2, {"frontend": -1.0}, weight=1.0, db_path=db_path)

        # Get pre-merge scores
        conn = get_connection(db_path)
        s1 = conn.execute(
            "SELECT score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ? AND tag = 'frontend'",
            (e1,),
        ).fetchone()
        s2 = conn.execute(
            "SELECT score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ? AND tag = 'frontend'",
            (e2,),
        ).fetchone()

        surv_evidence = s1["positive_evals"] + s1["negative_evals"]
        abs_evidence = s2["positive_evals"] + s2["negative_evals"]
        expected_score = (s1["score"] * surv_evidence + s2["score"] * abs_evidence) / (surv_evidence + abs_evidence)

        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        merged = conn.execute(
            "SELECT score, positive_evals, negative_evals FROM engram_tag_relevance WHERE engram_id = ? AND tag = 'frontend'",
            (e1,),
        ).fetchone()
        conn.close()

        assert abs(merged["score"] - expected_score) < 0.001
        assert merged["positive_evals"] == s1["positive_evals"] + s2["positive_evals"]
        assert merged["negative_evals"] == s1["negative_evals"] + s2["negative_evals"]

    def test_merge_invalidation_survivor_unverified(self, db_path):
        """Survivor is re-queued (dedup_verified=0) after merge."""
        e1 = _add_engram(db_path, "Survivor", verified=True)
        e2 = _add_engram(db_path, "Absorbed")

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "test-run", 0.9, "test", conn)
        conn.commit()

        row = conn.execute(
            "SELECT dedup_verified FROM engrams WHERE id = ?", (e1,)
        ).fetchone()
        conn.close()
        assert row["dedup_verified"] == 0

    def test_merge_audit_log_written(self, db_path):
        """engram_merge_log row is created."""
        e1 = _add_engram(db_path, "Survivor")
        e2 = _add_engram(db_path, "Absorbed")

        conn = get_connection(db_path)
        merge_engram_group(e1, [e2], "Merged", "run-123", 0.95, "Same rule", conn)
        conn.commit()

        row = conn.execute("SELECT * FROM engram_merge_log").fetchone()
        conn.close()
        assert row is not None
        assert row["survivor_id"] == e1
        assert json.loads(row["absorbed_ids"]) == [e2]
        assert row["canonical_text"] == "Merged"
        assert row["run_id"] == "run-123"
        assert row["confidence"] == 0.95
        assert row["reason"] == "Same rule"


# =============================================================================
# Integration tests (mock LLM)
# =============================================================================


def _mock_llm_response(groups, no_match_ids=None):
    """Create a mock LLM response."""
    return {
        "groups": groups,
        "no_match_ids": no_match_ids or [],
        "notes": [],
    }


class TestIntegration:

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_full_dedup_pass_known_clusters(self, mock_embed, mock_llm, db_path):
        """Feed known duplicate clusters, verify collapse (incremental mode)."""
        import numpy as np

        # Create enough verified for incremental mode
        e1 = _add_engram(db_path, "No migration code for dev projects", verified=True)
        _add_engram(db_path, "Always write unit tests", verified=True)
        _add_engram(db_path, "Use consistent naming", verified=True)
        e2 = _add_engram(db_path, "Skip compat migration in dev-only repos")
        e3 = _add_engram(db_path, "No backward compat code in internal projects")

        dim = 384
        base_emb = np.random.randn(dim).astype(np.float32)
        base_emb /= np.linalg.norm(base_emb)

        def mock_embed_fn(texts):
            result = []
            for _ in texts:
                noise = np.random.randn(dim).astype(np.float32) * 0.001
                emb = base_emb + noise
                emb /= np.linalg.norm(emb)
                result.append(emb)
            return np.array(result, dtype=np.float32)

        mock_embed.side_effect = mock_embed_fn

        # Mock LLM: merge e1, e2, e3
        mock_llm.return_value = _mock_llm_response(
            groups=[{
                "ids": sorted([e1, e2, e3]),
                "canonical_text": "Do not add migration or compatibility code for dev-only projects.",
                "confidence": 0.95,
                "reason": "Same rule, different wording."
            }],
        )

        summary = run_dedup(single_pass=True, db_path=db_path)

        assert summary["merged"] == 1
        # Survivor should exist, absorbed should be deprecated
        active = get_all_active_engrams(db_path=db_path)
        active_ids = {e["id"] for e in active}
        # At least one of the three should survive
        assert len(active_ids & {e1, e2, e3}) >= 1
        # At least two should be deprecated
        conn = get_connection(db_path)
        deprecated = conn.execute(
            "SELECT COUNT(*) FROM engrams WHERE deprecated = 1 AND id IN (?, ?, ?)",
            (e1, e2, e3),
        ).fetchone()[0]
        conn.close()
        assert deprecated >= 2

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_dedup_idempotent_after_convergence(self, mock_embed, mock_llm, db_path):
        """Second run after convergence produces zero merges."""
        import numpy as np

        # All verified, no unverified
        for i in range(3):
            _add_engram(db_path, f"Distinct engram {i}", verified=True)

        dim = 384
        def mock_embed_fn(texts):
            return np.random.randn(len(texts), dim).astype(np.float32)

        mock_embed.side_effect = mock_embed_fn

        summary = run_dedup(single_pass=True, db_path=db_path)
        assert summary["merged"] == 0

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_dedup_scan_only_no_mutations(self, mock_embed, mock_llm, db_path):
        """--scan doesn't modify DB."""
        import numpy as np

        # Incremental mode (>= 3 verified)
        e1 = _add_engram(db_path, "No migration code for dev projects", verified=True)
        _add_engram(db_path, "Always write tests", verified=True)
        _add_engram(db_path, "Use consistent naming", verified=True)
        e2 = _add_engram(db_path, "Skip compat migration in dev repos")

        dim = 384
        base_emb = np.random.randn(dim).astype(np.float32)
        base_emb /= np.linalg.norm(base_emb)

        def mock_embed_fn(texts):
            result = []
            for _ in texts:
                noise = np.random.randn(dim).astype(np.float32) * 0.001
                emb = base_emb + noise
                emb /= np.linalg.norm(emb)
                result.append(emb)
            return np.array(result, dtype=np.float32)

        mock_embed.side_effect = mock_embed_fn

        mock_llm.return_value = _mock_llm_response(
            groups=[{
                "ids": sorted([e1, e2]),
                "canonical_text": "Merged text.",
                "confidence": 0.9,
                "reason": "test"
            }],
        )

        # Snapshot before
        before = get_all_active_engrams(db_path=db_path)

        summary = run_dedup(scan_only=True, single_pass=True, db_path=db_path)

        # DB should be unchanged
        after = get_all_active_engrams(db_path=db_path)
        assert len(before) == len(after)
        assert summary["merged"] == 0

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_bootstrap_mode_all_unverified(self, mock_embed, mock_llm, db_path):
        """Triggers bootstrap when pool is empty."""
        import numpy as np

        e1 = _add_engram(db_path, "No migration code for dev projects")
        e2 = _add_engram(db_path, "Skip compat migration in dev repos")

        dim = 384
        base_emb = np.random.randn(dim).astype(np.float32)
        base_emb /= np.linalg.norm(base_emb)

        def mock_embed_fn(texts):
            result = []
            for _ in texts:
                noise = np.random.randn(dim).astype(np.float32) * 0.001
                emb = base_emb + noise
                emb /= np.linalg.norm(emb)
                result.append(emb)
            return np.array(result, dtype=np.float32)

        mock_embed.side_effect = mock_embed_fn

        mock_llm.return_value = _mock_llm_response(
            groups=[{
                "ids": [e1, e2],
                "canonical_text": "No migration code for dev-only projects.",
                "confidence": 0.9,
                "reason": "Same rule."
            }],
        )

        assert should_bootstrap(db_path=db_path) is True

        summary = run_dedup(single_pass=True, db_path=db_path)
        assert summary["merged"] == 1

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    @patch("src.dedup.build_index")
    @patch("src.dedup.build_tag_index")
    def test_multi_pass_convergence(self, mock_tag_idx, mock_idx, mock_embed, mock_llm, db_path):
        """Merges in pass 1 enable further merges in pass 2."""
        import numpy as np

        # Create enough verified to stay in incremental mode
        v1 = _add_engram(db_path, "No migration code for dev projects", verified=True)
        v2 = _add_engram(db_path, "Always write unit tests for new code", verified=True)
        v3 = _add_engram(db_path, "Use consistent naming conventions", verified=True)
        # Two unverified that match v1
        u1 = _add_engram(db_path, "Skip compat migration in dev repos")
        u2 = _add_engram(db_path, "No backward compat in internal repos")

        dim = 384
        base_emb = np.random.randn(dim).astype(np.float32)
        base_emb /= np.linalg.norm(base_emb)

        def mock_embed_fn(texts):
            result = []
            for _ in texts:
                noise = np.random.randn(dim).astype(np.float32) * 0.001
                emb = base_emb + noise
                emb /= np.linalg.norm(emb)
                result.append(emb)
            return np.array(result, dtype=np.float32)

        mock_embed.side_effect = mock_embed_fn

        call_count = [0]
        def llm_side_effect(batch, mode="incremental", min_confidence=0.8, run_id=""):
            call_count[0] += 1
            unverified_in_batch = batch["unverified_ids"]
            if call_count[0] == 1:
                # Pass 1: merge u1 into v1, mark u2 as no_match
                return _mock_llm_response(
                    groups=[{
                        "ids": sorted([v1, u1]),
                        "canonical_text": "No migration code for dev-only projects.",
                        "confidence": 0.9,
                        "reason": "Same rule."
                    }],
                    no_match_ids=[eid for eid in unverified_in_batch if eid not in {v1, u1}],
                )
            else:
                # Pass 2: merge u2 into survivor v1 (now re-queued as unverified)
                return _mock_llm_response(
                    groups=[{
                        "ids": sorted([v1, u2]),
                        "canonical_text": "Do not add migration or backward-compatibility code in dev-only projects.",
                        "confidence": 0.92,
                        "reason": "Same rule."
                    }],
                    no_match_ids=[eid for eid in unverified_in_batch if eid not in {v1, u2}],
                )

        mock_llm.side_effect = llm_side_effect

        summary = run_dedup(max_passes=3, db_path=db_path)

        # Should have merged in at least 2 passes
        assert summary["merged"] >= 2
        assert summary["passes"] >= 2

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_error_handling_retry(self, mock_embed, mock_llm, db_path):
        """LLM failure increments attempts, retryable next run."""
        import numpy as np

        # Use incremental mode (>= 3 verified)
        v1 = _add_engram(db_path, "No migration code for dev projects", verified=True)
        v2 = _add_engram(db_path, "Always write tests for new code", verified=True)
        v3 = _add_engram(db_path, "Use consistent naming conventions", verified=True)
        u1 = _add_engram(db_path, "Skip compat migration in dev repos")

        dim = 384
        base_emb = np.random.randn(dim).astype(np.float32)
        base_emb /= np.linalg.norm(base_emb)

        def mock_embed_fn(texts):
            result = []
            for _ in texts:
                noise = np.random.randn(dim).astype(np.float32) * 0.001
                emb = base_emb + noise
                emb /= np.linalg.norm(emb)
                result.append(emb)
            return np.array(result, dtype=np.float32)

        mock_embed.side_effect = mock_embed_fn

        # LLM returns None (failure)
        mock_llm.return_value = None

        summary = run_dedup(single_pass=True, db_path=db_path)

        assert summary["failed"] > 0

        # Check that dedup_attempts was incremented
        conn = get_connection(db_path)
        row = conn.execute(
            "SELECT dedup_attempts, dedup_last_error FROM engrams WHERE id = ?", (u1,)
        ).fetchone()
        conn.close()
        assert row["dedup_attempts"] >= 1
        assert row["dedup_last_error"] is not None


# =============================================================================
# CLI tests
# =============================================================================


class TestCLI:

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_cmd_dedup_scan_output(self, mock_embed, mock_llm, db_path, capsys):
        """Verify human-readable scan format."""
        import numpy as np

        # Incremental mode (>= 3 verified)
        e1 = _add_engram(db_path, "No migration code", verified=True)
        _add_engram(db_path, "Always write tests", verified=True)
        _add_engram(db_path, "Use consistent naming", verified=True)
        e2 = _add_engram(db_path, "Skip compat migration")

        dim = 384
        base_emb = np.random.randn(dim).astype(np.float32)
        base_emb /= np.linalg.norm(base_emb)

        def mock_embed_fn(texts):
            result = []
            for _ in texts:
                noise = np.random.randn(dim).astype(np.float32) * 0.001
                emb = base_emb + noise
                emb /= np.linalg.norm(emb)
                result.append(emb)
            return np.array(result, dtype=np.float32)

        mock_embed.side_effect = mock_embed_fn

        mock_llm.return_value = _mock_llm_response(
            groups=[{
                "ids": sorted([e1, e2]),
                "canonical_text": "Merged.",
                "confidence": 0.9,
                "reason": "Same rule."
            }],
        )

        summary = run_dedup(scan_only=True, single_pass=True, db_path=db_path)

        assert len(summary["pass_details"][0]["groups"]) == 1
        group = summary["pass_details"][0]["groups"][0]
        assert "canonical_text" in group
        assert "confidence" in group

    @patch("src.dedup.call_dedup_llm")
    @patch("src.dedup.embed_batch")
    def test_cmd_dedup_json_output(self, mock_embed, mock_llm, db_path):
        """Verify JSON summary structure."""
        import numpy as np

        _add_engram(db_path, "Engram one", verified=True)
        _add_engram(db_path, "Engram two")

        dim = 384
        def mock_embed_fn(texts):
            return np.random.randn(len(texts), dim).astype(np.float32)

        mock_embed.side_effect = mock_embed_fn

        mock_llm.return_value = _mock_llm_response(groups=[], no_match_ids=[2])

        summary = run_dedup(json_output=True, single_pass=True, db_path=db_path)

        assert "processed" in summary
        assert "merged" in summary
        assert "verified" in summary
        assert "failed" in summary
        assert "passes" in summary
        assert "pass_details" in summary


class TestSurvivorSelection:

    def test_prefer_verified(self):
        """Verified engrams are preferred as survivors."""
        engrams = {
            1: {"dedup_verified": 0, "occurrence_count": 10},
            2: {"dedup_verified": 1, "occurrence_count": 1},
        }
        assert select_survivor([1, 2], engrams) == 2

    def test_prefer_highest_occurrence(self):
        """Among same verification status, highest occurrence wins."""
        engrams = {
            1: {"dedup_verified": 0, "occurrence_count": 3},
            2: {"dedup_verified": 0, "occurrence_count": 7},
        }
        assert select_survivor([1, 2], engrams) == 2

    def test_prefer_lowest_id(self):
        """Tie-breaking: lowest ID wins."""
        engrams = {
            5: {"dedup_verified": 0, "occurrence_count": 3},
            3: {"dedup_verified": 0, "occurrence_count": 3},
        }
        assert select_survivor([5, 3], engrams) == 3
