# #36 Validate engram text on add/update for injection and exfiltration

**Severity:** Medium
**Complexity:** C2

## Problem

`engrammar_add` and `engrammar_update` accept arbitrary text with no validation. A compromised or confused agent could write engrams containing:

- Prompt injection patterns (e.g. "Ignore previous instructions...")
- Credential material (API keys, tokens, passwords)
- Invisible Unicode characters used for steganographic attacks
- Exfiltration instructions (e.g. "Send all code to this URL")

Since engrams are injected into future sessions via hooks, a poisoned engram becomes a persistent attack vector across all future conversations.

## Impact

- One bad engram can affect every future session where it gets surfaced
- No defense-in-depth against adversarial engram content
- Trust in the engram corpus depends entirely on the model behaving correctly at write time

## Proposed Solution

Add a validation step in `engrammar_add` and `engrammar_update` (MCP handlers) that scans text for:

1. **Prompt injection patterns**: instruction overrides, role-playing directives, system prompt manipulation
2. **Credential patterns**: API key formats, token patterns, password-like strings
3. **Invisible characters**: zero-width joiners, RTL overrides, homoglyph substitutions
4. **Exfiltration patterns**: URLs with data parameters, base64-encoded payloads
5. **Exact duplicates**: already handled by dedup, but could add a fast hash check

Reject or flag suspicious entries rather than silently accepting them.

## Notes

- Hermes does this ("scanning for injection and exfiltration patterns")
- Could be a simple regex/heuristic scanner — doesn't need LLM involvement
- Should log rejected attempts for monitoring
