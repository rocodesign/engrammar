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


# --- Candidate finding (copied from dedup.py to avoid DB deps) ---


def find_candidates(engrams, min_sim=0.50, top_k=8):
    """Find embedding-similar candidate pairs among all engrams.

    Returns:
        dict mapping engram_id -> [(other_id, similarity), ...]
        similarity matrix for analysis
    """
    if len(engrams) < 2:
        return {}, None

    texts = [e["text"] for e in engrams]
    embs = embed_batch(texts)

    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normed = embs / norms
    sim_matrix = normed @ normed.T

    candidate_map = {}
    for i, engram in enumerate(engrams):
        scores = sim_matrix[i].copy()
        scores[i] = -1  # exclude self

        above_threshold = np.where(scores >= min_sim)[0]
        if len(above_threshold) == 0:
            candidate_map[engram["id"]] = []
            continue

        sorted_indices = above_threshold[np.argsort(scores[above_threshold])[::-1]][:top_k]
        candidates = [
            (engrams[j]["id"], float(scores[j]))
            for j in sorted_indices
        ]
        candidate_map[engram["id"]] = candidates

    return candidate_map, sim_matrix


# --- Batch building ---


def build_batches(candidate_map, engrams_by_id, char_budget=6000):
    """Group engrams+candidates into batches respecting char budget."""
    all_ids = set(candidate_map.keys())
    # Only batch engrams that have candidates
    sorted_ids = sorted(uid for uid in candidate_map if candidate_map[uid])

    batches = []
    current_engrams = {}
    current_edges = []
    current_unverified = set()
    current_chars = 0

    for uid in sorted_ids:
        candidates = candidate_map[uid]
        engram_chars = len(engrams_by_id[uid]["text"])
        new_chars = engram_chars if uid not in current_engrams else 0
        for cid, sim in candidates:
            if cid not in current_engrams:
                new_chars += len(engrams_by_id[cid]["text"])

        if current_chars + new_chars > char_budget and current_unverified:
            batches.append({
                "engrams": list(current_engrams.values()),
                "candidate_edges": current_edges,
                "unverified_ids": current_unverified,
            })
            current_engrams = {}
            current_edges = []
            current_unverified = set()
            current_chars = 0

        if uid not in current_engrams:
            current_engrams[uid] = _engram_payload(engrams_by_id[uid])
            current_chars += engram_chars
        current_unverified.add(uid)

        for cid, sim in candidates:
            if cid not in current_engrams:
                current_engrams[cid] = _engram_payload(engrams_by_id[cid])
                current_chars += len(engrams_by_id[cid]["text"])
            current_edges.append({
                "source_id": uid,
                "target_id": cid,
                "similarity": round(sim, 4),
            })

    if current_unverified:
        batches.append({
            "engrams": list(current_engrams.values()),
            "candidate_edges": current_edges,
            "unverified_ids": current_unverified,
        })

    return batches


def _engram_payload(engram):
    return {
        "id": engram["id"],
        "status": "unverified",
        "text": engram["text"],
        "category": engram.get("category", "general"),
        "prerequisites": engram.get("prerequisites", {}),
        "occurrence_count": engram.get("occurrence_count", 1),
    }


# --- LLM call ---


_prompt_cache = {}


def _get_prompt(name):
    if name not in _prompt_cache:
        _prompt_cache[name] = load_prompt(name)
    return _prompt_cache[name]


def call_dedup_llm(batch, model, batch_id=""):
    """Send batch to LLM for dedup decisions. Returns parsed response or None."""
    import subprocess

    system_prompt = _get_prompt("dedup/system.md")
    mode_snippet = _get_prompt("dedup/bootstrap.md")

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


def _parse_json_response(text):
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


# --- Validation ---


def validate_response(response, batch):
    """Validate dedup response. Returns (valid_groups, errors)."""
    errors = []
    if not isinstance(response, dict):
        return [], ["Response is not a dict"]

    groups = response.get("groups", [])
    no_match_ids = response.get("no_match_ids", [])

    if not isinstance(groups, list):
        return [], ["groups is not a list"]

    input_ids = {e["id"] for e in batch["engrams"]}
    seen_ids = set()
    valid_groups = []

    for i, group in enumerate(groups):
        ids = group.get("ids", [])
        canonical = group.get("canonical_text", "")
        confidence = group.get("confidence", 0)

        group_errors = []
        if len(ids) < 2:
            group_errors.append(f"Group {i}: size < 2")
        unknown = set(ids) - input_ids
        if unknown:
            group_errors.append(f"Group {i}: unknown IDs {unknown}")
        duped = set(ids) & seen_ids
        if duped:
            group_errors.append(f"Group {i}: IDs {duped} already used")
        if not canonical or not canonical.strip():
            group_errors.append(f"Group {i}: empty canonical_text")
        if not isinstance(confidence, (int, float)) or not (0 <= confidence <= 1):
            group_errors.append(f"Group {i}: bad confidence {confidence}")

        if group_errors:
            errors.extend(group_errors)
        else:
            seen_ids.update(ids)
            valid_groups.append(group)

    for nid in no_match_ids:
        if nid not in input_ids:
            errors.append(f"no_match_ids: unknown ID {nid}")
        seen_ids.add(nid)

    missing = input_ids - seen_ids
    if missing:
        errors.append(f"Unaccounted IDs: {missing}")

    return valid_groups, errors


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

                response, elapsed, error = call_dedup_llm(batch, model, batch_id=batch_id)
                total_llm_time += elapsed

                if error:
                    print(f"ERROR: {error[:60]}")
                    total_errors += len(batch["unverified_ids"])
                    batch_details.append({"batch": bi, "error": error, "elapsed_s": elapsed})
                    continue

                valid_groups, val_errors = validate_response(response, batch)
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
