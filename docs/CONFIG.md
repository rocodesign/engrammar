# Config Reference

Engrammar loads configuration from `~/.engrammar/config.json`.

- The repo's top-level [`config.json`](/Users/romeocopaciu/work/ai-tools/engrammar/config.json) is the shipped default config.
- [`bash scripts/setup.sh`](/Users/romeocopaciu/work/ai-tools/engrammar/scripts/setup.sh) creates `~/.engrammar/config.json` on first install if it does not already exist.
- [`bash scripts/deploy.sh`](/Users/romeocopaciu/work/ai-tools/engrammar/scripts/deploy.sh) copies the repo `config.json` into `~/.engrammar/config.json`.
- Unspecified keys inherit defaults from [`src/core/config.py`](/Users/romeocopaciu/work/ai-tools/engrammar/src/core/config.py) and nested overrides are merged recursively.

## Full Default Config

```json
{
  "search": {
    "top_k": 3
  },
  "controls": {
    "global_disabled": false,
    "disabled_repos": [],
    "isolated_repos": []
  },
  "hooks": {
    "prompt_enabled": true,
    "tool_use_enabled": true,
    "skip_tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
    "min_score_prompt": 0.5,
    "min_score_tool": 0.4,
    "prerequisites_min_score": 0.3
  },
  "query_enrichment": {
    "prompt": {
      "strip_ide_tags": true,
      "inject_ide_file": false,
      "inject_ide_selection": false,
      "max_query_length": 300
    },
    "pre_tool": {
      "inject_narration": false,
      "narration_max_length": 150
    },
    "post_tool": {
      "inject_narration": true,
      "narration_max_length": 200,
      "inject_tool_context": true
    }
  },
  "scoring": {
    "rrf_floor": 0.015,
    "rrf_ceiling": 0.033,
    "weight_content_tag": 0.25,
    "weight_feedback": 0.2,
    "repo_match_boost": 0.05,
    "repo_mismatch_penalty": -0.08,
    "prompt_tag_top_k": 3,
    "prompt_tag_threshold": 0.6,
    "tag_sim_floor": 0.5,
    "tag_sim_ceiling": 0.8,
    "tag_mismatch_penalty": 0.0,
    "tag_mismatch_threshold": 0.2,
    "abstain_threshold": 0.55,
    "min_top1_score": 0.4
  },
  "models": {
    "extraction": "sonnet",
    "deduplication": "sonnet",
    "evaluation": "haiku"
  },
  "display": {
    "max_engrams_per_prompt": 3,
    "max_engrams_per_tool": 2,
    "show_scores": false,
    "show_categories": true
  }
}
```

## Options

### `search`

- `top_k`: Default number of results returned by `search()` when a caller does not pass `top_k`.

### `hooks`

- `prompt_enabled`: Enables or disables the `UserPromptSubmit` hook entirely.
- `tool_use_enabled`: Enables or disables the `PreToolUse` hook entirely.
- `skip_tools`: Tool names that should bypass `PreToolUse` retrieval.
- `min_score_prompt`: Minimum score a prompt-search result must have before it is injected into the prompt hook output.
- `min_score_tool`: Minimum score a tool-context result must have before it is injected into the tool hook output.
- `prerequisites_min_score`: Minimum score enforced when hook-triggered searches run with structural prerequisites enabled.

### `controls`

- `global_disabled`: Master kill switch for Engrammar. When true, hook injection, extraction, daemon-backed retrieval, and MCP-backed operations all fail closed.
- `disabled_repos`: List of repo names where Engrammar is disabled. These repos do not ingest new engrams, do not receive injected engrams, are skipped by transcript extraction and evaluation queues, and get a repo-local `.mcp.json` override so Engrammar MCP tools stay hidden until re-enabled.
- `isolated_repos`: List of repo names that are isolated. Isolated repos only see engrams stamped with their own repo name, and those engrams are hidden from all other repos.

### `query_enrichment.prompt`

- `strip_ide_tags`: Removes IDE metadata tags from the raw prompt before search.
- `inject_ide_file`: Prepends the currently opened IDE file path snippet to the search query.
- `inject_ide_selection`: Prepends the selected IDE snippet to the search query.
- `max_query_length`: Truncates the enriched prompt query to this many characters.

### `query_enrichment.pre_tool`

- `inject_narration`: Adds the latest assistant narration from the transcript into `PreToolUse` queries.
- `narration_max_length`: Character limit applied to narration injected into `PreToolUse`.

### `query_enrichment.post_tool`

- `inject_narration`: Includes the latest assistant narration when `PostToolUse` builds its search query.
- `narration_max_length`: Character limit applied to narration injected into `PostToolUse`.
- `inject_tool_context`: Appends tool-specific context such as file paths or grep patterns to `PostToolUse` queries.

### `scoring`

- `rrf_floor`: Lower normalization anchor for Reciprocal Rank Fusion scores before later boosts and penalties.
- `rrf_ceiling`: Upper normalization anchor for Reciprocal Rank Fusion scores before later boosts and penalties.
- `weight_content_tag`: Weight applied to prompt-tag versus engram content-tag affinity.
- `weight_feedback`: Weight applied to learned relevance feedback from prior evaluations.
- `repo_match_boost`: Score boost when an engram has previous positive evidence in the current repo.
- `repo_mismatch_penalty`: Score penalty when an engram has repo evidence, but not for the current repo.
- `prompt_tag_top_k`: Maximum number of prompt-derived tags to keep for content-tag scoring.
- `prompt_tag_threshold`: Minimum confidence required for a prompt-derived tag to be kept.
- `tag_sim_floor`: Similarity below this produces no positive content-tag bonus.
- `tag_sim_ceiling`: Similarity at or above this produces the maximum content-tag bonus.
- `tag_mismatch_penalty`: Penalty applied when prompt tags strongly disagree with an engram's content tags.
- `tag_mismatch_threshold`: Similarity threshold below which the mismatch penalty applies.
- `abstain_threshold`: If the best vector match falls below this, the search abstains instead of returning weak results.
- `min_top1_score`: If the best final result scores below this, search returns nothing.

### `models`

- `extraction`: Claude model alias used for transcript extraction.
- `deduplication`: Claude model alias used for deduplication.
- `evaluation`: Claude model alias used for evaluation runs.

### `display`

- `max_engrams_per_prompt`: Maximum number of engrams injected into the prompt hook output.
- `max_engrams_per_tool`: Maximum number of engrams injected into tool-related hook outputs.
- `show_scores`: Reserved display flag in the config schema; currently not read by the formatting code.
- `show_categories`: Shows or hides category labels in injected engram blocks.
