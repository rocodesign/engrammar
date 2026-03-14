#!/usr/bin/env python3
"""Evaluate deduplication merge quality using a judge model.

Takes dedup benchmark results and evaluates:
1. Merge precision: Were merge groups correct? (false merges)
2. Merge recall: Were near-threshold pairs that weren't merged actually duplicates? (missed merges)

Usage:
    python benchmark/run_dedup_eval.py benchmark/results/dedup-20260312-153340/haiku_sim0.6.json
    python benchmark/run_dedup_eval.py benchmark/results/dedup-20260312-153340/haiku_sim0.6.json --judge sonnet
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

from engrammar.core.embeddings import embed_batch


def load_dedup_result(path):
    with open(path) as f:
        return json.load(f)


def load_engrams_from_db():
    from engrammar.core.db import get_all_active_engrams
    engrams = get_all_active_engrams()
    for e in engrams:
        if "text" not in e and "engram" in e:
            e["text"] = e["engram"]
    return {e["id"]: e for e in engrams}


def call_judge(prompt, model):
    """Call LLM judge and return parsed JSON response."""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["ENGRAMMAR_INTERNAL_RUN"] = "1"

    start = time.time()
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model,
             "--output-format", "text", "--no-session-persistence"],
            capture_output=True, text=True, timeout=120,
            env=env, stdin=subprocess.DEVNULL,
        )
        elapsed = time.time() - start
        if result.returncode != 0:
            return None, elapsed
        text = result.stdout.strip()
        # Parse JSON from response
        if text.startswith("```"):
            lines = text.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text), elapsed
        except json.JSONDecodeError:
            start_idx = text.find("{")
            end_idx = text.rfind("}") + 1
            if start_idx >= 0 and end_idx > start_idx:
                try:
                    return json.loads(text[start_idx:end_idx]), elapsed
                except json.JSONDecodeError:
                    pass
        return None, elapsed
    except Exception:
        return None, time.time() - start


def evaluate_merges(groups, engrams_by_id, judge_model):
    """Evaluate each merge group: is this a correct merge?"""
    results = []

    for i, group in enumerate(groups):
        ids = group["ids"]
        texts = []
        for eid in ids:
            if eid in engrams_by_id:
                texts.append(f"[{eid}] {engrams_by_id[eid]['text']}")

        if len(texts) < 2:
            continue

        prompt = f"""You are evaluating whether a deduplication system correctly merged these engrams (learned lessons) as duplicates.

The system decided these engrams are duplicates and should be merged into one:

{chr(10).join(texts)}

The system's canonical merge text: "{group.get('canonical_text', '')}"
The system's reason: "{group.get('reason', '')}"

Evaluate this merge decision. Consider:
- Do all engrams express the SAME core lesson/rule/pattern?
- Would keeping them separate provide meaningfully different value?
- Is the canonical text a good synthesis?

Return strict JSON:
{{
  "verdict": "correct" | "partial" | "wrong",
  "confidence": 0.0-1.0,
  "reason": "1-2 sentence explanation",
  "issues": ["list any specific problems, empty if correct"]
}}

