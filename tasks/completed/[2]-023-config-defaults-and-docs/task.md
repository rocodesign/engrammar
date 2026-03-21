# Task: Sync shipped config defaults and document config options

- Priority: Medium
- Complexity: C1
- Status: Completed
- Started: 2026-03-22
- Completed: 2026-03-22

## Problem

The config loader, the shipped `config.json`, and the documentation had drifted apart.

- `config.json` was missing newer sections such as `query_enrichment`
- several supported keys still relied on fallback values in call sites instead of being defined centrally
- there was no dedicated config reference explaining what each option does

That made it hard to tell which defaults were real, what would be deployed, and how to safely customize the config.

## Fix

1. Centralize all supported defaults in `src/core/config.py`
2. Deep-merge nested config overrides so partial nested settings do not wipe sibling defaults
3. Sync the repo `config.json` with the loader defaults
4. Add `docs/CONFIG.md` and link it from the docs index
5. Add tests to keep the shipped config aligned with the loader defaults

## Files

- `src/core/config.py`
- `config.json`
- `docs/CONFIG.md`
- `docs/DOCS.md`
- `tests/test_config.py`
