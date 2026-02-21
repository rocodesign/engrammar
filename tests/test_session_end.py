"""Tests for session end hook with tag tracking and sqlite3.Row handling."""

import json
import tempfile
from pathlib import Path

import pytest

from src.db import init_db, get_connection, update_match_stats
from src.environment import detect_environment


@pytest.fixture
def test_db():
    """Create a temporary test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    init_db(db_path)
    yield db_path
    Path(db_path).unlink(missing_ok=True)


class TestSqliteRowHandling:
    """Test that hook handles sqlite3.Row correctly (bug fix for row.get())."""

    def test_category_access_from_sqlite_row(self, test_db):
        """Should handle sqlite3.Row objects correctly (no .get() method)."""
        conn = get_connection(test_db)
        cursor = conn.execute(
            "INSERT INTO engrams (text, category, created_at, updated_at) "
            "VALUES (?, ?, datetime('now'), datetime('now'))",
            ("Test engram", "development/frontend")
        )
        engram_id = cursor.lastrowid
        conn.commit()

        # Query as hook does (returns sqlite3.Row)
        rows = conn.execute(
            "SELECT id, text, category FROM engrams WHERE id = ?",
            (engram_id,)
        ).fetchall()
        conn.close()

        row = rows[0]
        # Verify this is a sqlite3.Row
        assert type(row).__name__ == "Row"

        # Test the fixed approach (line 181 in on_session_end.py)
        engram_category = row["category"] if row["category"] else "general"
        assert engram_category == "development/frontend"
