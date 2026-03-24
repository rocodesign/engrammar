#!/usr/bin/env python3
"""Evaluate extraction quality against labeled good/bad engram ground truth.

Compares extracted engrams from a benchmark run against labeled examples
to measure whether the prompt avoids bad engrams and preserves good ones.

Uses the repo's FastEmbed backend by default so the benchmark matches the
embedding stack used elsewhere in Engrammar. A word-overlap matcher is still
available, but only when explicitly requested.

Usage:
    python benchmark/eval_extraction_quality.py benchmark/results/<run_id>/
    python benchmark/eval_extraction_quality.py benchmark/results/<run_id>/ --threshold 0.90
    python benchmark/eval_extraction_quality.py benchmark/results/<run_id>/ --judge sonnet
    python benchmark/eval_extraction_quality.py benchmark/results/<run_id>/ --matcher-backend word-overlap
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

EVAL_DIR = PROJECT_ROOT / "benchmark" / "transcripts" / "evaluation"
WORD_RE = re.compile(r"[a-z0-9_:+./-]+")


@dataclass
class JudgeResult:
    same_learning: bool
    confidence: float
    reason: str


@dataclass
class MatchResult:
    outcome: str
    similarity: float
    candidate_text: str | None
    judge_result: JudgeResult | None = None


class SimilarityMatcher:
    """Match engram texts using an explicit backend.

    `auto` resolves to the repo's FastEmbed wrapper and fails closed if that
    backend cannot be loaded. `word-overlap` is kept only as an explicit,
    lower-fidelity fallback for debugging.
    """

    def __init__(self, backend="auto", embed_batch_fn=None):
        self._vectors = {}
        self._token_sets = {}

        if backend not in ("auto", "fastembed", "word-overlap"):
            raise ValueError(f"Unknown matcher backend: {backend}")

        if backend == "word-overlap":
            self.backend = "word-overlap"
            self._embed_batch = None
            return

        self._embed_batch = embed_batch_fn
        if self._embed_batch is None:
            try:
                from engrammar.core.embeddings import embed_batch
            except Exception as exc:
                raise RuntimeError(
                    "FastEmbed matcher unavailable. Install benchmark deps or "
                    "rerun with --matcher-backend word-overlap."
                ) from exc
            self._embed_batch = embed_batch

        self.backend = "fastembed"

    def similarities(self, source_text, candidate_texts):
        """Return similarity scores in the same order as candidate_texts."""
        if not candidate_texts:
            return []
        if self.backend == "word-overlap":
            return [
                self._word_overlap(source_text, candidate_text)
                for candidate_text in candidate_texts
            ]

        missing = [
            text for text in [source_text, *candidate_texts]
            if text not in self._vectors
        ]
        if missing:
            embs = self._embed_batch(missing)
            norms = np.linalg.norm(embs, axis=1, keepdims=True) + 1e-10
            normalized = embs / norms
            for text, vector in zip(missing, normalized):
                self._vectors[text] = np.asarray(vector, dtype=np.float32)

        source_vec = self._vectors[source_text]
        return [float(source_vec @ self._vectors[text]) for text in candidate_texts]

    def _word_overlap(self, text1, text2):
        words1 = self._tokenize(text1)
        words2 = self._tokenize(text2)
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / max(len(words1), len(words2))

    def _tokenize(self, text):
        if text not in self._token_sets:
            self._token_sets[text] = set(WORD_RE.findall(text.lower()))
        return self._token_sets[text]


def load_labeled_engrams():
    """Load good and bad labeled engrams with their source sessions."""
    good = []
    bad = []
    for path, target in [
        (EVAL_DIR / "good_engrams.jsonl", good),
        (EVAL_DIR / "bad_engrams.jsonl", bad),
    ]:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    target.append(json.loads(line))
    return good, bad


def load_run_results(run_dir):
    """Load all extracted engrams from a benchmark run, grouped by transcript."""
    results = {}  # session_id -> list of extracted engram dicts
    for path in sorted(Path(run_dir).glob("*.json")):
        if path.name in ("summary.json",):
            continue
        with open(path) as f:
            data = json.load(f)
        transcript = data.get("transcript_file", "")
        session_id = transcript.replace(".jsonl", "")
        engrams = data.get("engrams") or []
        if session_id and engrams:
            results.setdefault(session_id, []).extend(engrams)
    return results


def find_best_match(labeled_text, extracted_engrams, matcher):
    """Find the best matching extracted engram for a labeled engram."""
    candidate_texts = []
    for eng in extracted_engrams:
        if not isinstance(eng, dict):
            continue
        text = eng.get("engram", eng.get("text", ""))
        if text:
            candidate_texts.append(text)

    if not candidate_texts:
        return 0.0, None

    similarities = matcher.similarities(labeled_text, candidate_texts)
    best_idx = int(np.argmax(similarities))
    return similarities[best_idx], candidate_texts[best_idx]


def evaluate_match(
    labeled_text,
    extracted_engrams,
    matcher,
    threshold,
    borderline_threshold,
    judge_model=None,
):
    """Classify a labeled-vs-extracted match into direct/borderline/miss buckets."""
    best_sim, best_text = find_best_match(labeled_text, extracted_engrams, matcher)
    if not best_text:
        return MatchResult(outcome="miss", similarity=0.0, candidate_text=None)

    if best_sim >= threshold:
        return MatchResult(
            outcome="direct_match",
            similarity=best_sim,
            candidate_text=best_text,
        )

    if best_sim < borderline_threshold:
        return MatchResult(
            outcome="miss",
            similarity=best_sim,
            candidate_text=best_text,
        )

    if not judge_model:
        return MatchResult(
            outcome="borderline",
            similarity=best_sim,
            candidate_text=best_text,
        )

    judge_result = judge_same_learning(labeled_text, best_text, judge_model)
    if judge_result and judge_result.same_learning:
        return MatchResult(
            outcome="judge_match",
            similarity=best_sim,
            candidate_text=best_text,
            judge_result=judge_result,
        )
    if judge_result:
        return MatchResult(
            outcome="judge_reject",
            similarity=best_sim,
            candidate_text=best_text,
            judge_result=judge_result,
        )
    return MatchResult(
        outcome="borderline",
        similarity=best_sim,
        candidate_text=best_text,
    )


def judge_same_learning(labeled_text, candidate_text, model):
    """Ask Claude whether two engram phrasings express the same learning."""
    prompt = f"""You are comparing two candidate engrams.

