# #34 Procedural skill engrams — structured workflows, not just facts

**Severity:** High
**Complexity:** C3

## Problem

Engrams currently store flat text — facts, rules, conventions. But some knowledge is procedural: multi-step workflows, reusable scripts, deployment recipes, debugging runbooks. Flat text is a poor fit for these because:

- Steps lose their ordering and structure
- There's no place for pitfalls/gotchas per step
- Verification criteria get mixed in with the procedure
- Reusable scripts/commands can't be attached

## Impact

- Complex workflows must be rediscovered each session
- Agents can't benefit from previously-solved multi-step processes
- No way to store reusable scripts alongside the knowledge about when to use them

## Proposed Solution

Introduce a "procedural" engram type with structured fields:

```
- when_to_use: conditions that trigger this procedure
- steps: ordered list of steps
- pitfalls: common mistakes per step
- verification: how to confirm success
- scripts: optional attached shell/python scripts
```

Design considerations:
- Storage: could be JSON fields in the DB or separate markdown files (like Hermes SKILL.md)
- Retrieval: semantic search on `when_to_use` + step descriptions
- Injection: could be full or summarized depending on token budget (see #37)
- Creation: auto-extracted from transcripts where agent solved multi-step tasks, or manually via MCP tool

Inspired by Hermes Agent's Skills system (agentskills.io standard) but adapted to engrammar's search-and-inject architecture rather than Hermes's slash-command pattern.

## Notes

- This is the biggest architectural addition — needs careful design before implementation
- Consider starting with a minimal version: a `type` field on engrams + structured text format, before building full schema support
- Pairs well with #37 (progressive disclosure) for managing token cost of long procedures
