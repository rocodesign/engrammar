"""Extract engrams from Claude Code session facets.

Reads session facets from ~/.claude/usage-data/facets/, sends friction sessions
to Claude haiku for analysis, and imports extracted engrams into the Engrammar DB.
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
    add_engram,
    deprecate_engram,
    find_similar_engram,
    get_all_active_engrams,
    get_connection,
    get_env_tags_for_sessions,
    get_processed_session_ids,
    increment_engram_occurrence,
    mark_sessions_processed,
    update_tag_relevance,
    write_session_audit,
)
from .embeddings import build_index, embed_batch
from .prompt_loader import load_prompt

FACETS_DIR = Path.home() / ".claude" / "usage-data" / "facets"
MAX_LESSONS_PER_BATCH = 30

# Keyword → structural prerequisites mapping for auto-inference
KEYWORD_PREREQUISITES = {
    "figma mcp": {"mcp_servers": ["figma"]},
    "figma server": {"mcp_servers": ["figma"]},
}

# Prompts loaded from prompts/ directory (lazily cached)
_prompt_cache = {}


def _get_prompt(name):
    """Load and cache a prompt from prompts/ directory."""
    if name not in _prompt_cache:
        _prompt_cache[name] = load_prompt(name)
    return _prompt_cache[name]


def _parse_json_array(raw):
    """Robustly parse a JSON array of engram objects from LLM output.

    Handles common issues: extra text after the array, markdown fences,
    multiple JSON objects on separate lines.

    Returns:
        list of dicts (parsed engram array) or None if parsing fails
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
        if isinstance(result, list) and _is_engram_array(result):
            return result
    except json.JSONDecodeError:
        pass

    # Find complete JSON arrays by bracket matching; skip non-engram arrays like [1]
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
            if isinstance(candidate, list) and _is_engram_array(candidate):
                return candidate
        except json.JSONDecodeError:
            pass

        search_from = end + 1

    return None


def _is_engram_array(arr):
    """Check if a parsed JSON array looks like engram objects.

    Returns True for empty arrays (no engrams extracted) or arrays
    where every element is a dict with a 'engram' key.
    """
    if not arr:
        return True
    return all(isinstance(item, dict) and "engram" in item for item in arr)


def _infer_prerequisites(text, project_signals=None):
    """Infer prerequisites from engram text and optional project signals.

    Args:
        text: the engram text
        project_signals: optional list of project names from Haiku output

    Returns:
        dict of prerequisites (e.g. {"tags": ["acme"]}) or None
    """
    merged = {}
    text_lower = text.lower()

    # Check keyword map against engram text
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


