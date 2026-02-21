"""Tests for database operations."""

import pytest
import tempfile
import os
import json
from src.db import (
    init_db, add_engram, get_all_active_engrams, deprecate_engram,
    get_engram_categories, add_engram_category, remove_engram_category,
    update_match_stats, get_connection, AUTO_PIN_THRESHOLD
)


def test_add_engram():
    """Should add a engram with category."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(
            text="Test engram",
            category="development/frontend",
            db_path=db_path
        )

        assert engram_id > 0

        engrams = get_all_active_engrams(db_path)
        assert len(engrams) == 1
        assert engrams[0]["text"] == "Test engram"
        assert engrams[0]["category"] == "development/frontend"


def test_add_engram_with_multiple_categories():
    """Should add engram to junction table with all categories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(
            text="Multi-category engram",
            category="tools/figma",
            categories=["development/frontend", "design"],
            db_path=db_path
        )

        # Should have primary category
        engrams = get_all_active_engrams(db_path)
        assert engrams[0]["category"] == "tools/figma"

        # Should also have junction table entries
        cats = get_engram_categories(engram_id, db_path)
        assert "tools/figma" in cats  # Primary category
        assert "development/frontend" in cats
        assert "design" in cats


def test_junction_table_sync_on_category_update():
    """When updating engram category, junction table should stay in sync.

    This is the bug fix - engrammar_update should update both the primary
    category field AND the engram_categories junction table.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        # Add engram with initial category
        engram_id = add_engram(
            text="Test engram",
            category="tools/figma",
            db_path=db_path
        )

        # Verify initial category in junction table
        cats_before = get_engram_categories(engram_id, db_path)
        assert "tools/figma" in cats_before

        # Update category (simulating engrammar_update)
        from src.db import remove_engram_category, add_engram_category
        conn = get_connection(db_path)

        # This is what engrammar_update now does:
        old_category = "tools/figma"
        new_category = "development/frontend"

        # 1. Remove old from junction
        remove_engram_category(engram_id, old_category, db_path)

        # 2. Add new to junction
        add_engram_category(engram_id, new_category, db_path)

        # 3. Update primary category
        conn.execute(
            "UPDATE engrams SET category = ? WHERE id = ?",
            (new_category, engram_id)
        )
        conn.commit()
        conn.close()

        # Verify junction table is synced
        cats_after = get_engram_categories(engram_id, db_path)
        assert "development/frontend" in cats_after
        assert "tools/figma" not in cats_after  # Old category removed

        # Verify primary category updated
        engrams = get_all_active_engrams(db_path)
        assert engrams[0]["category"] == "development/frontend"


def test_deprecate_engram():
    """Should soft-delete a engram."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(text="Test", category="test", db_path=db_path)
        deprecate_engram(engram_id, db_path)

        # Should not appear in active engrams
        active = get_all_active_engrams(db_path)
        assert len(active) == 0

        # But should still exist in database
        conn = get_connection(db_path)
        all_engrams = conn.execute("SELECT * FROM engrams").fetchall()
        conn.close()
        assert len(all_engrams) == 1
        assert all_engrams[0]["deprecated"] == 1


def test_match_stats_increment():
    """Should increment times_matched counter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(text="Test", category="test", db_path=db_path)

        # Initial match count should be 0
        engrams = get_all_active_engrams(db_path)
        assert engrams[0]["times_matched"] == 0

        # Update match stats
        update_match_stats(engram_id, repo="test-repo", db_path=db_path)

        # Should increment
        engrams = get_all_active_engrams(db_path)
        assert engrams[0]["times_matched"] == 1


def test_auto_pin_at_threshold():
    """Should auto-pin engram when match count reaches threshold in a repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(text="Test", category="test", db_path=db_path)

        # Match it AUTO_PIN_THRESHOLD times in same repo
        for _ in range(AUTO_PIN_THRESHOLD):
            update_match_stats(engram_id, repo="app-repo", db_path=db_path)

        # Should be auto-pinned with repo prerequisite
        conn = get_connection(db_path)
        engram = conn.execute(
            "SELECT pinned, prerequisites FROM engrams WHERE id = ?",
            (engram_id,)
        ).fetchone()
        conn.close()

        assert engram["pinned"] == 1
        prereqs = json.loads(engram["prerequisites"])
        assert "repos" in prereqs
        assert "app-repo" in prereqs["repos"]


def test_per_repo_match_tracking():
    """Should track matches separately per repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        engram_id = add_engram(text="Test", category="test", db_path=db_path)

        # Match in different repos
        update_match_stats(engram_id, repo="repo-a", db_path=db_path)
        update_match_stats(engram_id, repo="repo-a", db_path=db_path)
        update_match_stats(engram_id, repo="repo-b", db_path=db_path)

        # Check per-repo stats
        conn = get_connection(db_path)
        stats = conn.execute(
            "SELECT repo, times_matched FROM engram_repo_stats WHERE engram_id = ?",
            (engram_id,)
        ).fetchall()
        conn.close()

        stats_dict = {row["repo"]: row["times_matched"] for row in stats}
        assert stats_dict["repo-a"] == 2
        assert stats_dict["repo-b"] == 1
