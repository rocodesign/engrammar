#!/usr/bin/env python3
"""Benchmark deduplication quality across models and similarity thresholds.

Pools engrams from extraction benchmark results, runs embedding-based
candidate finding + LLM dedup, and reports merge quality.

Usage:
    python benchmark/run_dedup.py --from-extraction benchmark/results/20260311-145245
    python benchmark/run_dedup.py --from-db
    python benchmark/run_dedup.py --from-extraction benchmark/results/LATEST --models haiku sonnet
    python benchmark/run_dedup.py --from-extraction benchmark/results/LATEST --min-sims 0.4 0.5 0.6
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

# Add project src to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

from engrammar.core.embeddings import embed_batch
from engrammar.core.prompt_loader import load_prompt
from pipeline.dedup import (
    _parse_json_response,
    build_batches as _prod_build_batches,
    find_candidates_bootstrap as _prod_find_candidates,
    validate_dedup_response,
)

RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"


# --- Engram loading ---


def load_engrams_from_extraction(results_dir):
    """Load and deduplicate engrams from extraction benchmark result files.

    Assigns sequential IDs. Returns list of engram dicts with 'id' and 'text' fields.
    """
    results_dir = Path(results_dir)
    engrams = []
    seen_texts = set()

    for json_file in sorted(results_dir.glob("*.json")):
        if json_file.name in ("summary.json",):
            continue
        try:
            with open(json_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        for eng in data.get("engrams", []):
            text = eng.get("engram", "").strip()
            if not text or text in seen_texts:
                continue
            seen_texts.add(text)
            engrams.append({
                "id": len(engrams) + 1,
                "text": text,
                "category": eng.get("category", "general"),
                "scope": eng.get("scope", ""),
                "source_file": json_file.name,
                "occurrence_count": 1,
            })

    return engrams


def load_engrams_from_db():
    """Load all active engrams from the engrammar database."""
    from engrammar.core.db import get_all_active_engrams
    engrams = get_all_active_engrams()
    # Normalize to expected format
    for e in engrams:
        if "text" not in e and "engram" in e:
            e["text"] = e["engram"]
    return engrams


# --- Candidate finding (delegates to production pipeline) ---


def find_candidates(engrams, min_sim=0.50, top_k=8):
    """Find embedding-similar candidate pairs among all engrams.

    Wraps production find_candidates_bootstrap and additionally computes
    the full similarity matrix needed for benchmark analysis/reporting.

    Returns:
        dict mapping engram_id -> [(other_id, similarity), ...]
        similarity matrix for analysis
    """
    candidate_map = _prod_find_candidates(engrams, min_sim=min_sim, top_k=top_k)

    # Production doesn't return the similarity matrix; compute it for reporting
    sim_matrix = None
    if len(engrams) >= 2:
        texts = [e["text"] for e in engrams]
        embs = embed_batch(texts)
        norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
        normed = embs / norms
        sim_matrix = normed @ normed.T

    return candidate_map, sim_matrix


# --- Batch building (delegates to production pipeline) ---


def build_batches(candidate_map, engrams_by_id, char_budget=6000):
    """Group engrams+candidates into batches respecting char budget.

    Wraps production build_batches — in benchmark mode all engrams are
    treated as unverified (bootstrap).
    """
    unverified_ids = set(candidate_map.keys())
    return _prod_build_batches(candidate_map, engrams_by_id, unverified_ids, char_budget=char_budget)


# --- LLM call (benchmark wrapper with model override + timing) ---


def call_benchmark_dedup_llm(batch, model, batch_id=""):
    """Send batch to LLM for dedup decisions with model override and timing.

    Uses production prompt assembly and JSON parsing. Returns
    (parsed_response, elapsed_seconds, error_string_or_None).
    """
    system_prompt = load_prompt("dedup/system.md")
    mode_snippet = load_prompt("dedup/bootstrap.md")

    payload = {
        "mode": "bootstrap",
        "batch_id": batch_id,
        "rules": {
            "min_confidence_hint": 0.8,
            "max_groups": 20,
        },
        "engrams": batch["engrams"],
        "candidate_edges": batch["candidate_edges"],
    }

    prompt = f"""{system_prompt}