def _maybe_backfill_prerequisites(engram_id, prerequisites, db_path=None):
    """Backfill prerequisites on an existing engram if it has none.

    Args:
        engram_id: existing engram to potentially update
        prerequisites: dict of prerequisites to set
        db_path: optional database path
    """
    if not prerequisites:
        return

    from .db import get_connection

    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT prerequisites FROM engrams WHERE id = ?", (engram_id,)
    ).fetchone()

    if row and not row["prerequisites"]:
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE engrams SET prerequisites = ?, updated_at = ? WHERE id = ?",
            (json.dumps(prerequisites), now, engram_id),
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
    """Call claude CLI in headless mode to extract engrams from sessions."""
    session_text = _format_sessions_for_prompt(sessions)
    prompt = _get_prompt("extraction/facet.md").format(sessions=session_text)

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
            stdin=subprocess.DEVNULL,
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
                {"session_id": f["session_id"], "had_friction": 0, "engrams_extracted": 0}
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

    # Extract engrams via Claude haiku
    # Batch if there are many sessions
    all_extracted = []
    for i in range(0, len(friction_sessions), MAX_LESSONS_PER_BATCH):
        batch = friction_sessions[i:i + MAX_LESSONS_PER_BATCH]
        extracted = _call_claude_for_extraction(batch)
        all_extracted.extend(extracted)

    if not all_extracted:
        print("  No engrams extracted.")
        # Still mark sessions as processed
        mark_sessions_processed([
            {"session_id": f["session_id"],
             "had_friction": 1 if f.get("friction_detail") else 0,
             "engrams_extracted": 0}
            for f in new_facets
        ])
        return summary

    # Import extracted engrams into DB
    added = 0
    merged = 0
    for engram_data in all_extracted:
        text = engram_data.get("engram", "")
        category = engram_data.get("category") or engram_data.get("topic", "general")
        if "/" not in category:
            category = "general/" + category
        source_sessions = engram_data.get("source_sessions", [])
        project_signals = engram_data.get("project_signals", [])

        if not text:
            continue

        # Infer prerequisites from text + Haiku signals
        prerequisites = _infer_prerequisites(text, project_signals)
        prerequisites = _enrich_with_session_tags(prerequisites, source_sessions)

        # Check for similar existing engram
        existing = find_similar_engram(text)
        if existing:
            increment_engram_occurrence(existing["id"], source_sessions)
            # Backfill prerequisites on existing engram if it has none
            _maybe_backfill_prerequisites(existing["id"], prerequisites)
            merged += 1
            print(f"  Merged into engram #{existing['id']}: {text[:60]}...")
        else:
            engram_id = add_engram(
                text=text,
                category=category,
                source="auto-extracted",
                source_sessions=source_sessions,
                occurrence_count=len(source_sessions) if source_sessions else 1,
                prerequisites=prerequisites,
            )
            added += 1
            prereq_str = f" prereqs={prerequisites}" if prerequisites else ""
            print(f"  Added engram #{engram_id} [{category}]{prereq_str}: {text[:60]}...")

    summary["extracted"] = added
    summary["merged"] = merged

    # Rebuild embedding index if new engrams were added
    if added > 0:
        print("  Rebuilding embedding index...")
        engrams = get_all_active_engrams()
        build_index(engrams)
        print(f"  Indexed {len(engrams)} engrams.")

    # Mark all new sessions as processed
    mark_sessions_processed([
        {"session_id": f["session_id"],
         "had_friction": 1 if f.get("friction_detail") else 0,
         "engrams_extracted": 1 if f.get("friction_detail") else 0}
        for f in new_facets
    ])

    summary["total_active"] = len(get_all_active_engrams())
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
    """Read user prompts from a transcript JSONL for shown-engram matching."""
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

                # Strip engrammar injection blocks to avoid re-learning injected engrams
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


def _read_transcript_messages_chunked(jsonl_path, chunk_chars=30000, overlap_chars=4000, msg_max_chars=1500):
    """Read a transcript JSONL and return overlapping chunks for extraction.

    Reads all messages, then splits into chunks at message boundaries with overlap.
    The overlap ensures friction patterns (wrong attempt -> user correction) spanning
    a boundary are captured in at least one chunk.

    Args:
        jsonl_path: path to transcript JSONL
        chunk_chars: target size per chunk (chars)
        overlap_chars: overlap between consecutive chunks
        msg_max_chars: per-message truncation limit (higher than default 500 to
                       preserve assistant wrong attempts needed for friction detection)

    Returns:
        list of chunk strings, each ready to send to extraction
    """
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

                content = _ENGRAMMAR_BLOCK_RE.sub("", content).strip()
                role = message_obj.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:msg_max_chars]}")
    except Exception:
        return []

    if not messages:
        return []

    # Single chunk if small enough
    full_text = "\n".join(messages)
    if len(full_text) <= chunk_chars:
        return [full_text]

    # Split into overlapping chunks at message boundaries
    chunks = []
    start_idx = 0

    while start_idx < len(messages):
        # Accumulate messages until we hit chunk_chars
        chunk_messages = []
        chunk_len = 0
        idx = start_idx

        while idx < len(messages):
            msg_len = len(messages[idx]) + 1  # +1 for newline
            if chunk_len + msg_len > chunk_chars and chunk_messages:
                break
            chunk_messages.append(messages[idx])
            chunk_len += msg_len
            idx += 1

        chunks.append("\n".join(chunk_messages))

        if idx >= len(messages):
            break

        # Step back by overlap_chars worth of messages for the next chunk
        overlap_len = 0
        overlap_start = idx
        while overlap_start > start_idx and overlap_len < overlap_chars:
            overlap_start -= 1
            overlap_len += len(messages[overlap_start]) + 1

        start_idx = overlap_start if overlap_start > start_idx else idx

    return chunks


