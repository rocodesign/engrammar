"""Extract lessons from Claude Code session facets.

Reads session facets from ~/.claude/usage-data/facets/, sends friction sessions
to Claude haiku for analysis, and imports extracted lessons into the Engrammar DB.
"""

import glob
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Pattern to strip engrammar injection blocks from transcripts
_ENGRAMMAR_BLOCK_RE = re.compile(
    r"\[ENGRAMMAR_V1\].*?\[/ENGRAMMAR_V1\]", re.DOTALL
)

from .db import (
    add_lesson,
    find_similar_lesson,
    get_all_active_lessons,
    get_connection,
    get_env_tags_for_sessions,
    get_processed_session_ids,
    increment_lesson_occurrence,
    mark_sessions_processed,
    update_tag_relevance,
    write_session_audit,
)
from .embeddings import build_index

FACETS_DIR = Path.home() / ".claude" / "usage-data" / "facets"
MAX_LESSONS_PER_BATCH = 30

# Keyword → structural prerequisites mapping for auto-inference
KEYWORD_PREREQUISITES = {
    "figma mcp": {"mcp_servers": ["figma"]},
    "figma server": {"mcp_servers": ["figma"]},
}

TRANSCRIPT_EXTRACTION_PROMPT = """You are analyzing a Claude Code conversation transcript to extract lessons from FRICTION — moments where the assistant got something wrong and the user had to intervene.

ONLY extract from these patterns:
1. **User corrections**: The assistant tried approach A, then the user said "no, do B instead" or "that's wrong, use X". Capture the rule: "Do B, not A" or "Use X because Y".
2. **Repeated struggle**: The assistant spent multiple turns on something that could have been avoided. Capture the shortcut or root cause.
3. **Discovered conventions**: The user revealed a project rule the assistant didn't know (naming, architecture, workflow). Capture the rule.
4. **Tooling gotchas**: A tool or API behaved unexpectedly and required a workaround. Capture the gotcha.

CRITICAL — DO NOT extract:
- User instructions or requests ("do X", "build Y", "add Z") — these are TASKS, not lessons
- Summaries of what was built or discussed
- Generic programming advice (validate inputs, write tests, use types)
- Implementation details about specific functions
- Anything that reads like a design decision rather than a correction

The test: if the lesson is something the user TOLD the assistant to do (not something the assistant got WRONG), it is NOT a lesson.

Good examples (notice the correction pattern):
- "Use cy.contains('button', 'Text') not cy.get('button').contains('Text') — the latter yields the deepest element, not the button"
- "In this monorepo, run codegen scoped to the app (nx run app:codegen), not workspace-wide"
- "PR descriptions: max 50 words, no co-authored-by lines — the assistant kept adding verbose descriptions"

Bad examples (these are just task summaries):
- "Rebuild similarity index after each batch" (user instruction, not a correction)
- "Validate input at system boundaries" (generic advice)
- "Session IDs are provided by Claude infrastructure" (factual description, no friction)
{existing_instructions}
Session transcript:
{transcript}

Output a JSON array of objects, each with:
- "category": hierarchical category path using these prefixes:
    - "development/frontend" (styling, components, react, etc.)
    - "development/backend" (APIs, databases, etc.)
    - "development/git" (branching, PRs, commits)
    - "development/testing" (test patterns, frameworks)
    - "development/architecture" (project structure, patterns)
    - "tools/<tool-name>" (figma, jira, playwright, claude-code, etc.)
    - "workflow/<area>" (communication, setup, debugging)
    - "general/<topic>" (catch-all for anything else)
  Be specific: "development/frontend/styling" not "tool-usage", "tools/playwright" not "tools/figma" for browser testing.
- "lesson": the specific, concrete lesson (1-2 sentences max)
- "source_sessions": ["{session_id}"]
- "scope": "general" if the lesson applies broadly, or "project-specific" if it only applies to a particular project/tool
- "project_signals": list of project/tool names when scope is "project-specific". Empty list when scope is "general".

If no lessons are worth extracting, output an empty array: []

Output ONLY valid JSON, no markdown fences, no explanation."""