Decide whether they express the same reusable learning, even if wording differs.

Treat them as the same learning only if a future assistant could substitute one
for the other without losing a material part of the advice.

Return ONLY valid JSON:
{{
  "same_learning": true or false,
  "confidence": 0.0 to 1.0,
  "reason": "brief reason"
}}

Labeled engram:
{labeled_text}

Extracted engram:
{candidate_text}
"""
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["ENGRAMMAR_INTERNAL_RUN"] = "1"

    try:
        result = subprocess.run(
            [
                "claude",
                "-p",
                prompt,
                "--model",
                model,
                "--output-format",
                "text",
                "--no-session-persistence",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        return None

    if result.returncode != 0:
        return None

    parsed = parse_json_object(result.stdout)
    if not parsed:
        return None

    return JudgeResult(
        same_learning=bool(parsed.get("same_learning")),
        confidence=float(parsed.get("confidence", 0.0)),
        reason=str(parsed.get("reason", "")).strip(),
    )


def parse_json_object(raw):
    """Parse a JSON object from plain text or fenced output."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escape = False
    end = None
    for idx, char in enumerate(text[start:], start):
        if escape:
            escape = False
            continue
        if char == "\\":
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = idx
                break

    if end is None:
        return None

    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def get_engram_sessions(engram):
    """Get the source session IDs for a labeled engram."""
    if engram.get("source_sessions"):
        return engram["source_sessions"]
    return _get_engram_sessions_from_db(engram["id"])