def _call_claude_for_transcript_extraction(transcript_text, session_id, existing_instructions=""):
    """Call claude CLI to extract engrams from a conversation transcript."""
    instructions_block = ""
    if existing_instructions:
        instructions_block = f"\nThe project already has these instructions documented — DO NOT extract engrams that restate this information:\n{existing_instructions}\n"
    prompt = _get_prompt("extraction/transcript.md").format(
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
            stdin=subprocess.DEVNULL,
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


def _process_extracted_engrams(extracted, session_id, env_tags):
    """Process extracted engram data — dedup, add to DB, update tag relevance.

    Args:
        extracted: list of engram dicts from Haiku (with 'engram', 'category', etc.)
        session_id: the source session ID
        env_tags: list of environment tag strings for this session

    Returns:
        tuple of (added_count, merged_count)
    """
    added = 0
    merged = 0
    for engram_data in extracted:
        text = engram_data.get("engram", "")
        category = engram_data.get("category") or engram_data.get("topic", "general")
        if "/" not in category:
            category = "general/" + category
        source_sessions = [session_id]
        project_signals = engram_data.get("project_signals", [])

        if not text:
            continue

        prerequisites = _infer_prerequisites(text, project_signals)
        prerequisites = _enrich_with_session_tags(prerequisites, source_sessions)

        existing = find_similar_engram(text)
        if existing:
            increment_engram_occurrence(existing["id"], source_sessions)
            _maybe_backfill_prerequisites(existing["id"], prerequisites)
            if env_tags:
                tag_scores = {tag: 0.5 for tag in env_tags}
                update_tag_relevance(existing["id"], tag_scores, weight=1.0)
            merged += 1
            print(f"  Merged into engram #{existing['id']}: {text[:60]}...")
        else:
            engram_id = add_engram(
                text=text,
                category=category,
                source="auto-extracted",
                source_sessions=source_sessions,
                occurrence_count=1,
                prerequisites=prerequisites,
            )
            if env_tags:
                tag_scores = {tag: 0.5 for tag in env_tags}
                update_tag_relevance(engram_id, tag_scores, weight=1.0)
            added += 1
            prereq_str = f" prereqs={prerequisites}" if prerequisites else ""
            print(f"  Added engram #{engram_id} [{category}]{prereq_str}: {text[:60]}...")

    return added, merged


def extract_from_single_session(session_id, transcript_path=None, projects_dir=None):
    """Extract engrams from a single session transcript.

    Used by the session-end hook for automatic extraction, or via
    `engrammar extract --session <uuid>`.

    Args:
        session_id: the session UUID to extract from
        transcript_path: optional path to the transcript JSONL
        projects_dir: override projects directory for transcript lookup

    Returns:
        dict with summary: {extracted, merged}
    """
    # Find transcript if not provided
    if not transcript_path:
        if projects_dir is None:
            projects_dir = os.path.expanduser("~/.claude/projects")
        pattern = os.path.join(projects_dir, "*", f"{session_id}.jsonl")
        matches = glob.glob(pattern)
        if not matches:
            print(f"No transcript found for session {session_id[:12]}")
            return {"extracted": 0, "merged": 0}
        transcript_path = matches[0]

    # Skip agent sessions (small transcripts < 10KB)
    if os.path.getsize(transcript_path) < 10_000:
        print(f"  Skipped (agent/short session)")
        return {"extracted": 0, "merged": 0}

    # Skip if already processed
    processed_ids = get_processed_session_ids()
    if session_id in processed_ids:
        print(f"Session {session_id[:12]} already processed.")
        return {"extracted": 0, "merged": 0}

    transcript_text = _read_transcript_messages(transcript_path)
    if not transcript_text or len(transcript_text) < 100:
        print(f"  Skipped (too short)")
        mark_sessions_processed([
            {"session_id": session_id, "had_friction": 0, "engrams_extracted": 0}
        ])
        return {"extracted": 0, "merged": 0}

    metadata = _read_transcript_metadata(transcript_path)
    env_tags = _detect_tags_for_cwd(metadata.get("cwd"))

    # Write session audit so _enrich_with_session_tags can look up tags
    if env_tags:
        write_session_audit(session_id, [], env_tags, metadata.get("repo", ""),
                            transcript_path=transcript_path)

    existing_instructions = _read_existing_instructions(metadata.get("cwd"))

    print(f"Extracting from session {session_id[:12]}...")
    extracted = _call_claude_for_transcript_extraction(
        transcript_text, session_id, existing_instructions=existing_instructions
    )

    if not extracted:
        print("  No engrams extracted.")
        mark_sessions_processed([
            {"session_id": session_id, "had_friction": 0, "engrams_extracted": 0}
        ])
        return {"extracted": 0, "merged": 0}

    added, merged = _process_extracted_engrams(extracted, session_id, env_tags)

    mark_sessions_processed([
        {"session_id": session_id, "had_friction": 1, "engrams_extracted": added + merged}
    ])

    # Rebuild index so new engrams are immediately searchable
    if added > 0:
        engrams = get_all_active_engrams()
        build_index(engrams)

    print(f"  Done. Added: {added}, Merged: {merged}")
    return {"extracted": added, "merged": merged}


def extract_from_transcripts(limit=None, dry_run=False, projects_dir=None):
    """Extract engrams from real conversation transcripts (not facets).

    Reads JSONL transcripts from ~/.claude/projects/, sends them to Haiku
    for engram extraction using the same criteria as MCP self-extraction
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

    # Find all transcript files (top-level only — excludes subagent transcripts)
    pattern = os.path.join(projects_dir, "*", "*.jsonl")
    session_files = sorted(glob.glob(pattern), key=os.path.getmtime)

    # Skip small transcripts (< 10KB) — agent sessions and trivial interactions
    session_files = [f for f in session_files if os.path.getsize(f) >= 10_000]

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
                    {"session_id": session_id, "had_friction": 0, "engrams_extracted": 0}
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
            print("  No engrams extracted.")
            mark_sessions_processed([
                {"session_id": session_id, "had_friction": 0, "engrams_extracted": 0}
            ])
            summary["processed"] += 1
            continue

        added, merged = _process_extracted_engrams(extracted, session_id, env_tags)

        mark_sessions_processed([
            {"session_id": session_id, "had_friction": 1, "engrams_extracted": added + merged}
        ])

        # Rebuild index after each transcript so the next one can dedup against fresh embeddings
        if added > 0:
            engrams = get_all_active_engrams()
            build_index(engrams)

        summary["processed"] += 1
        summary["extracted"] += added
        summary["merged"] += merged

    if summary["extracted"] > 0 and not dry_run:
        summary["total_active"] = len(get_all_active_engrams())

    # Backfill shown_engram_ids in session_audit records for the evaluator
    if not dry_run:
        _backfill_shown_engrams(projects_dir)

    print(f"\nDone. Processed: {summary['processed']}, "
          f"Added: {summary['extracted']}, Merged: {summary['merged']}, "
          f"Skipped: {summary['skipped']}")

    return summary


def _read_turn_offset(session_id):
    """Read the byte offset for a session's last processed turn.

    Returns:
        int: byte offset (0 if no offset file exists)
    """
    offset_dir = os.path.join(
        os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar")),
        ".turn_offsets",
    )
    offset_file = os.path.join(offset_dir, session_id)
    try:
        with open(offset_file, "r") as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return 0


def _write_turn_offset(session_id, offset):
    """Write the byte offset for a session's last processed turn."""
    offset_dir = os.path.join(
        os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar")),
        ".turn_offsets",
    )
    os.makedirs(offset_dir, exist_ok=True)
    offset_file = os.path.join(offset_dir, session_id)
    with open(offset_file, "w") as f:
        f.write(str(offset))


def _read_transcript_from_offset(jsonl_path, byte_offset, max_chars=8000):
    """Read transcript messages starting from byte_offset.

    Returns:
        tuple of (formatted_text, new_byte_offset)
    """
    messages = []
    try:
        with open(jsonl_path, "rb") as f:
            f.seek(byte_offset)
            new_offset = byte_offset
            for raw_line in f:
                new_offset = f.tell()
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
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

                content = _ENGRAMMAR_BLOCK_RE.sub("", content).strip()
                role = message_obj.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:500]}")
    except Exception:
        return "", byte_offset

    result = "\n".join(messages)
    if len(result) > max_chars:
        result = result[-max_chars:]
    return result, new_offset


