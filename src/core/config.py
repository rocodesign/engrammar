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
    "controls": {
        "global_disabled": False,
        "disabled_repos": [],
        "isolated_repos": [],
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
        "recency_decay_rate": 0.003,
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


def load_user_config():
    """Load the raw user config file without applying defaults."""
    if not os.path.exists(CONFIG_PATH):
        return {}

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        user_config = json.load(f)

    if isinstance(user_config, dict):
        return user_config
    return {}


def save_user_config(config):
    """Persist the raw user config file and invalidate the merged cache."""
    global _config_cache

    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
        f.write("\n")

    _config_cache = None


def set_global_disabled(disabled):
    """Persist the global Engrammar disabled state."""
    user_config = load_user_config()
    controls = user_config.setdefault("controls", {})
    controls["global_disabled"] = bool(disabled)
    save_user_config(user_config)


def set_repo_disabled(repo, disabled):
    """Persist the repo-specific disabled state."""
    if not repo:
        raise ValueError("repo is required")

    user_config = load_user_config()
    controls = user_config.setdefault("controls", {})
    repos = set(controls.get("disabled_repos", []))
    if disabled:
        repos.add(repo)
    else:
        repos.discard(repo)
    controls["disabled_repos"] = sorted(repos)
    save_user_config(user_config)


def set_repo_isolated(repo, isolated):
    """Persist the repo-specific isolation state."""
    if not repo:
        raise ValueError("repo is required")

    user_config = load_user_config()
    controls = user_config.setdefault("controls", {})
    repos = set(controls.get("isolated_repos", []))
    if isolated:
        repos.add(repo)
    else:
        repos.discard(repo)
    controls["isolated_repos"] = sorted(repos)
    save_user_config(user_config)
