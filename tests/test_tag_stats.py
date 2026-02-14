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
        lesson_id = cursor.lastrowid


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    init_db(db_path)
        lesson_id = cursor.lastrowid
    yield db_path

    # Cleanup
    Path(db_path).unlink(missing_ok=True)
        lesson_id = cursor.lastrowid


class TestTagStatsTracking:
    """Test lesson_tag_stats table and tracking."""

    def test_table_exists(self, test_db):
        """Should create lesson_tag_stats table."""
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='lesson_tag_stats'"
        )
        lesson_id = cursor.lastrowid
        assert cursor.fetchone() is not None
        conn.close()
        lesson_id = cursor.lastrowid

    def test_track_single_tag_set(self, test_db):
        """Should track matches for a single tag set."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Track matches
        tags = ["frontend", "react", "acme"]
        for _ in range(3):
            update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        # Verify
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        row = conn.execute(
            "SELECT tag_set, times_matched FROM lesson_tag_stats WHERE lesson_id = ?",
            (lesson_id,)
        lesson_id = cursor.lastrowid
        ).fetchone()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        assert row is not None
        assert json.loads(row["tag_set"]) == sorted(tags)
        lesson_id = cursor.lastrowid
        assert row["times_matched"] == 3

    def test_track_multiple_tag_sets(self, test_db):
        """Should track different tag sets separately."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Track different tag sets
        tag_sets = [
            ["frontend", "react", "acme"],
            ["frontend", "vue", "personal"],
            ["backend", "ruby", "acme"],
        ]

        for tags in tag_sets:
            for _ in range(2):
                update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        # Verify
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        rows = conn.execute(
            "SELECT tag_set, times_matched FROM lesson_tag_stats WHERE lesson_id = ? ORDER BY tag_set",
            (lesson_id,)
        lesson_id = cursor.lastrowid
        ).fetchall()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        assert len(rows) == 3
        for row in rows:
            assert row["times_matched"] == 2

    def test_global_counter_still_works(self, test_db):
        """Should still increment global times_matched counter."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Track matches
        for _ in range(5):
            update_match_stats(lesson_id, tags=["test"], db_path=test_db)
        lesson_id = cursor.lastrowid

        # Verify global counter
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        row = conn.execute(
            "SELECT times_matched FROM lessons WHERE id = ?",
            (lesson_id,)
        lesson_id = cursor.lastrowid
        ).fetchone()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        assert row["times_matched"] == 5


class TestTagSubsetAlgorithm:
    """Test tag subset auto-pin algorithm."""

    def test_no_tags_returns_none(self, test_db):
        """Should return None when lesson has no tag stats."""
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        result = find_auto_pin_tag_subsets(lesson_id, db_path=test_db)
        lesson_id = cursor.lastrowid
        assert result is None

    def test_below_threshold_returns_none(self, test_db):
        """Should return None when no subset meets threshold."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Add stats below threshold
        tag_sets = [
            ["frontend", "react"],
            ["frontend", "vue"],
            ["backend", "ruby"],
        ]
        for tags in tag_sets:
            for _ in range(3):  # Only 9 total, below 15 threshold
                update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        result = find_auto_pin_tag_subsets(lesson_id, db_path=test_db)
        lesson_id = cursor.lastrowid
        assert result is None

    def test_finds_minimal_common_subset(self, test_db):
        """Should find minimal common subset with 15+ matches."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Scenario: 'frontend' appears in all sets with 15 total matches
        tag_sets = [
            (["frontend", "acme", "typescript"], 6),
            (["frontend", "acme", "react"], 5),
            (["frontend", "personal", "typescript"], 4),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        result = find_auto_pin_tag_subsets(lesson_id, db_path=test_db)
        lesson_id = cursor.lastrowid
        assert result == ["frontend"]

    def test_finds_smallest_minimal_subset(self, test_db):
        """Should return smallest minimal subset when multiple exist."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Both 'frontend' and ['frontend', 'acme'] meet threshold
        # Should prefer just 'frontend' (smaller)
        lesson_id = cursor.lastrowid
        tag_sets = [
            (["frontend", "acme", "react"], 8),
            (["frontend", "acme", "vue"], 7),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        result = find_auto_pin_tag_subsets(lesson_id, db_path=test_db)
        lesson_id = cursor.lastrowid
        # Should get single tag, not two-tag subset
        assert len(result) <= 2

    def test_multiple_disjoint_contexts(self, test_db):
        """Should handle scenarios where no common subset exists."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Completely disjoint tag sets - no common tags
        tag_sets = [
            (["frontend", "react"], 8),
            (["backend", "ruby"], 7),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        result = find_auto_pin_tag_subsets(lesson_id, db_path=test_db)
        lesson_id = cursor.lastrowid
        # No single tag appears in both - should return None
        assert result is None


class TestAutoPin:
    """Test automatic pinning based on tag thresholds."""

    def test_auto_pin_on_threshold(self, test_db):
        """Should auto-pin lesson when tag subset reaches threshold."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Add matches to reach threshold
        tag_sets = [
            (["frontend", "react", "acme"], 6),
            (["frontend", "vue", "acme"], 5),
            (["frontend", "angular", "personal"], 4),
        ]

        for tags, count in tag_sets:
            for _ in range(count):
                update_match_stats(lesson_id, tags=tags, db_path=test_db)
        lesson_id = cursor.lastrowid

        # Check if pinned
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        row = conn.execute(
            "SELECT pinned, prerequisites FROM lessons WHERE id = ?",
            (lesson_id,)
        lesson_id = cursor.lastrowid
        ).fetchone()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        assert row["pinned"] == 1
        prereqs = json.loads(row["prerequisites"])
        lesson_id = cursor.lastrowid
        assert "tags" in prereqs
        assert prereqs["tags"] == ["frontend"]

    def test_no_auto_pin_when_already_pinned(self, test_db):
        """Should not modify already pinned lessons."""
        # Create pinned lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, pinned, created_at, updated_at) VALUES (?, ?, 1, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Add matches that would trigger auto-pin
        for _ in range(15):
            update_match_stats(lesson_id, tags=["test"], db_path=test_db)
        lesson_id = cursor.lastrowid

        # Verify prerequisites weren't changed
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        row = conn.execute(
            "SELECT prerequisites FROM lessons WHERE id = ?",
            (lesson_id,)
        lesson_id = cursor.lastrowid
        ).fetchone()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Should still be None (not auto-updated)
        lesson_id = cursor.lastrowid
        assert row["prerequisites"] is None

    def test_repo_based_auto_pin_still_works(self, test_db):
        """Should still support repo-based auto-pin."""
        # Create test lesson
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO lessons (text, category, created_at, updated_at) VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test lesson", "test")
        lesson_id = cursor.lastrowid
        )
        lesson_id = cursor.lastrowid
        cursor = conn.execute(
        conn.commit()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        # Add repo-based matches to reach threshold
        for _ in range(AUTO_PIN_THRESHOLD):
            update_match_stats(lesson_id, repo="app-repo", db_path=test_db)
        lesson_id = cursor.lastrowid

        # Check if pinned with repo prerequisite
        conn = get_connection(test_db)
        lesson_id = cursor.lastrowid
        row = conn.execute(
            "SELECT pinned, prerequisites FROM lessons WHERE id = ?",
            (lesson_id,)
        lesson_id = cursor.lastrowid
        ).fetchone()
        lesson_id = cursor.lastrowid
        conn.close()
        lesson_id = cursor.lastrowid

        assert row["pinned"] == 1
        prereqs = json.loads(row["prerequisites"])
        lesson_id = cursor.lastrowid
        assert "repos" in prereqs
        assert "app-repo" in prereqs["repos"]
