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

# ---------------------------------------------------------------------------
# Control presets: named scoring configs for subsystem ablation
# Each zeroes out a specific subsystem to measure its contribution.
# ---------------------------------------------------------------------------

CONTROL_PRESETS = {
    # Semantic search only — no tags, no repo prior, no feedback, no gating
    "semantic_only": {
        "weight_content_tag": 0.0,
        "weight_feedback": 0.0,
        "repo_match_boost": 0.0,
        "repo_mismatch_penalty": 0.0,
        "abstain_threshold": 0.0,
        "min_top1_score": 0.0,
    },
    # Semantic + content tag affinity — no repo/feedback/gating
    "semantic_plus_tags": {
        "weight_content_tag": 0.25,
        "weight_feedback": 0.0,
        "repo_match_boost": 0.0,
        "repo_mismatch_penalty": 0.0,
        "abstain_threshold": 0.0,
        "min_top1_score": 0.0,
    },
    # Semantic + tags + repo prior — no feedback/gating
    "semantic_plus_tags_repo": {
        "weight_content_tag": 0.25,
        "weight_feedback": 0.0,
        "repo_match_boost": 0.05,
        "repo_mismatch_penalty": -0.08,
        "abstain_threshold": 0.0,
        "min_top1_score": 0.0,
    },
    # Semantic + tags + filters (gating) — no repo/feedback
    "semantic_plus_filters": {
        "weight_content_tag": 0.25,
        "weight_feedback": 0.0,
        "repo_match_boost": 0.0,
        "repo_mismatch_penalty": 0.0,
        "abstain_threshold": 0.55,
        "min_top1_score": 0.40,
    },
    # Current production config (hook mode — higher min_score, abstention on)
    "hook_current": {
        "weight_content_tag": 0.25,
        "weight_feedback": 0.20,
        "repo_match_boost": 0.05,
        "repo_mismatch_penalty": -0.08,
        "abstain_threshold": 0.55,
        "min_top1_score": 0.40,
    },
    # Interactive search mode — no abstention, lower thresholds
    "interactive_current": {
        "weight_content_tag": 0.25,
        "weight_feedback": 0.20,
        "repo_match_boost": 0.05,
        "repo_mismatch_penalty": -0.08,
        "abstain_threshold": 0.0,
        "min_top1_score": 0.0,
    },
}

# Enrichment presets for --enrich flag
ENRICHMENT_PRESETS = {
    "none": {
        "prompt": {"strip_ide_tags": False, "inject_ide_file": False, "inject_ide_selection": False, "max_query_length": 0},
        "post_tool": {"inject_narration": False, "inject_tool_context": False},
    },
    "strip": {
        "prompt": {"strip_ide_tags": True, "inject_ide_file": False, "inject_ide_selection": False, "max_query_length": 300},
        "post_tool": {"inject_narration": True, "inject_tool_context": False},
    },
    "file": {
        "prompt": {"strip_ide_tags": True, "inject_ide_file": True, "inject_ide_selection": False, "max_query_length": 300},
        "post_tool": {"inject_narration": True, "inject_tool_context": True},
    },
    "full": {
        "prompt": {"strip_ide_tags": True, "inject_ide_file": True, "inject_ide_selection": True, "max_query_length": 400},
        "post_tool": {"inject_narration": True, "inject_tool_context": True, "narration_max_length": 250},
    },
}


def load_ground_truth():
    with open(GROUND_TRUTH_PATH) as f:
        return json.load(f)["labels"]


def load_queries():
    with open(QUERIES_PATH) as f:
        return json.load(f)


def build_query_gt_map(queries, ground_truth):
    """Map query list indices to ground truth idx values.

    Queries are 0-indexed in the list; ground truth labels use their own
    sparse idx (1, 3, 4, 5, ...). Match by comparing prompt text prefixes.
    """
    mapping = {}
    for i, q in enumerate(queries):
        prompt_prefix = q["prompt"][:60]
        for g in ground_truth:
            if g["query"][:60] in prompt_prefix or prompt_prefix[:40] in g["query"]:
                mapping[i] = g["idx"]
                break
    return mapping


# ---------------------------------------------------------------------------
# Pre-computation: run once, reuse across all configs
# ---------------------------------------------------------------------------

