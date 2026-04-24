"""Tests for CLI command functions."""

import json

import pytest
from unittest.mock import patch

from cli import (
    cmd_add,
    cmd_disable,
    cmd_isolate,
    cmd_search,
    cmd_update,
    cmd_deprecate,
    cmd_pin,
    cmd_unpin,
    cmd_list,
    cmd_detect_tags,
)
from src.core.db import add_engram, get_all_active_engrams, get_connection

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
    # Tags are now stored in engram_tags table, not prerequisites
    from src.core.db import get_content_tags
    tags = get_content_tags(engrams[0]["id"], db_path=test_db)
    assert "react" in tags
    assert "typescript" in tags


def test_cmd_add_no_args(test_db, capsys):
    cmd_add([])
    captured = capsys.readouterr()
    assert "Usage:" in captured.out


def test_cmd_search_results(test_db, capsys):
    with patch("src.search.engine.search") as mock_search:
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
    with patch("src.search.engine.search") as mock_search:
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


def test_cmd_update_category_syncs_levels(test_db, capsys):
    engram_id = add_engram(text="old text", category="general", db_path=test_db)

    cmd_update([str(engram_id), "--category", "development/frontend/forms"])
    captured = capsys.readouterr()
    assert f"Updated engram {engram_id}" in captured.out

    conn = get_connection(test_db)
    row = conn.execute(
        "SELECT category, level1, level2, level3 FROM engrams WHERE id = ?",
        (engram_id,),
    ).fetchone()
    cats = conn.execute(
        "SELECT category_path FROM engram_categories WHERE engram_id = ? ORDER BY category_path",
        (engram_id,),
    ).fetchall()
    conn.close()

    assert row["category"] == "development/frontend/forms"
    assert row["level1"] == "development"
    assert row["level2"] == "frontend"
    assert row["level3"] == "forms"
    assert [r["category_path"] for r in cats] == ["development/frontend/forms"]


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
    with patch("src.search.environment.detect_environment") as mock_env:
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


def test_cmd_isolate_shows_state(test_db, capsys):
    with patch("src.search.environment._detect_repo", return_value="engrammar"), \
         patch("src.core.config.load_config", return_value={
             "controls": {"isolated_repos": ["engrammar"]},
         }):
        cmd_isolate([])

    captured = capsys.readouterr()
    assert "Repo 'engrammar' isolation is on." in captured.out
    assert "engrammar isolate off" in captured.out


def test_cmd_disable_shows_state(test_db, capsys):
    with patch("src.search.environment._detect_repo", return_value="engrammar"), \
         patch("src.core.config.load_config", return_value={
             "controls": {
                 "global_disabled": True,
                 "disabled_repos": ["engrammar"],
             },
         }):
        cmd_disable([])

    captured = capsys.readouterr()
    assert "Global disable is on." in captured.out
    assert "engrammar disable global off" in captured.out
    assert "Repo 'engrammar' disable is on." in captured.out
    assert "engrammar disable repo off" in captured.out


def test_cmd_isolate_toggles_repo_state(test_db, monkeypatch, tmp_path, capsys):
    from src.core import config as config_module

    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_module, "_config_cache", None)

    with patch("src.search.environment._detect_repo", return_value="engrammar"):
        cmd_isolate(["on"])

    captured = capsys.readouterr()
    assert "Repo 'engrammar' isolation set to on." in captured.out

    with open(config_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["controls"]["isolated_repos"] == ["engrammar"]


def test_cmd_disable_global_toggles_config_and_mcp(test_db, monkeypatch, tmp_path, capsys):
    from src.core import config as config_module

    config_path = tmp_path / "config.json"
    claude_home = tmp_path / "home"
    claude_home.mkdir()
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_module, "_config_cache", None)
    monkeypatch.setenv("HOME", str(claude_home))

    cmd_disable(["global", "on"])

    captured = capsys.readouterr()
    assert "Global disable set to on." in captured.out

    with open(config_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["controls"]["global_disabled"] is True

    with open(claude_home / ".claude.json", "r", encoding="utf-8") as f:
        claude = json.load(f)
    assert claude["mcpServers"]["engrammar"]["disabled"] is True


def test_cmd_disable_repo_toggles_current_repo(test_db, monkeypatch, tmp_path, capsys):
    from src.core import config as config_module

    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config_module, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config_module, "_config_cache", None)

    with patch("src.search.environment._detect_repo", return_value="engrammar"):
        cmd_disable(["repo", "on"])

    captured = capsys.readouterr()
    assert "Repo 'engrammar' disable set to on." in captured.out

    with open(config_path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["controls"]["disabled_repos"] == ["engrammar"]
