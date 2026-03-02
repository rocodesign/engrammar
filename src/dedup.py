"""LLM-assisted engram deduplication pipeline."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone

import numpy as np

from .db import (
    get_connection,
    get_unverified_engrams,
    get_verified_engrams,
    mark_dedup_verified,
    merge_engram_group,
    record_dedup_error,
)
from .embeddings import embed_batch, build_index, build_tag_index

# --- Prompt constants ---

DEDUP_SYSTEM_PROMPT = """You are deduplicating "engrams" — short actionable lessons extracted from coding sessions.

Your job:
1) Identify true duplicate groups.
2) Propose one canonical text per duplicate group.
3) Report unmatched IDs according to mode-specific accounting rules.

High precision is required. If uncertain, do NOT merge.

Merge only when ALL are true:
- Same core action/recommendation
- Same expected outcome or rationale
- Context constraints are compatible (same or overlapping domains)

Do NOT merge when ANY are true:
- They are topically related but prescribe different actions
- One is broader/umbrella guidance and another is a specific sub-rule
- Details conflict (commands, flags, file paths, versions, APIs)

IMPORTANT: If two engrams express the same lesson but were learned in different
project contexts (e.g., one from "toptal" and one from "engrammar"), MERGE them
and GENERALIZE the canonical text to be context-independent. The tag/prerequisite
system handles context filtering separately — your job is to produce the best
universal phrasing of the lesson.

Canonical text rules:
- 1-2 sentences, concrete and actionable
- Generalize across contexts when the core lesson is the same
- Preserve important specifics from source items (commands, flags, paths, code spans)
  but drop project-specific details that don't affect the lesson
- Do not invent new facts not present in the input
- Keep wording concise and implementation-neutral

Output must be strict JSON matching the required schema. No markdown fences.
If uncertain, return fewer groups and place IDs in no_match_ids."""

INCREMENTAL_MODE_SNIPPET = """You are in INCREMENTAL mode.

Input contains:
- UNVERIFIED engrams that must be decided this pass
- VERIFIED candidate engrams that may be merge targets/bridges

Decision rules:
1) For each unverified engram, decide if it duplicates any verified candidate.
2) If a verified candidate bridges multiple unverified engrams, you may form one multi-ID group.
3) Every unverified ID must appear exactly once: either in one group or in no_match_ids.
4) Verified-only IDs must not appear in no_match_ids.
5) Every group must include at least one unverified ID."""

BOOTSTRAP_MODE_SNIPPET = """You are in BOOTSTRAP mode.

Input may contain only unverified engrams (or mostly unverified).
There is no stable verified pool yet.

