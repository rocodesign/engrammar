#!/usr/bin/env python3
"""Benchmark tag-relevance evaluation quality across models.

Loads real sessions from session_audit (sessions where engrams were shown),
runs the evaluation prompt with multiple models, and measures:
  1. Score distributions — what % of engrams get positive/negative scores
  2. Inter-model agreement — do haiku/sonnet agree on relevance?
  3. Judge-verified accuracy — is a sample of evaluations defensible?

Usage:
    python benchmark/run_eval_benchmark.py
    python benchmark/run_eval_benchmark.py --models haiku sonnet
    python benchmark/run_eval_benchmark.py --sessions 10
    python benchmark/run_eval_benchmark.py --judge opus --judge-samples 20
    python benchmark/run_eval_benchmark.py --dry-run
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

from engrammar.core.prompt_loader import load_prompt

RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"
_ENGRAMMAR_BLOCK_RE = re.compile(r"\[ENGRAMMAR_V1\].*?\[/ENGRAMMAR_V1\]", re.DOTALL)

_prompt_cache = {}


def _get_prompt(name):
    if name not in _prompt_cache:
        _prompt_cache[name] = load_prompt(name)
    return _prompt_cache[name]


# --- Data loading ---


def _read_transcript_file(path, max_chars=6000):
    """Read transcript from a JSONL file, returning head+tail excerpt."""
    messages = []
    try:
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("type") not in ("user", "assistant"):
                    continue
                msg = entry.get("message", {})
                content = msg.get("content", "")
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                elif not isinstance(content, str):
                    continue
                content = _ENGRAMMAR_BLOCK_RE.sub("", content).strip()
                role = msg.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:500]}")
    except Exception:
        return ""

    text = "\n".join(messages)
    if len(text) <= max_chars:
        return text

    ellipsis = "\n\n[...]\n\n"
    half = (max_chars - len(ellipsis)) // 2
    return text[:half] + ellipsis + text[-half:]


def _find_transcript_by_session(session_id, max_chars=6000):
    """Search ~/.claude/projects/ for a transcript matching session_id."""
    projects_dir = os.path.expanduser("~/.claude/projects")
    if not os.path.exists(projects_dir):
        return ""
    matches = glob.glob(os.path.join(projects_dir, "*", f"{session_id}.jsonl"))
    if not matches:
        return ""
    return _read_transcript_file(matches[0], max_chars=max_chars)


def load_test_sessions(n=10, db_path=None):
    """Load recent session_audit records that have transcripts and shown engrams.

    Returns list of session dicts ready for evaluation.
    """
    from engrammar.core.db import get_connection
    conn = get_connection(db_path)

    # Overfetch to compensate for sessions with missing transcripts
    rows = conn.execute("""
        SELECT session_id, shown_engram_ids, env_tags, repo, transcript_path
        FROM session_audit
        WHERE shown_engram_ids != '[]'
        ORDER BY rowid DESC
        LIMIT ?
    """, (n * 5,)).fetchall()
    conn.close()

    sessions = []
    for row in rows:
        if len(sessions) >= n:
            break
        shown_ids = json.loads(row["shown_engram_ids"])
        if not shown_ids:
            continue

        transcript = ""
        t_path = row["transcript_path"] if "transcript_path" in row.keys() else None
        if t_path and Path(t_path).exists():
            transcript = _read_transcript_file(t_path)
        if not transcript:
            transcript = _find_transcript_by_session(row["session_id"])
        if not transcript:
            continue

        sessions.append({
            "session_id": row["session_id"],
            "shown_engram_ids": shown_ids,
            "env_tags": json.loads(row["env_tags"]),
            "repo": row["repo"] or "unknown",
            "transcript": transcript,
        })

    return sessions


def load_engram_texts(ids, db_path=None):
    """Load engram id→text map from DB."""
    from engrammar.core.db import get_connection
    conn = get_connection(db_path)
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(
        f"SELECT id, text FROM engrams WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    conn.close()
    return {row["id"]: row["text"] for row in rows}


# --- Evaluation call ---


EVAL_BATCH_SIZE = 15


def _run_single_eval_batch(engram_ids, session, engram_texts, model):
    """Run evaluation for a single batch of engram IDs. Returns parsed result dict."""
    engrams_block = "\n".join(
        f"- ID {eid}: {engram_texts[eid]}"
        for eid in engram_ids
        if eid in engram_texts
    )
    if not engrams_block:
        return {"error": "no engrams found in DB", "elapsed_s": 0}

    prompt = _get_prompt("evaluation/tag_relevance.md").format(
        repo=session["repo"],
        env_tags=json.dumps(session["env_tags"]),
        engrams_block=engrams_block,
        transcript=session["transcript"],
    )

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
            return {"error": f"exit {result.returncode}: {result.stderr[:200]}", "elapsed_s": elapsed}

        output = result.stdout.strip()
        if output.startswith("```"):
            lines = output.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            output = "\n".join(lines)

        try:
            evaluations = json.loads(output)
        except json.JSONDecodeError:
            m = re.search(r'\[.*\]', output, re.DOTALL)
            if m:
                try:
                    evaluations = json.loads(m.group())
                except json.JSONDecodeError:
                    return {"error": f"JSON parse failed: {output[:200]}", "elapsed_s": elapsed}
            else:
                return {"error": f"no JSON array in output: {output[:200]}", "elapsed_s": elapsed}

        return {
            "evaluations": evaluations,
            "elapsed_s": elapsed,
            "prompt_chars": len(prompt),
        }

    except subprocess.TimeoutExpired:
        return {"error": "timeout", "elapsed_s": 120}
    except Exception as e:
        return {"error": str(e), "elapsed_s": time.time() - start}


def run_evaluation(session, engram_texts, model):
    """Call the tag_relevance evaluation prompt for a session.

    Batches large engram sets (>EVAL_BATCH_SIZE) to prevent quality degradation.
    Returns dict with raw scores, timing, and any error.
    """
    shown = [eid for eid in session["shown_engram_ids"] if eid in engram_texts]
    if not shown:
        return {"error": "no engrams found in DB", "elapsed_s": 0}

    if len(shown) <= EVAL_BATCH_SIZE:
        return _run_single_eval_batch(shown, session, engram_texts, model)

    # Batch large sets
    all_evaluations = []
    total_elapsed = 0
    total_prompt_chars = 0

    for i in range(0, len(shown), EVAL_BATCH_SIZE):
        batch = shown[i:i + EVAL_BATCH_SIZE]
        result = _run_single_eval_batch(batch, session, engram_texts, model)
        total_elapsed += result.get("elapsed_s", 0)
        total_prompt_chars += result.get("prompt_chars", 0)

        if "error" in result:
            return {"error": result["error"], "elapsed_s": total_elapsed}

        all_evaluations.extend(result.get("evaluations", []))

    return {
        "evaluations": all_evaluations,
        "elapsed_s": total_elapsed,
        "prompt_chars": total_prompt_chars,
    }


# --- Score analysis ---


def summarize_scores(evaluations, shown_ids):
    """Summarize tag_scores into per-engram signal: positive/neutral/negative."""
    scores_by_id = {}
    for ev in evaluations:
        eid = ev.get("engram_id")
        tag_scores = ev.get("tag_scores", {})
        if not tag_scores:
            scores_by_id[eid] = 0.0
            continue
        avg = sum(tag_scores.values()) / len(tag_scores)
        scores_by_id[eid] = avg

    result = {"positive": 0, "neutral": 0, "negative": 0, "total": len(shown_ids)}
    for eid in shown_ids:
        score = scores_by_id.get(eid, 0.0)
        if score > 0.1:
            result["positive"] += 1
        elif score < -0.1:
            result["negative"] += 1
        else:
            result["neutral"] += 1
    return result, scores_by_id


def agreement_rate(scores_a, scores_b):
    """Compute agreement between two score maps (same direction = agree).

    Returns fraction of engrams where both models agree on positive/neutral/negative.
    """
    common = set(scores_a) & set(scores_b)
    if not common:
        return None

    def bucket(s):
        if s > 0.1:
            return "pos"
        if s < -0.1:
            return "neg"
        return "neu"

    agreed = sum(1 for eid in common if bucket(scores_a[eid]) == bucket(scores_b[eid]))
    return agreed / len(common)


# --- Judge verification ---


def call_judge(prompt, model):
    """Call LLM judge and return parsed JSON."""
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
        if text.startswith("```"):
            lines = text.split("\n")[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text), elapsed
        except json.JSONDecodeError:
            s = text.find("{")
            e = text.rfind("}") + 1
            if s >= 0 and e > s:
                try:
                    return json.loads(text[s:e]), elapsed
                except json.JSONDecodeError:
                    pass
        return None, elapsed
    except Exception:
        return None, time.time() - start


def judge_evaluations(session_data, engram_texts, evaluations, judge_model, n=5):
    """Ask judge model whether n sampled evaluation scores are defensible.

    Picks the highest-magnitude scores to review (most interesting cases).
    """
    # Build (engram_id, score, tag_scores) list sorted by abs(score)
    scored = []
    for ev in evaluations:
        eid = ev.get("engram_id")
        tag_scores = ev.get("tag_scores", {})
        if not tag_scores or eid not in engram_texts:
            continue
        avg = sum(tag_scores.values()) / len(tag_scores)
        scored.append((abs(avg), avg, eid, tag_scores, ev.get("reason", "")))
    scored.sort(reverse=True)
    sample = scored[:n]

    results = []
    # Give judge the SAME transcript the evaluator saw
    transcript_for_judge = session_data["transcript"]

    # Build lookup for model's reasoning fields
    eval_by_id = {}
    for ev in evaluations:
        eval_by_id[ev.get("engram_id")] = ev

    for abs_score, avg_score, eid, tag_scores, reason in sample:
        engram_text = engram_texts.get(eid, "?")
        direction = "POSITIVE" if avg_score > 0.1 else ("NEGATIVE" if avg_score < -0.1 else "NEUTRAL")
        ev = eval_by_id.get(eid, {})
        model_action = ev.get("action", "not provided")
        model_found = ev.get("found", "not provided")

        prompt = f"""You are auditing a tag-relevance evaluation decision.

