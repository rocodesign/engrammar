"""Tests for CLI command functions."""

import json

import pytest
from unittest.mock import patch

from cli import (
    cmd_add,
    cmd_search,
    cmd_update,
    cmd_deprecate,
    cmd_pin,
    cmd_unpin,
    cmd_list,
    cmd_detect_tags,
)
from src.db import add_engram, get_all_active_engrams, get_connection

pytestmark = pytest.mark.usefixtures("mock_build_index")


def test_cmd_add_basic(test_db, capsys):
    cmd_add(["test engram text", "--category", "dev/frontend"])
    captured = capsys.readouterr()
    assert "Added engram #1" in captured.out
    assert "dev/frontend" in captured.out

    engrams = get_all_active_engrams(test_db)
    assert len(engrams) == 1
    assert engrams[0]["text"] == "test engram text"
    assert engrams[0]["category"] == "dev/frontend"


def test_cmd_add_with_tags(test_db, capsys):
    cmd_add(["engram with tags", "--category", "general", "--tags", "react,typescript"])
    captured = capsys.readouterr()
    assert "react" in captured.out
    assert "typescript" in captured.out

    engrams = get_all_active_engrams(test_db)
    prereqs = json.loads(engrams[0]["prerequisites"])
    assert "react" in prereqs["tags"]
    assert "typescript" in prereqs["tags"]


def test_cmd_add_no_args(test_db, capsys):
    cmd_add([])
    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_cmd_search_results(test_db, capsys):
    with patch("src.search.search") as mock_search:
        mock_search.return_value = [
            {
                "id": 1,
                "text": "Use react hooks",
                "category": "dev",
                "score": 0.95,
                "times_matched": 3,
                "occurrence_count": 1,
            }
        ]
        cmd_search(["react hooks"])
    captured = capsys.readouterr()
    assert "Found 1 results" in captured.out
    assert "Use react hooks" in captured.out


def test_cmd_search_no_results(test_db, capsys):
    with patch("src.search.search") as mock_search:
        mock_search.return_value = []
        cmd_search(["nonexistent query"])
    captured = capsys.readouterr()
    assert "No matching engrams found" in captured.out


def test_cmd_update_text(test_db, capsys):
    engram_id = add_engram(text="old text", category="general", db_path=test_db)
    cmd_update([str(engram_id), "--text", "new text"])
    captured = capsys.readouterr()
    assert f"Updated engram {engram_id}" in captured.out

    engrams = get_all_active_engrams(test_db)
    assert engrams[0]["text"] == "new text"


def test_cmd_update_nonexistent(test_db, capsys):
    cmd_update(["999", "--text", "nope"])
    captured = capsys.readouterr()
    assert "not found" in captured.out


def test_cmd_deprecate(test_db, capsys):
    engram_id = add_engram(text="to deprecate", category="general", db_path=test_db)
    cmd_deprecate([str(engram_id)])
    captured = capsys.readouterr()
    assert f"Deprecated engram {engram_id}" in captured.out

    engrams = get_all_active_engrams(test_db)
    assert len(engrams) == 0


def test_cmd_pin_unpin(test_db, capsys):
    engram_id = add_engram(text="pin me", category="general", db_path=test_db)

    cmd_pin([str(engram_id)])
    captured = capsys.readouterr()
    assert f"Pinned engram {engram_id}" in captured.out

    conn = get_connection(test_db)
    row = conn.execute("SELECT pinned FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    conn.close()
    assert row["pinned"] == 1

    cmd_unpin([str(engram_id)])
    captured = capsys.readouterr()
    assert f"Unpinned engram {engram_id}" in captured.out

    conn = get_connection(test_db)
    row = conn.execute("SELECT pinned FROM engrams WHERE id = ?", (engram_id,)).fetchone()
    conn.close()
    assert row["pinned"] == 0


def test_cmd_list(test_db, capsys):
    add_engram(text="engram one", category="general", db_path=test_db)
    add_engram(text="engram two", category="dev", db_path=test_db)

    cmd_list([])
    captured = capsys.readouterr()
    assert "of 2" in captured.out
    assert "engram one" in captured.out
    assert "engram two" in captured.out


def test_cmd_detect_tags(test_db, capsys):
    with patch("src.environment.detect_environment") as mock_env:
        mock_env.return_value = {
            "os": "darwin",
            "repo": "engrammar",
            "cwd": "/tmp",
            "tags": ["python", "cli"],
            "mcp_servers": [],
        }
        cmd_detect_tags([])
    captured = capsys.readouterr()
    assert "python" in captured.out
    assert "cli" in captured.out
