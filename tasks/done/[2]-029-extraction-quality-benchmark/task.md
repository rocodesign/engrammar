# Task: Extraction Quality Benchmark

- Priority: Medium
- Complexity: C2
- Status: Done (superseded by #032, infrastructure built in session 2026-03-23/24)

## Problem

Search has `search_ground_truth.json` with 88 labeled queries and a sweep pipeline that tests 576 configs in 30 seconds. Extraction has no equivalent — we can't measure whether the extraction prompt produces good engrams, misses important ones, or extracts noise.

This means:
- Prompt changes to `prompts/extraction/transcript.md` are untested
- We can't compare haiku vs sonnet extraction quality with data
- The `existing_tags_hint` and `env_tags` variables may or may not help — no measurement
- Content tag quality from extraction is unvalidated

## Proposed approach

### 1. Build extraction ground truth

Create `benchmark/extraction_ground_truth.json` with labeled session transcripts:

```json
{
  "sessions": [
    {
      "session_id": "abc123",
      "transcript_path": "benchmark/fixtures/transcripts/abc123.jsonl",
      "expected_engrams": [
        {
          "text_pattern": "sortable prop expects a comparator function",
          "category_prefix": "development/frontend",
          "required_tags": ["react", "sorting"],
          "note": "user corrected assistant on sortable API"
        }
      ],
      "expected_skip": [
        {
          "description": "task summary about building the dashboard",
          "note": "should NOT be extracted — it's a task instruction"
        }
      ]
    }
  ]
}
```

Source from:
- Sessions that produced high-quality engrams (spot-check merge log for survivors)
- Sessions where extraction produced noise (find engrams with negative eval scores)
- Synthetic transcripts with planted friction patterns

### 2. Build benchmark runner

`benchmark/run_extraction_benchmark.py` that:
- Runs extraction on each ground truth transcript
- Matches extracted engrams against expected patterns (fuzzy text match + category/tag checks)
- Measures:
  - **Precision**: what fraction of extracted engrams match an expected pattern
  - **Recall**: what fraction of expected engrams were extracted
  - **Noise rate**: how many extracted engrams match no expected pattern and no expected_skip
  - **Tag accuracy**: do extracted content_tags match expected tags

### 3. Use for A/B testing

Compare extraction prompt variants:
- Stricter vs looser friction criteria
- With vs without `existing_tags_hint`
- Different `max_chars` chunking strategies
- Haiku vs sonnet (cost/quality tradeoff)

## Bootstrapping: start small

Don't need 88 labeled sessions like search. Start with 5-8 transcripts covering:
- A correction session (user redirects assistant)
- A convention-revealing session (user explains project rules)
- A clean session with no friction (should extract nothing)
- A long multi-topic session (tests chunking)

Even 5 transcripts with 2-3 expected engrams each is enough to catch regressions.

## Relation to other tasks

- **#014** (extraction observability) is about runtime logging — this is about offline quality measurement. Complementary.
- **#012** (stage auto-extracted) could use quality scores from this benchmark to gate extraction output.
- Extraction quality feeds directly into search quality — bad extractions become noise in the search corpus.

## Files

- `benchmark/extraction_ground_truth.json` — new, labeled sessions
- `benchmark/fixtures/transcripts/` — new, transcript fixtures (anonymized excerpts)
- `benchmark/run_extraction_benchmark.py` — new, benchmark runner