EXTRACTION_PROMPT = """You are analyzing Claude Code session data to extract SPECIFIC, ACTIONABLE lessons.

DO NOT extract:
- Generic advice like "investigate methodically" or "ask for clarification"
- Implementation details about specific functions/code internals (e.g. "function X has a gap" or "module Y does Z internally")
- Bug descriptions or one-time fixes that won't recur

DO extract concrete, reusable knowledge like:
- "Use mcp__plugin_playwright_playwright__browser_navigate to open URLs in the browser, not Bash commands"
- "Figma MCP server must be connected before starting UI implementation — test with a simple figma tool call first"
- "Branch naming convention: taps-NUMBER (lowercase), not TEAM-NUMBER or feature/taps-NUMBER"
- "Never use inline styles in this codebase — use CSS classes or Tailwind component props"
- "PR descriptions: max 50 words, no co-authored-by lines, no file-by-file changelog"

Each lesson should be a rule or pattern that saves time if known in advance — not a description of what happened.

Here are the session summaries and friction details:

{sessions}

Output a JSON array of objects, each with:
- "category": hierarchical category path using these prefixes:
    - "development/frontend" (styling, components, react, etc.)
    - "development/backend" (APIs, databases, etc.)
    - "development/git" (branching, PRs, commits)
    - "development/testing" (test patterns, frameworks)
    - "development/architecture" (project structure, patterns)
    - "tools/<tool-name>" (figma, jira, playwright, claude-code, etc.)
    - "workflow/<area>" (communication, setup, debugging)
    - "general/<topic>" (catch-all for anything else)
  Be specific: "development/frontend/styling" not "tool-usage", "tools/playwright" not "tools/figma" for browser testing.
- "lesson": the specific, concrete lesson (1-2 sentences max)
- "source_sessions": list of session IDs this was derived from
- "scope": "general" if the lesson applies to any project, or "project-specific" if it only applies to a particular project/tool/framework
- "project_signals": list of project/tool names when scope is "project-specific" (e.g. ["Acme", "TEAM", "Tailwind", "Figma MCP", "Playwright"]). Empty list when scope is "general".

Output ONLY valid JSON, no markdown fences, no explanation."""


def _parse_json_array(raw):
    """Robustly parse a JSON array of lesson objects from LLM output.

    Handles common issues: extra text after the array, markdown fences,
    multiple JSON objects on separate lines.

    Returns:
        list of dicts (parsed lesson array) or None if parsing fails
    """
    text = raw.strip()

    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("\n", 1)[0] if "\n" in text else text[:-3]
        text = text.strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, list) and _is_lesson_array(result):
            return result
    except json.JSONDecodeError:
        pass

    # Find complete JSON arrays by bracket matching; skip non-lesson arrays like [1]
    search_from = 0
    while True:
        start = text.find("[", search_from)
        if start == -1:
            return None

        depth = 0
        in_string = False
        escape = False
        end = None
        for i, ch in enumerate(text[start:], start):
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == '"' and not escape:
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i
                    break

        if end is None:
            return None

        try:
            candidate = json.loads(text[start:end + 1])
            if isinstance(candidate, list) and _is_lesson_array(candidate):
                return candidate
        except json.JSONDecodeError:
            pass

        search_from = end + 1

    return None


def _is_lesson_array(arr):
    """Check if a parsed JSON array looks like lesson objects.

    Returns True for empty arrays (no lessons extracted) or arrays
    where every element is a dict with a 'lesson' key.
    """
    if not arr:
        return True
    return all(isinstance(item, dict) and "lesson" in item for item in arr)


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


def _enrich_with_session_tags(prerequisites, source_sessions, db_path=None):
    """Merge env_tags from session_audit into prerequisites.

    Args:
        prerequisites: existing prerequisites dict (or None)
        source_sessions: list of session ID strings
        db_path: optional database path

    Returns:
        updated prerequisites dict, or None if no tags found and input was None
    """
    tags = get_env_tags_for_sessions(source_sessions, db_path=db_path)
    if not tags:
        return prerequisites

    if prerequisites is None:
        prerequisites = {}

    existing_tags = set(prerequisites.get("tags", []))
    existing_tags.update(tags)
    prerequisites["tags"] = sorted(existing_tags)

    return prerequisites


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
        parsed = _parse_json_array(output)
        if parsed is None:
            print(f"Failed to parse Claude output as JSON array", file=sys.stderr)
            return []
        return parsed
    except subprocess.TimeoutExpired:
        print("Claude extraction timed out", file=sys.stderr)
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
        category = lesson_data.get("category") or lesson_data.get("topic", "general")
        if "/" not in category:
            category = "general/" + category
        source_sessions = lesson_data.get("source_sessions", [])
        project_signals = lesson_data.get("project_signals", [])

        if not text:
            continue

        # Infer prerequisites from text + Haiku signals
        prerequisites = _infer_prerequisites(text, project_signals)
        prerequisites = _enrich_with_session_tags(prerequisites, source_sessions)

        # Check for similar existing lesson
        existing = find_similar_lesson(text)
        if existing:
            increment_lesson_occurrence(existing["id"], source_sessions)
            # Backfill prerequisites on existing lesson if it has none
            _maybe_backfill_prerequisites(existing["id"], prerequisites)
            merged += 1
            print(f"  Merged into lesson #{existing['id']}: {text[:60]}...")
        else:
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


