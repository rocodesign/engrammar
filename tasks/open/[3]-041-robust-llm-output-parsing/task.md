# Task: Robust LLM Output Parsing with Fallback Strategies

- Priority: Low
- Complexity: C1
- Status: Open
- Inspired by: MetaClaw progressive JSON parsing — 4 fallback strategies for resilient LLM output handling

## Problem

Engrammar uses Haiku for extraction, evaluation, and dedup. LLM outputs occasionally contain malformed JSON, extra text before/after the JSON block, or partial responses. Currently most of these fail silently (see issue #019), and the pipeline moves on without capturing the result.

## Proposed approach

### Add a shared `parse_llm_json` utility with progressive fallback

```python
def parse_llm_json(raw_output: str, expected_type: type = dict) -> dict | list | None:
    """Parse LLM JSON output with progressive fallback strategies."""
```

Fallback chain:

1. **Direct parse** — `json.loads(raw_output)`
2. **Strip markdown fences** — extract content between ``` markers, then parse
3. **Regex JSON extraction** — find first `{...}` or `[...]` block via regex
4. **Partial/truncated recovery** — attempt to close unclosed braces/brackets and parse

Each strategy logs which fallback was needed (useful for observability, #014).

### Apply to all LLM-dependent pipelines

- `src/pipeline/extractor.py` — extraction output parsing
- `src/pipeline/evaluator.py` — evaluation verdict parsing
- `src/pipeline/dedup.py` — merge decision parsing
- `src/pipeline/evolver.py` (#039) — rewrite candidate parsing

## Why low priority

The current silent-failure path means we lose some results but don't inject garbage. This is a quality-of-life improvement that reduces waste, not a correctness fix.

## Relation to existing work

- `issues/open/[2]-019-errors-silent-fail-open/issue.md` — this makes failures recoverable instead of just visible
- `#014` (extraction pipeline observability) — fallback usage is a useful metric

## Files

- `src/utils/parsing.py` — new shared utility
- `src/pipeline/extractor.py` — adopt shared parser
- `src/pipeline/evaluator.py` — adopt shared parser
- `src/pipeline/dedup.py` — adopt shared parser
