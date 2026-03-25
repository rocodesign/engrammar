#!/usr/bin/env python3
"""Analyze all benchmark extraction runs against labeled_engrams.jsonl.

Matches each run's extracted engrams against the labeled ground truth using
fastembed cosine similarity, then reports per-run recall of good engrams
(value >= 3) and avoidance of bad engrams (value == 0).

Usage:
    python benchmark/analyze_runs.py
    python benchmark/analyze_runs.py --threshold 0.85
    python benchmark/analyze_runs.py --runs 20260323-123926 20260323-220540
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

EVAL_DIR = PROJECT_ROOT / "benchmark" / "transcripts" / "evaluation"
RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"


def load_labeled_engrams():
    """Load labeled engrams, split into good/bad/marginal by value."""
    engrams = []
    with open(EVAL_DIR / "labeled_engrams.jsonl") as f:
        for line in f:
            if line.strip():
                engrams.append(json.loads(line))

    good = [e for e in engrams if e.get("value", 0) >= 3]
    bad = [e for e in engrams if e.get("value", 0) == 0]
    marginal = [e for e in engrams if e.get("value", 0) in (1, 2)]
    return good, bad, marginal, engrams


def load_run(run_dir, prompt_filter=None):
    """Load extracted engrams from a run, grouped by transcript session prefix.

    If prompt_filter is set, only include results from that prompt variant.
    """
    run_dir = Path(run_dir)
    results = {}  # session_prefix -> list of engram texts
    meta = {}  # run metadata

    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            meta = json.load(f).get("config", {})

    for path in sorted(run_dir.glob("*.json")):
        if path.name == "summary.json":
            continue
        with open(path) as f:
            data = json.load(f)

        if prompt_filter and data.get("prompt", "") != prompt_filter:
            continue

        transcript = data.get("transcript_file", "")
        session_id = transcript.replace(".jsonl", "")
        # Truncate to first 12 chars to match labeled source format (e.g. '06e5ef74-b0b')
        session_prefix = session_id[:12] if len(session_id) > 12 else session_id
        engrams = data.get("engrams") or []
        texts = []
        for eng in engrams:
            if isinstance(eng, dict):
                text = eng.get("engram", eng.get("text", ""))
                if text:
                    texts.append(text)
        if texts:
            results.setdefault(session_prefix, []).extend(texts)

    return results, meta


def build_embeddings(texts, embed_fn):
    """Embed a list of texts, return dict of text -> normalized vector."""
    if not texts:
        return {}
    embs = embed_fn(texts)
    norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
    normalized = embs / norms
    return {text: np.asarray(vec, dtype=np.float32) for text, vec in zip(texts, normalized)}


def find_best_match(labeled_text, candidate_texts, vectors):
    """Find highest cosine similarity between labeled and candidates."""
    if not candidate_texts or labeled_text not in vectors:
        return 0.0, None

    source_vec = vectors[labeled_text]
    best_sim = 0.0
    best_text = None
    for ct in candidate_texts:
        if ct in vectors:
            sim = float(source_vec @ vectors[ct])
            if sim > best_sim:
                best_sim = sim
                best_text = ct
    return best_sim, best_text


def analyze_run(run_dir, good, bad, marginal, vectors, threshold=0.85, prompt_filter=None):
    """Analyze one run against labeled engrams."""
    results, meta = load_run(run_dir, prompt_filter=prompt_filter)
    run_name = Path(run_dir).name

    # Build label for this run from metadata
    prompts = meta.get("prompts", ["?"])
    models = meta.get("models", ["?"])
    ctx_sizes = meta.get("context_sizes", ["?"])
    label = f"{run_name} ({'/'.join(prompts)} | {'/'.join(models)} | ctx={ctx_sizes})"

    total_extracted = sum(len(v) for v in results.values())
    if total_extracted == 0:
        return None

    # Embed all extracted texts
    all_extracted = []
    for texts in results.values():
        all_extracted.extend(texts)

    # Add to vectors cache
    missing = [t for t in all_extracted if t not in vectors]
    if missing:
        from engrammar.core.embeddings import embed_batch
        new_vecs = build_embeddings(missing, embed_batch)
        vectors.update(new_vecs)

    # Evaluate good recall
    good_found = []
    good_missed = []
    good_skipped = 0
    for eng in good:
        source = eng["source"]
        if source.startswith("orig-"):
            good_skipped += 1
            continue
        candidates = results.get(source, [])
        if not candidates:
            good_skipped += 1
            continue
        sim, match = find_best_match(eng["text"], candidates, vectors)
        if sim >= threshold:
            good_found.append({"engram": eng, "sim": sim, "match": match})
        else:
            good_missed.append({"engram": eng, "sim": sim, "match": match})

    # Evaluate bad avoidance
    bad_extracted = []
    bad_avoided = []
    bad_skipped = 0
    for eng in bad:
        source = eng["source"]
        if source.startswith("orig-"):
            bad_skipped += 1
            continue
        candidates = results.get(source, [])
        if not candidates:
            bad_skipped += 1
            continue
        sim, match = find_best_match(eng["text"], candidates, vectors)
        if sim >= threshold:
            bad_extracted.append({"engram": eng, "sim": sim, "match": match})
        else:
            bad_avoided.append({"engram": eng, "sim": sim, "match": match})

    # Evaluate marginal
    marginal_extracted = []
    marginal_avoided = []
    for eng in marginal:
        source = eng["source"]
        if source.startswith("orig-"):
            continue
        candidates = results.get(source, [])
        if not candidates:
            continue
        sim, match = find_best_match(eng["text"], candidates, vectors)
        if sim >= threshold:
            marginal_extracted.append({"engram": eng, "sim": sim, "match": match})
        else:
            marginal_avoided.append({"engram": eng, "sim": sim, "match": match})

    good_testable = len(good_found) + len(good_missed)
    bad_testable = len(bad_extracted) + len(bad_avoided)

    return {
        "label": label,
        "run_name": run_name,
        "meta": meta,
        "total_extracted": total_extracted,
        "transcripts": len(results),
        "good_found": good_found,
        "good_missed": good_missed,
        "good_skipped": good_skipped,
        "good_recall": len(good_found) / good_testable * 100 if good_testable else 0,
        "bad_extracted": bad_extracted,
        "bad_avoided": bad_avoided,
        "bad_skipped": bad_skipped,
        "bad_avoidance": len(bad_avoided) / bad_testable * 100 if bad_testable else 0,
        "marginal_extracted": marginal_extracted,
        "marginal_avoided": marginal_avoided,
    }


def format_report(analysis, verbose=False):
    """Format analysis results as markdown."""
    lines = []
    a = analysis
    lines.append(f"### {a['label']}")
    lines.append(f"")
    lines.append(f"- **Extracted**: {a['total_extracted']} engrams from {a['transcripts']} transcripts")
    lines.append(f"- **Avg per transcript**: {a['total_extracted'] / max(a['transcripts'], 1):.1f}")

    good_testable = len(a["good_found"]) + len(a["good_missed"])
    bad_testable = len(a["bad_extracted"]) + len(a["bad_avoided"])

    lines.append(f"- **Good recall**: {len(a['good_found'])}/{good_testable} = **{a['good_recall']:.0f}%**")
    lines.append(f"- **Bad avoidance**: {len(a['bad_avoided'])}/{bad_testable} = **{a['bad_avoidance']:.0f}%**")
    marginal_total = len(a["marginal_extracted"]) + len(a["marginal_avoided"])
    if marginal_total:
        lines.append(f"- **Marginal extracted**: {len(a['marginal_extracted'])}/{marginal_total}")
    lines.append("")

    if verbose:
        if a["good_missed"]:
            lines.append("**Missed good engrams:**")
            for item in sorted(a["good_missed"], key=lambda x: x["sim"], reverse=True):
                eng = item["engram"]
                lines.append(f"- [v={eng['value']}, sim={item['sim']:.2f}] {eng['text'][:120]}")
                if item["match"]:
                    lines.append(f"  - closest: {item['match'][:120]}")
            lines.append("")

        if a["bad_extracted"]:
            lines.append("**Incorrectly extracted bad engrams:**")
            for item in sorted(a["bad_extracted"], key=lambda x: x["sim"], reverse=True):
                eng = item["engram"]
                lines.append(f"- [v={eng['value']}, sim={item['sim']:.2f}] {eng['text'][:120]}")
                if item["match"]:
                    lines.append(f"  - extracted as: {item['match'][:120]}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark runs")
    parser.add_argument("--runs", nargs="*", help="Specific run IDs to analyze")
    parser.add_argument("--threshold", type=float, default=0.85,
                        help="Cosine similarity threshold for match (default: 0.85)")
    parser.add_argument("--verbose", action="store_true", help="Show per-engram details")
    parser.add_argument("--split-prompts", action="store_true",
                        help="Analyze each prompt variant separately in multi-prompt runs")
    args = parser.parse_args()

    from engrammar.core.embeddings import embed_batch

    good, bad, marginal, all_engrams = load_labeled_engrams()
    print(f"Labeled: {len(good)} good (v>=3), {len(bad)} bad (v=0), {len(marginal)} marginal (v=1-2)")
    print(f"Threshold: {args.threshold}")
    print()

    # Pre-embed all labeled texts
    labeled_texts = [e["text"] for e in all_engrams]
    vectors = build_embeddings(labeled_texts, embed_batch)
    print(f"Embedded {len(vectors)} labeled engram texts")

    # Find runs to analyze
    if args.runs:
        run_dirs = [RESULTS_DIR / r for r in args.runs]
    else:
        # Auto-detect substantial runs (>5 result files)
        run_dirs = []
        for d in sorted(RESULTS_DIR.iterdir()):
            if not d.is_dir() or d.name.startswith(("dedup-", "eval-", "autoresearch")):
                continue
            json_count = len([f for f in d.glob("*.json") if f.name != "summary.json"])
            if json_count >= 5:
                run_dirs.append(d)

    analyses = []
    for rd in run_dirs:
        if args.split_prompts:
            # Detect prompts in this run
            prompts_in_run = set()
            for path in rd.glob("*.json"):
                if path.name == "summary.json":
                    continue
                with open(path) as f:
                    d = json.load(f)
                p = d.get("prompt", "")
                if p:
                    prompts_in_run.add(p)
            if len(prompts_in_run) > 1:
                for prompt_name in sorted(prompts_in_run):
                    print(f"Analyzing {rd.name}/{prompt_name}...", end=" ", flush=True)
                    result = analyze_run(rd, good, bad, marginal, vectors,
                                         threshold=args.threshold, prompt_filter=prompt_name)
                    if result:
                        result["label"] = f"{rd.name}/{prompt_name}"
                        result["run_name"] = f"{rd.name}/{prompt_name}"
                        analyses.append(result)
                        print(f"recall={result['good_recall']:.0f}% avoid={result['bad_avoidance']:.0f}%")
                    else:
                        print("(empty)")
                continue

        print(f"Analyzing {rd.name}...", end=" ", flush=True)
        result = analyze_run(rd, good, bad, marginal, vectors, threshold=args.threshold)
        if result:
            analyses.append(result)
            print(f"recall={result['good_recall']:.0f}% avoid={result['bad_avoidance']:.0f}%")
        else:
            print("(empty)")

    # Print comparison table
    print("\n" + "=" * 100)
    print("COMPARISON TABLE")
    print("=" * 100)
    print(f"{'Run':<24} {'Prompt':<22} {'Model':<8} {'Ctx':<12} {'#Ext':>5} {'GoodR':>7} {'BadAv':>7} {'Marg':>5}")
    print("-" * 100)
    for a in analyses:
        m = a["meta"]
        prompt = "/".join(m.get("prompts", ["?"]))[:20]
        model = "/".join(m.get("models", ["?"]))[:7]
        ctx = str(m.get("context_sizes", ["?"]))[:10]
        good_t = len(a["good_found"]) + len(a["good_missed"])
        bad_t = len(a["bad_extracted"]) + len(a["bad_avoided"])
        marg_t = len(a["marginal_extracted"]) + len(a["marginal_avoided"])
        print(f"{a['run_name']:<24} {prompt:<22} {model:<8} {ctx:<12} "
              f"{a['total_extracted']:>5} "
              f"{len(a['good_found'])}/{good_t:>3}  "
              f"{len(a['bad_avoided'])}/{bad_t:>3}  "
              f"{len(a['marginal_avoided'])}/{marg_t:>3}")

    # Print detailed reports
    print()
    for a in analyses:
        print(format_report(a, verbose=args.verbose))

    return analyses


if __name__ == "__main__":
    main()
