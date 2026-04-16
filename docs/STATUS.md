# Project Status

## What It Does

Engrammar builds a knowledge base from your Claude Code sessions automatically. When you correct Claude, struggle through something for multiple turns, or discover a project convention — it extracts that as an "engram" and stores it. Next time you're in a similar context, it injects the relevant ones into your session via hooks, so Claude doesn't repeat the same mistakes.

Think of it as an automatic, searchable CLAUDE.md that learns which tips apply where.

## What Works Well

- **Context awareness** — it detects your environment (git remote, file markers, dependencies, paths) and only shows engrams relevant to what you're working on. An engram about React patterns won't show up in a Ruby project.
- **Fully local search** — embeddings run locally via fastembed, no API keys needed for the core search. It combines vector similarity with keyword matching so it handles both semantic and exact queries.
- **Hooks integration** — it fires on session start, prompt submit, and before tool use, so relevant knowledge shows up at the right moment without you asking for it.
- **Per-turn learning** — after each assistant response, the Stop hook triggers incremental extraction using byte offsets. This is more reliable than end-of-session hooks (which don't fire on terminal close) and catches friction signals as they happen, not just at the end.
- **Curation quality gate** — extracted engrams go through a Sonnet-based quality review that rejects ~31% of low-value extractions (internal details, architecture descriptions, generic advice). This is the dominant filtering stage in the pipeline.
- **LLM-assisted deduplication** — a multi-pass dedup pipeline uses Haiku to detect conceptual duplicates that embedding similarity misses. Operates in incremental mode (unverified vs verified pool) or bootstrap mode (all-vs-all for initial canon).
- **It gets better over time** — there's an evaluation pipeline that tracks whether shown engrams were actually useful per-context, and filters out the noise gradually via EMA-smoothed tag relevance scores.
- **One-liner install** — `curl -fsSL https://raw.githubusercontent.com/rocodesign/engrammar/main/scripts/install.sh | bash` handles everything: Python check, venv, deps, DB, hooks, PATH.

## The Pipeline

Full processing flow from transcript to surfaced engram:

```
1. Extraction    — Stop hook triggers per-turn extraction via daemon; Haiku analyzes friction moments
2. Curation      — Quality gate batches uncurated engrams, Sonnet judges keep/reject + merges duplicates
3. Dedup         — LLM-assisted semantic dedup (multi-pass until convergence)
4. Evaluation    — After each session, Haiku judges whether shown engrams were relevant per-context
5. Tag Scoring   — EMA-smoothed per-tag relevance scores filter/boost engrams in future searches
6. Auto-Pin      — Engrams proven useful across 15+ matches auto-pin to minimal common tag subset
7. Search        — Hybrid vector+BM25+RRF with tag affinity boost and relevance filtering
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for full technical details.

## Pitfalls

- **Cold start** — it needs a few sessions to accumulate useful engrams. The first days are quiet.
- **Noise in early sessions** — before the evaluator accumulates enough signal (3+ evals per tag), engrams can show up in contexts where they don't belong. The curation gate filters the worst offenders upfront, but tag relevance scoring takes sessions to converge.
- **Shallow tool-use context** — the PreToolUse hook enriches queries with assistant narration from the transcript, which helps. But it still lacks file contents and diffs, so prompt-based and session-start hooks remain more effective.
- **Claude Code only** — currently only integrates with Claude Code via hooks and MCP. No support for other coding agents (Cursor, Windsurf, etc.) yet.
- **Setup isn't turnkey yet** — requires Python 3.10+ and Claude Code CLI. The one-liner install handles most of the setup, but it's not a single-click experience for non-technical users.

## Benchmarking

The `benchmark/` directory has harnesses for testing each pipeline stage independently:

- **Extraction benchmark** — compare models, context window sizes, and prompt variants on real transcripts
- **Quality gate benchmark** — test curation keep/reject verdicts
- **Dedup benchmark** — test semantic duplicate detection accuracy
- **Evaluation benchmark** — test relevance scoring quality
- **Search autoresearch** — test search result quality across query types
- **Attribution benchmark** — test tag attribution weighting

See [benchmark/README.md](../benchmark/README.md) for setup and usage.

## Future Improvements

- Richer tool-use context — file contents, diffs for better PreToolUse search (narration injection is done, but file/diff context is not)
- Dashboard to browse and manage engrams visually instead of just CLI
- Cross-team knowledge sharing — a shared pool for team conventions
- Support for other coding agents beyond Claude Code
