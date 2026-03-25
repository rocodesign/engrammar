"""Tests for config defaults and merging."""

import json
from copy import deepcopy
from pathlib import Path

from src.core import config


def test_load_config_returns_all_default_keys(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config, "_config_cache", None)

    loaded = config.load_config()

    assert loaded == config.DEFAULT_CONFIG
    assert loaded is not config.DEFAULT_CONFIG


def test_load_config_deep_merges_nested_overrides(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "hooks": {
                    "min_score_tool": 0.25,
                },
                "query_enrichment": {
                    "post_tool": {
                        "inject_narration": False,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_PATH", str(config_path))
    monkeypatch.setattr(config, "_config_cache", None)

    loaded = config.load_config()

    assert loaded["hooks"]["min_score_tool"] == 0.25
    assert loaded["hooks"]["min_score_prompt"] == config.DEFAULT_CONFIG["hooks"]["min_score_prompt"]
    assert loaded["query_enrichment"]["post_tool"]["inject_narration"] is False
    assert loaded["query_enrichment"]["post_tool"]["narration_max_length"] == 200
    assert loaded["query_enrichment"]["post_tool"]["inject_tool_context"] is True


def test_repo_config_matches_default_config():
    repo_root = Path(__file__).resolve().parents[1]
    repo_config = json.loads((repo_root / "config.json").read_text(encoding="utf-8"))

    assert repo_config == config.DEFAULT_CONFIG


def test_merge_config_does_not_mutate_source_defaults():
    before_defaults = deepcopy(config.DEFAULT_CONFIG)
    merged = config._merge_config(
        deepcopy(config.DEFAULT_CONFIG),
        {"query_enrichment": {"pre_tool": {"inject_narration": True}}},
    )

    assert merged["query_enrichment"]["pre_tool"]["inject_narration"] is True
    assert config.DEFAULT_CONFIG == before_defaults
