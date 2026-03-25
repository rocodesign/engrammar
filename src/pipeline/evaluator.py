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

from engrammar.core.config import load_config
from engrammar.core.db import get_connection, get_unprocessed_audit_sessions
from engrammar.core.prompt_loader import load_prompt

_prompt_cache = {}

# Attribution curve parameters for #030
_ATTRIBUTION_FLOOR = 0.20
_ATTRIBUTION_CEILING = 1.0


def _attribution_weight(sim, floor=_ATTRIBUTION_FLOOR, ceiling=_ATTRIBUTION_CEILING):
    """Shifted sigmoid: convert tag similarity to evaluation attribution weight.

    High-similarity tags get disproportionately more signal.
    Tags below floor get zero attribution (natural cutoff).

    Curve:  weight = ((sim - floor) / (ceiling - floor)) ** 2
        sim 0.95 → 0.88
        sim 0.80 → 0.56
        sim 0.40 → 0.06
        sim 0.20 → 0.00
    """
    if sim <= floor:
        return 0.0
    normalized = (sim - floor) / (ceiling - floor)
    return min(normalized ** 2, 1.0)


def _compute_weighted_attribution(content_tags, prompt_tags, eval_signal):
    """Distribute eval signal across content tags weighted by prompt tag similarity.

    For each content tag, compute best cosine similarity against prompt tags,
    then apply shifted sigmoid to determine how much of the eval signal it receives.

    Args:
        content_tags: list of engram content tag strings
        prompt_tags: list of (tag, score) tuples from prompt tag detection
        eval_signal: float, the evaluation verdict to distribute

    Returns:
        dict mapping content_tag -> weighted_score, or None if computation fails
    """
    try:
        import numpy as np
        from engrammar.core.embeddings import embed_batch

        prompt_tag_names = [t for t, _s in prompt_tags]
        if not prompt_tag_names or not content_tags:
            return None

        # Embed all tags
        all_tags = list(content_tags) + prompt_tag_names
        embeddings = embed_batch(all_tags)

        n_content = len(content_tags)
        content_embs = embeddings[:n_content]
        prompt_embs = embeddings[n_content:]

        # Normalize
        c_norms = np.linalg.norm(content_embs, axis=1, keepdims=True) + 1e-10
        p_norms = np.linalg.norm(prompt_embs, axis=1, keepdims=True) + 1e-10
        content_normed = content_embs / c_norms
        prompt_normed = prompt_embs / p_norms

        # Sim matrix: (n_content, n_prompt)
        sim_matrix = content_normed @ prompt_normed.T

        # Per content tag: best similarity against any prompt tag
        best_sims = sim_matrix.max(axis=1)  # (n_content,)

        # Apply shifted sigmoid and distribute signal
        weighted_scores = {}
        for i, tag in enumerate(content_tags):
            weight = _attribution_weight(float(best_sims[i]))
            if weight > 0:
                weighted_scores[tag] = eval_signal * weight

        return weighted_scores if weighted_scores else None

    except Exception:
        return None


def _get_prompt(name):
    """Load and cache a prompt from prompts/ directory."""
    if name not in _prompt_cache:
        _prompt_cache[name] = load_prompt(name)
    return _prompt_cache[name]


def _parse_transcript_turns(transcript_path):
    """Parse a transcript JSONL into a list of (timestamp, role, text) turns.

    Only includes user and assistant turns with text content.
    Strips engrammar injection blocks to avoid self-referential evaluation.
    """
    import re
    _ENGRAMMAR_BLOCK_RE = re.compile(
        r"\[ENGRAMMAR_V1\].*?\[/ENGRAMMAR_V1\]", re.DOTALL
    )

    turns = []
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

                content = _ENGRAMMAR_BLOCK_RE.sub("", content).strip()
                if not content:
                    continue

                role = message_obj.get("role", entry.get("type", ""))
                ts = entry.get("timestamp", "")
                turns.append((ts, role, content))
    except Exception:
        pass
    return turns