Decision rules:
1) Use candidate_edges to reason globally and form duplicate groups.
2) Every input ID must appear exactly once: either in one group or in no_match_ids.
3) Groups may be formed from any IDs in the batch (no verified/unverified restriction)."""

BOOTSTRAP_VERIFIED_THRESHOLD = 3


# --- Candidate finding ---


def find_candidates_for_unverified(unverified_engrams, verified_engrams, min_sim=0.50, top_k=8):
    """For each unverified engram, find top_k verified candidates above min_sim.

    Uses vectorized cosine similarity matrix.

    Returns:
        dict mapping unverified_id -> [(verified_id, similarity), ...]
    """
    if not unverified_engrams or not verified_engrams:
        return {}

    unverified_texts = [e["text"] for e in unverified_engrams]
    verified_texts = [e["text"] for e in verified_engrams]

    unverified_embs = embed_batch(unverified_texts)
    verified_embs = embed_batch(verified_texts)

    # Normalize
    u_norms = np.linalg.norm(unverified_embs, axis=1, keepdims=True) + 1e-10
    v_norms = np.linalg.norm(verified_embs, axis=1, keepdims=True) + 1e-10
    u_normed = unverified_embs / u_norms
    v_normed = verified_embs / v_norms

    # Cosine similarity matrix: (num_unverified, num_verified)
    sim_matrix = u_normed @ v_normed.T

    candidate_map = {}
    for i, engram in enumerate(unverified_engrams):
        scores = sim_matrix[i]
        # Get top_k indices above threshold
        above_threshold = np.where(scores >= min_sim)[0]
        if len(above_threshold) == 0:
            candidate_map[engram["id"]] = []
            continue

        # Sort by score descending, take top_k
        sorted_indices = above_threshold[np.argsort(scores[above_threshold])[::-1]][:top_k]
        candidates = [
            (verified_engrams[j]["id"], float(scores[j]))
            for j in sorted_indices
        ]
        candidate_map[engram["id"]] = candidates

    return candidate_map


def find_candidates_bootstrap(all_engrams, min_sim=0.50, top_k=8):
    """For bootstrap mode: find candidates among all engrams (no verified/unverified distinction).

    Returns:
        dict mapping engram_id -> [(other_id, similarity), ...]
        Only includes pairs where source_id < target_id to avoid double counting.
    """
    if len(all_engrams) < 2:
        return {}

    texts = [e["text"] for e in all_engrams]
    embs = embed_batch(texts)

    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normed = embs / norms
    sim_matrix = normed @ normed.T

    candidate_map = {}
    for i, engram in enumerate(all_engrams):
        scores = sim_matrix[i]
        # Exclude self
        scores[i] = -1

        above_threshold = np.where(scores >= min_sim)[0]
        if len(above_threshold) == 0:
            candidate_map[engram["id"]] = []
            continue

        sorted_indices = above_threshold[np.argsort(scores[above_threshold])[::-1]][:top_k]
        candidates = [
            (all_engrams[j]["id"], float(scores[j]))
            for j in sorted_indices
        ]
        candidate_map[engram["id"]] = candidates

    return candidate_map


# --- Batch building ---


def build_batches(candidate_map, engrams_by_id, unverified_ids, char_budget=6000):
    """Group unverified+candidate pairs into batches respecting char budget.

    Returns:
        list of batch dicts, each with:
          - engrams: list of engram dicts (with status field)
          - candidate_edges: list of {source_id, target_id, similarity}
          - unverified_ids: set of unverified IDs in this batch
    """
    # Sort unverified by ID for determinism
    sorted_unverified = sorted(uid for uid in candidate_map if uid in unverified_ids)

    batches = []
    current_batch_engrams = {}  # id -> engram dict
    current_edges = []
    current_unverified = set()
    current_chars = 0

    for uid in sorted_unverified:
        candidates = candidate_map.get(uid, [])

        # Estimate chars for this unverified engram + its candidates
        engram_chars = len(engrams_by_id[uid]["text"])
        new_candidate_chars = 0
        for cid, sim in candidates:
            if cid not in current_batch_engrams:
                new_candidate_chars += len(engrams_by_id[cid]["text"])

        total_new = engram_chars + new_candidate_chars

        # If adding this would exceed budget and we have content, flush
        if current_chars + total_new > char_budget and current_unverified:
            batches.append({
                "engrams": list(current_batch_engrams.values()),
                "candidate_edges": current_edges,
                "unverified_ids": current_unverified,
            })
            current_batch_engrams = {}
            current_edges = []
            current_unverified = set()
            current_chars = 0

        # Add this unverified engram
        if uid not in current_batch_engrams:
            current_batch_engrams[uid] = _engram_to_payload(engrams_by_id[uid], uid in unverified_ids)
            current_chars += engram_chars

        current_unverified.add(uid)

        # Add its candidates
        for cid, sim in candidates:
            if cid not in current_batch_engrams:
                current_batch_engrams[cid] = _engram_to_payload(engrams_by_id[cid], cid in unverified_ids)
                current_chars += len(engrams_by_id[cid]["text"])
            current_edges.append({
                "source_id": uid,
                "target_id": cid,
                "similarity": round(sim, 4),
            })

    # Final batch
    if current_unverified:
        batches.append({
            "engrams": list(current_batch_engrams.values()),
            "candidate_edges": current_edges,
            "unverified_ids": current_unverified,
        })

    return batches


def _engram_to_payload(engram, is_unverified):
    """Convert an engram dict to the LLM payload format."""
    prereqs = engram.get("prerequisites")
    if isinstance(prereqs, str):
        try:
            prereqs = json.loads(prereqs)
        except (json.JSONDecodeError, TypeError):
            prereqs = None

    return {
        "id": engram["id"],
        "status": "unverified" if is_unverified else "verified",
        "text": engram["text"],
        "category": engram.get("category", "general"),
        "prerequisites": prereqs or {},
        "occurrence_count": engram.get("occurrence_count", 1),
    }


# --- LLM call ---


def call_dedup_llm(batch, mode="incremental", min_confidence=0.8, run_id=""):
    """Send batch to Haiku via claude CLI subprocess.

    Returns:
        parsed response dict or None on failure.
    """
    mode_snippet = INCREMENTAL_MODE_SNIPPET if mode == "incremental" else BOOTSTRAP_MODE_SNIPPET

    batch_id = f"{run_id}-batch{id(batch) % 10000}" if run_id else f"batch-{id(batch) % 10000}"

    payload = {
        "mode": mode,
        "batch_id": batch_id,
        "rules": {
            "min_confidence_hint": min_confidence,
            "max_groups": 20,
        },
        "engrams": batch["engrams"],
        "candidate_edges": batch["candidate_edges"],
    }

    system_prompt = DEDUP_SYSTEM_PROMPT + "\n\n" + mode_snippet

    prompt = f"""{system_prompt}