Verdicts:
- "correct": All engrams are genuine duplicates, merge is right
- "partial": Some but not all should be merged (e.g., 3 merged but only 2 are duplicates)
- "wrong": These are distinct lessons that should NOT have been merged"""

        print(f"  Group {i+1}/{len(groups)} ({len(ids)} engrams)...", end=" ", flush=True)
        response, elapsed = call_judge(prompt, judge_model)

        if response:
            verdict = response.get("verdict", "error")
            conf = response.get("confidence", 0)
            print(f"{verdict} ({conf:.2f}) in {elapsed:.1f}s")
            results.append({
                "group_idx": i,
                "ids": ids,
                "canonical_text": group.get("canonical_text", ""),
                "original_confidence": group.get("confidence", 0),
                "verdict": verdict,
                "judge_confidence": conf,
                "reason": response.get("reason", ""),
                "issues": response.get("issues", []),
                "elapsed_s": round(elapsed, 2),
            })
        else:
            print(f"ERROR in {elapsed:.1f}s")
            results.append({
                "group_idx": i,
                "ids": ids,
                "verdict": "error",
                "elapsed_s": round(elapsed, 2),
            })

    return results


def find_missed_merges(groups, engrams_by_id, judge_model, min_sim=0.6, sample_size=10):
    """Find high-similarity pairs that weren't merged and check if they should have been."""
    # Get all merged ID sets
    merged_pairs = set()
    for g in groups:
        ids = g["ids"]
        for i, a in enumerate(ids):
            for b in ids[i+1:]:
                merged_pairs.add((min(a, b), max(a, b)))

    # Embed all engrams and find high-sim unmerged pairs
    all_ids = sorted(engrams_by_id.keys())
    texts = [engrams_by_id[eid]["text"] for eid in all_ids]

    if len(texts) < 2:
        return []

    embs = embed_batch(texts)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normed = embs / norms
    sim_matrix = normed @ normed.T

    # Find unmerged pairs above threshold
    unmerged_candidates = []
    for i in range(len(all_ids)):
        for j in range(i + 1, len(all_ids)):
            pair = (min(all_ids[i], all_ids[j]), max(all_ids[i], all_ids[j]))
            if pair not in merged_pairs and sim_matrix[i][j] >= min_sim:
                unmerged_candidates.append((sim_matrix[i][j], all_ids[i], all_ids[j]))

    unmerged_candidates.sort(reverse=True)
    sample = unmerged_candidates[:sample_size]

    if not sample:
        print("  No high-similarity unmerged pairs found.")
        return []

    print(f"  Checking {len(sample)} unmerged high-similarity pairs...")
    results = []

    for idx, (sim, id_a, id_b) in enumerate(sample):
        text_a = engrams_by_id[id_a]["text"]
        text_b = engrams_by_id[id_b]["text"]

        prompt = f"""You are evaluating whether two engrams (learned lessons) should be merged as duplicates.

These two engrams were NOT merged by the dedup system (embedding similarity: {sim:.3f}).

Engram A [{id_a}]: {text_a}

Engram B [{id_b}]: {text_b}

Should these be merged? Consider:
- Do they express the SAME core lesson/rule/pattern?
- Would keeping both provide meaningfully different value?
- Is the similarity superficial (same topic but different lessons) or substantive (same lesson)?

Return strict JSON:
{{
  "should_merge": true | false,
  "confidence": 0.0-1.0,
  "reason": "1-2 sentence explanation"
}}"""

        print(f"    Pair {idx+1}/{len(sample)} (sim={sim:.3f}, #{id_a} vs #{id_b})...", end=" ", flush=True)
        response, elapsed = call_judge(prompt, judge_model)

        if response:
            should = response.get("should_merge", False)
            conf = response.get("confidence", 0)
            label = "MISSED" if should else "ok"
            print(f"{label} ({conf:.2f}) in {elapsed:.1f}s")
            results.append({
                "id_a": id_a,
                "id_b": id_b,
                "similarity": round(sim, 4),
                "should_merge": should,
                "confidence": conf,
                "reason": response.get("reason", ""),
                "elapsed_s": round(elapsed, 2),
            })
        else:
            print(f"ERROR in {elapsed:.1f}s")
            results.append({
                "id_a": id_a, "id_b": id_b,
                "similarity": round(sim, 4),
                "should_merge": None,
                "elapsed_s": round(elapsed, 2),
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="Evaluate dedup merge quality")
    parser.add_argument("dedup_result", type=str,
                        help="Path to dedup result JSON (e.g., haiku_sim0.6.json)")
    parser.add_argument("--judge", type=str, default="sonnet",
                        help="Judge model (default: sonnet)")
    parser.add_argument("--skip-recall", action="store_true",
                        help="Skip missed-merge recall check")
    parser.add_argument("--recall-samples", type=int, default=10,
                        help="Number of unmerged pairs to check (default: 10)")
    args = parser.parse_args()

    result_path = Path(args.dedup_result)
    dedup_result = load_dedup_result(result_path)

    model = dedup_result["model"]
    min_sim = dedup_result["min_sim"]
    groups = dedup_result["groups"]

    print(f"Evaluating dedup result: {model} @ min_sim={min_sim}")
    print(f"  {len(groups)} merge groups to evaluate")
    print(f"  Judge model: {args.judge}\n")

    # Load engrams from DB
    engrams_by_id = load_engrams_from_db()
    print(f"Loaded {len(engrams_by_id)} engrams from DB\n")

    # 1. Evaluate merge precision
    print("=== Merge Precision (are merges correct?) ===\n")
    merge_evals = evaluate_merges(groups, engrams_by_id, args.judge)

    correct = sum(1 for e in merge_evals if e["verdict"] == "correct")
    partial = sum(1 for e in merge_evals if e["verdict"] == "partial")
    wrong = sum(1 for e in merge_evals if e["verdict"] == "wrong")
    errors = sum(1 for e in merge_evals if e["verdict"] == "error")
    total = len(merge_evals)

    print(f"\nPrecision summary: {correct} correct, {partial} partial, "
          f"{wrong} wrong, {errors} errors out of {total} groups")
    if total - errors > 0:
        precision = (correct + 0.5 * partial) / (total - errors)
        print(f"Precision score: {precision:.2%}")

    # 2. Check for missed merges (recall)
    recall_evals = []
    if not args.skip_recall:
        print(f"\n=== Merge Recall (missed duplicates?) ===\n")
        recall_evals = find_missed_merges(
            groups, engrams_by_id, args.judge,
            min_sim=min_sim, sample_size=args.recall_samples,
        )

        if recall_evals:
            missed = sum(1 for e in recall_evals if e.get("should_merge"))
            checked = sum(1 for e in recall_evals if e.get("should_merge") is not None)
            print(f"\nRecall summary: {missed} missed merges out of {checked} checked pairs")

    # Save evaluation results
    eval_output = {
        "source": str(result_path),
        "model_evaluated": model,
        "judge_model": args.judge,
        "min_sim": min_sim,
        "precision": {
            "total_groups": total,
            "correct": correct,
            "partial": partial,
            "wrong": wrong,
            "errors": errors,
            "score": round((correct + 0.5 * partial) / (total - errors), 4) if total - errors > 0 else None,
        },
        "merge_evaluations": merge_evals,
    }

    if recall_evals:
        missed = sum(1 for e in recall_evals if e.get("should_merge"))
        checked = sum(1 for e in recall_evals if e.get("should_merge") is not None)
        eval_output["recall"] = {
            "pairs_checked": checked,
            "missed_merges": missed,
            "miss_rate": round(missed / checked, 4) if checked > 0 else None,
        }
        eval_output["recall_evaluations"] = recall_evals

    # Save next to the dedup result
    eval_path = result_path.parent / f"eval_{result_path.stem}.json"

    def _default(obj):
        if isinstance(obj, (np.floating, np.integer)):
            return float(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    with open(eval_path, "w") as f:
        json.dump(eval_output, f, indent=2, default=_default)

    # Markdown report
    md = [
        f"# Dedup Evaluation — {model} @ min_sim={min_sim}\n",
        f"**Judge**: {args.judge}  ",
        f"**Groups evaluated**: {total}\n",
        "## Precision\n",
        f"| Verdict | Count |",
        f"|---------|------:|",
        f"| Correct | {correct} |",
        f"| Partial | {partial} |",
        f"| Wrong   | {wrong} |",
        f"| Error   | {errors} |",
    ]
    if total - errors > 0:
        md.append(f"\n**Precision score**: {(correct + 0.5 * partial) / (total - errors):.1%}\n")

    # Detail wrong/partial merges
    problems = [e for e in merge_evals if e["verdict"] in ("wrong", "partial")]
    if problems:
        md.append("### Problems\n")
        for e in problems:
            ids_str = ", ".join(f"#{eid}" for eid in e["ids"])
            md.append(f"**{e['verdict'].upper()}** ({ids_str}) — judge confidence {e['judge_confidence']:.2f}")
            md.append(f"  Canonical: {e.get('canonical_text', '')[:120]}")
            md.append(f"  Judge: {e['reason']}")
            for issue in e.get("issues", []):
                md.append(f"  - {issue}")
            md.append("")

    if recall_evals:
        missed_pairs = [e for e in recall_evals if e.get("should_merge")]
        md.append("## Recall\n")
        checked = sum(1 for e in recall_evals if e.get("should_merge") is not None)
        md.append(f"Checked {checked} high-similarity unmerged pairs, "
                   f"found {len(missed_pairs)} missed merges.\n")
        if missed_pairs:
            md.append("### Missed Merges\n")
            for e in missed_pairs:
                md.append(f"**#{e['id_a']} + #{e['id_b']}** (sim={e['similarity']:.3f}, conf={e['confidence']:.2f})")
                md.append(f"  {e['reason']}")
                if e['id_a'] in engrams_by_id:
                    md.append(f"  - [{e['id_a']}] {engrams_by_id[e['id_a']]['text'][:120]}")
                if e['id_b'] in engrams_by_id:
                    md.append(f"  - [{e['id_b']}] {engrams_by_id[e['id_b']]['text'][:120]}")
                md.append("")

    report_path = result_path.parent / f"eval_{result_path.stem}.md"
    with open(report_path, "w") as f:
        f.write("\n".join(md))

    print(f"\nEvaluation saved to: {eval_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