def _read_transcript_metadata(jsonl_path):
    """Extract cwd and repo from a transcript JSONL's metadata entries.

    Returns:
        dict with 'cwd' and 'repo' (or None for each if not found)
    """
    cwd = None
    repo = None
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not cwd and "cwd" in entry:
                    cwd = entry["cwd"]
                    if "/work/" in cwd:
                        parts = cwd.split("/work/")[-1].split("/")
                        if parts:
                            repo = parts[0]
                if cwd:
                    break
    except Exception:
        pass
    return {"cwd": cwd, "repo": repo}


def _detect_tags_for_cwd(cwd):
    """Detect environment tags by temporarily switching to the given cwd.

    Returns:
        list of tag strings, or empty list if cwd doesn't exist
    """
    if not cwd or not os.path.isdir(cwd):
        return []
    original_cwd = os.getcwd()
    try:
        os.chdir(cwd)
        from .tag_detectors import detect_tags
        return detect_tags()
    except Exception:
        return []
    finally:
        os.chdir(original_cwd)


def _read_existing_instructions(cwd):
    """Read instruction files from project and user-level directories.

    Reads CLAUDE.md and AGENTS.md from:
    1. The project directory (cwd)
    2. User-level locations (~/.claude/CLAUDE.md, ~/.shared-cli-agents/AGENTS.md)

    Returns:
        str with combined instruction content, or empty string if none found.
    """
    parts = []
    home = os.path.expanduser("~")

    # User-level instruction file (standard Claude Code location)
    user_claude_md = os.path.join(home, ".claude", "CLAUDE.md")
    if os.path.exists(user_claude_md):
        try:
            with open(user_claude_md, "r") as f:
                content = f.read(4000)
            if content.strip():
                parts.append(f"--- CLAUDE.md (user) ---\n{content.strip()}")
        except Exception:
            pass

    # Project-level instruction files
    if cwd and os.path.isdir(cwd):
        for filename in ("CLAUDE.md", "AGENTS.md"):
            filepath = os.path.join(cwd, filename)
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r") as f:
                        content = f.read(4000)
                    if content.strip():
                        parts.append(f"--- {filename} (project) ---\n{content.strip()}")
                except Exception:
                    pass

    return "\n\n".join(parts)


def _read_user_prompts(jsonl_path):
    """Read user prompts from a transcript JSONL for shown-lesson matching."""
    prompts = []
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") != "user":
                    continue
                message_obj = entry.get("message", {})
                content = message_obj.get("content", "")
                if isinstance(content, list):
                    text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                    content = " ".join(text_parts)
                elif not isinstance(content, str):
                    continue
                if content and len(content) > 5:
                    prompts.append(content[:500])
    except Exception:
        pass
    return prompts


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

                # Strip engrammar injection blocks to avoid re-learning injected lessons
                content = _ENGRAMMAR_BLOCK_RE.sub("", content).strip()

                role = message_obj.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:500]}")
    except Exception:
        return ""

    result = "\n".join(messages)
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result


