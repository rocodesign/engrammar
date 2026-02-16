"""Tests for MCP server tool handlers."""

import json

import pytest
from unittest.mock import patch

from src.mcp_server import (
    engrammar_add,
    engrammar_search,
    engrammar_update,
    engrammar_deprecate,
    engrammar_pin,
    engrammar_unpin,
    engrammar_list,
)
from src.db import add_lesson, get_all_active_lessons, get_connection

pytestmark = pytest.mark.usefixtures("mock_build_index")


def test_add_basic(test_db):
    result = engrammar_add(text="new lesson", category="dev")
    assert "Added lesson #1" in result
    assert "dev" in result

    lessons = get_all_active_lessons(test_db)
    assert len(lessons) == 1
    assert lessons[0]["text"] == "new lesson"


def test_add_empty_text(test_db):
    result = engrammar_add(text="", category="general")
    assert "Error" in result

    result = engrammar_add(text="   ", category="general")
    assert "Error" in result


def test_add_category_normalization(test_db):
    result = engrammar_add(text="test", category="/dev//frontend/")
    assert "dev/frontend" in result

    lessons = get_all_active_lessons(test_db)
    assert lessons[0]["category"] == "dev/frontend"


def test_add_empty_category(test_db):
    result = engrammar_add(text="test", category="///")
    assert "Error" in result


def test_add_with_tags_and_prereqs(test_db):
    result = engrammar_add(
        text="test",
        category="general",
        tags=["react", "frontend"],
        prerequisites={"repos": ["app-repo"]},
    )
    assert "Added lesson" in result

    lessons = get_all_active_lessons(test_db)
    prereqs = json.loads(lessons[0]["prerequisites"])
    assert "react" in prereqs["tags"]
    assert "app-repo" in prereqs["repos"]


def test_add_invalid_prereqs(test_db):
    result = engrammar_add(text="test", category="general", prerequisites="not json")
    assert "Error" in result


def test_search_results(test_db):
    with patch("src.search.search") as mock_search:
        mock_search.return_value = [
            {"id": 1, "text": "use hooks", "category": "dev", "score": 0.9}
        ]
        result = engrammar_search(query="hooks")
    assert "Found 1 lessons" in result
    assert "use hooks" in result


def test_search_no_results(test_db):
    with patch("src.search.search") as mock_search:
        mock_search.return_value = []
        result = engrammar_search(query="nonexistent")
    assert "No matching lessons found." in result


def test_update_text(test_db):
    lesson_id = add_lesson(text="old", category="general", db_path=test_db)
    result = engrammar_update(lesson_id=lesson_id, text="new text")
    assert f"Updated lesson #{lesson_id}" in result

    lessons = get_all_active_lessons(test_db)
    assert lessons[0]["text"] == "new text"


def test_update_empty_text(test_db):
    lesson_id = add_lesson(text="keep", category="general", db_path=test_db)
    result = engrammar_update(lesson_id=lesson_id, text="  ")
    assert "Error" in result


def test_update_category_normalization(test_db):
    lesson_id = add_lesson(text="test", category="general", db_path=test_db)
    result = engrammar_update(lesson_id=lesson_id, category="/dev//frontend/")
    assert "Updated" in result

    lessons = get_all_active_lessons(test_db)
    assert lessons[0]["category"] == "dev/frontend"


def test_deprecate_and_nonexistent(test_db):
    lesson_id = add_lesson(text="to remove", category="general", db_path=test_db)
    result = engrammar_deprecate(lesson_id=lesson_id)
    assert f"Deprecated lesson #{lesson_id}" in result

    lessons = get_all_active_lessons(test_db)
    assert len(lessons) == 0

    result = engrammar_deprecate(lesson_id=999)
    assert "Error" in result


def test_pin_unpin_idempotent(test_db):
    lesson_id = add_lesson(text="pin me", category="general", db_path=test_db)

    # Pin
    result = engrammar_pin(lesson_id=lesson_id)
    assert "Pinned" in result

    # Double pin
    result = engrammar_pin(lesson_id=lesson_id)
    assert "already pinned" in result

    # Unpin
    result = engrammar_unpin(lesson_id=lesson_id)
    assert "Unpinned" in result

    # Double unpin
    result = engrammar_unpin(lesson_id=lesson_id)
    assert "not pinned" in result


def test_list_category_filter(test_db):
    add_lesson(text="frontend lesson", category="dev/frontend", db_path=test_db)
    add_lesson(text="backend lesson", category="dev/backend", db_path=test_db)
    add_lesson(text="general lesson", category="general", db_path=test_db)

    result = engrammar_list(category="dev")
    assert "frontend lesson" in result
    assert "backend lesson" in result
    assert "general lesson" not in result