class PrecomputedData:
    """All embeddings and base scores pre-computed for fast sweep."""

    def __init__(self, queries, ground_truth=None):
        from engrammar.core.embeddings import embed_text, embed_batch, load_tag_vocab_index
        from engrammar.core.db import get_all_active_engrams, get_content_tags_batch
        from engrammar.search.prompt_tags import _load_tag_frequencies
        from engrammar.search.engine import search
        from engrammar.search.query_filter import is_low_information

        q_gt_map = build_query_gt_map(queries, ground_truth) if ground_truth else {}

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
        # and query embeddings for prompt tag detection.
        # Uses cwd from turn_data for proper repo prior and prerequisite filtering.
        self.query_data = []
        for i, q in enumerate(queries):
            qtext = q["prompt"]
            cwd = (q.get("turn_data") or {}).get("cwd")

            # Check query filter
            filtered, filter_reason = is_low_information(qtext)

            # Embed query for prompt tag detection
            q_emb = embed_text(qtext)
            q_norm = q_emb / (np.linalg.norm(q_emb) + 1e-10)

            # Run base search (disable tag affinity AND feedback to get naked base scores)
            import engrammar.core.config as cfg_mod
            cfg_mod._config_cache = None
            config = cfg_mod.load_config()
            config["scoring"]["weight_content_tag"] = 0.0  # disable tag affinity
            config["scoring"]["weight_feedback"] = 0.0     # disable feedback (swept separately)
            hits, meta = search(qtext, return_diagnostics=True, cwd=cwd, top_k=10)

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
                "idx": q_gt_map.get(i, i),
                "query": qtext[:100],
                "query_emb_norm": q_norm,
                "base_results": base_results,
                "filtered": filtered,
                "filter_reason": filter_reason,
                "best_vector_sim": best_vector_sim,
                "score_gap": score_gap,
            })

        # Pre-load per-engram tag relevance data for feedback sweep
        from engrammar.core.db import get_tag_relevance_with_evidence
        self.feedback_cache = {}  # (engram_id, tuple(tags)) -> (avg_score, total_evals)
        all_candidate_ids = set()
        for qd_item in self.query_data:
            for br in qd_item["base_results"]:
                all_candidate_ids.add(br["id"])
        for eid in all_candidate_ids:
            etags = self.content_tags_map.get(eid, [])
            if etags:
                avg_score, total_evals = get_tag_relevance_with_evidence(eid, etags)
                self.feedback_cache[eid] = (avg_score, total_evals)

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
        """Fast tag affinity using pre-computed embeddings with squared curve."""
        if not prompt_tag_indices or not engram_tag_indices:
            if prompt_tag_indices and not engram_tag_indices:
                return tag_mismatch_penalty * 0.5
            return 0.0

        # Compute similarity matrix: each engram tag's best sim against prompt tags
        pt_embs = self.tag_embeddings[prompt_tag_indices]  # (n_pt, dim)
        et_embs = self.tag_embeddings[engram_tag_indices]  # (n_et, dim)
        sim_matrix = pt_embs @ et_embs.T  # (n_pt, n_et)

        # Per engram-tag: best similarity across all prompt tags
        per_tag_best = sim_matrix.max(axis=0)  # (n_et,)
        best_sim = float(per_tag_best.max())

        # Squared curve per tag, normalized by tag count
        floor_denom = 1.0 - tag_sim_floor
        if floor_denom <= 0:
            floor_denom = 1.0
        norms = np.clip((per_tag_best - tag_sim_floor) / floor_denom, 0.0, None)
        tag_bonus = float((norms ** 2).sum())

        delta = w_content * tag_bonus

        # Mismatch penalty
        if best_sim < tag_mismatch_threshold:
            delta += tag_mismatch_penalty

        return delta


