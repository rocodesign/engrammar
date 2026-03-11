#!/usr/bin/env python3
"""Benchmark extraction quality across models, context sizes, and prompts.

Runs extraction prompts against cleaned transcripts with different
configurations and saves raw LLM output for comparison.

Usage:
    python benchmark/run_extraction.py
    python benchmark/run_extraction.py --transcripts benchmark/transcripts/b6f91235*.jsonl
    python benchmark/run_extraction.py --models haiku sonnet
    python benchmark/run_extraction.py --context-sizes 4000 8000 16000
    python benchmark/run_extraction.py --prompts prompts/extraction/transcript.md benchmark/prompts/v2.md
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

# Add project src to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.environ.setdefault("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
sys.path.insert(0, os.environ["ENGRAMMAR_HOME"])

ENGRAMMAR_BLOCK_RE = re.compile(r"\[ENGRAMMAR_V1\].*?\[/ENGRAMMAR_V1\]", re.DOTALL)

RESULTS_DIR = PROJECT_ROOT / "benchmark" / "results"


def read_transcript_messages(jsonl_path, max_chars=None, msg_max_chars=1500):
    """Read transcript messages, optionally capping total output size."""
    messages = []
    try:
        with open(jsonl_path, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") not in ("user", "assistant"):
                    continue

                message_obj = entry.get("message", {})
                content = message_obj.get("content", "")

                if isinstance(content, list):
                    text_parts = []
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "text":
                            text_parts.append(part.get("text", ""))
                    content = " ".join(text_parts)
                elif not isinstance(content, str):
                    continue

                content = ENGRAMMAR_BLOCK_RE.sub("", content).strip()
                role = message_obj.get("role", entry.get("type", ""))
                if content:
                    messages.append(f"{role}: {content[:msg_max_chars]}")
    except Exception as e:
        print(f"Error reading {jsonl_path}: {e}", file=sys.stderr)
        return ""

    result = "\n".join(messages)
    if max_chars and len(result) > max_chars:
        # Take the tail (most recent conversation) like the extractor does
        result = result[-max_chars:]
    return result


def load_prompt(path):
    """Load a prompt template, stripping YAML frontmatter if present."""
    with open(path, "r") as f:
        content = f.read()
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].strip()
    return content


def prompt_label(path):
    """Short label for a prompt file path."""
    p = Path(path)
    return p.stem


def run_extraction(transcript_text, model, prompt_template, session_id="benchmark"):
    """Run extraction with given model and return results + timing."""
    prompt = prompt_template.format(
        transcript=transcript_text,
        session_id=session_id,
        existing_instructions="",
        env_tags="[]",
    )

    prompt_chars = len(prompt)

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
            return {
                "error": f"claude exit code {result.returncode}: {result.stderr[:500]}",
                "elapsed_s": elapsed,
                "prompt_chars": prompt_chars,
            }

        output = result.stdout.strip()

        # Try to parse as JSON
        engrams = None
        try:
            parsed = json.loads(output)
            if isinstance(parsed, list):
                engrams = parsed
        except json.JSONDecodeError:
            # Try to find JSON array in output
            match = re.search(r'\[.*\]', output, re.DOTALL)
            if match:
                try:
                    engrams = json.loads(match.group())
                except json.JSONDecodeError:
                    pass

        return {
            "raw_output": output,
            "engrams": engrams,
            "engram_count": len(engrams) if engrams else 0,
            "elapsed_s": elapsed,
            "prompt_chars": prompt_chars,
            "transcript_chars": len(transcript_text),
        }

    except subprocess.TimeoutExpired:
        return {"error": "timeout", "elapsed_s": 300, "prompt_chars": prompt_chars}
    except Exception as e:
        return {"error": str(e), "elapsed_s": time.time() - start, "prompt_chars": prompt_chars}


def main():
    parser = argparse.ArgumentParser(description="Benchmark extraction quality")
    parser.add_argument("--transcripts", nargs="*",
                        help="Specific transcript files (default: all in benchmark/transcripts/)")
    parser.add_argument("--models", nargs="*", default=["haiku", "sonnet"],
                        help="Models to test (default: haiku sonnet)")
    parser.add_argument("--context-sizes", nargs="*", type=int,
                        default=[4000, 8000, 16000, 30000],
                        help="Context window sizes in chars (default: 4000 8000 16000 30000)")
    parser.add_argument("--msg-max-chars", type=int, default=1500,
                        help="Per-message truncation limit (default: 1500)")
    parser.add_argument("--prompts", nargs="*",
                        help="Prompt template files to compare (default: prompts/extraction/transcript.md)")
    parser.add_argument("--profile", type=str,
                        help="Use a named profile from benchmark/config.json (quick, compare-models, compare-prompts, full)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would run without calling LLM")
    args = parser.parse_args()

    # Apply profile defaults (CLI flags override)
    if args.profile:
        config_path = PROJECT_ROOT / "benchmark" / "config.json"
        with open(config_path) as f:
            profiles = json.load(f)["profiles"]
        if args.profile not in profiles:
            print(f"Unknown profile '{args.profile}'. Available: {', '.join(profiles.keys())}")
            return
        p = profiles[args.profile]
        print(f"Profile: {args.profile} — {p.get('description', '')}\n")
        if not args.models or args.models == ["haiku", "sonnet"]:
            args.models = p.get("models", args.models)
        if not args.context_sizes or args.context_sizes == [4000, 8000, 16000, 30000]:
            args.context_sizes = p.get("context_sizes", args.context_sizes)
        if not args.prompts:
            args.prompts = p.get("prompts")
        if args.msg_max_chars == 1500:
            args.msg_max_chars = p.get("msg_max_chars", 1500)
        if not args.transcripts and "transcripts" in p:
            args.transcripts = p["transcripts"]

    # Find transcripts
    if args.transcripts:
        transcript_files = []
        for pattern in args.transcripts:
            transcript_files.extend(glob.glob(pattern))
    else:
        transcript_files = sorted(glob.glob(
            str(PROJECT_ROOT / "benchmark" / "transcripts" / "*.jsonl")
        ))

    if not transcript_files:
        print("No transcript files found.")
        return

    # Apply transcript_count limit from profile
    if args.profile:
        config_path = PROJECT_ROOT / "benchmark" / "config.json"
        with open(config_path) as f:
            p = json.load(f)["profiles"].get(args.profile, {})
        tc = p.get("transcript_count")
        if tc and not args.transcripts and len(transcript_files) > tc:
            transcript_files = transcript_files[:tc]

    # Load prompts
    prompt_paths = args.prompts or [str(PROJECT_ROOT / "prompts" / "extraction" / "transcript.md")]
    prompts = {}
    for p in prompt_paths:
        label = prompt_label(p)
        prompts[label] = load_prompt(p)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Generate run ID
    run_id = time.strftime("%Y%m%d-%H%M%S")
    run_dir = RESULTS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    total = len(transcript_files) * len(args.models) * len(args.context_sizes) * len(prompts)
    print(f"Benchmark run: {run_id}")
    print(f"Transcripts: {len(transcript_files)}")
    print(f"Prompts: {', '.join(prompts.keys())}")
    print(f"Models: {args.models}")
    print(f"Context sizes: {args.context_sizes}")
    print(f"Total runs: {total}")
    print()

    all_results = []

    for t_path in transcript_files:
        t_name = Path(t_path).stem[:12]
        t_size_kb = os.path.getsize(t_path) / 1024

        for ctx_size in args.context_sizes:
            transcript_text = read_transcript_messages(
                t_path, max_chars=ctx_size, msg_max_chars=args.msg_max_chars
            )
            actual_chars = len(transcript_text)

            for p_label, p_template in prompts.items():
                for model in args.models:
                    label = f"{t_name} | {p_label} | {model} | ctx={ctx_size}"

                    if args.dry_run:
                        print(f"[DRY RUN] {label} — transcript {t_size_kb:.0f}KB, "
                              f"context {actual_chars} chars")
                        continue

                    print(f"Running: {label}...", end=" ", flush=True)

                    result = run_extraction(
                        transcript_text, model, p_template,
                        session_id=Path(t_path).stem,
                    )

                    result["transcript_file"] = Path(t_path).name
                    result["transcript_size_kb"] = round(t_size_kb, 1)
                    result["model"] = model
                    result["prompt"] = p_label
                    result["context_size_setting"] = ctx_size
                    result["msg_max_chars"] = args.msg_max_chars

                    all_results.append(result)

                    if "error" in result:
                        print(f"ERROR: {result['error'][:80]}")
                    else:
                        print(f"{result['engram_count']} engrams in {result['elapsed_s']:.1f}s")

                    # Save individual result
                    p_suffix = f"_{p_label}" if len(prompts) > 1 else ""
                    result_file = run_dir / f"{t_name}_{model}_ctx{ctx_size}{p_suffix}.json"
                    with open(result_file, "w") as f:
                        json.dump(result, f, indent=2)

    if args.dry_run:
        return

    # Save summary
    summary = {
        "run_id": run_id,
        "config": {
            "models": args.models,
            "prompts": list(prompts.keys()),
            "context_sizes": args.context_sizes,
            "msg_max_chars": args.msg_max_chars,
            "transcript_count": len(transcript_files),
        },
        "results": [],
    }

    for r in all_results:
        summary["results"].append({
            "transcript": r.get("transcript_file", ""),
            "model": r.get("model", ""),
            "prompt": r.get("prompt", ""),
            "context_size": r.get("context_size_setting", 0),
            "transcript_chars": r.get("transcript_chars", 0),
            "prompt_chars": r.get("prompt_chars", 0),
            "engram_count": r.get("engram_count", 0),
            "elapsed_s": round(r.get("elapsed_s", 0), 2),
            "error": r.get("error"),
        })

    summary_path = run_dir / "summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    # Write markdown report
    multi_prompt = len(prompts) > 1
    prompt_col = "| Prompt " if multi_prompt else ""
    prompt_sep = "|--------" if multi_prompt else ""

    md_lines = [
        f"# Extraction Benchmark — {run_id}\n",
        f"**Prompts**: {', '.join(prompts.keys())}  ",
        f"**Models**: {', '.join(args.models)}  ",
        f"**Context sizes**: {', '.join(str(s) for s in args.context_sizes)}  ",
        f"**Transcripts**: {len(transcript_files)}  ",
        f"**Per-message truncation**: {args.msg_max_chars} chars\n",
        "## Summary\n",
        f"| Transcript {prompt_col}| Model | CtxSize | Actual Chars | Engrams | Time (s) | Error |",
        f"|------------{prompt_sep}|-------|--------:|-------------:|--------:|---------:|-------|",
    ]

    for r in summary["results"]:
        t_name = r["transcript"][:12] if r["transcript"] else "?"
        error = r.get("error", "")[:30] if r.get("error") else ""
        p_col = f"| {r.get('prompt', '')} " if multi_prompt else ""
        md_lines.append(
            f"| {t_name} {p_col}| {r['model']} | {r['context_size']} | "
            f"{r['transcript_chars']} | {r['engram_count']} | "
            f"{r['elapsed_s']:.1f} | {error} |"
        )

    # Comparison table — group by prompt+model if multi-prompt, else just model
    configs = sorted(set(
        (r.get("prompt", ""), r["model"]) for r in summary["results"]
    ))
    config_labels = [f"{p}/{m}" if multi_prompt else m for p, m in configs]

    if len(config_labels) > 1:
        md_lines.append("\n## Comparison (avg engrams per context size)\n")
        md_lines.append("| CtxSize | " + " | ".join(config_labels) + " |")
        md_lines.append("|--------:|" + "|".join(["--------:" for _ in config_labels]) + "|")

        for ctx in args.context_sizes:
            row = [str(ctx)]
            for p_name, model in configs:
                matching = [r for r in summary["results"]
                            if r["model"] == model and r.get("prompt", "") == p_name
                            and r["context_size"] == ctx and not r.get("error")]
                if matching:
                    avg = sum(r["engram_count"] for r in matching) / len(matching)
                    avg_time = sum(r["elapsed_s"] for r in matching) / len(matching)
                    row.append(f"{avg:.1f} ({avg_time:.1f}s)")
                else:
                    row.append("—")
            md_lines.append("| " + " | ".join(row) + " |")

    # Per-transcript engrams detail
    md_lines.append("\n## Extracted Engrams Detail\n")
    for r in all_results:
        if r.get("engrams"):
            t_name = r.get("transcript_file", "?")[:12]
            model = r.get("model", "?")
            ctx = r.get("context_size_setting", "?")
            p_name = r.get("prompt", "")
            p_suffix = f" — {p_name}" if multi_prompt else ""
            md_lines.append(f"### {t_name} — {model} — ctx={ctx}{p_suffix}\n")
            for i, eng in enumerate(r["engrams"], 1):
                text = eng.get("engram", "?")
                cat = eng.get("category", "?")
                scope = eng.get("scope", "?")
                tags = eng.get("relevant_tags", [])
                tag_str = f" `{', '.join(tags)}`" if tags else ""
                md_lines.append(f"{i}. **[{cat}]** {text} _{scope}_{tag_str}")
            md_lines.append("")

    report_path = run_dir / "report.md"
    with open(report_path, "w") as f:
        f.write("\n".join(md_lines))

    # Also print summary to console
    print("\n" + "=" * 90)
    for line in md_lines[:20]:
        print(line)
    if len(md_lines) > 20:
        print(f"... ({len(md_lines) - 20} more lines)")

    print(f"\nResults saved to: {run_dir}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
