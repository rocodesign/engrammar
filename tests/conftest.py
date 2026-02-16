"""Shared fixtures for CLI, MCP server, and hook tests."""

import sys

import pytest

# Module alias: `from engrammar.X import Y` resolves to `from src.X import Y`
import src
import src.client
import src.config
import src.db
import src.embeddings
import src.environment
import src.hook_utils
import src.search

sys.modules["engrammar"] = src
for _attr in ("config", "db", "embeddings", "search", "environment", "hook_utils", "client"):
    sys.modules[f"engrammar.{_attr}"] = getattr(src, _attr)

from src import config, db
from src.db import init_db


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """Temp DB with patched DB_PATH so high-level callers default to it."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(db, "DB_PATH", db_path)
    monkeypatch.setattr(config, "_config_cache", None)
    init_db(db_path)
    return db_path


@pytest.fixture
def mock_build_index(monkeypatch):
    """Prevent embedding model load — opt in via pytestmark usefixtures."""
    monkeypatch.setattr("src.embeddings.build_index", lambda *a, **kw: 0)
