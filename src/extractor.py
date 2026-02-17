"""Extract lessons from Claude Code session facets.

Reads session facets from ~/.claude/usage-data/facets/, sends friction sessions
to Claude haiku for analysis, and imports extracted lessons into the Engrammar DB.
"""

import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .db import (
    TOPIC_CATEGORY_MAP,
    add_lesson,
    find_similar_lesson,
    get_all_active_lessons,
    get_processed_session_ids,
    increment_lesson_occurrence,
    mark_sessions_processed,
)
from .embeddings import build_index

FACETS_DIR = Path.home() / ".claude" / "usage-data" / "facets"
MAX_LESSONS_PER_BATCH = 30

# Keyword → structural prerequisites mapping for auto-inference
# Only structural prerequisites (mcp_servers, os, paths) — tag prerequisites
# are handled dynamically by the tag relevance scoring system.
KEYWORD_PREREQUISITES = {
    "figma mcp": {"mcp_servers": ["figma"]},
    "figma server": {"mcp_servers": ["figma"]},
}

TRANSCRIPT_EXTRACTION_PROMPT = """You are analyzing a Claude Code conversation transcript to extract SPECIFIC, ACTIONABLE lessons.

Look for these signals in the conversation:
- **User corrections**: The user steered the assistant away from an approach, tool, or pattern. Capture what was wrong AND the preferred alternative.
- **Significant effort**: The assistant spent multiple turns debugging, investigating, or iterating. Capture the root cause and fix so future sessions skip the struggle.
- **Discovered conventions**: A project-specific pattern, naming convention, architecture rule, or workflow preference was established. Capture it as a reusable rule.
- **Environment/tooling quirks**: A tool, API, or library behaved unexpectedly. Capture the gotcha and workaround.

DO NOT produce generic advice like "investigate methodically" or "ask for clarification."
DO produce concrete, reusable knowledge like:
- "Use mcp__plugin_playwright_playwright__browser_navigate to open URLs in the browser, not Bash commands"
- "Branch naming convention: taps-NUMBER (lowercase), not TEAM-NUMBER or feature/taps-NUMBER"
- "PR descriptions: max 50 words, no co-authored-by lines, no file-by-file changelog"

Each lesson should be something that saves time if known in advance.

Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "topic": short category (e.g. "browser-testing", "git-workflow", "styling", "project-structure", "tool-usage", "pr-creation")
- "lesson": the specific, concrete lesson (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "scope": "general" if the lesson applies broadly, or "project-specific" if it only applies to a particular project/tool
- "project_signals": list of project/tool names when scope is "project-specific". Empty list when scope is "general".

If no lessons are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation."""

EXTRACTION_PROMPT = """You are analyzing Claude Code session data to extract SPECIFIC, ACTIONABLE lessons.

DO NOT produce generic advice like "investigate methodically" or "ask for clarification."
DO produce concrete, reusable knowledge like:
- "Use mcp__plugin_playwright_playwright__browser_navigate to open URLs in the browser, not Bash commands"
- "Figma MCP server must be connected before starting UI implementation — test with a simple figma tool call first"
- "Branch naming convention: taps-NUMBER (lowercase), not TEAM-NUMBER or feature/taps-NUMBER"
- "Never use inline styles in this codebase — use CSS classes or Tailwind component props"
- "PR descriptions: max 50 words, no co-authored-by lines, no file-by-file changelog"

Each lesson should be something that saves time if known in advance. Think: "what specific thing did Claude waste time on that could be avoided with this one piece of knowledge?"

Here are the session summaries and friction details:

{sessions}

Output a JSON array of objects, each with:
- "topic": short category (e.g. "browser-testing", "figma", "git-workflow", "styling", "project-structure", "tool-usage", "pr-creation")
- "lesson": the specific, concrete lesson (1-2 sentences max)
- "source_sessions": list of session IDs this was derived from
- "scope": "general" if the lesson applies to any project, or "project-specific" if it only applies to a particular project/tool/framework
- "project_signals": list of project/tool names when scope is "project-specific" (e.g. ["Acme", "TEAM", "Tailwind", "Figma MCP", "Playwright"]). Empty list when scope is "general".

Output ONLY valid JSON, no markdown fences, no explanation."""