def run_sweep_fast(precomputed, ground_truth, param_grid):
    """Fast sweep: recompute tag affinity + feedback + abstention per config."""
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

        # Feedback params
        w_feedback = params.get("weight_feedback", 0.0)

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

            # Rescore each result: tag affinity + feedback
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
                # Feedback prior (no /3.0 — raw avg_score * weight)
                if w_feedback > 0:
                    fb = precomputed.feedback_cache.get(br["id"])
                    if fb:
                        avg_score, total_evals = fb
                        score += avg_score * w_feedback
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

    # Composite score (lower is better) — balanced objective
    # P@1 35%, P@3 20%, abstain 25%, class sep 10%, useful 10%
    composite = 1.0 - (
        0.35 * p1
        + 0.20 * p3
        + 0.25 * abstain_acc
        + 0.10 * min(class_separation, 1.0)
        + 0.10 * useful_acc
    )

    # Hook objective — weights abstain heavily, tolerates dropping low-confidence useful
    composite_hook = 1.0 - (
        0.30 * p1
        + 0.15 * p3
        + 0.35 * abstain_acc
        + 0.10 * min(class_separation, 1.0)
        + 0.10 * useful_acc
    )

    # Interactive objective — weights useful/P@3, penalizes over-abstention
    composite_interactive = 1.0 - (
        0.25 * p1
        + 0.30 * p3
        + 0.10 * abstain_acc
        + 0.10 * min(class_separation, 1.0)
        + 0.25 * useful_acc
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
        "composite_hook": round(composite_hook, 4),
        "composite_interactive": round(composite_interactive, 4),
        "labeled_queries": precision_total + abstain_total + useful_total,
    }


def compute_bucket_metrics(results, gt_by_idx):
    """Break down metrics by query bucket (relevant/useful/abstain) and type (prompt/tool/post_tool)."""
    gt_list = list(gt_by_idx.values())
    results_by_idx = {r["idx"]: r for r in results}

    buckets = {}
    for gt in gt_list:
        idx = gt["idx"]
        r = results_by_idx.get(idx)
        if not r:
            continue

        bucket = gt["expect"]
        qtype = gt.get("type", "prompt")

        for key in [f"expect:{bucket}", f"type:{qtype}"]:
            buckets.setdefault(key, []).append(r)

    bucket_metrics = {}
    for key, bucket_results in buckets.items():
        bucket_metrics[key] = compute_metrics(bucket_results, gt_by_idx)

    return bucket_metrics


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_ablation():
    """Run control preset ablations and compare subsystem contributions."""
    from engrammar.search.engine import search
    import engrammar.core.config as cfg_mod

    queries = load_queries()
    gt = load_ground_truth()
    gt_by_idx = {g["idx"]: g for g in gt}
    q_gt_map = build_query_gt_map(queries, gt)

    all_results = {}

    for preset_name, overrides in CONTROL_PRESETS.items():
        cfg_mod._config_cache = None
        config = cfg_mod.load_config()
        config["scoring"].update(overrides)

        results = []
        total_time = 0

        for i, q in enumerate(queries):
            t0 = time.time()
            try:
                cwd = (q.get("turn_data") or {}).get("cwd")
                hits, meta = search(q["prompt"], return_diagnostics=True, cwd=cwd, top_k=5)
            except Exception as e:
                hits, meta = [], {"error": str(e)}
            elapsed = (time.time() - t0) * 1000
            total_time += elapsed

            was_filtered = meta.get("abstained", False) or meta.get("skip_reason", "")
            results.append({
                "idx": q_gt_map.get(i, i),
                "hits": [{"id": h["id"], "score": h["score"], "text": h["text"][:80]}
                         for h in hits[:5]],
                "filtered": bool(was_filtered),
            })

        metrics = compute_metrics(results, gt_by_idx)
        metrics["avg_latency_ms"] = round(total_time / max(len(results), 1), 1)
        bucket = compute_bucket_metrics(results, gt_by_idx)
        all_results[preset_name] = {"metrics": metrics, "bucket_metrics": bucket}
        print(f"  {preset_name}: composite={metrics['composite']:.4f} "
              f"hook={metrics['composite_hook']:.4f} "
              f"interactive={metrics['composite_interactive']:.4f}", flush=True)

    # Print comparison table
    print("\n" + "=" * 110)
    print("  Control Preset Ablation")
    print("=" * 110)
    print(f"  {'Preset':<25s} {'P@1':>5s} {'P@3':>5s} {'Abst':>5s} {'Usef':>5s} "
          f"{'Sep':>6s} {'Composite':>9s} {'Hook':>9s} {'Interact':>9s} {'ms':>5s}")
    print("-" * 110)

    for name in CONTROL_PRESETS:
        m = all_results[name]["metrics"]
        print(f"  {name:<25s} {m['precision_at_1']:>4.0%} {m['precision_at_3']:>4.0%} "
              f"{m['abstain_accuracy']:>4.0%} {m['useful_accuracy']:>4.0%} "
              f"{m['class_separation']:>6.3f} {m['composite']:>9.4f} "
              f"{m['composite_hook']:>9.4f} {m['composite_interactive']:>9.4f} "
              f"{m['avg_latency_ms']:>4.0f}")

    # Subsystem deltas (incremental contribution)
    print("\n--- Subsystem Contribution (delta from semantic_only) ---")
    base = all_results["semantic_only"]["metrics"]
    for name in ["semantic_plus_tags", "semantic_plus_tags_repo", "semantic_plus_filters", "hook_current"]:
        m = all_results[name]["metrics"]
        delta_c = base["composite"] - m["composite"]  # positive = improvement
        delta_p1 = m["precision_at_1"] - base["precision_at_1"]
        delta_abs = m["abstain_accuracy"] - base["abstain_accuracy"]
        print(f"  + {name:<25s} composite: {delta_c:+.4f}  P@1: {delta_p1:+.2%}  abstain: {delta_abs:+.2%}")

    # Bucket breakdown for best config
    print("\n--- Bucket Metrics (hook_current) ---")
    for key, bm in sorted(all_results["hook_current"]["bucket_metrics"].items()):
        print(f"  {key:<20s} P@1={bm['precision_at_1']:.0%} P@3={bm['precision_at_3']:.0%} "
              f"abstain={bm['abstain_accuracy']:.0%} useful={bm['useful_accuracy']:.0%} "
              f"n={bm['labeled_queries']}")

    # Save
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outpath = os.path.join(RESULTS_DIR, f"ablation-{timestamp}.json")
    serializable = {k: v for k, v in all_results.items()}
    with open(outpath, "w") as f:
        json.dump({"timestamp": timestamp, "presets": serializable}, f, indent=2)
    print(f"\nSaved to {outpath}")