{mode_snippet}

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

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["ENGRAMMAR_INTERNAL_RUN"] = "1"

    start = time.time()
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
        elapsed = time.time() - start

        if result.returncode != 0:
            return None, elapsed, f"exit code {result.returncode}: {result.stderr[:200]}"

        output = result.stdout.strip()
        parsed = _parse_json_response(output)
        if parsed is None:
            return None, elapsed, f"JSON parse failed: {output[:200]}"
        return parsed, elapsed, None

    except subprocess.TimeoutExpired:
        return None, 300, "timeout"
    except Exception as e:
        return None, time.time() - start, str(e)


# --- Main ---


def resolve_results_dir(path_str):
    """Resolve LATEST or a specific results dir.

    LATEST picks the most recent extraction results dir (excludes dedup-* dirs).
    """
    p = Path(path_str)
    if p.name == "LATEST":
        parent = p.parent
        # Only consider extraction result dirs (date-stamped, not dedup-*)
        dirs = sorted(
            d for d in parent.iterdir()
            if d.is_dir() and not d.name.startswith("dedup-")
        )
        if not dirs:
            print(f"No extraction results in {parent}")
            sys.exit(1)
        return dirs[-1]
    return p


def main():
    parser = argparse.ArgumentParser(description="Benchmark deduplication quality")
    parser.add_argument("--from-extraction", type=str,
                        help="Path to extraction benchmark results dir (use LATEST for most recent)")
    parser.add_argument("--from-db", action="store_true",
                        help="Use engrams from the engrammar database")
    parser.add_argument("--models", nargs="*", default=["haiku"],
                        help="Models to test (default: haiku)")
    parser.add_argument("--min-sims", nargs="*", type=float, default=[0.50],
                        help="Minimum similarity thresholds to test (default: 0.50)")
    parser.add_argument("--batch-size", type=int, default=6000,
                        help="Char budget per LLM batch (default: 6000)")
    parser.add_argument("--top-k", type=int, default=8,
                        help="Max candidates per engram (default: 8)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show candidate stats without calling LLM")
    args = parser.parse_args()

    if not args.from_extraction and not args.from_db:
        print("Specify --from-extraction <dir> or --from-db")
        return

    # Load engrams
    if args.from_extraction:
        results_dir = resolve_results_dir(args.from_extraction)
        print(f"Loading engrams from extraction results: {results_dir}")
        engrams = load_engrams_from_extraction(results_dir)
        source_label = results_dir.name
    else:
        print("Loading engrams from database")
        engrams = load_engrams_from_db()
        source_label = "database"

    if not engrams:
        print("No engrams found.")
        return

    print(f"Loaded {len(engrams)} unique engrams from {source_label}\n")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_DIR / f"dedup-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    engrams_by_id = {e["id"]: e for e in engrams}
    all_results = []

    for min_sim in args.min_sims:
        print(f"--- min_sim={min_sim} ---")

        # Embedding + candidate finding (shared across models)
        t0 = time.time()
        candidate_map, sim_matrix = find_candidates(engrams, min_sim=min_sim, top_k=args.top_k)
        embed_time = time.time() - t0

        with_candidates = sum(1 for v in candidate_map.values() if v)
        total_edges = sum(len(v) for v in candidate_map.values())
        no_candidates = len(engrams) - with_candidates

        print(f"Embedding + candidates: {embed_time:.1f}s")
        print(f"  {with_candidates} engrams with candidates, {no_candidates} unique (no match)")
        print(f"  {total_edges} total candidate edges")

        # Similarity distribution
        if sim_matrix is not None:
            upper = sim_matrix[np.triu_indices(len(engrams), k=1)]
            if len(upper) > 0:
                above = (upper >= min_sim).sum()
                print(f"  Similarity stats: mean={upper.mean():.3f}, "
                      f"max={upper.max():.3f}, "
                      f"pairs above {min_sim}: {above}")

        # Build batches
        batches = build_batches(candidate_map, engrams_by_id, char_budget=args.batch_size)
        print(f"  {len(batches)} batch(es)\n")

        if args.dry_run:
            # Show top candidate pairs
            print("  Top 10 similar pairs:")
            if sim_matrix is not None:
                pairs = []
                for i in range(len(engrams)):
                    for j in range(i + 1, len(engrams)):
                        if sim_matrix[i][j] >= min_sim:
                            pairs.append((sim_matrix[i][j], engrams[i], engrams[j]))
                pairs.sort(key=lambda x: x[0], reverse=True)
                for sim, e1, e2 in pairs[:10]:
                    print(f"    {sim:.3f}: [{e1['id']}] {e1['text'][:60]}...")
                    print(f"           [{e2['id']}] {e2['text'][:60]}...")
            continue

        for model in args.models:
            print(f"  Model: {model}")
            model_start = time.time()

            total_groups = 0
            total_merged = 0
            total_no_match = 0
            total_errors = 0
            total_llm_time = 0
            all_groups = []
            batch_details = []

            for bi, batch in enumerate(batches):
                batch_id = f"bench-{run_id}-sim{min_sim}-b{bi}"
                print(f"    Batch {bi + 1}/{len(batches)} "
                      f"({len(batch['unverified_ids'])} engrams, "
                      f"{len(batch['engrams'])} total)...", end=" ", flush=True)

                response, elapsed, error = call_benchmark_dedup_llm(batch, model, batch_id=batch_id)
                total_llm_time += elapsed

                if error:
                    print(f"ERROR: {error[:60]}")
                    total_errors += len(batch["unverified_ids"])
                    batch_details.append({"batch": bi, "error": error, "elapsed_s": elapsed})
                    continue

                valid_groups, val_errors = validate_dedup_response(response, batch, mode="bootstrap")
                if val_errors:
                    for ve in val_errors[:3]:
                        print(f"\n      validation: {ve}", end="")

                n_groups = len(valid_groups)
                n_merged = sum(len(g["ids"]) for g in valid_groups)
                n_no_match = len(response.get("no_match_ids", []))

                total_groups += n_groups
                total_merged += n_merged
                total_no_match += n_no_match
                all_groups.extend(valid_groups)

                batch_details.append({
                    "batch": bi,
                    "groups": n_groups,
                    "merged_ids": n_merged,
                    "no_match": n_no_match,
                    "validation_errors": len(val_errors),
                    "elapsed_s": round(elapsed, 2),
                    "response": response,
                })

                print(f"{n_groups} groups, {n_merged} merged, {n_no_match} unique in {elapsed:.1f}s")

            model_elapsed = time.time() - model_start

            # Deduplicate across batches: IDs can appear in groups in multiple batches
            # Each group = 1 survivor + N-1 absorbed. Collect unique absorbed IDs.
            all_grouped_ids = set()
            unique_groups = []
            for g in all_groups:
                # Skip if all IDs already accounted for
                new_ids = set(g["ids"]) - all_grouped_ids
                if len(new_ids) < 2:
                    continue
                all_grouped_ids.update(g["ids"])
                unique_groups.append(g)

            # Reduction = total unique grouped IDs - number of unique groups (survivors)
            reduction = len(all_grouped_ids) - len(unique_groups) if unique_groups else 0

            result = {
                "model": model,
                "min_sim": min_sim,
                "batch_size": args.batch_size,
                "top_k": args.top_k,
                "input_engrams": len(engrams),
                "with_candidates": with_candidates,
                "no_candidates": no_candidates,
                "num_batches": len(batches),
                "total_groups": len(unique_groups),
                "total_merged_ids": len(all_grouped_ids),
                "total_no_match": total_no_match,
                "total_errors": total_errors,
                "reduction": reduction,
                "output_engrams": len(engrams) - reduction,
                "reduction_pct": round(100 * reduction / len(engrams), 1) if engrams else 0,
                "embed_time_s": round(embed_time, 2),
                "llm_time_s": round(total_llm_time, 2),
                "total_time_s": round(model_elapsed, 2),
                "groups": [{
                    "ids": g["ids"],
                    "canonical_text": g["canonical_text"],
                    "confidence": g["confidence"],
                    "reason": g.get("reason", ""),
                } for g in unique_groups],
                "batch_details": batch_details,
            }
            all_results.append(result)

            # Save individual result
            result_file = run_dir / f"{model}_sim{min_sim}.json"
            with open(result_file, "w") as f:
                json.dump(result, f, indent=2)

            print(f"\n    {model} summary: {total_groups} groups, "
                  f"{reduction} engrams reduced ({result['reduction_pct']}%), "
                  f"{result['output_engrams']}/{len(engrams)} remaining, "
                  f"{total_llm_time:.1f}s LLM time\n")

    if args.dry_run:
        return

    # Save summary + report
    summary = {
        "run_id": run_id,
        "source": source_label,
        "input_engrams": len(engrams),
        "config": {
            "models": args.models,
            "min_sims": args.min_sims,
            "batch_size": args.batch_size,
            "top_k": args.top_k,
        },
        "results": [{
            "model": r["model"],
            "min_sim": r["min_sim"],
            "input_engrams": r["input_engrams"],
            "total_groups": r["total_groups"],
            "reduction": r["reduction"],
            "reduction_pct": r["reduction_pct"],
            "output_engrams": r["output_engrams"],
            "llm_time_s": r["llm_time_s"],
        } for r in all_results],
    }

    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    # Markdown report
    md = [
        f"# Dedup Benchmark — {run_id}\n",
        f"**Source**: {source_label}  ",
        f"**Input engrams**: {len(engrams)}  ",
        f"**Models**: {', '.join(args.models)}  ",
        f"**Similarity thresholds**: {', '.join(str(s) for s in args.min_sims)}  ",
        f"**Batch size**: {args.batch_size} chars  ",
        f"**Top-k candidates**: {args.top_k}\n",
        "## Summary\n",
        "| Model | min_sim | Batches | Groups | Merged IDs | Reduction | Output | LLM Time |",
        "|-------|--------:|--------:|-------:|-----------:|----------:|-------:|---------:|",
    ]

    for r in all_results:
        md.append(
            f"| {r['model']} | {r['min_sim']} | {r['num_batches']} | "
            f"{r['total_groups']} | {r['total_merged_ids']} | "
            f"-{r['reduction']} ({r['reduction_pct']}%) | "
            f"{r['output_engrams']} | {r['llm_time_s']:.1f}s |"
        )

    # Merge groups detail
    md.append("\n## Merge Groups\n")
    for r in all_results:
        md.append(f"### {r['model']} — min_sim={r['min_sim']}\n")
        if not r["groups"]:
            md.append("_No groups found._\n")
            continue
        for i, g in enumerate(r["groups"], 1):
            ids_str = ", ".join(f"#{eid}" for eid in g["ids"])
            md.append(f"**Group {i}** ({ids_str}) — confidence {g['confidence']:.2f}")
            md.append(f"  Canonical: {g['canonical_text']}")
            md.append(f"  Reason: {g['reason']}")
            # Show original texts
            for eid in g["ids"]:
                if eid in engrams_by_id:
                    md.append(f"  - [{eid}] {engrams_by_id[eid]['text'][:120]}")
            md.append("")

    # Input engrams reference
    md.append("\n## Input Engrams\n")
    for e in engrams:
        cat = e.get("category", "")
        md.append(f"- **[{e['id']}]** [{cat}] {e['text'][:150]}")

    report_path = run_dir / "report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(md))

    print("=" * 70)
    for line in md[:20]:
        print(line)
    if len(md) > 20:
        print(f"... ({len(md) - 20} more lines)")

    print(f"\nResults saved to: {run_dir}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