@lru_cache(maxsize=None)
def _get_engram_sessions_from_db(engram_id):
    try:
        import sqlite3

        db_path = os.path.expanduser("~/.engrammar/engrams.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT source_sessions FROM engrams WHERE id = ?",
            (engram_id,),
        ).fetchone()
        conn.close()
        if row and row["source_sessions"]:
            return json.loads(row["source_sessions"])
    except Exception:
        pass
    return []


def counted_status(engram, default_status):
    """Return benchmark counting policy for a labeled engram."""
    return engram.get("benchmark_status", default_status)


def format_match_detail(prefix, engram, match_result, reason=None):
    """Render a single benchmark line."""
    reason_suffix = f" [{reason}]" if reason else ""
    text = engram["text"]
    if match_result.outcome == "direct_match":
        return (
            f"  {prefix} #{engram['id']} (sim={match_result.similarity:.2f})"
            f"{reason_suffix}: {text[:80]}..."
        )
    if match_result.outcome == "judge_match":
        conf = match_result.judge_result.confidence if match_result.judge_result else 0.0
        return (
            f"  {prefix} #{engram['id']} (sim={match_result.similarity:.2f}, "
            f"judge={conf:.2f}){reason_suffix}: {text[:80]}..."
        )
    if match_result.outcome == "borderline":
        return (
            f"  {prefix} #{engram['id']} (best={match_result.similarity:.2f})"
            f"{reason_suffix}: {text[:80]}..."
        )
    if match_result.outcome == "judge_reject":
        conf = match_result.judge_result.confidence if match_result.judge_result else 0.0
        return (
            f"  {prefix} #{engram['id']} (best={match_result.similarity:.2f}, "
            f"judge reject={conf:.2f}){reason_suffix}: {text[:80]}..."
        )
    return (
        f"  {prefix} #{engram['id']} (best={match_result.similarity:.2f})"
        f"{reason_suffix}: {text[:80]}..."
    )


