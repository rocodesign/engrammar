#!/usr/bin/env python3
"""Autoresearch loop for search scoring optimization.

Inspired by karpathy/autoresearch: propose parameter changes, run benchmark,
measure quality metric, keep improvements, revert regressions.

Pre-computes all embeddings once, then sweeps scoring params with pure numpy.
576 configs in ~30 seconds instead of ~2 hours.

Usage:
    python benchmark/run_search_autoresearch.py              # single evaluation
    python benchmark/run_search_autoresearch.py --sweep       # grid sweep over key params
    python benchmark/run_search_autoresearch.py --report      # show best config from results
"""

import argparse
import json
import math
import os
import statistics
import sys
import time
from datetime import datetime
from itertools import product

import numpy as np

sys.path.insert(0, os.path.expanduser("~/.engrammar"))

GROUND_TRUTH_PATH = os.path.join(os.path.dirname(__file__), "search_ground_truth.json")
QUERIES_PATH = os.path.join(os.path.dirname(__file__), "search_queries.json")
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results", "autoresearch")
ABSTAIN_SCORE_THRESHOLD = 0.30


def load_ground_truth():
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)["labels"]


def load_queries():
    with open(QUERIES_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Pre-computation: run once, reuse across all configs
# ---------------------------------------------------------------------------

class PrecomputedData:
    """All embeddings and base scores pre-computed for fast sweep."""

    def __init__(self, queries):
        from engrammar.core.embeddings import embed_text, embed_batch, load_tag_vocab_index
        from engrammar.core.db import get_all_active_engrams, get_content_tags_batch
        from engrammar.search.prompt_tags import _load_tag_frequencies
        from engrammar.search.engine import search
        from engrammar.search.query_filter import is_low_information

        print("Pre-computing embeddings and base scores...")
        t0 = time.time()

        # Load engrams and content tags
        engrams = get_all_active_engrams()
        engram_ids = [e["id"] for e in engrams]
        self.content_tags_map = get_content_tags_batch(engram_ids)

        # Collect all unique content tags across all engrams
        all_tags = set()
        for tags in self.content_tags_map.values():
            all_tags.update(tags)
        all_tags = sorted(all_tags)
        self.tag_to_idx = {t: i for i, t in enumerate(all_tags)}

        # Embed all unique content tags
        if all_tags:
            tag_embs = embed_batch(all_tags)
            tag_norms = np.linalg.norm(tag_embs, axis=1, keepdims=True) + 1e-10
            self.tag_embeddings = tag_embs / tag_norms  # (n_tags, dim)
        else:
            self.tag_embeddings = np.zeros((0, 384), dtype=np.float32)

        # Load tag vocab for prompt tag detection
        vocab_embeddings, vocab_labels = load_tag_vocab_index()
        self.vocab_embeddings = vocab_embeddings
        self.vocab_labels = vocab_labels or []
        if vocab_embeddings is not None:
            v_norms = np.linalg.norm(vocab_embeddings, axis=1, keepdims=True) + 1e-10
            self.vocab_normed = vocab_embeddings / v_norms
        else:
            self.vocab_normed = None

        # Tag frequencies for IDF
        tag_freqs = _load_tag_frequencies()
        self.tag_freqs = tag_freqs
        self.max_freq = max(tag_freqs.values()) if tag_freqs else 1

        # Pre-compute base search results (RRF + repo + feedback, no tag affinity)
        # and query embeddings for prompt tag detection
        self.query_data = []
        for i, q in enumerate(queries):
            qtext = q["prompt"]

            # Check query filter
            filtered, filter_reason = is_low_information(qtext)

            # Embed query for prompt tag detection
            q_emb = embed_text(qtext)
            q_norm = q_emb / (np.linalg.norm(q_emb) + 1e-10)

            # Run base search (with tag affinity weight=0 to get base scores)
            import engrammar.core.config as cfg_mod
            cfg_mod._config_cache = None
            config = cfg_mod.load_config()
            config["scoring"]["weight_content_tag"] = 0.0  # disable tag affinity
            hits, meta = search(qtext, return_diagnostics=True, skip_prerequisites=True, top_k=10)

            base_results = []
            best_vector_sim = 0.0
            for h in hits:
                d = h.get("_diag", {})
                eid = h["id"]
                etags = self.content_tags_map.get(eid, [])
                etag_indices = [self.tag_to_idx[t] for t in etags if t in self.tag_to_idx]
                vsim = d.get("vector_sim", 0.0)
                if vsim > best_vector_sim:
                    best_vector_sim = vsim
                base_results.append({
                    "id": eid,
                    "base_score": h["score"],
                    "text": h["text"][:80],
                    "content_tags": etags,
                    "tag_indices": etag_indices,
                    "vector_sim": vsim,
                })

            # Pre-compute score gap (top1 - top2) for margin-based abstain
            score_gap = 0.0
            if len(base_results) >= 2:
                score_gap = base_results[0]["base_score"] - base_results[1]["base_score"]

            self.query_data.append({
                "idx": i,
                "query": qtext[:100],
                "query_emb_norm": q_norm,
                "base_results": base_results,
                "filtered": filtered,
                "filter_reason": filter_reason,
                "best_vector_sim": best_vector_sim,
                "score_gap": score_gap,
            })

        elapsed = time.time() - t0
        print(f"Pre-computation done: {len(queries)} queries, {len(all_tags)} unique tags, "
              f"{len(engrams)} engrams in {elapsed:.1f}s")

    def detect_prompt_tags_fast(self, query_emb_norm, threshold, top_k, selectivity_limit):
        """Fast prompt tag detection using pre-computed vocab embeddings."""
        if self.vocab_normed is None or len(self.vocab_labels) == 0:
            return []

        sims = self.vocab_normed @ query_emb_norm

        # IDF weighting
        weighted = []
        for i, label in enumerate(self.vocab_labels):
            sim_f = float(sims[i])
            freq = self.tag_freqs.get(label, 1)
            freq_ratio = freq / self.max_freq
            idf = 1.0 - 0.3 * freq_ratio
            adj = sim_f * idf
            if adj >= threshold:
                weighted.append((i, label, adj))

        if not weighted:
            return []

        # Selectivity check
        selectivity = len(weighted) / max(len(self.vocab_labels), 1)
        if selectivity > selectivity_limit:
            return []

        weighted.sort(key=lambda x: -x[2])

        # Gap-based filtering
        if len(weighted) >= 2:
            top_score = weighted[0][2]
            median_score = weighted[len(weighted) // 2][2]
            gap = top_score - median_score
            if gap < 0.03:
                return []
            cutoff = top_score - gap * 0.6
            weighted = [(i, l, s) for i, l, s in weighted if s >= cutoff]

        result = [(label, score) for _, label, score in weighted[:top_k]]
        # Return tag indices for fast similarity lookup
        tag_indices = [self.tag_to_idx[label] for label, _ in result if label in self.tag_to_idx]
        return result, tag_indices

    def compute_tag_affinity(self, prompt_tag_indices, engram_tag_indices,
                             tag_sim_floor, tag_sim_ceiling,
                             tag_mismatch_threshold, tag_mismatch_penalty, w_content):
        """Fast tag affinity using pre-computed embeddings."""
        if not prompt_tag_indices or not engram_tag_indices:
            if prompt_tag_indices and not engram_tag_indices:
                return tag_mismatch_penalty * 0.5
            return 0.0

        # Compute best similarity across all prompt-tag × engram-tag pairs
        pt_embs = self.tag_embeddings[prompt_tag_indices]  # (n_pt, dim)
        et_embs = self.tag_embeddings[engram_tag_indices]  # (n_et, dim)
        sim_matrix = pt_embs @ et_embs.T  # (n_pt, n_et)
        best_sim = float(sim_matrix.max())

        # Thresholded ramp
        tag_range = tag_sim_ceiling - tag_sim_floor
        if best_sim < tag_sim_floor:
            tag_bonus = 0.0
        elif tag_range > 0 and best_sim < tag_sim_ceiling:
            tag_bonus = (best_sim - tag_sim_floor) / tag_range
        else:
            tag_bonus = 1.0

        delta = w_content * tag_bonus

        # Mismatch penalty
        if best_sim < tag_mismatch_threshold:
            delta += tag_mismatch_penalty

        return delta


def run_sweep_fast(precomputed, ground_truth, param_grid):
    """Fast sweep: only recompute tag affinity + abstention per config."""
    gt_by_idx = {g["idx"]: g for g in ground_truth}
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    combos = list(product(*values))
    print(f"Grid sweep: {len(combos)} configurations")

    best_composite = 1.0
    best_config = None
    all_results = []

    for ci, combo in enumerate(combos):
        params = dict(zip(keys, combo))

        # Tag affinity params
        w_content = params.get("weight_content_tag", 0.20)
        tag_sim_floor = params.get("tag_sim_floor", 0.55)
        tag_sim_ceiling = params.get("tag_sim_ceiling", 0.85)
        tag_mismatch_penalty = 0.0  # kept out per instructions
        tag_mismatch_threshold = 0.20
        prompt_tag_threshold = params.get("prompt_tag_threshold", 0.60)
        prompt_tag_top_k = params.get("prompt_tag_top_k", 3)

        # Abstention params
        min_vector_sim = params.get("min_vector_sim", 0.0)
        min_top1_score = params.get("min_top1_score", 0.0)
        min_score_margin = params.get("min_score_margin", 0.0)

        # Per-query: recompute prompt tags + tag affinity + abstention
        query_results = []
        for qd in precomputed.query_data:
            # Check query filter first (pre-computed, always applies)
            if qd["filtered"]:
                query_results.append({
                    "idx": qd["idx"],
                    "hits": [],
                    "prompt_tags": [],
                    "filtered": True,
                })
                continue

            # Check vector similarity abstain
            if min_vector_sim > 0 and qd["best_vector_sim"] < min_vector_sim:
                query_results.append({
                    "idx": qd["idx"],
                    "hits": [],
                    "prompt_tags": [],
                    "filtered": True,
                })
                continue

            # Detect prompt tags with current threshold
            query_words = len(qd["query"].strip().split())
            selectivity_limit = min(0.30 + query_words * 0.03, 0.55)
            pt_result = precomputed.detect_prompt_tags_fast(
                qd["query_emb_norm"], prompt_tag_threshold,
                prompt_tag_top_k, selectivity_limit
            )
            prompt_tags = pt_result[0] if pt_result else []
            prompt_tag_indices = pt_result[1] if pt_result else []

            # Rescore each result
            scored = []
            for br in qd["base_results"]:
                score = br["base_score"]
                if w_content > 0 and prompt_tag_indices:
                    delta = precomputed.compute_tag_affinity(
                        prompt_tag_indices, br["tag_indices"],
                        tag_sim_floor, tag_sim_ceiling,
                        tag_mismatch_threshold, tag_mismatch_penalty, w_content
                    )
                    score += delta
                scored.append({
                    "id": br["id"],
                    "score": round(score, 4),
                    "text": br["text"],
                })

            scored.sort(key=lambda x: -x["score"])

            # Post-scoring abstention: min top-1 score
            if min_top1_score > 0 and scored and scored[0]["score"] < min_top1_score:
                query_results.append({
                    "idx": qd["idx"],
                    "hits": [],
                    "prompt_tags": prompt_tags,
                    "filtered": True,
                })
                continue

            # Post-scoring abstention: score margin (top1 - top2)
            if min_score_margin > 0 and len(scored) >= 2:
                margin = scored[0]["score"] - scored[1]["score"]
                if margin < min_score_margin:
                    query_results.append({
                        "idx": qd["idx"],
                        "hits": [],
                        "prompt_tags": prompt_tags,
                        "filtered": True,
                    })
                    continue

            query_results.append({
                "idx": qd["idx"],
                "hits": scored[:5],
                "prompt_tags": prompt_tags,
                "filtered": False,
            })

        metrics = compute_metrics(query_results, gt_by_idx)
        all_results.append({"config": params, "metrics": metrics})

        if metrics["composite"] < best_composite:
            best_composite = metrics["composite"]
            best_config = params
            print(f"  [{ci+1}/{len(combos)}] NEW BEST composite={metrics['composite']:.4f} "
                  f"p@1={metrics['precision_at_1']:.2f} p@3={metrics['precision_at_3']:.2f} "
                  f"abstain={metrics['abstain_accuracy']:.2f} useful={metrics['useful_accuracy']:.2f} "
                  f"sep={metrics['class_separation']:.3f}"
                  f" | {json.dumps(params)}", flush=True)
        elif (ci + 1) % 200 == 0:
            print(f"  [{ci+1}/{len(combos)}] best so far: {best_composite:.4f}", flush=True)

    all_results.sort(key=lambda x: x["metrics"]["composite"])
    return best_config, all_results


def compute_metrics(results, gt_by_idx):
    """Compute quality metrics from benchmark results against ground truth.

    Label buckets:
        - 'relevant': exact engram IDs expected, measures P@1 and P@3
        - 'useful': topically relevant results expected but no exact ID,
          counts as positive if top-1 score > useful_score_threshold
        - 'abstain': should return nothing or score below threshold
    """
    USEFUL_SCORE_THRESHOLD = 0.40  # useful queries should score at least this

    precision_hits_1 = 0
    precision_hits_3 = 0
    precision_total = 0
    useful_correct = 0
    useful_total = 0
    abstain_correct = 0
    abstain_total = 0
    top1_scores = []
    relevant_scores = []
    useful_scores = []
    abstain_scores = []

    for r in results:
        gt = gt_by_idx.get(r["idx"])
        if not gt:
            continue

        top1_score = r["hits"][0]["score"] if r["hits"] else 0.0
        top1_id = r["hits"][0]["id"] if r["hits"] else None
        top3_ids = [h["id"] for h in r["hits"][:3]]
        was_filtered = r.get("filtered", False)

        if gt["expect"] == "relevant" and gt["expected_ids"]:
            precision_total += 1
            if not was_filtered:
                if top1_id in gt["expected_ids"]:
                    precision_hits_1 += 1
                if any(eid in top3_ids for eid in gt["expected_ids"]):
                    precision_hits_3 += 1
            relevant_scores.append(top1_score)

        elif gt["expect"] == "useful":
            useful_total += 1
            useful_scores.append(top1_score)
            if not was_filtered and top1_score >= USEFUL_SCORE_THRESHOLD:
                useful_correct += 1

        elif gt["expect"] == "abstain":
            abstain_total += 1
            abstain_scores.append(top1_score)
            if was_filtered or top1_score < ABSTAIN_SCORE_THRESHOLD:
                abstain_correct += 1

        top1_scores.append(top1_score)

    score_std = statistics.stdev(top1_scores) if len(top1_scores) > 1 else 0
    avg_relevant = statistics.mean(relevant_scores) if relevant_scores else 0
    avg_useful = statistics.mean(useful_scores) if useful_scores else 0
    avg_abstain = statistics.mean(abstain_scores) if abstain_scores else 0
    class_separation = avg_relevant - avg_abstain

    p1 = precision_hits_1 / max(precision_total, 1)
    p3 = precision_hits_3 / max(precision_total, 1)
    useful_acc = useful_correct / max(useful_total, 1)
    abstain_acc = abstain_correct / max(abstain_total, 1)

    # Composite score (lower is better)
    # P@1 35%, P@3 20%, abstain 25%, class sep 10%, useful 10%
    composite = 1.0 - (
        0.35 * p1
        + 0.20 * p3
        + 0.25 * abstain_acc
        + 0.10 * min(class_separation, 1.0)
        + 0.10 * useful_acc
    )

    return {
        "precision_at_1": round(p1, 4),
        "precision_at_3": round(p3, 4),
        "useful_accuracy": round(useful_acc, 4),
        "abstain_accuracy": round(abstain_acc, 4),
        "score_std": round(score_std, 4),
        "class_separation": round(class_separation, 4),
        "avg_relevant_score": round(avg_relevant, 4),
        "avg_useful_score": round(avg_useful, 4),
        "avg_abstain_score": round(avg_abstain, 4),
        "composite": round(composite, 4),
        "labeled_queries": precision_total + abstain_total + useful_total,
    }


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_single_eval(scoring_overrides=None):
    """Run a single evaluation and print results."""
    from engrammar.search.engine import search
    from engrammar.search.query_filter import is_low_information
    import engrammar.core.config as cfg_mod

    queries = load_queries()
    gt = load_ground_truth()
    gt_by_idx = {g["idx"]: g for g in gt}

    cfg_mod._config_cache = None
    config = cfg_mod.load_config()
    if scoring_overrides:
        config["scoring"].update(scoring_overrides)

    results = []
    total_time = 0

    for i, q in enumerate(queries):
        t0 = time.time()
        try:
            hits, meta = search(q["prompt"], return_diagnostics=True, skip_prerequisites=True, top_k=5)
        except Exception as e:
            hits, meta = [], {"error": str(e)}
        elapsed = (time.time() - t0) * 1000
        total_time += elapsed

        was_filtered = meta.get("abstained", False) or meta.get("skip_reason", "")
        results.append({
            "idx": i,
            "query": q["prompt"][:100],
            "hits": [{"id": h["id"], "score": h["score"], "text": h["text"][:80], "diag": h.get("_diag", {})}
                     for h in hits[:5]],
            "prompt_tags": meta.get("prompt_tags", []),
            "filtered": bool(was_filtered),
            "time_ms": round(elapsed, 1),
        })

    metrics = compute_metrics(results, gt_by_idx)
    metrics["avg_latency_ms"] = round(total_time / max(len(results), 1), 1)
    metrics["total_queries"] = len(results)

    print("=== Search Benchmark Results ===")
    print(f"Queries: {metrics['total_queries']} ({metrics['labeled_queries']} labeled)")
    print(f"Avg latency: {metrics['avg_latency_ms']}ms")
    print(f"\nPrecision@1:      {metrics['precision_at_1']:.2%}")
    print(f"Precision@3:      {metrics['precision_at_3']:.2%}")
    print(f"Useful accuracy:  {metrics['useful_accuracy']:.2%}")
    print(f"Abstain accuracy: {metrics['abstain_accuracy']:.2%}")
    print(f"Score std dev:    {metrics['score_std']:.4f}")
    print(f"Class separation: {metrics['class_separation']:.4f} "
          f"(relevant={metrics['avg_relevant_score']:.3f} vs abstain={metrics['avg_abstain_score']:.3f})")
    print(f"Composite:        {metrics['composite']:.4f} (lower is better)")

    if scoring_overrides:
        print(f"\nConfig overrides: {json.dumps(scoring_overrides)}")

    print("\n--- Labeled Query Details ---")
    for r in results:
        g = gt_by_idx.get(r["idx"])
        if not g:
            continue
        top1 = r["hits"][0] if r["hits"] else None
        top1_score = top1["score"] if top1 else 0
        top1_id = top1["id"] if top1 else None

        was_filtered = r.get("filtered", False)
        if g["expect"] == "relevant" and g["expected_ids"]:
            if was_filtered:
                hit_mark = "BLOCKED"
            elif top1_id in g["expected_ids"]:
                hit_mark = "OK"
            elif any(h["id"] in g["expected_ids"] for h in r["hits"][:3]):
                hit_mark = "ok@3"
            else:
                hit_mark = "MISS"
        elif g["expect"] == "useful":
            if was_filtered:
                hit_mark = "BLOCKED"
            elif top1_score >= 0.40:
                hit_mark = "OK"
            else:
                hit_mark = f"LOW({top1_score:.2f})"
        elif g["expect"] == "abstain":
            if was_filtered:
                hit_mark = "SKIP"
            elif top1_score < 0.30:
                hit_mark = "OK"
            else:
                hit_mark = f"NOISE({top1_score:.2f})"
        else:
            hit_mark = ""

        tags = [t for t, _ in r.get("prompt_tags", [])]
        print(f"  Q{r['idx']:02d} [{hit_mark:8s}] score={top1_score:.4f} tags={tags[:3]} | {g['query'][:50]}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outpath = os.path.join(RESULTS_DIR, f"eval-{timestamp}.json")
    with open(outpath, "w") as f:
        json.dump({"config": scoring_overrides or {}, "metrics": metrics, "results": results}, f, indent=2)
    print(f"\nSaved to {outpath}")


def cmd_sweep():
    """Grid sweep with pre-computed embeddings."""
    queries = load_queries()
    gt = load_ground_truth()

    precomputed = PrecomputedData(queries)

    param_grid = {
        # Tag affinity (best from previous sweep, narrow range)
        "weight_content_tag": [0.15, 0.20, 0.25],
        "tag_sim_floor": [0.50, 0.55, 0.60],
        "tag_sim_ceiling": [0.80, 0.85],
        "prompt_tag_threshold": [0.55, 0.60],
        # Abstention features (new — main focus of this sweep)
        "min_vector_sim": [0.0, 0.55, 0.60, 0.65, 0.70],
        "min_top1_score": [0.0, 0.30, 0.40],
        "min_score_margin": [0.0, 0.05, 0.10],
    }

    t0 = time.time()
    best_config, all_results = run_sweep_fast(precomputed, gt, param_grid)
    elapsed = time.time() - t0

    best_metrics = all_results[0]["metrics"]
    print(f"\nSweep completed in {elapsed:.1f}s")
    print(f"\nBest config (composite={best_metrics['composite']:.4f}):")
    print(json.dumps(best_config, indent=2))
    print(f"\nBest metrics:")
    for k, v in best_metrics.items():
        print(f"  {k}: {v}")

    print(f"\nTop 10 configs:")
    for i, r in enumerate(all_results[:10]):
        m = r["metrics"]
        print(f"  {i+1}. composite={m['composite']:.4f} p@1={m['precision_at_1']:.2f} "
              f"p@3={m['precision_at_3']:.2f} abstain={m['abstain_accuracy']:.2f} "
              f"sep={m['class_separation']:.3f}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outpath = os.path.join(RESULTS_DIR, f"sweep-{timestamp}.json")
    with open(outpath, "w") as f:
        json.dump({
            "timestamp": timestamp,
            "elapsed_seconds": round(elapsed, 1),
            "total_configs": len(all_results),
            "best_config": best_config,
            "best_metrics": best_metrics,
            "top_20": all_results[:20],
        }, f, indent=2)
    print(f"\nSaved to {outpath}")


def cmd_report():
    """Show best config from previous sweep results."""
    if not os.path.exists(RESULTS_DIR):
        print("No autoresearch results found. Run --sweep first.")
        return

    sweep_files = sorted(f for f in os.listdir(RESULTS_DIR) if f.startswith("sweep-"))
    if not sweep_files:
        print("No sweep results found.")
        return

    latest = os.path.join(RESULTS_DIR, sweep_files[-1])
    with open(latest) as f:
        data = json.load(f)

    print(f"=== Sweep Report ({data['timestamp']}) ===")
    print(f"Configs tested: {data['total_configs']} in {data.get('elapsed_seconds', '?')}s")
    print(f"\nBest config (composite={data['best_metrics']['composite']:.4f}):")
    print(json.dumps(data["best_config"], indent=2))
    print(f"\nMetrics:")
    for k, v in data["best_metrics"].items():
        print(f"  {k}: {v}")

    print(f"\nTop 10 configs:")
    for i, r in enumerate(data.get("top_20", [])[:10]):
        m = r["metrics"]
        print(f"  {i+1}. composite={m['composite']:.4f} p@1={m['precision_at_1']:.2f} "
              f"p@3={m['precision_at_3']:.2f} abstain={m['abstain_accuracy']:.2f} "
              f"| {json.dumps(r['config'])}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search autoresearch loop")
    parser.add_argument("--sweep", action="store_true", help="Grid sweep over parameters")
    parser.add_argument("--report", action="store_true", help="Show best config from results")
    parser.add_argument("--override", type=str, help="JSON scoring overrides for single eval")
    args = parser.parse_args()

    if args.sweep:
        cmd_sweep()
    elif args.report:
        cmd_report()
    else:
        overrides = json.loads(args.override) if args.override else None
        cmd_single_eval(overrides)
