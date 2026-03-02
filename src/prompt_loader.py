"""Load prompt files from the prompts/ directory, stripping YAML frontmatter."""

import os

# Search order: repo prompts/ during dev, ~/.engrammar/prompts/ when deployed
_PROMPTS_DIRS = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts"),
    os.path.join(os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar")), "prompts"),
]


def load_prompt(relative_path):
    """Load a prompt file from prompts/ dir, stripping YAML frontmatter.

    Args:
        relative_path: path relative to the prompts/ directory, e.g. "extraction/transcript.md"

    Returns:
        str: the prompt body (everything after the YAML frontmatter)

    Raises:
        FileNotFoundError: if prompt file not found in any search location
    """
    for base in _PROMPTS_DIRS:
        full_path = os.path.join(base, relative_path)
        if os.path.exists(full_path):
            with open(full_path, "r") as f:
                content = f.read()
            return _strip_frontmatter(content)

    raise FileNotFoundError(
        f"Prompt file '{relative_path}' not found in: {', '.join(_PROMPTS_DIRS)}"
    )


def _strip_frontmatter(content):
    """Strip YAML frontmatter (--- delimited) from markdown content."""
    if not content.startswith("---"):
        return content

    # Find the closing ---
    end = content.find("\n---", 3)
    if end == -1:
        return content

    # Skip past the closing --- and any leading newline
    body = content[end + 4:]
    return body.lstrip("\n")
