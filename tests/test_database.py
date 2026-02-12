"""Tests for database operations."""

import pytest
import tempfile
import os
import json
from src.db import (
    init_db, add_lesson, get_all_active_lessons, deprecate_lesson,
    get_lesson_categories, add_lesson_category, remove_lesson_category,
    update_match_stats, get_connection, AUTO_PIN_THRESHOLD
)


def test_add_lesson():
    """Should add a lesson with category."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        lesson_id = add_lesson(
            text="Test lesson",
            category="development/frontend",
            db_path=db_path
        )

        assert lesson_id > 0

        lessons = get_all_active_lessons(db_path)
        assert len(lessons) == 1
        assert lessons[0]["text"] == "Test lesson"
        assert lessons[0]["category"] == "development/frontend"


def test_add_lesson_with_multiple_categories():
    """Should add lesson to junction table with all categories."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        lesson_id = add_lesson(
            text="Multi-category lesson",
            category="tools/figma",
            categories=["development/frontend", "design"],
            db_path=db_path
        )

        # Should have primary category
        lessons = get_all_active_lessons(db_path)
        assert lessons[0]["category"] == "tools/figma"

        # Should also have junction table entries
        cats = get_lesson_categories(lesson_id, db_path)
        assert "tools/figma" in cats  # Primary category
        assert "development/frontend" in cats
        assert "design" in cats


def test_junction_table_sync_on_category_update():
    """When updating lesson category, junction table should stay in sync.

    This is the bug fix - engrammar_update should update both the primary
    category field AND the lesson_categories junction table.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        # Add lesson with initial category
        lesson_id = add_lesson(
            text="Test lesson",
            category="tools/figma",
            db_path=db_path
        )

        # Verify initial category in junction table
        cats_before = get_lesson_categories(lesson_id, db_path)
        assert "tools/figma" in cats_before

        # Update category (simulating engrammar_update)
        from src.db import remove_lesson_category, add_lesson_category
        conn = get_connection(db_path)

        # This is what engrammar_update now does:
        old_category = "tools/figma"
        new_category = "development/frontend"

        # 1. Remove old from junction
        remove_lesson_category(lesson_id, old_category, db_path)

        # 2. Add new to junction
        add_lesson_category(lesson_id, new_category, db_path)

        # 3. Update primary category
        conn.execute(
            "UPDATE lessons SET category = ? WHERE id = ?",
            (new_category, lesson_id)
        )
        conn.commit()
        conn.close()

        # Verify junction table is synced
        cats_after = get_lesson_categories(lesson_id, db_path)
        assert "development/frontend" in cats_after
        assert "tools/figma" not in cats_after  # Old category removed

        # Verify primary category updated
        lessons = get_all_active_lessons(db_path)
        assert lessons[0]["category"] == "development/frontend"


def test_deprecate_lesson():
    """Should soft-delete a lesson."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        lesson_id = add_lesson(text="Test", category="test", db_path=db_path)
        deprecate_lesson(lesson_id, db_path)

        # Should not appear in active lessons
        active = get_all_active_lessons(db_path)
        assert len(active) == 0

        # But should still exist in database
        conn = get_connection(db_path)
        all_lessons = conn.execute("SELECT * FROM lessons").fetchall()
        conn.close()
        assert len(all_lessons) == 1
        assert all_lessons[0]["deprecated"] == 1


def test_match_stats_increment():
    """Should increment times_matched counter."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        lesson_id = add_lesson(text="Test", category="test", db_path=db_path)

        # Initial match count should be 0
        lessons = get_all_active_lessons(db_path)
        assert lessons[0]["times_matched"] == 0

        # Update match stats
        update_match_stats(lesson_id, repo="test-repo", db_path=db_path)

        # Should increment
        lessons = get_all_active_lessons(db_path)
        assert lessons[0]["times_matched"] == 1


def test_auto_pin_at_threshold():
    """Should auto-pin lesson when match count reaches threshold in a repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        lesson_id = add_lesson(text="Test", category="test", db_path=db_path)

        # Match it AUTO_PIN_THRESHOLD times in same repo
        for _ in range(AUTO_PIN_THRESHOLD):
            update_match_stats(lesson_id, repo="app-repo", db_path=db_path)

        # Should be auto-pinned with repo prerequisite
        conn = get_connection(db_path)
        lesson = conn.execute(
            "SELECT pinned, prerequisites FROM lessons WHERE id = ?",
            (lesson_id,)
        ).fetchone()
        conn.close()

        assert lesson["pinned"] == 1
        prereqs = json.loads(lesson["prerequisites"])
        assert "repos" in prereqs
        assert "app-repo" in prereqs["repos"]


def test_per_repo_match_tracking():
    """Should track matches separately per repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        init_db(db_path)

        lesson_id = add_lesson(text="Test", category="test", db_path=db_path)

        # Match in different repos
        update_match_stats(lesson_id, repo="repo-a", db_path=db_path)
        update_match_stats(lesson_id, repo="repo-a", db_path=db_path)
        update_match_stats(lesson_id, repo="repo-b", db_path=db_path)

        # Check per-repo stats
        conn = get_connection(db_path)
        stats = conn.execute(
            "SELECT repo, times_matched FROM lesson_repo_stats WHERE lesson_id = ?",
            (lesson_id,)
        ).fetchall()
        conn.close()

        stats_dict = {row["repo"]: row["times_matched"] for row in stats}
        assert stats_dict["repo-a"] == 2
        assert stats_dict["repo-b"] == 1
