#!/usr/bin/env python3
"""End-to-end attribution benchmark with autoresearch parameter sweep.

Tests how evaluation feedback (positive/negative) affects search ranking
over multiple rounds. Sweeps attribution parameters to find optimal values.

The benchmark:
1. Copies production DB to an isolated temp copy
2. For each ground truth query with expected_ids:
   - Runs search, records baseline ranks of expected engrams
   - Simulates N evaluation rounds (positive for expected, negative for wrong)
   - After each round, re-searches and tracks rank changes
3. Measures: rank improvement, signal strength, convergence speed
4. Sweeps: EMA_ALPHA, RELEVANCE_WEIGHT, attribution floor

Usage:
    python benchmark/run_attribution_benchmark.py              # single run with current config
    python benchmark/run_attribution_benchmark.py --sweep      # grid sweep
    python benchmark/run_attribution_benchmark.py --report     # show best config from results
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from itertools import product

sys.path.insert(0, os.path.expanduser("~/.engrammar"))

GROUND_TRUTH_PATH = os.path.join(os.path.dirname(__file__), "search_ground_truth.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results", "attribution")
PROD_DB_PATH = os.path.expanduser("~/.engrammar/engrams.db")

# Number of simulated eval rounds per query
NUM_EVAL_ROUNDS = 5
# Score given by evaluator for positive/negative engrams (on -3 to +3 scale)
POSITIVE_EVAL_SCORE = 2  # "applied, useful"
NEGATIVE_EVAL_SCORE = -1  # "noise, irrelevant"


def load_ground_truth():
    """Load ground truth queries that have expected_ids (relevant type)."""
    with open(GROUND_TRUTH_PATH) as f:
        data = json.load(f)
    return [l for l in data["labels"] if l["expect"] == "relevant" and l.get("expected_ids")]


def copy_db(dest_path):
    """Copy production DB to isolated location."""
    shutil.copy2(PROD_DB_PATH, dest_path)


def run_search(query, db_path, top_k=10):
    """Run search and return results with diagnostics."""
    from engrammar.search.engine import search
    results, meta = search(
        query, db_path=db_path, top_k=top_k,
        skip_prerequisites=True, return_diagnostics=True,
    )
    return results, meta


def get_rank(results, engram_id):
    """Get 1-based rank of engram_id in results, or None if not found."""
    for i, r in enumerate(results):
        if r["id"] == engram_id:
            return i + 1
    return None


def get_score(results, engram_id):
    """Get score of engram_id in results, or None if not found."""
    for r in results:
        if r["id"] == engram_id:
            return r["score"]
    return None


def simulate_evaluation(engram_id, eval_score, prompt_tags, db_path, config):
    """Simulate an evaluation round for one engram.

    Distributes eval_score to content tags using weighted attribution,
    just like the real evaluator does.
    """
    from engrammar.core.db import get_content_tags, update_tag_relevance
    from engrammar.pipeline.evaluator import _compute_weighted_attribution

    content_tags = get_content_tags(engram_id, db_path=db_path)
    if not content_tags:
        return

    # Normalize score to [-1, 1] like the evaluator
    normalized = eval_score / 3.0

    # Weighted attribution if prompt tags available
    if prompt_tags:
        weighted = _compute_weighted_attribution(content_tags, prompt_tags, normalized)
        if weighted:
            update_tag_relevance(engram_id, weighted, weight=1.0, db_path=db_path)
            return

    # Fallback: uniform
    uniform = {tag: normalized for tag in content_tags}
    update_tag_relevance(engram_id, uniform, weight=1.0, db_path=db_path)


def run_single_config(ground_truth, config, verbose=False):
    """Run full attribution benchmark with one parameter config.

    Returns dict with metrics.
    """
    from engrammar.core import db as db_module
    from engrammar.core import config as config_module

    # Create isolated DB copy
    tmp_dir = tempfile.mkdtemp(prefix="attr_bench_")
    db_path = os.path.join(tmp_dir, "engrams.db")
    copy_db(db_path)

    # Patch EMA_ALPHA in db module
    original_alpha = db_module.EMA_ALPHA
    db_module.EMA_ALPHA = config["ema_alpha"]

    # Patch scoring config
    original_config_cache = config_module._config_cache
    try:
        cfg = config_module.load_config()
        cfg.setdefault("scoring", {})
        cfg["scoring"]["weight_feedback"] = config["weight_feedback"]
        config_module._config_cache = cfg
    except Exception:
        pass

    try:
        query_results = []

        for gt in ground_truth:
            query = gt["query"]
            expected_ids = set(gt["expected_ids"])

            # Baseline search
            results, meta = run_search(query, db_path, top_k=20)
            prompt_tags = meta.get("prompt_tags", [])

            # Per-query: track best rank among all expected engrams per round
            def best_rank(res):
                ranks = [get_rank(res, eid) for eid in expected_ids]
                valid = [r for r in ranks if r is not None]
                return min(valid) if valid else None

            # Per-engram tracking for verbose output
            round_ranks = {eid: [get_rank(results, eid)] for eid in expected_ids}
            best_ranks = [best_rank(results)]

            for round_num in range(NUM_EVAL_ROUNDS):
                # Positive eval for expected engrams only
                for eid in expected_ids:
                    simulate_evaluation(eid, POSITIVE_EVAL_SCORE, prompt_tags, db_path, config)

                # Re-search after eval
                results, _ = run_search(query, db_path, top_k=20)
                best_ranks.append(best_rank(results))
                for eid in expected_ids:
                    round_ranks[eid].append(get_rank(results, eid))

            # Per-query metrics
            initial_best = best_ranks[0]
            final_best = best_ranks[-1]
            initial_r = initial_best if initial_best is not None else 21
            final_r = final_best if final_best is not None else 21

            any_in_top1_before = initial_best == 1
            any_in_top1_after = final_best == 1
            any_in_top3_before = initial_best is not None and initial_best <= 3
            any_in_top3_after = final_best is not None and final_best <= 3

            query_results.append({
                "query": query[:60],
                "expected_ids": list(expected_ids),
                "best_rank_trajectory": best_ranks,
                "initial_best": initial_best,
                "final_best": final_best,
                "improvement": initial_r - final_r,
                "top1_before": any_in_top1_before,
                "top1_after": any_in_top1_after,
                "top3_before": any_in_top3_before,
                "top3_after": any_in_top3_after,
            })

            if verbose:
                traj = " → ".join(str(r) if r else "–" for r in best_ranks)
                improved = final_r < initial_r
                marker = "✓" if improved else "="
                print(f"  {marker} [{query[:45]}]: best={traj}")
                # Show individual engrams if multiple expected
                if len(expected_ids) > 1:
                    for eid in sorted(expected_ids):
                        etraj = " → ".join(str(r) if r else "–" for r in round_ranks[eid])
                        print(f"      EG#{eid}: {etraj}")

        # Aggregate metrics
        total = len(query_results)
        if total == 0:
            return {"error": "no results"}

        improved = sum(1 for r in query_results if r["improvement"] > 0)
        avg_improvement = sum(r["improvement"] for r in query_results) / total
        top1_before = sum(1 for r in query_results if r["top1_before"])
        top1_after = sum(1 for r in query_results if r["top1_after"])
        top3_before = sum(1 for r in query_results if r["top3_before"])
        top3_after = sum(1 for r in query_results if r["top3_after"])

        # Convergence: how many rounds until best rank stabilizes
        convergence_rounds = []
        for r in query_results:
            traj = r["best_rank_trajectory"]
            for i in range(1, len(traj)):
                if traj[i] == traj[-1]:
                    convergence_rounds.append(i)
                    break
            else:
                convergence_rounds.append(len(traj))
        avg_convergence = sum(convergence_rounds) / len(convergence_rounds)

        return {
            "config": config,
            "total_queries": total,
            "improved": improved,
            "avg_improvement": round(avg_improvement, 2),
            "top1_before": top1_before,
            "top1_after": top1_after,
            "top1_gain": top1_after - top1_before,
            "top3_before": top3_before,
            "top3_after": top3_after,
            "top3_gain": top3_after - top3_before,
            "improvement_rate": round(improved / total, 3),
            "avg_convergence_rounds": round(avg_convergence, 2),
            "details": query_results,
        }

    finally:
        # Restore patched values
        db_module.EMA_ALPHA = original_alpha
        config_module._config_cache = original_config_cache
        # Cleanup
        shutil.rmtree(tmp_dir, ignore_errors=True)


def composite_score(metrics):
    """Single number to compare configs. Higher is better."""
    return (
        metrics["top1_gain"] * 3.0                # top-1 gains are the primary goal
        + metrics["top3_gain"] * 1.5              # top-3 gains also matter
        + metrics["improvement_rate"] * 5.0       # % of queries that improved
        + metrics["avg_improvement"] * 1.0        # average rank movement
    )


def run_sweep(ground_truth):
    """Grid sweep over attribution parameters."""
    # Parameters to sweep
    ema_alphas = [0.15, 0.20, 0.25, 0.30, 0.40, 0.50]
    weight_feedbacks = [0.10, 0.15, 0.20, 0.30, 0.40]
    # Attribution floor is in evaluator.py, harder to patch at runtime
    # so we sweep the two main knobs

    configs = []
    for alpha, wf in product(ema_alphas, weight_feedbacks):
        configs.append({
            "ema_alpha": alpha,
            "weight_feedback": wf,
        })

    print(f"Sweeping {len(configs)} configs across {len(ground_truth)} queries...")
    print(f"Parameters: ema_alpha × weight_feedback = {len(ema_alphas)} × {len(weight_feedbacks)}")
    print()

    results = []
    best_score = -999
    best_config = None

    for i, cfg in enumerate(configs):
        t0 = time.time()
        metrics = run_single_config(ground_truth, cfg)
        elapsed = time.time() - t0
        score = composite_score(metrics)
        metrics["composite_score"] = round(score, 3)
        results.append(metrics)

        marker = "★" if score > best_score else " "
        if score > best_score:
            best_score = score
            best_config = cfg

        print(
            f"  {marker} [{i+1:3d}/{len(configs)}] "
            f"alpha={cfg['ema_alpha']:.2f} wf={cfg['weight_feedback']:.2f} | "
            f"improved={metrics['improved']}/{metrics['total_queries']} "
            f"top1={metrics['top1_before']}→{metrics['top1_after']} "
            f"top3={metrics['top3_before']}→{metrics['top3_after']} "
            f"avg_impr={metrics['avg_improvement']:+.1f} "
            f"conv={metrics['avg_convergence_rounds']:.1f} "
            f"score={score:+.2f} "
            f"({elapsed:.1f}s)"
        )

    print()
    print(f"Best config: {best_config}")
    print(f"Best composite score: {best_score:.3f}")

    return results, best_config


def save_results(results, label="single"):
    """Save results to JSON."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"attribution_{label}_{ts}.json")

    # Strip detailed trajectories for sweep results to keep file small
    for r in results:
        if "details" in r and label == "sweep":
            for d in r["details"]:
                del d["rank_trajectory"]  # keep summary only

    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to {path}")
    return path