def print_closest(match_result, label="closest"):
    """Print the best candidate text, if present."""
    if match_result.candidate_text:
        print(f"         {label}: {match_result.candidate_text[:100]}...")
    if match_result.judge_result and match_result.judge_result.reason:
        print(f"         judge: {match_result.judge_result.reason[:100]}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate extraction quality")
    parser.add_argument("run_dir", help="Path to benchmark results directory")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.90,
        help="Direct similarity threshold for a confirmed match (default: 0.90)",
    )
    parser.add_argument(
        "--borderline-threshold",
        type=float,
        default=0.80,
        help="Lower threshold for borderline candidates (default: 0.80)",
    )
    parser.add_argument(
        "--matcher-backend",
        choices=["auto", "fastembed", "word-overlap"],
        default="auto",
        help="Similarity backend to use (default: auto -> fastembed)",
    )
    parser.add_argument(
        "--judge",
        type=str,
        default=None,
        help="Optional Claude model to adjudicate borderline matches",
    )
    args = parser.parse_args()

    if args.borderline_threshold > args.threshold:
        raise SystemExit("--borderline-threshold must be <= --threshold")

    matcher = SimilarityMatcher(backend=args.matcher_backend)

    good, bad = load_labeled_engrams()
    results = load_run_results(args.run_dir)

    print(f"Labeled: {len(good)} good, {len(bad)} bad")
    print(
        f"Extracted from {len(results)} transcripts, "
        f"{sum(len(v) for v in results.values())} total engrams"
    )
    print(f"Matcher backend: {matcher.backend}")
    print(f"Direct match threshold: {args.threshold}")
    print(f"Borderline threshold:  {args.borderline_threshold}")
    print(f"Judge: {args.judge or 'none'}")
    print()

    print("=" * 80)
    print("GOOD ENGRAMS — should be extracted (recall)")
    print("=" * 80)
    good_found = 0
    good_borderline = 0
    good_missed = 0
    for eng in good:
        status = counted_status(eng, "must_extract")
        if status == "do_not_count":
            print(f"  SKIP  #{eng['id']}: benchmark_status=do_not_count")
            continue

        sessions = get_engram_sessions(eng)
        candidate_engrams = []
        for sid in sessions:
            candidate_engrams.extend(results.get(sid, []))

        if not candidate_engrams:
            print(f"  SKIP  #{eng['id']}: source transcript not in run")
            continue

        match_result = evaluate_match(
            eng["text"],
            candidate_engrams,
            matcher,
            args.threshold,
            args.borderline_threshold,
            judge_model=args.judge,
        )
        if match_result.outcome in ("direct_match", "judge_match"):
            good_found += 1
            print(format_match_detail("FOUND", eng, match_result))
        elif match_result.outcome == "borderline":
            good_borderline += 1
            print(format_match_detail("BORDER", eng, match_result))
            print_closest(match_result)
        else:
            good_missed += 1
            print(format_match_detail("MISS ", eng, match_result))
            print_closest(match_result)

    print()
    print("=" * 80)
    print("BAD ENGRAMS — should NOT be extracted (precision)")
    print("=" * 80)
    bad_extracted = 0
    bad_borderline = 0
    bad_avoided = 0
    for eng in bad:
        status = counted_status(eng, "must_avoid")
        if status == "do_not_count":
            print(f"  SKIP  #{eng['id']}: benchmark_status=do_not_count")
            continue

        sessions = get_engram_sessions(eng)
        candidate_engrams = []
        for sid in sessions:
            candidate_engrams.extend(results.get(sid, []))

        if not candidate_engrams:
            print(f"  SKIP  #{eng['id']}: source transcript not in run")
            continue

        match_result = evaluate_match(
            eng["text"],
            candidate_engrams,
            matcher,
            args.threshold,
            args.borderline_threshold,
            judge_model=args.judge,
        )
        reason = eng.get("reason_bad", "unknown")
        if match_result.outcome in ("direct_match", "judge_match"):
            bad_extracted += 1
            print(format_match_detail("FAIL ", eng, match_result, reason=reason))
            print_closest(match_result, label="extracted")
        elif match_result.outcome == "borderline":
            bad_borderline += 1
            print(format_match_detail("BORDER", eng, match_result, reason=reason))
            print_closest(match_result, label="closest")
        else:
            bad_avoided += 1
            print(format_match_detail("OK   ", eng, match_result, reason=reason))

    good_total = good_found + good_borderline + good_missed
    bad_total = bad_extracted + bad_borderline + bad_avoided

    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    if good_total > 0:
        recall = good_found / good_total * 100
        print(f"Good engram recall:    {good_found}/{good_total} = {recall:.0f}%")
        print(f"Good borderline:       {good_borderline}")
        resolved_good = good_found + good_missed
        if resolved_good > 0:
            resolved_recall = good_found / resolved_good * 100
            print(
                f"Resolved good recall:  {good_found}/{resolved_good} = "
                f"{resolved_recall:.0f}%"
            )
    else:
        print("Good engram recall:    no testable good engrams")

    if bad_total > 0:
        precision = bad_avoided / bad_total * 100
        print(f"Bad engram avoidance:  {bad_avoided}/{bad_total} = {precision:.0f}%")
        print(f"Bad borderline:        {bad_borderline}")
        resolved_bad = bad_extracted + bad_avoided
        if resolved_bad > 0:
            resolved_precision = bad_avoided / resolved_bad * 100
            print(
                f"Resolved bad avoid:    {bad_avoided}/{resolved_bad} = "
                f"{resolved_precision:.0f}%"
            )
    else:
        print("Bad engram avoidance:  no testable bad engrams")

    total_extracted = sum(len(v) for v in results.values())
    print(
        f"Total extracted:       {total_extracted} engrams from {len(results)} transcripts"
    )
    print(f"Avg per transcript:    {total_extracted / max(len(results), 1):.1f}")


if __name__ == "__main__":
    main()
