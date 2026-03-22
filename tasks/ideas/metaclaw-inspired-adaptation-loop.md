# Idea: MetaClaw-Inspired Adaptation Loop

Captured from reviewing `aiming-lab/MetaClaw` on 2026-03-22.

## Why this is different from current engrammar

Engrammar already has:

- retrieval-time injection via hooks
- per-turn extraction into durable engrams
- post-hoc evaluation that updates tag relevance

What it does **not** have is a closed improvement loop that rewrites, stages, and re-tests its own learning artifacts based on repeated failure patterns.

## Proposal

Keep engrammar retrieval-first. Do **not** copy MetaClaw's RL fine-tuning path. Instead, borrow the higher-level loop:

1. collect failed or low-quality episodes
2. synthesize a better reusable artifact from them
3. stage it safely
4. re-test it on held-out evidence before broad injection

## Candidate pieces

### 1. Failure-driven engram evolution

When evaluation repeatedly scores an engram negatively, or when multiple sessions produce near-duplicate corrections around the same topic:

- generate a rewritten engram candidate
- optionally split one vague engram into several narrower ones
- preserve links to the source sessions and negative evidence

This is different from plain extraction. The trigger is not "new friction happened" but "existing memory keeps failing in deployment."

This should feed into `#012` candidate staging rather than bypassing it.

### 2. Procedural skill synthesis from repeated episodes

MetaClaw's strongest reusable idea is its skill library. For engrammar, the analogue is not a separate agent framework but richer procedural engrams:

- detect when multiple sessions solve the same multi-step workflow
- compress them into a structured "how to do X" artifact
- inject a summary first, then expand on demand

This overlaps with issue `#34` procedural skill engrams and issue `#37` progressive disclosure.

### 3. Idle-time learning jobs

MetaClaw schedules heavier learning work away from the foreground path. Engrammar could do the same for expensive quality-improvement jobs:

- re-extract candidate engrams with the latest prompt
- run dedup / cluster cleanup
- sweep extraction prompt variants against benchmark data
- run candidate-promotion checks

The daemon already has a background maintenance path, so this is mostly a scheduling/policy extension, not a new architecture.

### 4. Benchmark-gated evolution

MetaClaw mentions support/query separation to avoid stale or self-reinforcing reward signals. The engrammar analogue:

- use one set of sessions to propose prompt/engram rewrites
- use a separate held-out benchmark to accept or reject those changes

This matters most for:

- extraction prompt changes
- dedup prompt changes
- automatic engram rewrites from failed episodes

Without this gate, engrammar risks overfitting to noisy recent sessions and amplifying bad extractions.

## Likely implementation path

1. Finish safety rails first: `#012`, `#029`, `#031`
2. Add a small queue of "failing engrams" based on repeated negative evaluation
3. Generate rewritten candidates offline only
4. Validate candidates against held-out benchmark sessions before promotion
5. Only then consider richer procedural formats

## Related tracked work

- `tasks/open/[2]-012-stage-auto-extracted-engrams/task.md`
- `tasks/open/[2]-022-session-observational-memory/task.md`
- `tasks/open/[2]-029-extraction-quality-benchmark/task.md`
- `tasks/open/[1]-031-preserve-evaluation-context-through-dedup/task.md`
- `issues/open/[2]-034-procedural-skill-engrams/issue.md`
- `issues/open/[2]-037-progressive-disclosure-summaries/issue.md`
