#!/usr/bin/env python3
"""SessionEnd hook — analyzes which lessons were actually useful during the session.

Uses Haiku to evaluate each shown lesson against the session context.
Only increments match stats for lessons that were genuinely relevant/useful.
"""

import json
import sys
import os
import traceback
from datetime import datetime

# Add engrammar package to path
ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, ENGRAMMAR_HOME)

SHOWN_PATH = os.path.join(ENGRAMMAR_HOME, ".session-shown.json")
ERROR_LOG_PATH = os.path.join(ENGRAMMAR_HOME, ".hook-errors.log")


def _log_error(context, error):
    """Log errors to .hook-errors.log for debugging."""
    try:
        with open(ERROR_LOG_PATH, "a") as f:
            timestamp = datetime.utcnow().isoformat()
            f.write(f"\n[{timestamp}] SessionEnd - {context}\n")
            f.write(f"Error: {error}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass


def _load_shown():
    """Load set of lesson IDs shown this session."""
    try:
        if os.path.exists(SHOWN_PATH):
            with open(SHOWN_PATH, "r") as f:
                return set(json.load(f))
    except Exception as e:
        _log_error("load shown lessons", e)
    return set()


def _clear_shown():
    """Clear session-shown tracking file."""
    try:
        if os.path.exists(SHOWN_PATH):
            os.remove(SHOWN_PATH)
    except Exception as e:
        _log_error("clear shown lessons", e)


def _evaluate_lesson_usefulness(lesson_text, lesson_category, session_summary):
    """Ask Haiku if a lesson was useful in the session.

    Args:
        lesson_text: The lesson text
        lesson_category: Lesson category
        session_summary: Brief summary of what happened in the session

    Returns:
        bool: True if lesson was useful, False otherwise

    Note:
        Requires ANTHROPIC_API_KEY environment variable or apiKey in ~/.claude.json.
        If not available, defaults to marking all shown lessons as useful.
    """
    try:
        # Check for anthropic package
        try:
            import anthropic
        except ImportError:
            # No anthropic package - fail open
            return True

        # Get API key from environment
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            # Try reading from Claude Code config
            claude_config_path = os.path.expanduser("~/.claude.json")
            if os.path.exists(claude_config_path):
                try:
                    with open(claude_config_path, "r") as f:
                        config = json.load(f)
                        api_key = config.get("apiKey")
                except Exception:
                    pass

        if not api_key:
            # No API key - fail open (mark as useful)
            # This allows the system to work without AI evaluation
            return True

        client = anthropic.Anthropic(api_key=api_key)

        prompt = f"""You are evaluating whether a lesson was useful during a Claude Code session.

Lesson: [{lesson_category}] {lesson_text}

Session activity summary: {session_summary}

Was this lesson actually relevant and useful during this session? Consider:
- Did the assistant follow this lesson?
- Did the lesson prevent an error or guide correct behavior?
- Was the topic of the lesson even relevant to what was done?

Answer only: YES or NO"""

        response = client.messages.create(
            model="claude-haiku-4.5-20251001",
            max_tokens=10,
            messages=[{"role": "user", "content": prompt}]
        )

        answer = response.content[0].text.strip().upper()
        return answer == "YES"

    except Exception as e:
        # Any error - fail open (mark as useful)
        # This ensures the system continues working even if evaluation fails
        return True


def main():
    try:
        # Read session end data
        raw = sys.stdin.read().strip()
        if not raw:
            # No session data, just clear shown and exit
            _clear_shown()
            return

        data = json.loads(raw)

        # Get lessons shown during session
        shown_ids = _load_shown()
        if not shown_ids:
            return  # No lessons to evaluate

        # Get lesson details
        from engrammar.db import get_connection

        conn = get_connection()
        placeholders = ",".join("?" * len(shown_ids))
        rows = conn.execute(
            f"SELECT id, text, category FROM lessons WHERE id IN ({placeholders})",
            tuple(shown_ids)
        ).fetchall()
        conn.close()

        if not rows:
            _clear_shown()
            return

        # Get session summary from hook data
        # The SessionEnd hook receives various session metadata
        session_summary = data.get("summary", "")
        if not session_summary:
            # Try to construct from available data
            session_info = []
            if "tool_calls_count" in data:
                session_info.append(f"{data['tool_calls_count']} tool calls")
            if "duration_seconds" in data:
                mins = data["duration_seconds"] / 60
                session_info.append(f"{mins:.1f} minutes")
            session_summary = ", ".join(session_info) if session_info else "session completed"

        # Evaluate each lesson
        from engrammar.environment import detect_environment
        from engrammar.db import update_match_stats

        env = detect_environment()
        repo = env.get("repo")
        tags = env.get("tags", [])

        useful_count = 0
        for row in rows:
            lesson_id = row["id"]
            lesson_text = row["text"]
            # sqlite3.Row doesn't have .get(), use bracket with default
            lesson_category = row["category"] if row["category"] else "general"

            # Evaluate with Haiku
            is_useful = _evaluate_lesson_usefulness(lesson_text, lesson_category, session_summary)

            if is_useful:
                update_match_stats(lesson_id, repo=repo, tags=tags)
                useful_count += 1

        # Log evaluation results
        try:
            log_path = os.path.join(ENGRAMMAR_HOME, ".session-evaluations.log")
            with open(log_path, "a") as f:
                timestamp = datetime.utcnow().isoformat()
                f.write(f"\n[{timestamp}] Session evaluation:\n")
                f.write(f"  Shown: {len(shown_ids)} lessons\n")
                f.write(f"  Useful: {useful_count} lessons\n")
                f.write(f"  Repo: {repo}\n")
        except Exception:
            pass

        # Clear shown lessons for next session
        _clear_shown()

    except Exception as e:
        _log_error("main execution", e)
        # Clear shown anyway to avoid stale state
        _clear_shown()


if __name__ == "__main__":
    main()
