"""Tests for robust JSON array parsing in extractor output."""

from src.extractor import _parse_json_array


def test_parse_json_array_skips_prefix_bracket_reference():
    """Should ignore a prefix like 'Note [1]' and parse lesson payload array."""
    raw = 'Note [1]\n[{"lesson":"Use X","category":"general"}]'
    parsed = _parse_json_array(raw)

    assert parsed == [{"lesson": "Use X", "category": "general"}]


def test_parse_json_array_skips_non_lesson_array_then_uses_lesson_array():
    """Should skip [1] and continue scanning for the lesson array."""
    raw = 'Intro [1]\n[1]\n[{"lesson":"Use Y","category":"general"}]'
    parsed = _parse_json_array(raw)

    assert parsed == [{"lesson": "Use Y", "category": "general"}]


def test_parse_json_array_rejects_non_lesson_array():
    """Should return None when only non-lesson arrays are present."""
    raw = "Note [1]\n[1]"
    parsed = _parse_json_array(raw)

    assert parsed is None
