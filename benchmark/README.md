# Extraction Benchmark

Compares engram extraction quality across models, context window sizes, and prompt variants using real conversation transcripts.

## Setup

Copy some conversation transcripts into the benchmark:

```bash
./benchmark/copy_transcripts.sh          # copies 5 largest transcripts
./benchmark/copy_transcripts.sh 3        # copies 3 largest
./benchmark/copy_transcripts.sh 10 8000  # copies 10 largest, min 8KB
```

This copies `.jsonl` files from `~/.claude/projects/` for the current project and strips `[ENGRAMMAR_V1]` injection blocks so extraction runs on clean input.

## Running with Profiles

Use named profiles from `benchmark/config.json`:

```bash
python3 benchmark/run_extraction.py --profile quick            # 1 transcript, haiku, 2 sizes
python3 benchmark/run_extraction.py --profile compare-models   # haiku vs sonnet
python3 benchmark/run_extraction.py --profile compare-prompts  # v1 vs v2 prompt side-by-side
python3 benchmark/run_extraction.py --profile full             # all combos

# Preview what a profile will run
python3 benchmark/run_extraction.py --profile compare-prompts --dry-run

# Override profile settings with CLI flags
python3 benchmark/run_extraction.py --profile quick --models sonnet
```

## Running with CLI Flags

```bash
# Specific models/sizes
python3 benchmark/run_extraction.py --models haiku sonnet --context-sizes 8000 16000

# Compare prompt variants
python3 benchmark/run_extraction.py --prompts benchmark/prompts/v1-original.md benchmark/prompts/v2-reusable.md

# Single transcript
python3 benchmark/run_extraction.py --transcripts benchmark/transcripts/b6f91235*.jsonl

# Dry run (shows what would run)
python3 benchmark/run_extraction.py --dry-run
```

## Prompt Variants

Store prompt variants in `benchmark/prompts/` for A/B testing:

- `v1-original.md` — baseline prompt (no abstraction guidance)
- `v2-reusable.md` — adds abstraction-level guidance, filters over-specific and architecture-description engrams

The production prompt is at `prompts/extraction/transcript.md`.

## Output

Results go to `benchmark/results/<timestamp>/`:
- Per-run `.json` files with raw extracted engrams
- `summary.json` with all runs
- `report.md` with markdown tables (side-by-side when comparing prompts)

Both `benchmark/results/` and `benchmark/transcripts/` are gitignored (contain personal conversation data).
