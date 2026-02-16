"""Shared hook utilities — replaces copy-pasted code across hooks."""

import json
import os
import sys
import traceback
from datetime import datetime

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
ERROR_LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".hook-errors.log")


def log_error(hook_name, context, error):
    """Write error to .hook-errors.log."""
    try:
        with open(ERROR_LOG_PATH, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"\n[{timestamp}] {hook_name} - {context}\n")
            f.write(f"Error: {error}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def parse_hook_input():
    """Read and parse the JSON payload from stdin (provided by Claude's hook system).

    Returns:
        dict with keys like session_id, transcript_path, etc., or empty dict on failure.
    """
    try:
        raw = sys.stdin.read().strip()
        if raw:
            return json.loads(raw)
    except (json.JSONDecodeError, Exception):
        pass
    return {}


def format_lessons_block(lessons, show_categories=True):
    """Format lessons in [ENGRAMMAR_V1] block with EG#ID markers.

    Args:
        lessons: list of lesson dicts (must have 'id', 'text', optionally 'category')
        show_categories: whether to include [category] prefix

    Returns:
        str: formatted block, or empty string if no lessons
    """
    if not lessons:
        return ""

    lines = ["[ENGRAMMAR_V1]"]
    for lesson in lessons:
        cat = f"[{lesson.get('category', 'general')}] " if show_categories and lesson.get("category") else ""
        lines.append(f"- [EG#{lesson['id']}]{cat}{lesson['text']}")
    lines.append(
        "Treat these as soft constraints. If one doesn't apply here, "
        "call engrammar_feedback(lesson_id, applicable=false, reason=\"...\")."
    )
    lines.append("[/ENGRAMMAR_V1]")
    return "\n".join(lines)


def make_hook_output(hook_event_name, context_text):
    """Build the standard hook output dict."""
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event_name,
            "additionalContext": context_text,
        }
    }