def show_report():
    """Show best config from most recent sweep results."""
    if not os.path.isdir(RESULTS_DIR):
        print("No results found. Run --sweep first.")
        return

    files = sorted(f for f in os.listdir(RESULTS_DIR) if f.startswith("attribution_sweep"))
    if not files:
        print("No sweep results found.")
        return

    path = os.path.join(RESULTS_DIR, files[-1])
    print(f"Loading: {path}")
    with open(path) as f:
        results = json.load(f)

    # Sort by composite score
    scored = [(r, composite_score(r) if "composite_score" not in r else r["composite_score"]) for r in results]
    scored.sort(key=lambda x: x[1], reverse=True)

    print(f"\nTop 10 configs (out of {len(results)}):\n")
    print(f"{'Rank':<5} {'alpha':<7} {'wf':<7} {'improved':<10} {'top1':<10} {'top3':<10} {'avg_impr':<10} {'conv':<6} {'score':<8}")
    print("-" * 66)
    for i, (r, score) in enumerate(scored[:10]):
        cfg = r["config"]
        print(
            f"{i+1:<5} {cfg['ema_alpha']:<7.2f} {cfg['weight_feedback']:<7.2f} "
            f"{r['improved']}/{r['total_queries']:<7} "
            f"{r['top1_before']}→{r['top1_after']:<7} "
            f"{r['top3_before']}→{r['top3_after']:<7} "
            f"{r['avg_improvement']:<+10.1f} "
            f"{r['avg_convergence_rounds']:<6.1f} "
            f"{score:<+8.2f}"
        )

    print(f"\nCurrent production: ema_alpha=0.30, weight_feedback=0.20")
    best = scored[0][0]["config"]
    print(f"Best found:         ema_alpha={best['ema_alpha']:.2f}, weight_feedback={best['weight_feedback']:.2f}")