def _read_transcript_context(jsonl_path, byte_offset, max_chars=2000):
    """Read prior context (tail of content before byte_offset) for continuity.

    Returns:
        str: formatted message text from before the offset
    """
    if byte_offset <= 0:
        return ""

    messages = []
    try:
        with open(jsonl_path, "rb") as f:
            while f.tell() < byte_offset:
                raw_line = f.readline()
                if not raw_line:
                    break
                if f.tell() > byte_offset:
                    break
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
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


def cleanup_old_turn_offsets(max_age_hours=24):
    """Delete turn offset files older than max_age_hours."""
    offset_dir = os.path.join(
        os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar")),
        ".turn_offsets",
    )
    if not os.path.isdir(offset_dir):
        return
    now = datetime.now(timezone.utc).timestamp()
    cutoff = now - (max_age_hours * 3600)
    for fname in os.listdir(offset_dir):
        fpath = os.path.join(offset_dir, fname)
        try:
            if os.path.getmtime(fpath) < cutoff:
                os.unlink(fpath)
        except OSError:
            pass


def extract_from_turn(session_id, transcript_path):
    """Extract engrams from new transcript content since last turn.

    Called by the Stop hook (via daemon) after each assistant response.
    Uses byte offsets to only process new content.

    Args:
        session_id: the session UUID
        transcript_path: path to the transcript JSONL

    Returns:
        dict with summary: {extracted, merged, skipped_reason}
    """
    if not transcript_path or not os.path.exists(transcript_path):
        return {"extracted": 0, "merged": 0, "skipped_reason": "no_transcript"}

    # Skip agent sessions (small transcripts < 10KB)
    if os.path.getsize(transcript_path) < 10_000:
        return {"extracted": 0, "merged": 0, "skipped_reason": "small_transcript"}

    # Read byte offset
    byte_offset = _read_turn_offset(session_id)

    # Read new messages from offset
    new_text, new_offset = _read_transcript_from_offset(transcript_path, byte_offset)

    # Skip if no meaningful new content
    if not new_text or len(new_text) < 50:
        # Still update offset so we don't re-read non-message lines
        if new_offset > byte_offset:
            _write_turn_offset(session_id, new_offset)
        return {"extracted": 0, "merged": 0, "skipped_reason": "too_short"}

    # Read prior context for continuity
    context = _read_transcript_context(transcript_path, byte_offset)

    # Combine context + new content for extraction
    if context:
        full_text = f"[Prior context]\n{context}\n\n[New conversation]\n{new_text}"
    else:
        full_text = new_text

    # Get metadata and env tags
    metadata = _read_transcript_metadata(transcript_path)
    env_tags = _detect_tags_for_cwd(metadata.get("cwd"))

    # Write session audit so _enrich_with_session_tags works
    if env_tags:
        write_session_audit(session_id, [], env_tags, metadata.get("repo", ""),
                            transcript_path=transcript_path)

    # Read existing instructions to avoid duplicating documented knowledge
    existing_instructions = _read_existing_instructions(metadata.get("cwd"))

    print(f"Extracting from turn (session {session_id[:12]}, offset {byte_offset}->{new_offset})...")
    extracted = _call_claude_for_transcript_extraction(
        full_text, session_id, existing_instructions=existing_instructions
    )

    if not extracted:
        print("  No engrams extracted from turn.")
        _write_turn_offset(session_id, new_offset)
        return {"extracted": 0, "merged": 0}

    added, merged = _process_extracted_engrams(extracted, session_id, env_tags)

    # Rebuild index so new engrams are immediately searchable
    if added > 0:
        engrams = get_all_active_engrams()
        build_index(engrams)

    # Save new offset
    _write_turn_offset(session_id, new_offset)

    print(f"  Turn done. Added: {added}, Merged: {merged}")
    return {"extracted": added, "merged": merged}