def _infer_prerequisites(text, project_signals=None):
    """Infer prerequisites from lesson text and optional project signals.

    Args:
        text: the lesson text
        project_signals: optional list of project names from Haiku output

    Returns:
        dict of prerequisites (e.g. {"tags": ["acme"]}) or None
    """
    merged = {}
    text_lower = text.lower()

    # Check keyword map against lesson text
    for keyword, prereqs in KEYWORD_PREREQUISITES.items():
        if keyword in text_lower:
            for key, val in prereqs.items():
                if key in merged:
                    if isinstance(merged[key], list) and isinstance(val, list):
                        merged[key] = sorted(set(merged[key] + val))
                    else:
                        merged[key] = val
                else:
                    merged[key] = list(val) if isinstance(val, list) else val

    # Check project_signals from Haiku
    if project_signals:
        for signal in project_signals:
            signal_lower = signal.lower()
            for keyword, prereqs in KEYWORD_PREREQUISITES.items():
                if keyword in signal_lower or signal_lower in keyword:
                    for key, val in prereqs.items():
                        if key in merged:
                            if isinstance(merged[key], list) and isinstance(val, list):
                                merged[key] = sorted(set(merged[key] + val))
                            else:
                                merged[key] = val
                        else:
                            merged[key] = list(val) if isinstance(val, list) else val

    return merged if merged else None


def _maybe_backfill_prerequisites(lesson_id, prerequisites, db_path=None):
    """Backfill prerequisites on an existing lesson if it has none.

    Args:
        lesson_id: existing lesson to potentially update
        prerequisites: dict of prerequisites to set
        db_path: optional database path
    """
    if not prerequisites:
        return

    from .db import get_connection

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT prerequisites FROM lessons WHERE id = ?", (lesson_id,)
    ).fetchone()

    if row and not row["prerequisites"]:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE lessons SET prerequisites = ?, updated_at = ? WHERE id = ?",
            (json.dumps(prerequisites), now, lesson_id),
        )
        conn.commit()
    conn.close()


def _load_facets():
    """Load all facet files from the Claude usage data directory."""
    if not FACETS_DIR.exists():
        return []
    facets = []
    for fpath in FACETS_DIR.glob("*.json"):
        try:
            with open(fpath) as f:
                facets.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            continue
    return facets


def _format_sessions_for_prompt(sessions):
    """Format session facets into text for the extraction prompt."""
    parts = []
    for s in sessions:
        parts.append(
            f"Session {s['session_id'][:8]}:\n"
            f"  Summary: {s.get('brief_summary', 'N/A')}\n"
            f"  Friction: {s.get('friction_detail', 'N/A')}\n"
            f"  Friction types: {json.dumps(s.get('friction_counts', {}))}\n"
            f"  Outcome: {s.get('outcome', 'N/A')}"
        )
    return "\n\n".join(parts)


