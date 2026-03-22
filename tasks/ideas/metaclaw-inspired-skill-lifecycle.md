# Idea: MetaClaw-inspired skill lifecycle for engrammar

MetaClaw is interesting for engrammar less because of its RL layer and more because it treats learned skills as a lifecycle:

1. capture session experience
2. synthesize or evolve skills after the session
3. keep serving responsive while learning runs asynchronously
4. avoid trusting stale evidence after a skill changes

## Most applicable ideas

### 1. Session-end skill synthesis

Engrammar already extracts per turn, but MetaClaw also does an explicit session-close pass over buffered turns. That maps well to:

- `tasks/ideas/session-end-reflection.md`
- `tasks/open/[2]-022-session-observational-memory/task.md`
- `tasks/open/[2]-016-adaptive-evaluation-transcript-context/task.md`

Potential engrammar version:

- keep fast per-turn extraction for low latency
- add a session-end synthesis pass that compresses the whole session into candidate engrams
- bias that pass toward corrections, failed attempts, and discovered procedures

This should improve recall for learnings that are only obvious across multiple turns.

### 2. Failure-focused procedural extraction

MetaClaw evolves skills from failed or weak episodes, not just generic summaries. For engrammar, that suggests prioritizing extraction of:

- debugging runbooks
- deployment/checklist procedures
- "if X happens, do Y" recovery patterns

This aligns directly with `issues/open/[2]-034-procedural-skill-engrams/issue.md`.

### 3. Version or generation boundaries for learned knowledge

MetaClaw tags samples with `skill_generation` and discards stale pre-evolution samples after the skill library changes. Engrammar has no equivalent boundary today: evaluation evidence can keep accumulating even if an engram is materially rewritten or merged.

Potential engrammar version:

- add a `version` or `generation` field on engrams
- bump it on major text / structure changes or dedup merges
- attribute evaluator evidence to the version that was actually shown
- avoid blending pre-rewrite and post-rewrite usefulness into one score

This would make tag relevance and candidate promotion more trustworthy.

### 4. Asynchronous "slow learning" windows

MetaClaw schedules expensive updates during idle windows. Engrammar already runs extraction and evaluation in the background, but heavier work still competes with active sessions.

Potential engrammar version:

- reserve heavier jobs for maintenance windows
- examples: full dedup scans, long-session synthesis, summary generation, candidate promotion sweeps, benchmark runs

This fits the current daemon model better than adding more work directly to the Stop hook path.

### 5. Distinguish support evidence from query evidence

MetaClaw separates the episodes that caused a skill update from the episodes later used to evaluate it. Engrammar could borrow the same principle without RL:

- transcripts that created or substantially rewrote an engram should not be the main evidence used to prove that engram is generally useful
- promotion should lean more on later reuse than on the originating session

This would strengthen `tasks/open/[2]-012-stage-auto-extracted-engrams/task.md`.

## Probably not worth copying

- online RL / LoRA fine-tuning
- PRM reward modeling
- teacher distillation

Engrammar's leverage is retrieval quality and memory quality, not model weight updates.

## Suggested order

1. Finish candidate/staging and stronger evaluation context
2. Add procedural engram format + progressive disclosure
3. Add session-end synthesis for cross-turn learnings
4. Add engram versioning so post-edit evidence is not polluted by older evaluations