def _backfill_shown_engrams(projects_dir=None):
    """Populate shown_engram_ids in session_audit records.

    For each audit record with empty shown_engram_ids, searches user prompts
    from the transcript against the engram DB to find which engrams would have
    been shown. Updates the audit record in place.
    """
    from .search import search

    conn = get_connection()
    rows = conn.execute(
        "SELECT session_id, env_tags, repo, transcript_path FROM session_audit WHERE shown_engram_ids = '[]'"
    ).fetchall()
    conn.close()

    if not rows:
        return

    print(f"\nBackfilling shown engrams for {len(rows)} session(s)...")
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

        # Search for matching engrams
        all_engram_ids = set()
        for prompt in user_prompts:
            if len(prompt) < 5:
                continue
            try:
                results = search(prompt, top_k=5, skip_prerequisites=True)
                for engram in results:
                    all_engram_ids.add(engram["id"])
            except Exception:
                continue

        if all_engram_ids:
            env_tags = json.loads(row["env_tags"])
            write_session_audit(
                session_id, sorted(all_engram_ids), env_tags,
                row["repo"], transcript_path=transcript_path,
            )
            updated += 1

    print(f"  Updated {updated} audit record(s) with shown engrams.")


def reextract_engrams(category=None, limit=None, prune=False, dry_run=False):
    """Re-extract from source sessions and identify engrams the current prompt wouldn't extract.

    Loads active auto-extracted engrams, groups by source session, re-runs extraction
    with the current prompt, and compares via embedding similarity. Engrams that no
    re-extracted engram matches are "unconfirmed" — optionally pruned.

    Args:
        category: only check engrams in this category (prefix match)
        limit: max engrams to check
        prune: if True, deprecate unconfirmed engrams
        dry_run: if True, list what would be checked without calling Haiku

    Returns:
        dict with confirmed, unconfirmed, skipped counts and unconfirmed details
    """
    import numpy as np

    projects_dir = os.path.expanduser("~/.claude/projects")

    # 1. Load target engrams (active, auto-extracted only)
    all_engrams = get_all_active_engrams()
    target_engrams = [
        e for e in all_engrams
        if e.get("source") not in ("manual", "self-extracted")
    ]

    if category:
        target_engrams = [
            e for e in target_engrams
            if (e.get("category") or "").startswith(category)
        ]

    if limit:
        target_engrams = target_engrams[:limit]

    if not target_engrams:
        print("No eligible engrams to re-check.")
        return {"confirmed": 0, "unconfirmed": 0, "skipped": 0, "unconfirmed_engrams": []}

    print(f"Checking {len(target_engrams)} engram(s)...\n")

    if dry_run:
        for e in target_engrams:
            sessions = json.loads(e.get("source_sessions") or "[]")
            print(f"  #{e['id']}: [{e.get('category', 'general')}] {e['text'][:70]}...")
            print(f"    source sessions: {len(sessions)}")
        return {
            "confirmed": 0,
            "unconfirmed": 0,
            "skipped": 0,
            "would_check": len(target_engrams),
            "unconfirmed_engrams": [],
        }

    # 2. Group engrams by source session
    #    session_id -> list of engram dicts
    session_to_engrams = {}
    engrams_without_sessions = []
    for e in target_engrams:
        sessions = json.loads(e.get("source_sessions") or "[]")
        if not sessions:
            engrams_without_sessions.append(e)
            continue
        for sid in sessions:
            session_to_engrams.setdefault(sid, []).append(e)

    # 3. For each unique session, find transcript and re-extract
    #    session_id -> list of re-extracted engram text strings
    session_reextracted = {}
    sessions_skipped = set()

    conn = get_connection()
    for session_id in session_to_engrams:
        # Look up transcript path from session_audit
        row = conn.execute(
            "SELECT transcript_path FROM session_audit WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        transcript_path = row["transcript_path"] if row and row["transcript_path"] else None

        # Glob fallback if not in audit
        if not transcript_path or not os.path.exists(transcript_path):
            pattern = os.path.join(projects_dir, "*", f"{session_id}.jsonl")
            matches = glob.glob(pattern)
            transcript_path = matches[0] if matches else None

        if not transcript_path or not os.path.exists(transcript_path):
            print(f"  Session {session_id[:12]}: transcript not found — skipping")
            sessions_skipped.add(session_id)
            continue

        # Skip tiny transcripts
        if os.path.getsize(transcript_path) < 10_000:
            print(f"  Session {session_id[:12]}: too small — skipping")
            sessions_skipped.add(session_id)
            continue

        chunks = _read_transcript_messages_chunked(transcript_path)
        if not chunks:
            print(f"  Session {session_id[:12]}: too short — skipping")
            sessions_skipped.add(session_id)
            continue

        metadata = _read_transcript_metadata(transcript_path)
        existing_instructions = _read_existing_instructions(metadata.get("cwd"))

        print(f"  Session {session_id[:12]}: re-extracting ({len(chunks)} chunk(s))...")
        texts = []
        for ci, chunk in enumerate(chunks):
            extracted = _call_claude_for_transcript_extraction(
                chunk, session_id, existing_instructions=existing_instructions
            )
            chunk_texts = [item.get("engram", "") for item in extracted if item.get("engram")]
            texts.extend(chunk_texts)
            if len(chunks) > 1:
                print(f"    chunk {ci + 1}/{len(chunks)}: {len(chunk_texts)} engram(s)")

        session_reextracted[session_id] = texts
        print(f"    got {len(texts)} engram(s) from current prompt")

    conn.close()

    # 4. Compare each existing engram against re-extracted engrams via embedding similarity
    confirmed = []
    unconfirmed = []
    skipped = []

    # Collect all unique re-extracted texts for batch embedding
    all_reextracted_texts = []
    text_to_idx = {}
    for texts in session_reextracted.values():
        for t in texts:
            if t not in text_to_idx:
                text_to_idx[t] = len(all_reextracted_texts)
                all_reextracted_texts.append(t)

    # Batch embed all re-extracted texts
    reextracted_embeddings = None
    if all_reextracted_texts:
        reextracted_embeddings = embed_batch(all_reextracted_texts)

    # Embed all target engram texts
    target_texts = [e["text"] for e in target_engrams]
    target_embeddings = embed_batch(target_texts)

    SIMILARITY_THRESHOLD = 0.80

    for i, engram in enumerate(target_engrams):
        sessions = json.loads(engram.get("source_sessions") or "[]")

        if not sessions:
            skipped.append(engram)
            continue

        # Check if ALL sessions were skipped (no data to compare)
        relevant_sessions = [s for s in sessions if s not in sessions_skipped]
        if not relevant_sessions:
            skipped.append(engram)
            continue

        # An engram is confirmed if ANY session confirms it
        is_confirmed = False
        engram_emb = target_embeddings[i]
        engram_norm = engram_emb / (np.linalg.norm(engram_emb) + 1e-10)

        for sid in relevant_sessions:
            texts = session_reextracted.get(sid, [])
            if not texts:
                continue

            # Get indices of re-extracted texts for this session
            indices = [text_to_idx[t] for t in texts if t in text_to_idx]
            if not indices:
                continue

            session_embs = reextracted_embeddings[indices]
            norms = np.linalg.norm(session_embs, axis=1, keepdims=True) + 1e-10
            session_embs_normed = session_embs / norms

            similarities = session_embs_normed @ engram_norm
            max_sim = float(np.max(similarities))

            if max_sim >= SIMILARITY_THRESHOLD:
                is_confirmed = True
                break

        if is_confirmed:
            confirmed.append(engram)
        else:
            unconfirmed.append(engram)

    # 5. Report results
    print(f"\n=== Re-extraction Results ===")
    print(f"Confirmed:   {len(confirmed)} (current prompt still extracts these)")
    print(f"Unconfirmed: {len(unconfirmed)} (current prompt would NOT extract these)")
    print(f"Skipped:     {len(skipped)} (no transcript found or no sessions)")

    if unconfirmed:
        print(f"\nUnconfirmed engrams:")
        for e in unconfirmed:
            print(f"  #{e['id']}: [{e.get('category', 'general')}] {e['text'][:80]}...")

    # 6. Prune if requested
    if prune and unconfirmed:
        print(f"\nDeprecating {len(unconfirmed)} unconfirmed engram(s)...")
        for e in unconfirmed:
            deprecate_engram(e["id"])
            print(f"  Deprecated #{e['id']}")

        # Rebuild index after deprecations
        from .embeddings import build_index as rebuild_index, build_tag_index
        remaining = get_all_active_engrams()
        rebuild_index(remaining)
        build_tag_index(remaining)
        print("Index rebuilt.")

    return {
        "confirmed": len(confirmed),
        "unconfirmed": len(unconfirmed),
        "skipped": len(skipped),
        "unconfirmed_engrams": [
            {"id": e["id"], "category": e.get("category", "general"), "text": e["text"]}
            for e in unconfirmed
        ],
    }
