"""Tests for tag statistics tracking and auto-pin algorithm."""

import json
import tempfile
from pathlib import Path

import pytest

from src.db import (
    init_db,
    update_match_stats,
    find_auto_pin_tag_subsets,
    get_connection,
    AUTO_PIN_THRESHOLD,
)


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)


def _create_engram(test_db, text="Test engram", pinned=False):
    """Helper to create a engram and return its ID."""
    conn = get_connection(test_db)
    cursor = conn.execute(
        "INSERT INTO engrams (text, category, pinned, created_at, updated_at) VALUES (?, ?, ?, datetime('now'), datetime('now'))",
        (text, "test", 1 if pinned else 0),
    )
    engram_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return engram_id


class TestTagStatsTracking:
    """Test engram_tag_stats table and tracking."""

    def test_table_exists(self, test_db):
        """Should create engram_tag_stats table."""
        conn = get_connection(test_db)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='engram_tag_stats'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_track_single_tag_set(self, test_db):
        """Should track matches for a single tag set."""
        engram_id = _create_engram(test_db)

        tags = ["frontend", "react", "acme"]
        for _ in range(3):
            update_match_stats(engram_id, tags=tags, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT tag_set, times_matched FROM engram_tag_stats WHERE engram_id = ?",
            (engram_id,),
        ).fetchone()
        conn.close()

        assert row is not None
        assert json.loads(row["tag_set"]) == sorted(tags)
        assert row["times_matched"] == 3

    def test_track_multiple_tag_sets(self, test_db):
        """Should track different tag sets separately."""
        engram_id = _create_engram(test_db)

        tag_sets = [
            ["frontend", "react", "acme"],
            ["frontend", "vue", "personal"],
            ["backend", "ruby", "acme"],
        ]

        for tags in tag_sets:
            for _ in range(2):
                update_match_stats(engram_id, tags=tags, db_path=test_db)

        conn = get_connection(test_db)
        rows = conn.execute(
            "SELECT tag_set, times_matched FROM engram_tag_stats WHERE engram_id = ? ORDER BY tag_set",
            (engram_id,),
        ).fetchall()
        conn.close()

        assert len(rows) == 3
        for row in rows:
            assert row["times_matched"] == 2

    def test_global_counter_still_works(self, test_db):
        """Should still increment global times_matched counter."""
        engram_id = _create_engram(test_db)

        for _ in range(5):
            update_match_stats(engram_id, tags=["test"], db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT times_matched FROM engrams WHERE id = ?",
            (engram_id,),
        ).fetchone()
        conn.close()

        assert row["times_matched"] == 5


class TestTagSubsetAlgorithm:
    """Test tag subset auto-pin algorithm."""

    def test_no_tags_returns_none(self, test_db):
        """Should return None when engram has no tag stats."""
        engram_id = _create_engram(test_db)
        result = find_auto_pin_tag_subsets(engram_id, db_path=test_db)
        assert result is None

    def test_below_threshold_returns_none(self, test_db):
        """Should return None when no subset meets threshold."""
        engram_id = _create_engram(test_db)

        tag_sets = [
            ["frontend", "react"],
            ["frontend", "vue"],
            ["backend", "ruby"],
        ]
        for tags in tag_sets:
            for _ in range(3):  # Only 9 total, below 15 threshold
                update_match_stats(engram_id, tags=tags, db_path=test_db)

        result = find_auto_pin_tag_subsets(engram_id, db_path=test_db)
        assert result is None

    def test_finds_minimal_common_subset(self, test_db):
        """Should find minimal common subset with 15+ matches."""
        engram_id = _create_engram(test_db)

        tag_sets = [
            (["frontend", "acme", "typescript"], 6),
            (["frontend", "acme", "react"], 5),
            (["frontend", "personal", "typescript"], 4),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(engram_id, tags=tags, db_path=test_db)

        result = find_auto_pin_tag_subsets(engram_id, db_path=test_db)
        assert result == ["frontend"]

    def test_finds_smallest_minimal_subset(self, test_db):
        """Should return smallest minimal subset when multiple exist."""
        engram_id = _create_engram(test_db)

        tag_sets = [
            (["frontend", "acme", "react"], 8),
            (["frontend", "acme", "vue"], 7),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(engram_id, tags=tags, db_path=test_db)

        result = find_auto_pin_tag_subsets(engram_id, db_path=test_db)
        assert len(result) <= 2

    def test_multiple_disjoint_contexts(self, test_db):
        """Should handle scenarios where no common subset exists."""
        engram_id = _create_engram(test_db)

        tag_sets = [
            (["frontend", "react"], 8),
            (["backend", "ruby"], 7),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(engram_id, tags=tags, db_path=test_db)

        result = find_auto_pin_tag_subsets(engram_id, db_path=test_db)
        assert result is None


class TestAutoPin:
    """Test automatic pinning based on tag thresholds."""

    def test_auto_pin_on_threshold(self, test_db):
        """Should auto-pin engram when tag subset reaches threshold."""
        engram_id = _create_engram(test_db)

        tag_sets = [
            (["frontend", "react", "acme"], 6),
            (["frontend", "vue", "acme"], 5),
            (["frontend", "angular", "personal"], 4),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(engram_id, tags=tags, db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT pinned, prerequisites FROM engrams WHERE id = ?",
            (engram_id,),
        ).fetchone()
        conn.close()

        assert row["pinned"] == 1
        prereqs = json.loads(row["prerequisites"])
        assert "tags" in prereqs
        assert prereqs["tags"] == ["frontend"]

    def test_no_auto_pin_when_already_pinned(self, test_db):
        """Should not modify already pinned engrams."""
        engram_id = _create_engram(test_db, pinned=True)

        for _ in range(15):
            update_match_stats(engram_id, tags=["test"], db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT prerequisites FROM engrams WHERE id = ?",
            (engram_id,),
        ).fetchone()
        conn.close()

        assert row["prerequisites"] is None

    def test_repo_based_auto_pin_still_works(self, test_db):
        """Should still support repo-based auto-pin."""
        engram_id = _create_engram(test_db)

        for _ in range(AUTO_PIN_THRESHOLD):
            update_match_stats(engram_id, repo="app-repo", db_path=test_db)

        conn = get_connection(test_db)
        row = conn.execute(
            "SELECT pinned, prerequisites FROM engrams WHERE id = ?",
            (engram_id,),
        ).fetchone()
        conn.close()

        assert row["pinned"] == 1
        prereqs = json.loads(row["prerequisites"])
        assert "repos" in prereqs
        assert "app-repo" in prereqs["repos"]
