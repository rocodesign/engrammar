"""Engram curation pipeline — quality review + dedup in similarity-sorted batches.

Runs when uncurated engram count exceeds a configurable threshold.
Takes priority over extraction in the daemon's processing slot.
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import numpy as np

from engrammar.core.config import load_config
from engrammar.core.db import (
    get_connection,
    get_uncurated_engrams,
    get_uncurated_count,
    mark_curated,
    reject_by_curation,
    merge_engram_group,
)
from engrammar.core.embeddings import embed_batch
from engrammar.core.prompt_loader import load_prompt


def should_curate(db_path=None):
    """Check if there are enough uncurated engrams to trigger curation."""
    config = load_config()
    threshold = config.get("curation", {}).get("threshold", 100)
    count = get_uncurated_count(db_path=db_path)
    return count >= threshold, count


def build_similarity_batches(engrams, batch_size=20):
    """Split engrams into fixed-size batches, sorted by similarity.

    Embeds all engrams, sorts by greedy nearest-neighbor walk,
    then chunks into batches of batch_size.
    """
    if not engrams:
        return []

    texts = [e["text"] for e in engrams]
    embs = embed_batch(texts)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normed = embs / norms

    # Greedy nearest-neighbor walk to sort by similarity
    n = len(engrams)
    remaining = set(range(n))
    order = []

    current = 0
    remaining.discard(current)
    order.append(current)

    sim_matrix = normed @ normed.T

    while remaining:
        best_idx = -1
        best_sim = -1
        for j in remaining:
            s = float(sim_matrix[current, j])
            if s > best_sim:
                best_sim = s
                best_idx = j
        remaining.discard(best_idx)
        order.append(best_idx)
        current = best_idx

    # Chunk into fixed-size batches
    batches = []
    for i in range(0, n, batch_size):
        chunk = order[i:i + batch_size]
        batch_engrams = [engrams[j] for j in chunk]
        batches.append(batch_engrams)

    return batches


def call_curation_llm(batch, model=None):
    """Send a batch of engrams through the curation LLM.

    Returns parsed response dict or None.
    """
    if model is None:
        config = load_config()
        model = config.get("models", {}).get("curation", "sonnet")

    prompt_template = load_prompt("curation/system.md")
    engrams_json = json.dumps(
        [{"id": e["id"], "text": e["text"]} for e in batch],
        indent=2,
    )
    prompt = prompt_template.replace("{engrams_json}", engrams_json)

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["ENGRAMMAR_INTERNAL_RUN"] = "1"

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model,
             "--output-format", "text", "--no-session-persistence"],
            capture_output=True,
            text=True,
            timeout=300,
            env=env,
            stdin=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            print(f"  Curation LLM error: {result.stderr[:200]}", file=sys.stderr)
            return None

        return _parse_json(result.stdout.strip())
    except subprocess.TimeoutExpired:
        print("  Curation LLM timeout", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("  claude CLI not found — skipping curation", file=sys.stderr)
        return None


def _parse_json(text):
    """Parse JSON from LLM output."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
    return None


def _apply_verdicts(verdicts, engram_ids_in_batch, db_path=None):
    """Apply keep/reject verdicts from the LLM response.

    Returns (kept_ids, rejected_ids).
    """
    kept = []
    rejected = []

    for v in verdicts:
        eid = v.get("id")
        if eid not in engram_ids_in_batch:
            continue
        if v.get("verdict") == "reject":
            rejected.append(eid)
        else:
            kept.append(eid)

    # Mark in DB
    mark_curated(kept, db_path=db_path)
    reject_by_curation(rejected, db_path=db_path)

    return kept, rejected


def _apply_merges(merge_groups, kept_ids, run_id, db_path=None):
    """Apply merge groups from the LLM response.

    Returns count of merged engrams.
    """
    kept_set = set(kept_ids)
    merged_count = 0

    for group in merge_groups:
        ids = [eid for eid in group.get("ids", []) if eid in kept_set]
        canonical = group.get("canonical_text", "")
        reason = group.get("reason", "")

        if len(ids) < 2 or not canonical:
            continue

        survivor_id = ids[0]
        absorbed_ids = ids[1:]

        try:
            conn = get_connection(db_path)
            merge_engram_group(
                survivor_id=survivor_id,
                absorbed_ids=absorbed_ids,
                canonical_text=canonical,
                run_id=run_id,
                confidence=0.9,
                reason=reason,
                conn=conn,
            )
            conn.commit()
            conn.close()
            merged_count += len(absorbed_ids)
        except Exception as e:
            print(f"  Merge failed for group {ids}: {e}", file=sys.stderr)
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass

    return merged_count


def run_curation(limit=None, dry_run=False, db_path=None):
    """Main curation entry point.

    Loads uncurated engrams, batches by similarity, runs LLM curation,
    applies verdicts and merges.

    Returns summary dict.
    """
    config = load_config()
    curation_config = config.get("curation", {})
    batch_size = curation_config.get("batch_size", 20)
    model = config.get("models", {}).get("curation", "sonnet")

    summary = {
        "processed": 0,
        "kept": 0,
        "rejected": 0,
        "merged": 0,
        "failed_batches": 0,
        "batches": 0,
    }

    # Load uncurated engrams
    engrams = get_uncurated_engrams(limit=limit, db_path=db_path)
    if not engrams:
        print("No uncurated engrams to process")
        return summary

    summary["processed"] = len(engrams)
    print(f"Curating {len(engrams)} engrams (model={model}, batch_size={batch_size})")

    # Build similarity-sorted batches
    batches = build_similarity_batches(engrams, batch_size=batch_size)
    summary["batches"] = len(batches)
    print(f"Created {len(batches)} batches")

    if dry_run:
        for i, batch in enumerate(batches):
            print(f"\nBatch {i+1} ({len(batch)} engrams):")
            for e in batch:
                print(f"  [{e['id']}] {e['text'][:100]}...")
        return summary

    run_id = f"curation-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    for i, batch in enumerate(batches):
        batch_ids = {e["id"] for e in batch}
        print(f"Batch {i+1}/{len(batches)} ({len(batch)} engrams)...", end=" ", flush=True)

        start = time.time()
        result = call_curation_llm(batch, model=model)
        elapsed = time.time() - start

        if not result:
            print(f"FAILED ({elapsed:.1f}s)")
            # Mark batch as curated anyway to avoid infinite retry
            mark_curated(list(batch_ids), db_path=db_path)
            summary["kept"] += len(batch_ids)
            summary["failed_batches"] += 1
            continue

        verdicts = result.get("verdicts", [])
        merge_groups = result.get("merge_groups", [])

        kept, rejected = _apply_verdicts(verdicts, batch_ids, db_path=db_path)
        merged = _apply_merges(merge_groups, kept, run_id, db_path=db_path)

        summary["kept"] += len(kept)
        summary["rejected"] += len(rejected)
        summary["merged"] += merged

        print(f"keep={len(kept)} reject={len(rejected)} merged={merged} ({elapsed:.1f}s)")

    print(f"\nCuration complete: {summary['kept']} kept, {summary['rejected']} rejected, "
          f"{summary['merged']} merged, {summary['failed_batches']} failed batches")

    return summary