def main():
    parser = argparse.ArgumentParser(description="Attribution benchmark with autoresearch")
    parser.add_argument("--sweep", action="store_true", help="Grid sweep over parameters")
    parser.add_argument("--report", action="store_true", help="Show best config from results")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show per-engram trajectories")
    args = parser.parse_args()

    if args.report:
        show_report()
        return

    ground_truth = load_ground_truth()
    print(f"Loaded {len(ground_truth)} ground truth queries with expected_ids")

    if args.sweep:
        results, best = run_sweep(ground_truth)
        save_results(results, "sweep")
    else:
        # Single run with current production config
        config = {"ema_alpha": 0.30, "weight_feedback": 0.20}
        print(f"Running single evaluation with config: {config}")
        print(f"Simulating {NUM_EVAL_ROUNDS} eval rounds per query...\n")
        metrics = run_single_config(ground_truth, config, verbose=args.verbose or True)

        print(f"\n{'='*60}")
        print(f"RESULTS ({metrics['total_queries']} queries)")
        print(f"{'='*60}")
        print(f"  Queries improved:     {metrics['improved']} ({metrics['improvement_rate']*100:.0f}%)")
        print(f"  Avg rank improvement: {metrics['avg_improvement']:+.1f}")
        print(f"  Top-1: {metrics['top1_before']} → {metrics['top1_after']} ({metrics['top1_gain']:+d})")
        print(f"  Top-3: {metrics['top3_before']} → {metrics['top3_after']} ({metrics['top3_gain']:+d})")
        print(f"  Avg convergence:      {metrics['avg_convergence_rounds']:.1f} rounds")

        save_results([metrics], "single")


if __name__ == "__main__":
    main()
