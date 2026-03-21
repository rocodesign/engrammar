"""Cheap pre-filter for low-information queries that should not trigger search.

Catches acknowledgements, interruptions, session-local references, and
other patterns that never produce useful engram matches. Runs before
embedding computation so it's effectively free.
"""

import re

# Patterns that indicate no useful search intent
_ACKNOWLEDGEMENT_PATTERNS = re.compile(
    r"^("
    r"yes[,.]?\s*"
    r"|yeah[,.]?\s*"
    r"|ok[,.]?\s*"
    r"|sure[,.]?\s*"
    r"|right[,.]?\s*"
    r"|exactly[,.]?\s*"
    r"|correct[,.]?\s*"
    r"|agreed[,.]?\s*"
    r"|nice[,.]?\s*"
    r"|cool[,.]?\s*"
    r"|perfect[,.]?\s*"
    r"|thanks[,.]?\s*"
    r"|thank you[,.]?\s*"
    r"|good[,.]?\s*"
    r"|great[,.]?\s*"
    r"|sounds good[,.]?\s*"
    r"|go ahead[,.]?\s*"
    r"|let'?s do (it|that)[,.]?\s*"
    r"|I (agree|allowed it|see)[,.]?\s*"
    r")$",
    re.IGNORECASE,
)

_INTERRUPTION_PATTERNS = re.compile(
    r"^\[Request interrupted",
    re.IGNORECASE,
)

_FILLER_PATTERNS = re.compile(
    r"^("
    r"still running\??"
    r"|what'?s going on\??"
    r"|what happened\??"
    r"|is (it|that) done\??"
    r"|are we done\??"
    r"|anything else\??"
    r"|what do you think\??"
    r"|how about (it|that)\??"
    r"|I (don'?t know|mean)[,.]?\s*$"
    r"|wait[,.]?\s*$"
    r")$",
    re.IGNORECASE,
)

# Short session-local references (e.g., "can we consider 039 done?")
_SESSION_REF_PATTERN = re.compile(
    r"^(can we |let'?s |should we )?(consider|close|mark|finish|move)\s+#?\d+",
    re.IGNORECASE,
)


def is_low_information(query):
    """Check if a query is too low-information to produce useful search results.

    Args:
        query: raw user prompt text

    Returns:
        (should_skip, reason) tuple. should_skip=True means don't search.
    """
    if not query:
        return True, "empty"

    # Strip IDE context tags to check the actual user text
    text = re.sub(r"<[^>]+>.*?</[^>]+>", "", query).strip()
    if not text:
        return True, "only_ide_tags"

    # Very short queries (< 3 words after stripping)
    words = text.split()
    if len(words) <= 2 and len(text) < 15:
        # Allow short but topical queries like "happo CI" or "git hooks"
        if not any(c.isupper() and len(w) > 2 for w in words for c in w[1:]):
            # Check if it's a bare acknowledgement
            if _ACKNOWLEDGEMENT_PATTERNS.match(text):
                return True, "acknowledgement"

    if _INTERRUPTION_PATTERNS.match(text):
        return True, "interruption"

    if _ACKNOWLEDGEMENT_PATTERNS.match(text):
        return True, "acknowledgement"

    if _FILLER_PATTERNS.match(text):
        return True, "filler"

    if _SESSION_REF_PATTERN.match(text):
        return True, "session_ref"

    return False, ""
