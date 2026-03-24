"""Tests for per-turn extraction coordination with batch extraction."""

import json
import os
import tempfile

import pytest

from src.core.db import (
    get_connection,
    get_processed_session_ids,
    init_db,
    mark_sessions_processed,
)
from src.pipeline.extractor import (
    _get_turn_coverage,
    _read_turn_offset,
    _write_turn_offset,
)


@pytest.fixture
def offset_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def transcript_file():
    """Create a fake transcript JSONL with enough content."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as f:
        for i in range(50):
            entry = {
                "type": "user" if i % 2 == 0 else "assistant",
                "message": {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"Message number {i} with some filler content to make it longer. " * 10,
                },
            }
            f.write(json.dumps(entry) + "\n")
        path = f.name
    yield path
    os.unlink(path)


# --- mark_sessions_processed upsert ---


def test_mark_sessions_processed_upsert(test_db):
    """Second call updates counts instead of being ignored."""
    mark_sessions_processed(
        [{"session_id": "sess-1", "had_friction": 0, "engrams_extracted": 0}],
        db_path=test_db,
    )
    mark_sessions_processed(
        [{"session_id": "sess-1", "had_friction": 1, "engrams_extracted": 5}],
        db_path=test_db,
    )

    conn = get_connection(test_db)
    row = conn.execute(
        "SELECT had_friction, engrams_extracted FROM processed_sessions WHERE session_id = ?",
        ("sess-1",),
    ).fetchone()
    conn.close()

    assert row["had_friction"] == 1
    assert row["engrams_extracted"] == 5


def test_mark_sessions_processed_keeps_max(test_db):
    """Upsert keeps the MAX of had_friction and engrams_extracted."""
    mark_sessions_processed(
        [{"session_id": "sess-2", "had_friction": 1, "engrams_extracted": 10}],
        db_path=test_db,
    )
    # Second call has lower values — should keep the higher ones
    mark_sessions_processed(
        [{"session_id": "sess-2", "had_friction": 0, "engrams_extracted": 3}],
        db_path=test_db,
    )

    conn = get_connection(test_db)
    row = conn.execute(
        "SELECT had_friction, engrams_extracted FROM processed_sessions WHERE session_id = ?",
        ("sess-2",),
    ).fetchone()
    conn.close()

    assert row["had_friction"] == 1
    assert row["engrams_extracted"] == 10


# --- _get_turn_coverage ---


def test_get_turn_coverage_no_offset(transcript_file, offset_dir, monkeypatch):
    """Returns (0, file_size) when no turn offset exists."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    turn_offset, file_size = _get_turn_coverage("no-such-session", transcript_file)
    assert turn_offset == 0
    assert file_size == os.path.getsize(transcript_file)


def test_get_turn_coverage_with_offset(transcript_file, offset_dir, monkeypatch):
    """Returns stored offset and file size."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    _write_turn_offset("sess-cov", 5000)
    turn_offset, file_size = _get_turn_coverage("sess-cov", transcript_file)
    assert turn_offset == 5000
    assert file_size == os.path.getsize(transcript_file)


def test_get_turn_coverage_missing_file(offset_dir, monkeypatch):
    """Returns (offset, 0) when transcript file doesn't exist."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    _write_turn_offset("sess-gone", 1000)
    turn_offset, file_size = _get_turn_coverage("sess-gone", "/nonexistent/file.jsonl")
    assert turn_offset == 1000
    assert file_size == 0


# --- Turn offset read/write ---


def test_turn_offset_roundtrip(offset_dir, monkeypatch):
    """Write and read back a turn offset."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    assert _read_turn_offset("sess-rt") == 0
    _write_turn_offset("sess-rt", 12345)
    assert _read_turn_offset("sess-rt") == 12345


def test_turn_offset_updates(offset_dir, monkeypatch):
    """Subsequent writes overwrite the offset."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    _write_turn_offset("sess-upd", 100)
    _write_turn_offset("sess-upd", 500)
    assert _read_turn_offset("sess-upd") == 500


# --- Min content threshold ---


def test_extract_from_turn_skips_short_content(offset_dir, monkeypatch):
    """Per-turn extraction skips when new content is below MIN_TURN_CHARS
    and does NOT advance the offset, so content accumulates."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    # Create a small transcript (below 20K chars of new content)
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as f:
        for i in range(5):
            entry = {
                "type": "user" if i % 2 == 0 else "assistant",
                "message": {
                    "role": "user" if i % 2 == 0 else "assistant",
                    "content": f"Short message {i}. " * 20,
                },
            }
            f.write(json.dumps(entry) + "\n")
        # Pad to get past the 10KB agent session filter
        for i in range(100):
            entry = {"type": "system", "message": {"content": "x" * 100}}
            f.write(json.dumps(entry) + "\n")
        small_path = f.name

    try:
        from src.pipeline.extractor import extract_from_turn

        session_id = "sess-short"
        result = extract_from_turn(session_id, small_path)

        assert result["skipped_reason"] == "below_threshold"
        # Offset should NOT have advanced
        assert _read_turn_offset(session_id) == 0
    finally:
        os.unlink(small_path)


def test_extract_from_turn_skips_agent_sessions(offset_dir, monkeypatch):
    """Transcripts under 10KB are skipped as agent sessions."""
    monkeypatch.setenv("ENGRAMMAR_HOME", offset_dir)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False
    ) as f:
        f.write(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        tiny_path = f.name

    try:
        from src.pipeline.extractor import extract_from_turn

        result = extract_from_turn("sess-tiny", tiny_path)
        assert result["skipped_reason"] == "small_transcript"
    finally:
        os.unlink(tiny_path)
