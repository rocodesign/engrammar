# Project Status

## What It Does

Engrammar builds a knowledge base from your Claude Code sessions automatically. When you correct Claude, struggle through something for multiple turns, or discover a project convention — it extracts that as an "engram" and stores it. Next time you're in a similar context, it injects the relevant ones into your session via hooks, so Claude doesn't repeat the same mistakes.

Think of it as an automatic, searchable CLAUDE.md that learns which tips apply where.

## What Works Well

- **Context awareness** — it detects your environment (git remote, file markers, dependencies, paths) and only shows engrams relevant to what you're working on. An engram about React patterns won't show up in a Ruby project.
- **Fully local search** — embeddings run locally via fastembed, no API keys needed for the core search. It combines vector similarity with keyword matching so it handles both semantic and exact queries.
- **Hooks integration** — it fires on session start, prompt submit, and before tool use, so relevant knowledge shows up at the right moment without you asking for it.
- **End-of-session learning** — after each session, it automatically evaluates whether shown engrams were relevant and extracts new ones from friction moments, so the knowledge base improves without manual effort.
- **It gets better over time** — there's an evaluation pipeline that tracks whether shown engrams were actually useful per-context, and filters out the noise gradually.

## Pitfalls

- **Cold start** — it needs a few sessions to accumulate useful engrams. The first days are quiet.
- **Extraction quality is hit or miss** — it uses Haiku to extract from transcripts, which sometimes pulls out low-value stuff. You'll want to prune with `engrammar list` and `engrammar deprecate` occasionally.
- **Noise before the evaluator kicks in** — early on, engrams can show up in contexts where they don't belong. The tag relevance scoring fixes this over time but it takes sessions to converge.
- **Shallow tool-use context** — the PreToolUse hook only sees the tool name and basic parameters, so it rarely finds useful engrams. Searching against the actual file content or diffs being written would make this much more relevant.
- **Claude Code only** — currently only integrates with Claude Code via hooks and MCP. Support for other coding agents (Cursor, Windsurf, etc.) is planned but not there yet.
- **Setup isn't turnkey yet** — requires Python 3.12+, a setup script, and configuring hooks in Claude Code settings. Not a one-click install.

## Future Improvements

- Better deduplication — similar engrams still slip through sometimes
- Smarter extraction — being more selective about what's worth saving vs. session-specific noise
- Richer tool-use context (file contents, diffs) for better PreToolUse search
- Easier onboarding — ideally a single install command that handles everything
- Dashboard to browse and manage engrams visually instead of just CLI
- Cross-team knowledge sharing — a shared pool for team conventions
- Support for other coding agents beyond Claude Code