Here is the batch to process:

{json.dumps(payload, indent=2)}

Return strict JSON with this schema:
{{
  "groups": [
    {{
      "ids": [int, ...],
      "canonical_text": "string",
      "confidence": float,
      "reason": "string (max 160 chars)"
    }}
  ],
  "no_match_ids": [int, ...],
  "notes": []
}}"""

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
            print(f"Dedup LLM call failed: {result.stderr}", file=sys.stderr)
            return None

        output = result.stdout.strip()
        return _parse_json_response(output)
    except subprocess.TimeoutExpired:
        print("Dedup LLM call timed out", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("claude CLI not found — skipping dedup", file=sys.stderr)
        return None


def _parse_json_response(text):
    """Parse JSON from LLM output, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first and last lines (fences)
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None


# --- Response validation ---


def validate_dedup_response(response, batch, mode="incremental"):
    """Strict validation per task spec output constraints.

    Returns:
        (valid_groups, errors) where valid_groups is list of group dicts,
        errors is list of strings.
    """
    errors = []

    if not isinstance(response, dict):
        return [], ["Response is not a dict"]

    groups = response.get("groups", [])
    no_match_ids = response.get("no_match_ids", [])

    if not isinstance(groups, list):
        return [], ["groups is not a list"]
    if not isinstance(no_match_ids, list):
        return [], ["no_match_ids is not a list"]

    # Build set of all input IDs
    input_ids = {e["id"] for e in batch["engrams"]}
    unverified_ids = batch["unverified_ids"]
    verified_ids = input_ids - unverified_ids

    # Track ID accounting
    seen_ids = set()
    valid_groups = []

    for i, group in enumerate(groups):
        group_errors = []

        ids = group.get("ids", [])
        canonical_text = group.get("canonical_text", "")
        confidence = group.get("confidence", 0)
        reason = group.get("reason", "")

        # Group size >= 2
        if len(ids) < 2:
            group_errors.append(f"Group {i}: size < 2")

        # All IDs must exist in input
        unknown_ids = set(ids) - input_ids
        if unknown_ids:
            group_errors.append(f"Group {i}: unknown IDs {unknown_ids}")

        # No duplicates across groups
        duplicated = set(ids) & seen_ids
        if duplicated:
            group_errors.append(f"Group {i}: IDs {duplicated} already in another group")

        # Confidence in [0, 1]
        if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
            group_errors.append(f"Group {i}: confidence {confidence} not in [0,1]")

        # Canonical text non-empty
        if not canonical_text or not canonical_text.strip():
            group_errors.append(f"Group {i}: empty canonical_text")

        # Truncate long reasons (LLMs often exceed 160 char target)
        if len(reason) > 200:
            group["reason"] = reason[:197] + "..."

        # In incremental mode, each group must include at least one unverified ID
        if mode == "incremental":
            if not any(eid in unverified_ids for eid in ids):
                group_errors.append(f"Group {i}: no unverified ID in incremental mode")

        if group_errors:
            errors.extend(group_errors)
        else:
            seen_ids.update(ids)
            valid_groups.append(group)

    # Check no_match_ids
    for nid in no_match_ids:
        if nid not in input_ids:
            errors.append(f"no_match_ids contains unknown ID {nid}")
        if nid in seen_ids:
            errors.append(f"no_match_ids contains ID {nid} already in a group")
        seen_ids.add(nid)

    # Accounting: every unverified ID must appear exactly once
    if mode == "incremental":
        missing_unverified = unverified_ids - seen_ids
        if missing_unverified:
            errors.append(f"Unverified IDs not accounted for: {missing_unverified}")

        # Verified-only IDs must not appear in no_match_ids
        verified_in_no_match = verified_ids & set(no_match_ids)
        if verified_in_no_match:
            errors.append(f"Verified IDs in no_match_ids: {verified_in_no_match}")
    elif mode == "bootstrap":
        missing = input_ids - seen_ids
        if missing:
            errors.append(f"IDs not accounted for: {missing}")

    return valid_groups, errors


# --- Bootstrap detection ---