def _extract_local_windows(transcript_path, shown_context, max_chars_per_window=2000):
    """Extract transcript windows around the turns where engrams were shown.

    For each shown engram, finds the user prompt that triggered the search
    and extracts: [user prompt] + [assistant response] + [next user turn].
    This gives the evaluator exactly the context needed to judge whether
    the engram's advice was acted on.

    Args:
        transcript_path: path to the session JSONL
        shown_context: list of dicts from get_shown_engram_context() with
            engram_id, hook_event, query_text, shown_at timestamp
        max_chars_per_window: max chars per window

    Returns:
        str: combined windows with markers, or empty string on failure
    """
    turns = _parse_transcript_turns(transcript_path)
    if not turns:
        return ""

    # Index turns by approximate timestamp for matching
    # shown_at is ISO format like "2026-03-22T14:29:33.905126"
    # transcript timestamps are "2026-03-22T00:14:11.934Z"
    # Find the user turn whose text best matches the query_text

    windows = []
    seen_turn_indices = set()

    for ctx in shown_context:
        query = ctx.get("query_text", "")
        if not query:
            continue

        # Find the user turn that best matches this query
        best_idx = None
        best_overlap = 0
        query_words = set(query.lower().split()[:10])

        for i, (ts, role, text) in enumerate(turns):
            if role != "user":
                continue
            turn_words = set(text.lower().split()[:20])
            overlap = len(query_words & turn_words)
            if overlap > best_overlap:
                best_overlap = overlap
                best_idx = i

        if best_idx is None or best_overlap < 2:
            continue

        # Skip if we already have a window for this turn
        if best_idx in seen_turn_indices:
            continue
        seen_turn_indices.add(best_idx)

        # Extract window: [user prompt] + [assistant response(s)] + [next user turn]
        window_parts = []
        chars = 0

        # The triggering user turn
        _, role, text = turns[best_idx]
        truncated = text[:max_chars_per_window // 3]
        window_parts.append(f"user: {truncated}")
        chars += len(truncated)

        # Following turns (assistant response + next user reaction)
        for j in range(best_idx + 1, min(best_idx + 6, len(turns))):
            ts_j, role_j, text_j = turns[j]
            remaining = max_chars_per_window - chars
            if remaining < 100:
                break
            truncated_j = text_j[:remaining]
            window_parts.append(f"{role_j}: {truncated_j}")
            chars += len(truncated_j)
            # Stop after first user response (the reaction)
            if role_j == "user":
                break

        if window_parts:
            engram_ids = [c["engram_id"] for c in shown_context
                          if c.get("query_text") == query]
            header = f"[Context for engram(s) {engram_ids}]"
            windows.append(header + "\n" + "\n".join(window_parts))

    if not windows:
        return ""

    return "\n\n---\n\n".join(windows)


def _find_transcript_excerpt(session_id, max_chars=6000):
    """Search ~/.claude/projects/ for a JSONL matching this session ID.

    Returns head + tail of the transcript to cover both early and late interactions.
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

    # Take head + tail to cover both early and late interactions
    result = "\n".join(messages)
    if len(result) > max_chars:
        ellipsis = "\n\n[...]\n\n"
        half = (max_chars - len(ellipsis)) // 2
        result = result[:half] + ellipsis + result[-half:]
    return result


def _read_transcript_file(transcript_path, max_chars=6000):
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
        ellipsis = "\n\n[...]\n\n"
        half = (max_chars - len(ellipsis)) // 2
        result = result[:half] + ellipsis + result[-half:]
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
    def _format_engram(e):
        return f"- ID {e['id']}: {e['text']}"

    engrams_block = "\n".join(_format_engram(l) for l in shown_engrams)

    prompt = _get_prompt("evaluation/tag_relevance.md").format(
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
            ["claude", "-p", prompt, "--model", load_config().get("models", {}).get("evaluation", "haiku"),
             "--output-format", "text", "--no-session-persistence"],
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

        evaluations = json.loads(output)
        # Enforce transcript evidence gate: cap score at +1 when no quote found
        for ev in evaluations:
            found = ev.get("found", "")
            score = ev.get("score", 0)
            if (not found or found.upper().strip() == "NO") and score > 1:
                ev["score"] = 1
        return evaluations
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

    # Load per-engram prompt context for weighted attribution (#030)
    engram_context = {}
    try:
        ctx_raw = row["engram_context"] if "engram_context" in row.keys() else None
        if ctx_raw:
            engram_context = json.loads(ctx_raw)
    except (json.JSONDecodeError, TypeError):
        pass

    if not shown_engram_ids:
        conn.close()
        return True  # Nothing to evaluate

    # Load engram texts and content tags
    placeholders = ",".join("?" * len(shown_engram_ids))
    engrams = conn.execute(
        f"SELECT id, text FROM engrams WHERE id IN ({placeholders})",
        tuple(shown_engram_ids),
    ).fetchall()

    if not engrams:
        conn.close()
        return True  # Engrams may have been deleted

    from engrammar.core.db import get_content_tags_batch
    content_tags_map = get_content_tags_batch(shown_engram_ids, db_path=db_path)
    conn.close()

    shown_engrams = []
    for r in engrams:
        entry = {"id": r["id"], "text": r["text"], "tags": content_tags_map.get(r["id"], [])}
        # Add matched_tags from engram_context — the prompt tags that caused the match
        ctx = engram_context.get(str(r["id"]), {})
        prompt_tags = ctx.get("prompt_tags")  # [(tag, score), ...]
        if prompt_tags:
            entry["matched_tags"] = [t for t, _s in prompt_tags]
        shown_engrams.append(entry)

    # Find transcript — combine local windows (#016) with head+tail fallback.
    # Local windows provide precise context for matched engrams;
    # head+tail covers engrams from tool/session-start hooks that don't
    # match a specific user turn.
    transcript = ""

    # Always get head+tail as the baseline
    if transcript_path and os.path.isfile(transcript_path):
        transcript = _read_transcript_file(transcript_path)
    if not transcript:
        transcript = _find_transcript_excerpt(session_id)

    # Prepend local windows for engrams with prompt context (#016)
    if transcript_path and os.path.isfile(transcript_path) and engram_context:
        try:
            from engrammar.core.db import get_shown_engram_context
            shown_ctx = get_shown_engram_context(session_id, db_path=db_path)
            if shown_ctx:
                local = _extract_local_windows(transcript_path, shown_ctx)
                if local:
                    transcript = local + "\n\n--- Session overview (head+tail) ---\n\n" + transcript
        except Exception:
            pass

    # Call Claude for evaluation — batch large sets to avoid quality degradation
    BATCH_SIZE = 15
    evaluations = []
    if len(shown_engrams) <= BATCH_SIZE:
        evaluations = _call_claude_for_evaluation(
            session_id, shown_engrams, env_tags, repo, transcript
        )
    else:
        for i in range(0, len(shown_engrams), BATCH_SIZE):
            batch = shown_engrams[i:i + BATCH_SIZE]
            batch_results = _call_claude_for_evaluation(
                session_id, batch, env_tags, repo, transcript
            )
            if batch_results:
                evaluations.extend(batch_results)

    if not evaluations:
        # Mark as failed, increment retry
        _mark_session_status(session_id, "failed", db_path)
        return False

    # Distribute evaluation scores to tags via attribution (#030)
    # Claude returns a single score per engram (-3 to +3). We distribute
    # that score to content tags weighted by prompt-tag similarity (which
    # tags caused the match get more signal), and to env tags uniformly.
    try:
        from engrammar.core.db import update_tag_relevance, get_content_tags
        for ev in evaluations:
            engram_id = ev.get("engram_id")
            score = ev.get("score", 0)
            if not engram_id or score == 0:
                continue

            # Normalize score to [-1, 1] range for tag relevance EMA
            normalized = score / 3.0

            # 1. Env tag scoring: uniform signal on repo tag
            if repo:
                update_tag_relevance(engram_id, {f"repo:{repo}": normalized}, weight=1.0, db_path=db_path)

            # 2. Content tag scoring: weighted by prompt-tag similarity
            content_tags = get_content_tags(engram_id, db_path=db_path)
            if not content_tags:
                continue

            ctx = engram_context.get(str(engram_id), {})
            prompt_tags = ctx.get("prompt_tags") if ctx else None

            if prompt_tags:
                # Weighted attribution: matched tags get more signal
                weighted = _compute_weighted_attribution(content_tags, prompt_tags, normalized)
                if weighted:
                    update_tag_relevance(engram_id, weighted, weight=1.0, db_path=db_path)
                    continue

            # Fallback: uniform distribution when no prompt context available
            uniform = {tag: normalized for tag in content_tags}
            update_tag_relevance(engram_id, uniform, weight=1.0, db_path=db_path)
    except ImportError:
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
