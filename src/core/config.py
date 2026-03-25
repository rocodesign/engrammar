"""Settings loader for Engrammar."""

from copy import deepcopy
import json
import os

ENGRAMMAR_HOME = os.environ.get("ENGRAMMAR_HOME", os.path.expanduser("~/.engrammar"))
DB_PATH = os.path.join(ENGRAMMAR_HOME, "engrams.db")
INDEX_PATH = os.path.join(ENGRAMMAR_HOME, "embeddings.npy")
IDS_PATH = os.path.join(ENGRAMMAR_HOME, "embedding_ids.npy")
TAG_INDEX_PATH = os.path.join(ENGRAMMAR_HOME, "tag_embeddings.npy")
TAG_IDS_PATH = os.path.join(ENGRAMMAR_HOME, "tag_embedding_ids.npy")
TAG_VOCAB_INDEX_PATH = os.path.join(ENGRAMMAR_HOME, "tag_vocab_embeddings.npy")
TAG_VOCAB_LABELS_PATH = os.path.join(ENGRAMMAR_HOME, "tag_vocab_labels.json")
CONFIG_PATH = os.path.join(ENGRAMMAR_HOME, "config.json")
LAST_SEARCH_PATH = os.path.join(ENGRAMMAR_HOME, ".last-search.json")

_config_cache = None


DEFAULT_CONFIG = {
    "search": {
        "top_k": 3,
    },
    "hooks": {
        "prompt_enabled": True,
        "tool_use_enabled": True,
        "post_tool_enabled": False,
        "skip_tools": [],
        "min_score_prompt": 0.50,
        "min_score_tool": 0.40,
        "prerequisites_min_score": 0.3,
    },
    "query_enrichment": {
        "prompt": {
            "strip_ide_tags": True,
            "inject_ide_file": False,
            "inject_ide_selection": False,
            "max_query_length": 300,
        },
        "pre_tool": {
            "inject_narration": True,
            "narration_max_length": 200,
        },
        "post_tool": {
            "inject_narration": True,
            "narration_max_length": 200,
            "inject_tool_context": True,
        },
    },
    "scoring": {
        "rrf_floor_mult": 1.0,
        "rrf_ceiling_mult": 1.0,
        "weight_content_tag": 0.25,
        "weight_feedback": 0.20,
        "repo_match_boost": 0.05,
        "repo_mismatch_penalty": -0.08,
        "prompt_tag_top_k": 3,
        "prompt_tag_threshold": 0.60,
        "tag_sim_floor": 0.50,
        "tag_sim_ceiling": 0.80,
        "tag_mismatch_penalty": 0.0,
        "tag_mismatch_threshold": 0.20,
        "abstain_threshold": 0.55,
        "min_top1_score": 0.40,
    },
    "models": {
        "extraction": "sonnet",
        "deduplication": "sonnet",
        "evaluation": "haiku",
        "curation": "sonnet",
    },
    "curation": {
        "threshold": 100,
        "batch_size": 20,
    },
    "display": {
        "max_engrams_per_prompt": 3,
        "max_engrams_per_tool": 2,
        "show_scores": False,
        "show_categories": True,
    },
}


def _merge_config(base, overrides):
    """Recursively merge user overrides into defaults."""
    for key, value in overrides.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge_config(base[key], value)
        else:
            base[key] = value
    return base


def load_config():
    """Load config from config.json, with defaults."""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    config = deepcopy(DEFAULT_CONFIG)

    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            user_config = json.load(f)
        if isinstance(user_config, dict):
            _merge_config(config, user_config)

    _config_cache = config
    return config