def _call_claude_for_transcript_extraction(transcript_text, session_id, existing_instructions=""):
    """Call claude CLI to extract lessons from a conversation transcript."""
    instructions_block = ""
    if existing_instructions:
        instructions_block = f"\nThe project already has these instructions documented — DO NOT extract lessons that restate this information:\n{existing_instructions}\n"
    prompt = TRANSCRIPT_EXTRACTION_PROMPT.format(
        transcript=transcript_text,
        session_id=session_id,
        existing_instructions=instructions_block,
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
        parsed = _parse_json_array(output)
        if parsed is None:
            print(f"Failed to parse Claude output as JSON array", file=sys.stderr)
            return []
        return parsed
    except subprocess.TimeoutExpired:
        print("Claude extraction timed out", file=sys.stderr)
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
    session_files = sorted(glob.glob(pattern), key=os.path.getmtime)

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

        # Detect env tags from the transcript's working directory
        metadata = _read_transcript_metadata(fpath)
        env_tags = _detect_tags_for_cwd(metadata.get("cwd"))

        if dry_run:
            print(f"  Would analyze {len(transcript_text)} chars of transcript")
            if env_tags:
                print(f"  Tags: {', '.join(env_tags)}")
            summary["processed"] += 1
            continue

        # Write session_audit so _enrich_with_session_tags can look up tags
        if env_tags:
            write_session_audit(session_id, [], env_tags, metadata.get("repo", ""),
                                transcript_path=fpath)

        # Read existing project instructions to avoid duplicating documented knowledge
        existing_instructions = _read_existing_instructions(metadata.get("cwd"))

        extracted = _call_claude_for_transcript_extraction(
            transcript_text, session_id, existing_instructions=existing_instructions
        )

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
            # Use category directly from LLM; fall back to topic for legacy format
            category = lesson_data.get("category") or lesson_data.get("topic", "general")
            if "/" not in category:
                category = "general/" + category
            # Always use the real session_id — don't trust LLM to echo it correctly
            source_sessions = [session_id]
            project_signals = lesson_data.get("project_signals", [])

            if not text:
                continue

            prerequisites = _infer_prerequisites(text, project_signals)
            prerequisites = _enrich_with_session_tags(prerequisites, source_sessions)

            existing = find_similar_lesson(text)
            if existing:
                increment_lesson_occurrence(existing["id"], source_sessions)
                _maybe_backfill_prerequisites(existing["id"], prerequisites)
                # Reinforce tag relevance for merged lesson
                if env_tags:
                    tag_scores = {tag: 0.5 for tag in env_tags}
                    update_tag_relevance(existing["id"], tag_scores, weight=1.0)
                merged += 1
                print(f"  Merged into lesson #{existing['id']}: {text[:60]}...")
            else:
                lesson_id = add_lesson(
                    text=text,
                    category=category,
                    source="auto-extracted",
                    source_sessions=source_sessions,
                    occurrence_count=1,
                    prerequisites=prerequisites,
                )
                # Initialize tag relevance scores from detected env tags
                if env_tags:
                    tag_scores = {tag: 0.5 for tag in env_tags}
                    update_tag_relevance(lesson_id, tag_scores, weight=1.0)
                added += 1
                prereq_str = f" prereqs={prerequisites}" if prerequisites else ""
                print(f"  Added lesson #{lesson_id} [{category}]{prereq_str}: {text[:60]}...")

        mark_sessions_processed([
            {"session_id": session_id, "had_friction": 1, "lessons_extracted": added + merged}
        ])

        # Rebuild index after each transcript so the next one can dedup against fresh embeddings
        if added > 0:
            lessons = get_all_active_lessons()
            build_index(lessons)

        summary["processed"] += 1
        summary["extracted"] += added
        summary["merged"] += merged

    if summary["extracted"] > 0 and not dry_run:
        summary["total_active"] = len(get_all_active_lessons())

    # Backfill shown_lesson_ids in session_audit records for the evaluator
    if not dry_run:
        _backfill_shown_lessons(projects_dir)

    print(f"\nDone. Processed: {summary['processed']}, "
          f"Added: {summary['extracted']}, Merged: {summary['merged']}, "
          f"Skipped: {summary['skipped']}")

    return summary


def _backfill_shown_lessons(projects_dir=None):
    """Populate shown_lesson_ids in session_audit records.

    For each audit record with empty shown_lesson_ids, searches user prompts
    from the transcript against the lesson DB to find which lessons would have
    been shown. Updates the audit record in place.
    """
    from .search import search

    conn = get_connection()
    rows = conn.execute(
        "SELECT session_id, env_tags, repo, transcript_path FROM session_audit WHERE shown_lesson_ids = '[]'"
    ).fetchall()
    conn.close()

    if not rows:
        return

    print(f"\nBackfilling shown lessons for {len(rows)} session(s)...")
    updated = 0

    for row in rows:
        session_id = row["session_id"]
        transcript_path = row["transcript_path"]

        if not transcript_path or not os.path.exists(transcript_path):
            # Try to find transcript by session_id
            if projects_dir is None:
                projects_dir = os.path.expanduser("~/.claude/projects")
            pattern = os.path.join(projects_dir, "*", f"{session_id}.jsonl")
            matches = glob.glob(pattern)
            if matches:
                transcript_path = matches[0]
            else:
                continue

        # Read user prompts from transcript
        user_prompts = _read_user_prompts(transcript_path)
        if not user_prompts:
            continue

        # Search for matching lessons
        all_lesson_ids = set()
        for prompt in user_prompts:
            if len(prompt) < 5:
                continue
            try:
                results = search(prompt, top_k=5, skip_prerequisites=True)
                for lesson in results:
                    all_lesson_ids.add(lesson["id"])
            except Exception:
                continue

        if all_lesson_ids:
            env_tags = json.loads(row["env_tags"])
            write_session_audit(
                session_id, sorted(all_lesson_ids), env_tags,
                row["repo"], transcript_path=transcript_path,
            )
            updated += 1

    print(f"  Updated {updated} audit record(s) with shown lessons.")
