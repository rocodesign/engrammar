#!/usr/bin/env python3
"""Run quality gate + dedup on extracted engrams from a benchmark run.

Takes engrams from a prior extraction run, batches them by cosine similarity,
sends each batch through the quality gate prompt, and evaluates the results
against labeled_engrams.jsonl.

Usage:
    python benchmark/run_quality_gate.py benchmark/results/20260325-012954/ --prompt-filter v6-targeted-precision
    python benchmark/run_quality_gate.py benchmark/results/20260325-012954/ --prompt-filter v6-targeted-precision --dry-run
    python benchmark/run_quality_gate.py benchmark/results/20260325-012954/ --prompt-filter v6-targeted-precision --gate-model opus
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

EVAL_DIR = PROJECT_ROOT / "benchmark" / "transcripts" / "evaluation"
RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"


def load_extraction_results(run_dir, prompt_filter=None):
    """Load all extracted engrams from a benchmark run.

    Returns list of dicts with id, text, source_session, transcript fields.
    """
    engrams = []
    idx = 0
    for path in sorted(Path(run_dir).glob("*.json")):
        if path.name == "summary.json":
            continue
        with open(path) as f:
            data = json.load(f)

        if prompt_filter and data.get("prompt", "") != prompt_filter:
            continue

        transcript = data.get("transcript_file", "")
        session_prefix = transcript.replace(".jsonl", "")[:12]

        for eng in data.get("engrams") or []:
            if not isinstance(eng, dict):
                continue
            text = eng.get("engram", eng.get("text", ""))
            if not text:
                continue
            engrams.append({
                "id": idx,
                "text": text,
                "source_session": session_prefix,
                "transcript": transcript,
                "category": eng.get("category", ""),
            })
            idx += 1

    return engrams


def build_similarity_batches(engrams, embed_fn, batch_size=10):
    """Split engrams into fixed-size batches, sorted by similarity.

    Embeds all engrams, sorts by similarity (via greedy nearest-neighbor walk),
    then chunks into batches of batch_size. Related engrams end up together
    without creating tiny singleton batches.
    """
    if not engrams:
        return []

    texts = [e["text"] for e in engrams]
    embs = embed_fn(texts)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normed = embs / norms

    # Greedy nearest-neighbor walk to sort by similarity
    n = len(engrams)
    remaining = set(range(n))
    order = []

    # Start from index 0
    current = 0
    remaining.discard(current)
    order.append(current)

    sim_matrix = normed @ normed.T

    while remaining:
        # Find most similar remaining engram to current
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
        batch_engrams = [{"id": engrams[j]["id"], "text": engrams[j]["text"]} for j in chunk]
        batches.append(batch_engrams)

    return batches


def load_gate_prompt(prompt_path):
    """Load quality gate prompt template."""
    with open(prompt_path) as f:
        content = f.read()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].strip()
    return content


def run_gate_on_batch(batch, prompt_template, model):
    """Send a batch through the quality gate LLM.

    Returns parsed response or None.
    """
    engrams_json = json.dumps(batch, indent=2)
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
            print(f"  Gate LLM error: {result.stderr[:200]}", file=sys.stderr)
            return None

        output = result.stdout.strip()
        return _parse_json(output)
    except subprocess.TimeoutExpired:
        print("  Gate LLM timeout", file=sys.stderr)
        return None
    except FileNotFoundError:
        print("  claude CLI not found", file=sys.stderr)
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


def evaluate_gate_results(engrams, gate_verdicts, merge_groups):
    """Evaluate quality gate results against labeled_engrams.jsonl.

    Returns dict with metrics.
    """
    from engrammar.core.embeddings import embed_batch

    # Load labeled
    with open(EVAL_DIR / "labeled_engrams.jsonl") as f:
        labeled = [json.loads(l) for l in f if l.strip()]

    good_labeled = [e for e in labeled if e.get("value", 0) >= 3]
    bad_labeled = [e for e in labeled if e.get("value", 0) == 0]

    # Build engram lookup
    engram_by_id = {e["id"]: e for e in engrams}

    # Get kept engram texts (after gate + merge)
    kept_ids = {v["id"] for v in gate_verdicts if v.get("verdict") == "keep"}
    rejected_ids = {v["id"] for v in gate_verdicts if v.get("verdict") == "reject"}

    # Apply merges: replace merged IDs with canonical text
    merged_away = set()
    canonical_texts = []
    for group in merge_groups:
        ids = group.get("ids", [])
        canonical = group.get("canonical_text", "")
        if canonical and len(ids) > 1:
            canonical_texts.append(canonical)
            merged_away.update(ids)  # all merged IDs replaced by canonical

    # Final kept texts: non-merged keeps + canonical texts
    final_texts = []
    for eid in kept_ids:
        if eid not in merged_away:
            final_texts.append(engram_by_id[eid]["text"])
    final_texts.extend(canonical_texts)

    # Group by session
    kept_by_session = {}
    for eid in kept_ids:
        if eid in merged_away:
            continue
        e = engram_by_id[eid]
        kept_by_session.setdefault(e["source_session"], []).append(e["text"])
    # Add canonical texts to all sessions they came from
    for group in merge_groups:
        canonical = group.get("canonical_text", "")
        if not canonical:
            continue
        for eid in group.get("ids", []):
            if eid in engram_by_id:
                sess = engram_by_id[eid]["source_session"]
                kept_by_session.setdefault(sess, []).append(canonical)

    # Embed everything for matching
    all_texts = list(set(
        [e["text"] for e in labeled] + final_texts
    ))
    embs = embed_batch(all_texts)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normalized = embs / norms
    vectors = {t: np.asarray(v, dtype=np.float32) for t, v in zip(all_texts, normalized)}

    threshold = 0.85

    # Good recall: how many good labeled engrams still have a match in kept pool?
    good_found = good_missed = good_skipped = 0
    for eng in good_labeled:
        if eng["source"].startswith("orig-"):
            good_skipped += 1
            continue
        candidates = kept_by_session.get(eng["source"], [])
        if not candidates:
            good_skipped += 1
            continue

        source_vec = vectors.get(eng["text"])
        if source_vec is None:
            good_skipped += 1
            continue
        best_sim = max(
            (float(source_vec @ vectors[ct]) for ct in candidates if ct in vectors),
            default=0
        )
        if best_sim >= threshold:
            good_found += 1
        else:
            good_missed += 1

    # Bad avoidance: how many bad labeled engrams are NOT in kept pool?
    bad_extracted = bad_avoided = bad_skipped = 0
    for eng in bad_labeled:
        if eng["source"].startswith("orig-"):
            bad_skipped += 1
            continue
        candidates = kept_by_session.get(eng["source"], [])
        if not candidates:
            bad_skipped += 1
            continue

        source_vec = vectors.get(eng["text"])
        if source_vec is None:
            bad_skipped += 1
            continue
        best_sim = max(
            (float(source_vec @ vectors[ct]) for ct in candidates if ct in vectors),
            default=0
        )
        if best_sim >= threshold:
            bad_extracted += 1
        else:
            bad_avoided += 1

    good_total = good_found + good_missed
    bad_total = bad_extracted + bad_avoided

    return {
        "input_count": len(engrams),
        "kept_count": len(kept_ids),
        "rejected_count": len(rejected_ids),
        "merged_groups": len(merge_groups),
        "merged_engrams": len(merged_away),
        "final_count": len(final_texts),
        "good_recall": good_found / good_total * 100 if good_total else 0,
        "good_found": good_found,
        "good_total": good_total,
        "bad_avoidance": bad_avoided / bad_total * 100 if bad_total else 0,
        "bad_avoided": bad_avoided,
        "bad_total": bad_total,
    }


def main():
    parser = argparse.ArgumentParser(description="Run quality gate on extraction results")
    parser.add_argument("run_dir", help="Path to extraction results directory")
    parser.add_argument("--prompt-filter", help="Only use results from this prompt variant")
    parser.add_argument("--gate-prompt", default=str(PROJECT_ROOT / "benchmark/prompts/quality-gate/v2-gate-dedup.md"),
                        help="Quality gate prompt file")
    parser.add_argument("--gate-model", default="opus", help="Model for quality gate (default: opus)")
    parser.add_argument("--batch-size", type=int, default=10, help="Engrams per batch")
    parser.add_argument("--dry-run", action="store_true", help="Show batches without calling LLM")
    args = parser.parse_args()

    from engrammar.core.embeddings import embed_batch

    # Load extraction results
    engrams = load_extraction_results(args.run_dir, prompt_filter=args.prompt_filter)
    print(f"Loaded {len(engrams)} extracted engrams")
    if not engrams:
        print("No engrams to process")
        return

    # Build similarity-based batches
    print(f"Building batches of {args.batch_size}, sorted by similarity...")
    batches = build_similarity_batches(engrams, embed_batch, args.batch_size)
    print(f"Created {len(batches)} batches (sizes: {[len(b) for b in batches]})")

    if args.dry_run:
        for i, batch in enumerate(batches):
            print(f"\nBatch {i+1} ({len(batch)} engrams):")
            for eng in batch:
                print(f"  [{eng['id']}] {eng['text'][:100]}...")
        return

    # Load prompt
    prompt_template = load_gate_prompt(args.gate_prompt)

    # Run gate on each batch
    all_verdicts = []
    all_merge_groups = []
    total_elapsed = 0

    for i, batch in enumerate(batches):
        print(f"Batch {i+1}/{len(batches)} ({len(batch)} engrams)...", end=" ", flush=True)
        start = time.time()
        result = run_gate_on_batch(batch, prompt_template, args.gate_model)
        elapsed = time.time() - start
        total_elapsed += elapsed

        if result:
            verdicts = result.get("verdicts", [])
            merges = result.get("merge_groups", [])
            kept = sum(1 for v in verdicts if v.get("verdict") == "keep")
            rejected = sum(1 for v in verdicts if v.get("verdict") == "reject")
            print(f"keep={kept} reject={rejected} merges={len(merges)} ({elapsed:.1f}s)")
            all_verdicts.extend(verdicts)
            all_merge_groups.extend(merges)
        else:
            print(f"FAILED ({elapsed:.1f}s)")

    # Save results
    run_id = time.strftime("%Y%m%d-%H%M%S")
    out_dir = RESULTS_DIR / f"gate-{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(out_dir / "gate_results.json", "w") as f:
        json.dump({
            "source_run": str(args.run_dir),
            "prompt_filter": args.prompt_filter,
            "gate_model": args.gate_model,
            "gate_prompt": args.gate_prompt,
            "batches": len(batches),
            "total_elapsed_s": round(total_elapsed, 1),
            "verdicts": all_verdicts,
            "merge_groups": all_merge_groups,
        }, f, indent=2)

    # Evaluate
    print(f"\nEvaluating against labeled_engrams.jsonl...")
    metrics = evaluate_gate_results(engrams, all_verdicts, all_merge_groups)

    print(f"\n{'='*70}")
    print(f"QUALITY GATE RESULTS")
    print(f"{'='*70}")
    print(f"Input:     {metrics['input_count']} engrams")
    print(f"Kept:      {metrics['kept_count']}")
    print(f"Rejected:  {metrics['rejected_count']}")
    print(f"Merged:    {metrics['merged_groups']} groups ({metrics['merged_engrams']} engrams merged)")
    print(f"Final:     {metrics['final_count']} unique engrams")
    print(f"")
    print(f"Good recall:    {metrics['good_found']}/{metrics['good_total']} = {metrics['good_recall']:.0f}%")
    print(f"Bad avoidance:  {metrics['bad_avoided']}/{metrics['bad_total']} = {metrics['bad_avoidance']:.0f}%")
    print(f"Total time:     {total_elapsed:.0f}s")
    print(f"\nResults saved to: {out_dir}")

    with open(out_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2)


if __name__ == "__main__":
    main()