def should_bootstrap(db_path=None):
    """Return True if verified pool is empty or below threshold."""
    verified = get_verified_engrams(db_path=db_path)
    return len(verified) < BOOTSTRAP_VERIFIED_THRESHOLD


# --- Survivor selection ---


def select_survivor(ids, engrams_by_id):
    """Select deterministic survivor: prefer verified > highest occurrence_count > lowest ID."""
    candidates = [(eid, engrams_by_id[eid]) for eid in ids if eid in engrams_by_id]
    candidates.sort(key=lambda x: (
        -(x[1].get("dedup_verified", 0)),
        -(x[1].get("occurrence_count", 1)),
        x[0],
    ))
    return candidates[0][0]


# --- Orchestrator ---


def run_dedup(
    scan_only=False, limit=None, batch_size=None, max_candidates=8,
    min_sim=0.50, min_confidence=0.8, max_passes=10, single_pass=False,
    engram_id=None, json_output=False, db_path=None
):
    """Main entry point. Multi-pass until convergence.

    Returns:
        summary dict with processed, merged, verified, skipped, failed counts.
    """
    summary = {
        "processed": 0,
        "merged": 0,
        "verified": 0,
        "skipped": 0,
        "failed": 0,
        "passes": 0,
        "pass_details": [],
    }

    char_budget = batch_size or 6000

    for pass_num in range(1, max_passes + 1):
        summary["passes"] = pass_num
        pass_result = _run_single_pass(
            scan_only=scan_only,
            limit=limit,
            char_budget=char_budget,
            max_candidates=max_candidates,
            min_sim=min_sim,
            min_confidence=min_confidence,
            engram_id=engram_id,
            json_output=json_output,
            db_path=db_path,
            pass_num=pass_num,
        )

        summary["processed"] += pass_result["processed"]
        summary["merged"] += pass_result["merged"]
        summary["verified"] += pass_result["verified"]
        summary["skipped"] += pass_result["skipped"]
        summary["failed"] += pass_result["failed"]
        summary["pass_details"].append(pass_result)

        if not json_output and not scan_only:
            print(f"\nPass {pass_num}: {pass_result['merged']} merged, "
                  f"{pass_result['verified']} verified, "
                  f"{pass_result['failed']} failed")

        # Stop conditions
        if pass_result["merged"] == 0 or single_pass or scan_only:
            break

        # Rebuild index between passes
        if pass_result["merged"] > 0:
            from .db import get_all_active_engrams
            engrams = get_all_active_engrams(db_path=db_path)
            if engrams:
                build_index(engrams)
                build_tag_index(engrams)

    return summary