A model evaluated whether an engram (learned lesson) was acted on during a session.

Engram: "{engram_text}"

Session transcript (same excerpt the model saw):
{transcript_for_judge}

The model's evaluation:
- Direction: {direction}
- Tag scores: {json.dumps(tag_scores)}
- Action identified: "{model_action}"
- Transcript quote: "{model_found}"
- Reason given: "{reason}"

Is this evaluation defensible? Consider:
1. Does the transcript quote actually appear in the transcript above? (Check for fabricated quotes)
2. If the quote is real, does it show the engram's advice was followed (positive) or violated (negative)?
3. Are the tag scores relevant to the engram's domain (not just the session's project)?
4. If neutral: is the topic genuinely absent from the session?

Return strict JSON:
{{
  "verdict": "correct" | "questionable" | "wrong",
  "confidence": 0.0-1.0,
  "reason": "1-2 sentence explanation"
}}"""

        response, elapsed = call_judge(prompt, judge_model)
        if response:
            verdict = response.get("verdict", "error")
            conf = response.get("confidence", 0)
            results.append({
                "engram_id": eid,
                "avg_score": round(avg_score, 3),
                "direction": direction,
                "verdict": verdict,
                "judge_confidence": conf,
                "reason": response.get("reason", ""),
                "elapsed_s": round(elapsed, 2),
            })
        else:
            results.append({
                "engram_id": eid,
                "avg_score": round(avg_score, 3),
                "direction": direction,
                "verdict": "error",
                "elapsed_s": round(elapsed, 2),
            })

    return results


# --- Main ---


def main():
    parser = argparse.ArgumentParser(description="Benchmark tag-relevance evaluation quality")
    parser.add_argument("--models", nargs="*", default=["haiku"],
                        help="Models to test (default: haiku)")
    parser.add_argument("--sessions", type=int, default=10,
                        help="Number of sessions to evaluate (default: 10)")
    parser.add_argument("--judge", type=str, default=None,
                        help="Judge model for accuracy verification (e.g. opus). Skipped if not set.")
    parser.add_argument("--judge-samples", type=int, default=5,
                        help="Engrams to judge per session (default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show session stats without calling LLM")
    args = parser.parse_args()

    print(f"Loading {args.sessions} sessions from session_audit...")
    sessions = load_test_sessions(n=args.sessions)
    if not sessions:
        print("No sessions with transcripts found in session_audit.")
        return

    print(f"Found {len(sessions)} sessions with transcripts\n")

    # Collect all engram IDs across sessions
    all_ids = set()
    for s in sessions:
        all_ids.update(s["shown_engram_ids"])
    engram_texts = load_engram_texts(list(all_ids))
    print(f"Loaded {len(engram_texts)} engram texts\n")

    if args.dry_run:
        for s in sessions:
            found = sum(1 for eid in s["shown_engram_ids"] if eid in engram_texts)
            print(f"  {s['session_id'][:12]} — {found}/{len(s['shown_engram_ids'])} engrams, "
                  f"tags={s['env_tags'][:3]}, repo={s['repo']}")
        return

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_DIR / f"eval-{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Per-model results: session_id → {evaluations, scores_by_id, summary, elapsed_s}
    model_results = {m: {} for m in args.models}
    all_session_results = []

    for si, session in enumerate(sessions):
        sid = session["session_id"]
        shown = [eid for eid in session["shown_engram_ids"] if eid in engram_texts]
        if not shown:
            print(f"Session {sid[:12]}: no engrams in DB — skip")
            continue

        print(f"Session {si+1}/{len(sessions)} {sid[:12]} "
              f"({len(shown)} engrams, repo={session['repo']}):")

        session_row = {
            "session_id": sid,
            "repo": session["repo"],
            "env_tags": session["env_tags"],
            "shown_engrams": len(shown),
            "models": {},
        }

        for model in args.models:
            print(f"  {model}...", end=" ", flush=True)
            result = run_evaluation(session, engram_texts, model)

            if "error" in result:
                print(f"ERROR: {result['error'][:60]}")
                session_row["models"][model] = {"error": result["error"]}
                continue

            evaluations = result["evaluations"]
            summary, scores_by_id = summarize_scores(evaluations, shown)

            print(f"+{summary['positive']} ={summary['neutral']} -{summary['negative']} "
                  f"in {result['elapsed_s']:.1f}s")

            model_results[model][sid] = {
                "evaluations": evaluations,
                "scores_by_id": scores_by_id,
                "summary": summary,
                "elapsed_s": result["elapsed_s"],
            }

            session_row["models"][model] = {
                "summary": summary,
                "elapsed_s": round(result["elapsed_s"], 2),
                "evaluations": evaluations,
            }

        # Inter-model agreement (if multiple models)
        if len(args.models) >= 2:
            m0, m1 = args.models[0], args.models[1]
            if sid in model_results[m0] and sid in model_results[m1]:
                agree = agreement_rate(
                    model_results[m0][sid]["scores_by_id"],
                    model_results[m1][sid]["scores_by_id"],
                )
                if agree is not None:
                    print(f"  agreement ({m0} vs {m1}): {agree:.0%}")
                    session_row["agreement"] = round(agree, 4)

        all_session_results.append(session_row)
        print()

    # Judge verification — judge all models, not just the first
    judge_results = []
    if args.judge:
        print(f"\n=== Judge verification ({args.judge}) ===\n")
        for model in args.models:
            for session in sessions:
                sid = session["session_id"]
                if sid not in model_results[model]:
                    continue
                mr = model_results[model][sid]
                evals = mr["evaluations"]
                if not evals:
                    continue

                shown_ids = [e for e in session["shown_engram_ids"] if e in engram_texts]
                if not shown_ids:
                    continue

                print(f"  Judging {sid[:12]} ({model})...")
                verdicts = judge_evaluations(
                    session, engram_texts, evals, args.judge, n=args.judge_samples
                )
                for v in verdicts:
                    print(f"    [{v['engram_id']}] {v['direction']} → {v['verdict']} ({v.get('judge_confidence', 0):.2f})")
                judge_results.append({"session_id": sid, "model": model, "verdicts": verdicts})

    # Save summary JSON
    summary_data = {
        "run_id": run_id,
        "config": {
            "models": args.models,
            "sessions": len(sessions),
            "judge": args.judge,
            "judge_samples": args.judge_samples if args.judge else 0,
        },
        "sessions": all_session_results,
        "judge_results": judge_results,
    }

    with open(run_dir / "summary.json", "w") as f:
        json.dump(summary_data, f, indent=2)

    # Markdown report
    md = [
        f"# Evaluation Benchmark — {run_id}\n",
        f"**Models**: {', '.join(args.models)}  ",
        f"**Sessions**: {len(sessions)}  ",
        f"**Judge**: {args.judge or 'none'}\n",
        "## Per-Session Results\n",
        "| Session | Engrams |" + "".join(f" {m} +/=/- | {m} time |" for m in args.models) +
        (" Agreement |" if len(args.models) >= 2 else "") + " Repo |",
        "|---------|--------:|" + "".join("|-----------|--------:|" for _ in args.models) +
        ("----------:|" if len(args.models) >= 2 else "") + "------|",
    ]

    for row in all_session_results:
        sid = row["session_id"][:12]
        cols = [f"| {sid} | {row['shown_engrams']} |"]
        for model in args.models:
            mr = row["models"].get(model, {})
            if "error" in mr:
                cols.append(f" error |  — |")
            elif "summary" in mr:
                s = mr["summary"]
                cols.append(f" {s['positive']}/{s['neutral']}/{s['negative']} | {mr['elapsed_s']:.1f}s |")
            else:
                cols.append(f" — | — |")
        if len(args.models) >= 2 and "agreement" in row:
            cols.append(f" {row['agreement']:.0%} |")
        elif len(args.models) >= 2:
            cols.append(" — |")
        cols.append(f" {row['repo'][:20]} |")
        md.append("".join(cols))

    # Aggregate stats per model
    md.append("\n## Aggregate Stats\n")
    md.append("| Model | Sessions | Avg +ve | Avg neutral | Avg -ve | Avg time |")
    md.append("|-------|--------:|--------:|------------:|--------:|---------:|")

    for model in args.models:
        results = [r["models"][model] for r in all_session_results
                   if model in r["models"] and "summary" in r["models"][model]]
        if not results:
            continue
        avg_pos = sum(r["summary"]["positive"] / r["summary"]["total"]
                      for r in results if r["summary"]["total"] > 0) / len(results)
        avg_neu = sum(r["summary"]["neutral"] / r["summary"]["total"]
                      for r in results if r["summary"]["total"] > 0) / len(results)
        avg_neg = sum(r["summary"]["negative"] / r["summary"]["total"]
                      for r in results if r["summary"]["total"] > 0) / len(results)
        avg_t = sum(r["elapsed_s"] for r in results) / len(results)
        md.append(f"| {model} | {len(results)} | {avg_pos:.0%} | {avg_neu:.0%} | {avg_neg:.0%} | {avg_t:.1f}s |")

    # Inter-model agreement summary
    if len(args.models) >= 2:
        agreements = [r["agreement"] for r in all_session_results if "agreement" in r]
        if agreements:
            avg_agree = sum(agreements) / len(agreements)
            md.append(f"\n**Inter-model agreement** ({args.models[0]} vs {args.models[1]}): "
                      f"{avg_agree:.0%} avg across {len(agreements)} sessions\n")

    # Judge results — per model breakdown
    if judge_results:
        md.append(f"\n## Judge Verification ({args.judge})\n")

        # Group by model
        for model in args.models:
            model_verdicts = [v for jr in judge_results if jr["model"] == model
                              for v in jr["verdicts"]]
            if not model_verdicts:
                continue

            correct = sum(1 for v in model_verdicts if v["verdict"] == "correct")
            questionable = sum(1 for v in model_verdicts if v["verdict"] == "questionable")
            wrong = sum(1 for v in model_verdicts if v["verdict"] == "wrong")
            errors = sum(1 for v in model_verdicts if v["verdict"] == "error")
            total_judged = len(model_verdicts)

            md.append(f"### {model}\n")
            md.append(f"| Verdict | Count | % |")
            md.append(f"|---------|------:|--:|")
            md.append(f"| Correct | {correct} | {correct/total_judged:.0%} |")
            md.append(f"| Questionable | {questionable} | {questionable/total_judged:.0%} |")
            md.append(f"| Wrong | {wrong} | {wrong/total_judged:.0%} |")
            if errors:
                md.append(f"| Error | {errors} | {errors/total_judged:.0%} |")

            problems = [v for jr in judge_results if jr["model"] == model
                        for v in jr["verdicts"] if v["verdict"] in ("wrong", "questionable")]
            if problems:
                md.append(f"\n**Problems ({model}):**\n")
                for v in problems:
                    md.append(f"- **{v['verdict'].upper()}** engram #{v['engram_id']} "
                              f"scored {v['direction']} ({v['avg_score']:+.2f}) — "
                              f"judge conf {v['judge_confidence']:.2f}")
                    md.append(f"  {v.get('reason', '')}")
                md.append("")

    report_path = run_dir / "report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(md))

    print("=" * 70)
    for line in md[:25]:
        print(line)
    if len(md) > 25:
        print(f"... ({len(md) - 25} more lines)")
    print(f"\nResults saved to: {run_dir}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
