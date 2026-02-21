"""Evaluate engram relevance per session — runs via `cli.py evaluate`.

Reads session_audit records, finds the transcript excerpt, sends to Haiku
for per-engram tag scoring, and accumulates results into engram_tag_relevance.
Follows the same pattern as extractor.py (claude -p, no API key needed).
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime

from .db import get_connection, get_unprocessed_audit_sessions

EVALUATION_PROMPT = """You are evaluating which engrams were relevant during a Claude Code session.

Each engram was shown to the assistant during the session. Based on the transcript,
determine how relevant each engram was to the actual work done, broken down by
environment tag.

Session info:
- Repository: {repo}
- Environment tags: {env_tags}

Engrams shown (ID and text):
{engrams_block}

Session transcript excerpt:
{transcript}

For each engram, output a JSON object with:
- "engram_id": the engram ID number
- "tag_scores": dict mapping each relevant env tag to a score from -1.0 to 1.0
  (-1.0 = actively wrong/misleading in this context, 0 = irrelevant, 1.0 = very helpful)
- "reason": optional brief explanation (only for negative scores)

Output ONLY a valid JSON array. No markdown fences, no explanation.

Example output:
[{{"engram_id": 42, "tag_scores": {{"typescript": 0.9, "frontend": 0.6}}}},
 {{"engram_id": 17, "tag_scores": {{"typescript": -0.5}}, "reason": "wrong context"}}]"""


def _find_transcript_excerpt(session_id, max_chars=4000):
    """Search ~/.claude/projects/ for a JSONL matching this session ID.

    Returns the tail of the transcript (last max_chars chars of message content).
    """
    projects_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.exists(projects_dir):
        return ""

    # Search for the session ID in JSONL filenames
    pattern = os.path.join(projects_dir, "*", f"{session_id}.jsonl")
    matches = glob.glob(pattern)

    if not matches:
        # Try searching inside files for the session ID
        all_jsonls = glob.glob(os.path.join(projects_dir, "*", "*.jsonl"))
        # Check most recent files first (more likely to match)
        all_jsonls.sort(key=lambda f: os.path.getmtime(f), reverse=True)
        for jsonl_path in all_jsonls[:20]:  # Limit search
            try:
                with open(jsonl_path, "r") as f:
                    first_line = f.readline()
                    if session_id in first_line:
                        matches = [jsonl_path]
                        break
            except Exception:
                continue

    if not matches:
        return ""

    # Read messages from the transcript, take the tail
    messages = []
    try:
        with open(matches[0], "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") not in ("user", "assistant"):
                    continue

                message_obj = entry.get("message", {})
                content = message_obj.get("content", "")

                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    content = " ".join(text_parts)
                elif not isinstance(content, str):
                    continue

                role = message_obj.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:500]}")
    except Exception:
        return ""

    # Take the tail to fit within max_chars
    result = "\n".join(messages)
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result


def _read_transcript_file(transcript_path, max_chars=4000):
    """Read transcript directly from a known file path.

    Returns the tail of the transcript (last max_chars chars of message content).
    """
    messages = []
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") not in ("user", "assistant"):
                    continue

                message_obj = entry.get("message", {})
                content = message_obj.get("content", "")

                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    content = " ".join(text_parts)
                elif not isinstance(content, str):
                    continue

                role = message_obj.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:500]}")
    except Exception:
        return ""

    result = "\n".join(messages)
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result


def _call_claude_for_evaluation(session_id, shown_engrams, env_tags, repo, transcript=""):
    """Call claude CLI in headless mode to evaluate engram relevance.

    Args:
        session_id: for logging
        shown_engrams: list of dicts with 'id' and 'text' keys
        env_tags: list of environment tag strings
        repo: repository name
        transcript: session transcript excerpt

    Returns:
        list of dicts with engram_id, tag_scores, and optional reason
    """
    engrams_block = "\n".join(
        f"- ID {l['id']}: {l['text']}" for l in shown_engrams
    )

    prompt = EVALUATION_PROMPT.format(
        repo=repo or "unknown",
        env_tags=json.dumps(env_tags),
        engrams_block=engrams_block,
        transcript=transcript or "(transcript not available)",
    )

    try:
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env["ENGRAMMAR_INTERNAL_RUN"] = "1"

        result = subprocess.run(
            ["claude", "-p", prompt, "--model", "haiku", "--output-format", "text", "--no-session-persistence"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
        )

        if result.returncode != 0:
            print(f"Claude evaluation failed for {session_id}: {result.stderr}", file=sys.stderr)
            return []

        output = result.stdout.strip()
        # Strip markdown fences if present
        if output.startswith("```"):
            output = output.split("\n", 1)[1]
            if output.endswith("```"):
                output = output.rsplit("\n", 1)[0]

        return json.loads(output)
    except subprocess.TimeoutExpired:
        print(f"Claude evaluation timed out for {session_id}", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Failed to parse evaluation output for {session_id}: {e}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("claude CLI not found — skipping evaluation", file=sys.stderr)
        return []


def run_evaluation_for_session(session_id, db_path=None):
    """Evaluate a single session's engram relevance.

    Returns:
        True if evaluation completed successfully, False otherwise
    """
    conn = get_connection(db_path)

    # Load audit record
    row = conn.execute(
        "SELECT * FROM session_audit WHERE session_id = ?", (session_id,)
    ).fetchone()

    if not row:
        conn.close()
        return False

    shown_engram_ids = json.loads(row["shown_engram_ids"])
    env_tags = json.loads(row["env_tags"])
    repo = row["repo"]
    transcript_path = row["transcript_path"] if "transcript_path" in row.keys() else None

    if not shown_engram_ids:
        conn.close()
        return True  # Nothing to evaluate

    # Load engram texts
    placeholders = ",".join("?" * len(shown_engram_ids))
    engrams = conn.execute(
        f"SELECT id, text FROM engrams WHERE id IN ({placeholders})",
        tuple(shown_engram_ids),
    ).fetchall()
    conn.close()

    if not engrams:
        return True  # Engrams may have been deleted

    shown_engrams = [{"id": r["id"], "text": r["text"]} for r in engrams]

    # Find transcript — use stored path if available, fall back to glob search
    transcript = ""
    if transcript_path and os.path.isfile(transcript_path):
        transcript = _read_transcript_file(transcript_path)
    if not transcript:
        transcript = _find_transcript_excerpt(session_id)

    # Call Claude for evaluation
    evaluations = _call_claude_for_evaluation(
        session_id, shown_engrams, env_tags, repo, transcript
    )

    if not evaluations:
        # Mark as failed, increment retry
        _mark_session_status(session_id, "failed", db_path)
        return False

    # Accumulate scores (import here to avoid circular dependency in Commit D)
    try:
        from .db import update_tag_relevance
        for ev in evaluations:
            engram_id = ev.get("engram_id")
            tag_scores = ev.get("tag_scores", {})
            if engram_id and tag_scores:
                update_tag_relevance(engram_id, tag_scores, weight=1.0, db_path=db_path)
    except ImportError:
        # update_tag_relevance not yet available (added in Commit D)
        pass

    _mark_session_status(session_id, "completed", db_path)
    return True


def _mark_session_status(session_id, status, db_path=None):
    """Mark a session as completed or failed in processed_relevance_sessions."""
    conn = get_connection(db_path)
    now = datetime.utcnow().isoformat()

    existing = conn.execute(
        "SELECT retry_count FROM processed_relevance_sessions WHERE session_id = ?",
        (session_id,),
    ).fetchone()

    if existing:
        retry_count = existing["retry_count"] + (1 if status == "failed" else 0)
        conn.execute(
            """UPDATE processed_relevance_sessions
               SET status = ?, processed_at = ?, retry_count = ?
               WHERE session_id = ?""",
            (status, now, retry_count, session_id),
        )
    else:
        conn.execute(
            """INSERT INTO processed_relevance_sessions (session_id, processed_at, retry_count, status)
               VALUES (?, ?, ?, ?)""",
            (session_id, now, 1 if status == "failed" else 0, status),
        )

    conn.commit()
    conn.close()


def run_pending_evaluations(limit=5, db_path=None):
    """Process a batch of unprocessed sessions.

    Returns:
        dict with completed, failed, skipped counts
    """
    sessions = get_unprocessed_audit_sessions(limit=limit, db_path=db_path)

    results = {"completed": 0, "failed": 0, "skipped": 0, "total": len(sessions)}

    for session in sessions:
        session_id = session["session_id"]
        success = run_evaluation_for_session(session_id, db_path=db_path)
        if success:
            results["completed"] += 1
        else:
            results["failed"] += 1

    return results