def _call_claude_for_extraction(sessions):
    """Call claude CLI in headless mode to extract lessons from sessions."""
    session_text = _format_sessions_for_prompt(sessions)
    prompt = EXTRACTION_PROMPT.format(sessions=session_text)

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
            print(f"Claude extraction failed: {result.stderr}", file=sys.stderr)
            return []

        output = result.stdout.strip()
        # Strip markdown fences if present
        if output.startswith("```"):
            output = output.split("\n", 1)[1]
            if output.endswith("```"):
                output = output.rsplit("\n", 1)[0]

        return json.loads(output)
    except subprocess.TimeoutExpired:
        print("Claude extraction timed out", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Failed to parse Claude output: {e}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("claude CLI not found — skipping extraction", file=sys.stderr)
        return []


def extract_from_sessions(dry_run=False):
    """Main extraction entry point.

    Args:
        dry_run: if True, show what would be extracted without writing to DB

    Returns:
        dict with summary: {new_sessions, with_friction, extracted, merged, total_active}
    """
    now = datetime.now(timezone.utc).isoformat()
    facets = _load_facets()

    if not facets:
        return {"new_sessions": 0, "with_friction": 0, "extracted": 0, "merged": 0}

    # Filter out already-processed sessions
    processed = get_processed_session_ids()
    new_facets = [f for f in facets if f.get("session_id", "") not in processed]

    # Split into friction vs no-friction
    friction_sessions = [f for f in new_facets if f.get("friction_detail")]
    no_friction_sessions = [f for f in new_facets if not f.get("friction_detail")]

    summary = {
        "new_sessions": len(new_facets),
        "with_friction": len(friction_sessions),
        "extracted": 0,
        "merged": 0,
    }

    if not friction_sessions:
        # Mark all new sessions as processed (even without friction)
        if not dry_run and new_facets:
            mark_sessions_processed([
                {"session_id": f["session_id"], "had_friction": 0, "lessons_extracted": 0}
                for f in new_facets
            ])
        print(f"[{now}] No new sessions with friction. "
              f"{len(new_facets)} session(s) marked as processed.")
        return summary

    print(f"[{now}] Found {len(friction_sessions)} new session(s) with friction.")

    if dry_run:
        print("\n--- DRY RUN: Sessions that would be analyzed ---")
        for s in friction_sessions:
            print(f"  {s['session_id'][:8]}: {s.get('brief_summary', 'N/A')}")
            print(f"    Friction: {s.get('friction_detail', 'N/A')}")
        return summary

    # Extract lessons via Claude haiku
    # Batch if there are many sessions
    all_extracted = []
    for i in range(0, len(friction_sessions), MAX_LESSONS_PER_BATCH):
        batch = friction_sessions[i:i + MAX_LESSONS_PER_BATCH]
        extracted = _call_claude_for_extraction(batch)
        all_extracted.extend(extracted)

    if not all_extracted:
        print("  No lessons extracted.")
        # Still mark sessions as processed
        mark_sessions_processed([
            {"session_id": f["session_id"],
             "had_friction": 1 if f.get("friction_detail") else 0,
             "lessons_extracted": 0}
            for f in new_facets
        ])
        return summary

    # Import extracted lessons into DB
    added = 0
    merged = 0
    for lesson_data in all_extracted:
        text = lesson_data.get("lesson", "")
        topic = lesson_data.get("topic", "general")
        source_sessions = lesson_data.get("source_sessions", [])
        project_signals = lesson_data.get("project_signals", [])

        if not text:
            continue

        # Infer prerequisites from text + Haiku signals
        prerequisites = _infer_prerequisites(text, project_signals)

        # Check for similar existing lesson
        existing = find_similar_lesson(text)
        if existing:
            increment_lesson_occurrence(existing["id"], source_sessions)
            # Backfill prerequisites on existing lesson if it has none
            _maybe_backfill_prerequisites(existing["id"], prerequisites)
            merged += 1
            print(f"  Merged into lesson #{existing['id']}: {text[:60]}...")
        else:
            category = TOPIC_CATEGORY_MAP.get(topic, "general/" + topic)
            lesson_id = add_lesson(
                text=text,
                category=category,
                source="auto-extracted",
                source_sessions=source_sessions,
                occurrence_count=len(source_sessions) if source_sessions else 1,
                prerequisites=prerequisites,
            )
            added += 1
            prereq_str = f" prereqs={prerequisites}" if prerequisites else ""
            print(f"  Added lesson #{lesson_id} [{category}]{prereq_str}: {text[:60]}...")

    summary["extracted"] = added
    summary["merged"] = merged

    # Rebuild embedding index if new lessons were added
    if added > 0:
        print("  Rebuilding embedding index...")
        lessons = get_all_active_lessons()
        build_index(lessons)
        print(f"  Indexed {len(lessons)} lessons.")

    # Mark all new sessions as processed
    mark_sessions_processed([
        {"session_id": f["session_id"],
         "had_friction": 1 if f.get("friction_detail") else 0,
         "lessons_extracted": 1 if f.get("friction_detail") else 0}
        for f in new_facets
    ])

    summary["total_active"] = len(get_all_active_lessons())
    print(f"  Done. Added: {added}, Merged: {merged}, Total active: {summary['total_active']}")

    return summary


def _read_transcript_messages(jsonl_path, max_chars=8000):
    """Read a transcript JSONL and return formatted message text."""
    messages = []
    try:
        with open(jsonl_path, "r") as f:
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


def _call_claude_for_transcript_extraction(transcript_text, session_id):
    """Call claude CLI to extract lessons from a conversation transcript."""
    prompt = TRANSCRIPT_EXTRACTION_PROMPT.format(
        transcript=transcript_text,
        session_id=session_id,
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
            print(f"Claude extraction failed: {result.stderr}", file=sys.stderr)
            return []

        output = result.stdout.strip()
        if output.startswith("```"):
            output = output.split("\n", 1)[1]
            if output.endswith("```"):
                output = output.rsplit("\n", 1)[0]

        return json.loads(output)
    except subprocess.TimeoutExpired:
        print("Claude extraction timed out", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Failed to parse Claude output: {e}", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("claude CLI not found — skipping extraction", file=sys.stderr)
        return []


def extract_from_transcripts(limit=None, dry_run=False, projects_dir=None):
    """Extract lessons from real conversation transcripts (not facets).

    Reads JSONL transcripts from ~/.claude/projects/, sends them to Haiku
    for lesson extraction using the same criteria as MCP self-extraction
    (corrections, significant effort, conventions, quirks).

    Args:
        limit: max number of transcripts to process (most recent first)
        dry_run: show what would be extracted without writing to DB
        projects_dir: override projects directory

    Returns:
        dict with summary: {processed, extracted, merged, skipped, total_active}
    """
    if projects_dir is None:
        projects_dir = os.path.expanduser("~/.claude/projects")

    if not os.path.exists(projects_dir):
        print("No projects directory found.")
        return {"processed": 0, "extracted": 0, "merged": 0, "skipped": 0}

    # Find all transcript files
    pattern = os.path.join(projects_dir, "*", "*.jsonl")
    session_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    if limit:
        session_files = session_files[:limit]

    if not session_files:
        print("No transcript files found.")
        return {"processed": 0, "extracted": 0, "merged": 0, "skipped": 0}

    # Filter out already-processed sessions
    processed_ids = get_processed_session_ids()
    unprocessed = []
    for fpath in session_files:
        sid = os.path.basename(fpath).replace(".jsonl", "")
        if sid not in processed_ids:
            unprocessed.append((sid, fpath))

    if not unprocessed:
        print(f"All {len(session_files)} transcripts already processed.")
        return {"processed": 0, "extracted": 0, "merged": 0, "skipped": 0}

    print(f"Found {len(unprocessed)} unprocessed transcript(s) (of {len(session_files)} total)\n")

    summary = {"processed": 0, "extracted": 0, "merged": 0, "skipped": 0}

    for i, (session_id, fpath) in enumerate(unprocessed, 1):
        print(f"[{i}/{len(unprocessed)}] {session_id[:12]}...")

        transcript_text = _read_transcript_messages(fpath)
        if not transcript_text or len(transcript_text) < 100:
            print("  Skipped (too short)")
            summary["skipped"] += 1
            if not dry_run:
                mark_sessions_processed([
                    {"session_id": session_id, "had_friction": 0, "lessons_extracted": 0}
                ])
            continue

        if dry_run:
            print(f"  Would analyze {len(transcript_text)} chars of transcript")
            summary["processed"] += 1
            continue

        extracted = _call_claude_for_transcript_extraction(transcript_text, session_id)

        if not extracted:
            print("  No lessons extracted.")
            mark_sessions_processed([
                {"session_id": session_id, "had_friction": 0, "lessons_extracted": 0}
            ])
            summary["processed"] += 1
            continue

        added = 0
        merged = 0
        for lesson_data in extracted:
            text = lesson_data.get("lesson", "")
            topic = lesson_data.get("topic", "general")
            source_sessions = lesson_data.get("source_sessions", [session_id])
            project_signals = lesson_data.get("project_signals", [])

            if not text:
                continue

            prerequisites = _infer_prerequisites(text, project_signals)

            existing = find_similar_lesson(text)
            if existing:
                increment_lesson_occurrence(existing["id"], source_sessions)
                _maybe_backfill_prerequisites(existing["id"], prerequisites)
                merged += 1
                print(f"  Merged into lesson #{existing['id']}: {text[:60]}...")
            else:
                category = TOPIC_CATEGORY_MAP.get(topic, "general/" + topic)
                lesson_id = add_lesson(
                    text=text,
                    category=category,
                    source="auto-extracted",
                    source_sessions=source_sessions,
                    occurrence_count=1,
                    prerequisites=prerequisites,
                )
                added += 1
                prereq_str = f" prereqs={prerequisites}" if prerequisites else ""
                print(f"  Added lesson #{lesson_id} [{category}]{prereq_str}: {text[:60]}...")

        mark_sessions_processed([
            {"session_id": session_id, "had_friction": 1, "lessons_extracted": added + merged}
        ])

        summary["processed"] += 1
        summary["extracted"] += added
        summary["merged"] += merged

    # Rebuild index if new lessons were added
    if summary["extracted"] > 0 and not dry_run:
        print("\nRebuilding embedding index...")
        lessons = get_all_active_lessons()
        build_index(lessons)
        summary["total_active"] = len(lessons)
        print(f"Indexed {len(lessons)} lessons.")

    print(f"\nDone. Processed: {summary['processed']}, "
          f"Added: {summary['extracted']}, Merged: {summary['merged']}, "
          f"Skipped: {summary['skipped']}")

    return summary
