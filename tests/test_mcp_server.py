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
from src.db import add_engram, get_all_active_engrams, get_connection

pytestmark = pytest.mark.usefixtures("mock_build_index")


def test_add_basic(test_db):
    result = engrammar_add(text="new engram", category="dev")
    assert "Added engram #1" in result
    assert "dev" in result

    engrams = get_all_active_engrams(test_db)
    assert len(engrams) == 1
    assert engrams[0]["text"] == "new engram"


def test_add_captures_session_id(test_db, monkeypatch):
    """engrammar_add auto-reads session_id from file and stores it in source_sessions."""
    real_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
    monkeypatch.setattr("src.hook_utils.read_session_id", lambda: real_uuid)

    result = engrammar_add(text="self-extracted engram", category="dev", source="self-extracted")
    assert "Added engram" in result

    conn = get_connection(test_db)
    row = conn.execute("SELECT source_sessions FROM engrams WHERE id = 1").fetchone()
    conn.close()
    sessions = json.loads(row["source_sessions"])
    assert sessions == [real_uuid]


def test_add_ignores_fake_session_id(test_db, monkeypatch):
    """engrammar_add rejects non-UUID session IDs (e.g. 'current-sess')."""
    monkeypatch.setattr("src.hook_utils.read_session_id", lambda: "current-sess")

    result = engrammar_add(text="engram", category="dev")
    assert "Added engram" in result

    conn = get_connection(test_db)
    row = conn.execute("SELECT source_sessions FROM engrams WHERE id = 1").fetchone()
    conn.close()
    sessions = json.loads(row["source_sessions"])
    assert sessions == []


def test_add_no_session_file(test_db, monkeypatch):
    """engrammar_add works when no session file exists."""
    monkeypatch.setattr("src.hook_utils.read_session_id", lambda: None)

    result = engrammar_add(text="engram", category="dev")
    assert "Added engram" in result

    conn = get_connection(test_db)
    row = conn.execute("SELECT source_sessions FROM engrams WHERE id = 1").fetchone()
    conn.close()
    sessions = json.loads(row["source_sessions"])
    assert sessions == []


def test_add_empty_text(test_db):
    result = engrammar_add(text="", category="general")
    assert "Error" in result

    result = engrammar_add(text="   ", category="general")
    assert "Error" in result


def test_add_category_normalization(test_db):
    result = engrammar_add(text="test", category="/dev//frontend/")
    assert "dev/frontend" in result

    engrams = get_all_active_engrams(test_db)
    assert engrams[0]["category"] == "dev/frontend"


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
    assert "Added engram" in result

    engrams = get_all_active_engrams(test_db)
    prereqs = json.loads(engrams[0]["prerequisites"])
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
    assert "Found 1 engrams" in result
    assert "use hooks" in result


def test_search_no_results(test_db):
    with patch("src.search.search") as mock_search:
        mock_search.return_value = []
        result = engrammar_search(query="nonexistent")
    assert "No matching engrams found." in result


def test_update_text(test_db):
    engram_id = add_engram(text="old", category="general", db_path=test_db)
    result = engrammar_update(engram_id=engram_id, text="new text")
    assert f"Updated engram #{engram_id}" in result

    engrams = get_all_active_engrams(test_db)
    assert engrams[0]["text"] == "new text"


def test_update_empty_text(test_db):
    engram_id = add_engram(text="keep", category="general", db_path=test_db)
    result = engrammar_update(engram_id=engram_id, text="  ")
    assert "Error" in result


def test_update_category_normalization(test_db):
    engram_id = add_engram(text="test", category="general", db_path=test_db)
    result = engrammar_update(engram_id=engram_id, category="/dev//frontend/")
    assert "Updated" in result

    engrams = get_all_active_engrams(test_db)
    assert engrams[0]["category"] == "dev/frontend"


def test_deprecate_and_nonexistent(test_db):
    engram_id = add_engram(text="to remove", category="general", db_path=test_db)
    result = engrammar_deprecate(engram_id=engram_id)
    assert f"Deprecated engram #{engram_id}" in result

    engrams = get_all_active_engrams(test_db)
    assert len(engrams) == 0

    result = engrammar_deprecate(engram_id=999)
    assert "Error" in result


def test_pin_unpin_idempotent(test_db):
    engram_id = add_engram(text="pin me", category="general", db_path=test_db)

    # Pin
    result = engrammar_pin(engram_id=engram_id)
    assert "Pinned" in result

    # Double pin
    result = engrammar_pin(engram_id=engram_id)
    assert "already pinned" in result

    # Unpin
    result = engrammar_unpin(engram_id=engram_id)
    assert "Unpinned" in result

    # Double unpin
    result = engrammar_unpin(engram_id=engram_id)
    assert "not pinned" in result


def test_list_category_filter(test_db):
    add_engram(text="frontend engram", category="dev/frontend", db_path=test_db)
    add_engram(text="backend engram", category="dev/backend", db_path=test_db)
    add_engram(text="general engram", category="general", db_path=test_db)

    result = engrammar_list(category="dev")
    assert "frontend engram" in result
    assert "backend engram" in result
    assert "general engram" not in result
