"""Tests for robust JSON array parsing in extractor output."""

from src.extractor import _parse_json_array


def test_parse_json_array_skips_prefix_bracket_reference():
    """Should ignore a prefix like 'Note [1]' and parse engram payload array."""
    raw = 'Note [1]\n[{"engram":"Use X","category":"general"}]'
    parsed = _parse_json_array(raw)

    assert parsed == [{"engram": "Use X", "category": "general"}]


def test_parse_json_array_skips_non_engram_array_then_uses_engram_array():
    """Should skip [1] and continue scanning for the engram array."""
    raw = 'Intro [1]\n[1]\n[{"engram":"Use Y","category":"general"}]'
    parsed = _parse_json_array(raw)

    assert parsed == [{"engram": "Use Y", "category": "general"}]


def test_parse_json_array_rejects_non_engram_array():
    """Should return None when only non-engram arrays are present."""
    raw = "Note [1]\n[1]"
    parsed = _parse_json_array(raw)

    assert parsed is None