def _run_single_pass(
    scan_only, limit, char_budget, max_candidates, min_sim, min_confidence,
    engram_id, json_output, db_path, pass_num
):
    """Run a single dedup pass."""
    result = {"processed": 0, "merged": 0, "verified": 0, "skipped": 0, "failed": 0, "groups": []}

    bootstrap = should_bootstrap(db_path=db_path)
    mode = "bootstrap" if bootstrap else "incremental"

    if not json_output:
        print(f"\n--- Pass {pass_num} (mode: {mode}) ---")

    # Load pools
    if engram_id:
        # --id mode: load all active engrams, target is the specified one
        from .db import get_all_active_engrams
        all_active = get_all_active_engrams(db_path=db_path)
        target = [e for e in all_active if e["id"] == engram_id]
        if not target:
            if not json_output:
                print(f"Engram {engram_id} not found or deprecated.")
            return result
        # Treat target as unverified, rest as verified (for candidate finding)
        unverified = target
        verified = [e for e in all_active if e["id"] != engram_id]
    else:
        unverified = get_unverified_engrams(limit=limit, db_path=db_path)
        verified = get_verified_engrams(db_path=db_path)

    if not unverified:
        if not json_output:
            print("No unverified engrams to process.")
        return result

    if not json_output:
        print(f"Unverified: {len(unverified)}, Verified pool: {len(verified)}")

    # Build ID lookup
    all_engrams_list = unverified + verified
    engrams_by_id = {e["id"]: e for e in all_engrams_list}
    unverified_ids = {e["id"] for e in unverified}

    # Find candidates
    if engram_id:
        # --id mode: always use incremental (target vs all others)
        mode = "incremental"
        candidate_map = find_candidates_for_unverified(
            unverified, verified, min_sim=min_sim, top_k=max_candidates
        )
    elif bootstrap:
        # Bootstrap: search among ALL active engrams (unverified + verified)
        all_active = unverified + [v for v in verified if v["id"] not in unverified_ids]
        candidate_map = find_candidates_bootstrap(
            all_active, min_sim=min_sim, top_k=max_candidates
        )
        # In bootstrap mode, all IDs are treated as needing decisions
        unverified_ids = {e["id"] for e in all_active}
        engrams_by_id = {e["id"]: e for e in all_active}
    else:
        candidate_map = find_candidates_for_unverified(
            unverified, verified, min_sim=min_sim, top_k=max_candidates
        )

    # Filter engrams with no candidates (mark verified if incremental)
    engrams_with_candidates = {}
    for uid, candidates in candidate_map.items():
        if candidates:
            engrams_with_candidates[uid] = candidates
        elif not scan_only and mode == "incremental":
            mark_dedup_verified(uid, db_path=db_path)
            result["verified"] += 1

    if not engrams_with_candidates:
        result["processed"] = len(unverified)
        if not json_output:
            print(f"No candidates found above min_sim={min_sim}. Verified {result['verified']} engrams.")
        return result

    # Build batches
    batches = build_batches(engrams_with_candidates, engrams_by_id, unverified_ids, char_budget=char_budget)

    if not json_output:
        print(f"Built {len(batches)} batch(es) with {len(engrams_with_candidates)} engrams having candidates")

    run_id = f"run-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}-pass{pass_num}"

    for batch_idx, batch in enumerate(batches):
        if not json_output:
            print(f"\nBatch {batch_idx + 1}/{len(batches)}: "
                  f"{len(batch['unverified_ids'])} unverified, "
                  f"{len(batch['engrams'])} total engrams")

        result["processed"] += len(batch["unverified_ids"])

        # Call LLM
        response = call_dedup_llm(batch, mode=mode, min_confidence=min_confidence, run_id=run_id)

        if response is None:
            # LLM failure — record errors on all unverified in batch
            if not scan_only:
                for uid in batch["unverified_ids"]:
                    record_dedup_error(uid, "LLM call failed", db_path=db_path)
            result["failed"] += len(batch["unverified_ids"])
            continue

        # Validate
        valid_groups, validation_errors = validate_dedup_response(response, batch, mode=mode)

        if validation_errors:
            if not json_output:
                for err in validation_errors:
                    print(f"  Validation error: {err}", file=sys.stderr)

            # If no valid groups at all, fail the batch
            if not valid_groups:
                if not scan_only:
                    for uid in batch["unverified_ids"]:
                        record_dedup_error(uid, f"Validation failed: {'; '.join(validation_errors)}", db_path=db_path)
                result["failed"] += len(batch["unverified_ids"])
                continue

        # Process valid groups
        merged_unverified = set()
        for group in valid_groups:
            ids = sorted(group["ids"])
            canonical_text = group["canonical_text"]
            confidence = group["confidence"]
            reason = group["reason"]

            survivor_id = select_survivor(ids, engrams_by_id)
            absorbed_ids = [eid for eid in ids if eid != survivor_id]

            if scan_only:
                result["groups"].append({
                    "survivor_id": survivor_id,
                    "absorbed_ids": absorbed_ids,
                    "canonical_text": canonical_text,
                    "confidence": confidence,
                    "reason": reason,
                })
                if not json_output:
                    print(f"\n  Group: {ids}")
                    print(f"  Survivor: #{survivor_id}")
                    print(f"  Absorbed: {['#' + str(a) for a in absorbed_ids]}")
                    print(f"  Confidence: {confidence:.2f}")
                    print(f"  Reason: {reason}")
                    print(f"  Canonical: {canonical_text}")
            else:
                # Execute merge
                try:
                    conn = get_connection(db_path)
                    merge_engram_group(
                        survivor_id=survivor_id,
                        absorbed_ids=absorbed_ids,
                        canonical_text=canonical_text,
                        run_id=run_id,
                        confidence=confidence,
                        reason=reason,
                        conn=conn,
                    )
                    conn.commit()
                    conn.close()
                    result["merged"] += 1
                    merged_unverified.update(uid for uid in ids if uid in unverified_ids)
                    if not json_output:
                        print(f"  Merged: {ids} -> #{survivor_id}")
                except Exception as e:
                    conn.rollback()
                    conn.close()
                    print(f"  Merge failed for group {ids}: {e}", file=sys.stderr)
                    result["failed"] += 1

        # Mark no_match unverified as verified
        if not scan_only:
            no_match_ids = set(response.get("no_match_ids", []))
            for uid in batch["unverified_ids"]:
                if uid in no_match_ids and uid not in merged_unverified:
                    mark_dedup_verified(uid, db_path=db_path)
                    result["verified"] += 1

    return result
