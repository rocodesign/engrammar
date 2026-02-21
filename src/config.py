"""Settings loader for Engrammar."""

import json
import os

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
DB_PATH = os.path.join(ENGRAMMAR_HOME, "engrams.db")
INDEX_PATH = os.path.join(ENGRAMMAR_HOME, "embeddings.npy")
IDS_PATH = os.path.join(ENGRAMMAR_HOME, "embedding_ids.npy")
TAG_INDEX_PATH = os.path.join(ENGRAMMAR_HOME, "tag_embeddings.npy")
TAG_IDS_PATH = os.path.join(ENGRAMMAR_HOME, "tag_embedding_ids.npy")
CONFIG_PATH = os.path.join(ENGRAMMAR_HOME, "config.json")
LAST_SEARCH_PATH = os.path.join(ENGRAMMAR_HOME, ".last-search.json")

_config_cache = None


def load_config():
    """Load config from config.json, with defaults."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    defaults = {
        "search": {
            "top_k": 3,
        },
        "hooks": {
            "prompt_enabled": True,
            "tool_use_enabled": True,
            "skip_tools": ["Read", "Glob", "Grep", "WebFetch", "WebSearch"],
        },
        "display": {
            "max_engrams_per_prompt": 3,
            "max_engrams_per_tool": 2,
            "show_scores": False,
            "show_categories": True,
        },
    }

    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            user_config = json.load(f)
        # Merge user config over defaults
        for section, values in user_config.items():
            if section in defaults and isinstance(values, dict):
                defaults[section].update(values)
            else:
                defaults[section] = values

    _config_cache = defaults
    return defaults
