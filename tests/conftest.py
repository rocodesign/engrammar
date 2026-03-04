"""Shared fixtures for CLI, MCP server, and hook tests."""

import sys

import pytest

# Module alias: `from engrammar.X.Y import Z` resolves to `from src.X.Y import Z`
# IMPORTANT: Set up package-level aliases BEFORE importing any src submodules,
# because cross-subpackage imports (e.g. `from engrammar.core.config import ...`
# inside src/search/engine.py) resolve at import time.
import src
import src.core
import src.search
import src.pipeline
import src.infra

sys.modules["engrammar"] = src
sys.modules["engrammar.core"] = src.core
sys.modules["engrammar.search"] = src.search
sys.modules["engrammar.pipeline"] = src.pipeline
sys.modules["engrammar.infra"] = src.infra

# Now safe to import individual modules (their cross-subpackage imports will resolve)
import src.core.config
import src.core.db
import src.core.embeddings
import src.core.prompt_loader
import src.search.engine
import src.search.environment
import src.search.tag_detectors
import src.search.tag_patterns
import src.pipeline.extractor
import src.pipeline.evaluator
import src.pipeline.dedup
import src.infra.hook_utils
import src.infra.client
import src.infra.daemon
import src.infra.mcp_server
import src.infra.register_hooks

# Map individual modules so `from engrammar.core.db import ...` works everywhere.
# Cross-subpackage imports (e.g. `from engrammar.core.db import ...` inside dedup.py)
# can cause Python to overwrite the `src.core.db` attribute with a new module object
# while `sys.modules["src.core.db"]` still points to the original. This breaks
# `patch("src.core.db.X")` in tests. Fix: reconcile both sys.modules entries to the
# same object (the one on the package attribute, which is what actual imports resolve to).
for subpkg, modules in {
    "core": ["config", "db", "embeddings", "prompt_loader"],
    "search": ["engine", "environment", "tag_detectors", "tag_patterns"],
    "pipeline": ["extractor", "evaluator", "dedup"],
    "infra": ["hook_utils", "client", "daemon", "mcp_server", "register_hooks"],
}.items():
    for mod in modules:
        actual = getattr(getattr(src, subpkg), mod)
        sys.modules[f"engrammar.{subpkg}.{mod}"] = actual
        sys.modules[f"src.{subpkg}.{mod}"] = actual

from src.core import config, db
from src.core.db import init_db


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
    monkeypatch.setattr("src.core.embeddings.build_index", lambda *a, **kw: 0)