def cmd_single_eval(scoring_overrides=None):
    """Run a single evaluation and print results."""
    from engrammar.search.engine import search
    from engrammar.search.query_filter import is_low_information
    import engrammar.core.config as cfg_mod

    queries = load_queries()
    gt = load_ground_truth()
    gt_by_idx = {g["idx"]: g for g in gt}
    q_gt_map = build_query_gt_map(queries, gt)

    cfg_mod._config_cache = None
    config = cfg_mod.load_config()
    if scoring_overrides:
        config["scoring"].update(scoring_overrides)

    results = []
    total_time = 0

    for i, q in enumerate(queries):
        t0 = time.time()
        try:
            cwd = (q.get("turn_data") or {}).get("cwd")
            hits, meta = search(q["prompt"], return_diagnostics=True, cwd=cwd, top_k=5)
        except Exception as e:
            hits, meta = [], {"error": str(e)}
        elapsed = (time.time() - t0) * 1000
        total_time += elapsed

        was_filtered = meta.get("abstained", False) or meta.get("skip_reason", "")
        results.append({
            "idx": q_gt_map.get(i, i),
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

    precomputed = PrecomputedData(queries, ground_truth=gt)

    param_grid = {
        # Tag affinity — squared curve (floor matters, ceiling unused)
        "weight_content_tag": [0.15, 0.20, 0.25, 0.30],
        "tag_sim_floor": [0.45, 0.50, 0.55, 0.60],
        "tag_sim_ceiling": [0.85],  # unused by squared curve, kept for compat
        "prompt_tag_threshold": [0.55, 0.60],
        # Feedback — /3.0 removed, so weight_feedback needs re-tuning
        "weight_feedback": [0.03, 0.05, 0.07, 0.10, 0.15],
        # Abstention
        "min_vector_sim": [0.0, 0.55, 0.65],
        "min_top1_score": [0.0, 0.30, 0.40],
        "min_score_margin": [0.0],
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


def _build_enriched_query(q, strategy):
    """Build a search query from a benchmark entry using the given enrichment strategy.

    Strategies:
        raw         — pass prompt as-is (includes IDE tags, system tags)
        strip       — strip IDE/system tags only
        strip+file  — strip tags, prepend [file: path] if available
        strip+prior — strip tags, prepend prior_assistant for vague queries
        full        — strip tags, inject file + prior_assistant
        post_tool:narration+tool — narration + tool context (post_tool default)
        post_tool:narration      — narration only
        post_tool:tool           — tool context only
    """
    import re

    prompt = q["prompt"]
    td = q.get("turn_data", {}) or {}
    qtype = q.get("type", "prompt")

    def strip_tags(text):
        text = re.sub(r'<ide_opened_file>.*?</ide_opened_file>\s*', '', text, flags=re.DOTALL)
        text = re.sub(r'<ide_selection>.*?</ide_selection>\s*', '', text, flags=re.DOTALL)
        text = re.sub(r'<task-notification>.*?</task-notification>\s*', '', text, flags=re.DOTALL)
        text = re.sub(r'<system-reminder>.*?</system-reminder>\s*', '', text, flags=re.DOTALL)
        return text.strip()

    if strategy == "raw":
        return prompt[:400]

    if qtype == "post_tool":
        narration = td.get("narration", "")
        tool_input = td.get("tool_input", {})
        tool_name = td.get("tool_name", "")

        tool_ctx = ""
        if tool_name == "Read":
            path = tool_input.get("file_path", "")
            if path:
                segments = path.split("/")
                tool_ctx = "/".join(segments[-3:]) if len(segments) > 3 else path
        elif tool_name in ("Grep", "Glob"):
            tool_ctx = tool_input.get("pattern", "")

        if strategy == "post_tool:narration+tool":
            parts = [p for p in [narration[:200], tool_ctx] if p]
            return " ".join(parts) if parts else prompt
        elif strategy == "post_tool:narration":
            return narration[:200] if narration else prompt
        elif strategy == "post_tool:tool":
            return tool_ctx if tool_ctx else prompt

    # For prompt/tool types
    clean = strip_tags(prompt) if strategy != "raw" else prompt

    if strategy == "strip":
        return clean[:300]

    if strategy in ("strip+file", "full"):
        ide_file = td.get("ide_file", "")
        if ide_file:
            clean = f"[file: {ide_file}] {clean}"

    if strategy in ("strip+prior", "full"):
        prior = td.get("prior_assistant", "")
        if prior and len(clean.split()) < 8:
            # Only inject prior for short/vague queries
            clean = f"{prior[:150]} {clean}"

    return clean[:400]


def cmd_enrich_compare(scoring_overrides=None):
    """Compare enrichment strategies across all queries."""
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

    # Strategies to compare
    strategies = ["raw", "strip", "strip+file", "strip+prior", "full"]
    post_tool_strategies = ["post_tool:narration+tool", "post_tool:narration", "post_tool:tool"]

    all_strategy_results = {}

    q_gt_map = build_query_gt_map(queries, gt)

    for strategy in strategies + post_tool_strategies:
        results = []
        total_time = 0

        for i, q in enumerate(queries):
            qtype = q.get("type", "prompt")

            # Skip post_tool strategies for non-post_tool queries and vice versa
            if strategy.startswith("post_tool:") and qtype != "post_tool":
                continue
            if not strategy.startswith("post_tool:") and qtype == "post_tool":
                continue

            enriched = _build_enriched_query(q, strategy)

            t0 = time.time()
            try:
                cwd = (q.get("turn_data") or {}).get("cwd")
                hits, meta = search(enriched, return_diagnostics=True, cwd=cwd, top_k=5)
            except Exception as e:
                hits, meta = [], {"error": str(e)}
            elapsed = (time.time() - t0) * 1000
            total_time += elapsed

            was_filtered = meta.get("abstained", False) or meta.get("skip_reason", "")
            gt_idx = q_gt_map.get(i, i)
            results.append({
                "idx": gt_idx,
                "query": enriched[:100],
                "original": q["prompt"][:80],
                "hits": [{"id": h["id"], "score": h["score"], "text": h["text"][:80]}
                         for h in hits[:5]],
                "filtered": bool(was_filtered),
                "time_ms": round(elapsed, 1),
            })

        if not results:
            continue

        metrics = compute_metrics(results, gt_by_idx)
        metrics["avg_latency_ms"] = round(total_time / max(len(results), 1), 1)
        metrics["total_queries"] = len(results)
        all_strategy_results[strategy] = {"metrics": metrics, "results": results}

    # Print comparison table
    print("\n" + "=" * 90)
    print("  Enrichment Strategy Comparison")
    print("=" * 90)
    print(f"  {'Strategy':<25s} {'P@1':>6s} {'P@3':>6s} {'Abstain':>8s} {'Useful':>7s} "
          f"{'Sep':>6s} {'Composite':>10s} {'Queries':>8s} {'Latency':>8s}")
    print("-" * 90)

    for strategy in strategies + post_tool_strategies:
        if strategy not in all_strategy_results:
            continue
        m = all_strategy_results[strategy]["metrics"]
        print(f"  {strategy:<25s} {m['precision_at_1']:>5.0%} {m['precision_at_3']:>5.0%} "
              f"{m['abstain_accuracy']:>7.0%} {m['useful_accuracy']:>6.0%} "
              f"{m['class_separation']:>6.3f} {m['composite']:>9.4f} "
              f"{m['total_queries']:>7d} {m['avg_latency_ms']:>6.0f}ms")

    print("-" * 90)

    # Find best prompt strategy
    prompt_strategies = {k: v for k, v in all_strategy_results.items() if not k.startswith("post_tool:")}
    if prompt_strategies:
        best = min(prompt_strategies.items(), key=lambda x: x[1]["metrics"]["composite"])
        print(f"\n  Best prompt strategy: {best[0]} (composite={best[1]['metrics']['composite']:.4f})")

    # Per-query diff: show where strategies diverge
    print("\n--- Per-query divergence (strip vs strip+prior) ---")
    for strategy_a, strategy_b in [("strip", "strip+prior"), ("strip", "strip+file")]:
        if strategy_a not in all_strategy_results or strategy_b not in all_strategy_results:
            continue
        ra = {r["idx"]: r for r in all_strategy_results[strategy_a]["results"]}
        rb = {r["idx"]: r for r in all_strategy_results[strategy_b]["results"]}
        diffs = 0
        for idx in ra:
            if idx not in rb:
                continue
            a_top = ra[idx]["hits"][0]["id"] if ra[idx]["hits"] else None
            b_top = rb[idx]["hits"][0]["id"] if rb[idx]["hits"] else None
            a_score = ra[idx]["hits"][0]["score"] if ra[idx]["hits"] else 0
            b_score = rb[idx]["hits"][0]["score"] if rb[idx]["hits"] else 0
            if a_top != b_top or abs(a_score - b_score) > 0.05:
                g = gt_by_idx.get(idx)
                label = g["query"][:40] if g else ra[idx]["original"][:40]
                expected = g["expected_ids"][:2] if g else []
                print(f"  Q{idx:02d} {strategy_a}: #{a_top}({a_score:.3f}) vs "
                      f"{strategy_b}: #{b_top}({b_score:.3f}) expected={expected} | {label}")
                diffs += 1
        if diffs == 0:
            print(f"  (no divergence between {strategy_a} and {strategy_b})")

    # Save results
    os.makedirs(RESULTS_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    outpath = os.path.join(RESULTS_DIR, f"enrich-{timestamp}.json")
    serializable = {k: {"metrics": v["metrics"]} for k, v in all_strategy_results.items()}
    with open(outpath, "w") as f:
        json.dump({"timestamp": timestamp, "strategies": serializable}, f, indent=2)
    print(f"\nSaved to {outpath}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search autoresearch loop")
    parser.add_argument("--sweep", action="store_true", help="Grid sweep over parameters")
    parser.add_argument("--enrich", action="store_true", help="Compare enrichment strategies")
    parser.add_argument("--ablation", action="store_true", help="Run control preset ablations")
    parser.add_argument("--report", action="store_true", help="Show best config from results")
    parser.add_argument("--override", type=str, help="JSON scoring overrides for single eval")
    args = parser.parse_args()

    if args.sweep:
        cmd_sweep()
    elif args.enrich:
        overrides = json.loads(args.override) if args.override else None
        cmd_enrich_compare(overrides)
    elif args.ablation:
        cmd_ablation()
    elif args.report:
        cmd_report()
    else:
        overrides = json.loads(args.override) if args.override else None
        cmd_single_eval(overrides)
