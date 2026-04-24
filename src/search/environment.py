"""Environment detection for filtering engrams by prerequisites."""

import json
import os
import platform
import subprocess

from engrammar.core.config import load_config

from .tag_detectors import detect_tags


def detect_environment(cwd=None):
    """Detect current environment context.

    Args:
        cwd: override working directory (used when daemon detects env for a remote caller)

    Returns dict with:
        os: "darwin" | "linux" | "windows"
        repo: repository name from git remote (e.g. "app-repo")
        cwd: current working directory
        mcp_servers: list of configured MCP server names
        tags: list of detected environment tags
    """
    effective_cwd = cwd or os.getcwd()
    env = {
        "os": platform.system().lower(),
        "repo": _detect_repo(cwd=effective_cwd),
        "cwd": effective_cwd,
        "mcp_servers": _detect_mcp_servers(),
        "tags": detect_tags(cwd=effective_cwd),
    }
    return env


def _detect_repo(cwd=None):
    """Get repository name from git remote origin."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            # Extract repo name from URL
            # "git@github.com:org/repo.git" or "https://github.com/org/repo.git"
            name = url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            return name
    except Exception:
        pass
    return None


def _detect_mcp_servers():
    """Get list of configured MCP server names from Claude config."""
    servers = set()
    # MCP servers live in ~/.claude.json (user-level) and .mcp.json (project-level)
    for path in ["~/.claude.json", ".mcp.json"]:
        try:
            full = os.path.expanduser(path)
            if os.path.exists(full):
                with open(full, "r") as f:
                    data = json.load(f)
                servers.update(data.get("mcpServers", {}).keys())
        except Exception:
            pass
    return list(servers)


def is_global_disabled(config=None):
    """Return whether Engrammar is globally disabled."""
    current_config = config or load_config()
    return bool(current_config.get("controls", {}).get("global_disabled", False))


def is_repo_disabled(repo=None, cwd=None, config=None):
    """Return whether the repo is disabled for Engrammar."""
    current_config = config or load_config()
    current_repo = repo if repo is not None else _detect_repo(cwd=cwd)
    if not current_repo:
        return False
    disabled_repos = current_config.get("controls", {}).get("disabled_repos", [])
    return current_repo in disabled_repos


def is_repo_isolated(repo=None, cwd=None, config=None):
    """Return whether the repo is isolated for Engrammar."""
    current_config = config or load_config()
    current_repo = repo if repo is not None else _detect_repo(cwd=cwd)
    if not current_repo:
        return False
    isolated_repos = current_config.get("controls", {}).get("isolated_repos", [])
    return current_repo in isolated_repos


def is_engrammar_active(cwd=None, config=None):
    """Return whether Engrammar should run in the current scope."""
    current_config = config or load_config()
    if is_global_disabled(current_config):
        return False
    return not is_repo_disabled(cwd=cwd, config=current_config)


def filter_engrams_for_repo_scope(engrams, repo=None, cwd=None, config=None):
    """Filter engrams by current repo isolation boundaries."""
    current_config = config or load_config()
    isolated_repos = set(current_config.get("controls", {}).get("isolated_repos", []))
    if not isolated_repos:
        return list(engrams)

    current_repo = repo if repo is not None else _detect_repo(cwd=cwd)
    if not current_repo:
        return list(engrams)

    if current_repo and current_repo in isolated_repos:
        return [engram for engram in engrams if engram.get("origin_repo") == current_repo]

    return [engram for engram in engrams if engram.get("origin_repo") not in isolated_repos]


def check_structural_prerequisites(prerequisites, env=None):
    """Check only non-tag prerequisites (os, repo, paths, mcp_servers).

    Strips the 'tags' key and delegates to check_prerequisites().
    Used by session start and daemon for pinned engrams where tag filtering
    is handled separately via tag relevance scores.

    Args:
        prerequisites: dict with optional keys: os, mcp_servers, paths, tags
        env: environment dict (auto-detected if None)

    Returns:
        True if all structural prerequisites are met
    """
    if not prerequisites:
        return True

    if isinstance(prerequisites, str):
        try:
            prerequisites = json.loads(prerequisites)
        except (json.JSONDecodeError, TypeError):
            return True

    if not isinstance(prerequisites, dict):
        return True

    # Strip tags — those are handled by tag relevance scoring
    structural = {k: v for k, v in prerequisites.items() if k != "tags"}
    return check_prerequisites(structural, env)


def check_tag_prerequisites(prerequisites, env=None):
    """DEPRECATED: Tags are now content tags in engram_tags table, not hard prerequisites.

    Always returns True. Kept temporarily for callers that haven't been migrated yet.
    """
    return True


def check_prerequisites(prerequisites, env=None):
    """Check if current environment meets engram prerequisites.

    Args:
        prerequisites: dict with optional keys: os, mcp_servers, paths
        env: environment dict (auto-detected if None)

    Returns:
        True if all prerequisites are met (or prerequisites is empty/None)
    """
    if not prerequisites:
        return True

    if isinstance(prerequisites, str):
        try:
            prerequisites = json.loads(prerequisites)
        except (json.JSONDecodeError, TypeError):
            return True

    if not isinstance(prerequisites, dict):
        return True

    if env is None:
        env = detect_environment()

    # Check OS
    req_os = prerequisites.get("os")
    if req_os:
        if isinstance(req_os, str):
            req_os = [req_os]
        if env["os"] not in req_os:
            return False

    # Repo is a soft signal via repo:X content tags, not a hard gate.
    # prerequisites.repos is kept for metadata but no longer blocks retrieval.

    # Check paths (directory prefix match, e.g. "~/work/acme")
    req_paths = prerequisites.get("paths")
    if req_paths:
        if isinstance(req_paths, str):
            req_paths = [req_paths]
        cwd = os.path.realpath(env.get("cwd", ""))
        expanded = [os.path.realpath(os.path.expanduser(p)) for p in req_paths]
        if not any(cwd == p or cwd.startswith(p + os.sep) for p in expanded):
            return False

    # Check MCP servers
    req_mcp = prerequisites.get("mcp_servers")
    if req_mcp:
        if isinstance(req_mcp, str):
            req_mcp = [req_mcp]
        available = set(env.get("mcp_servers", []))
        if not all(s in available for s in req_mcp):
            return False

    # Tags are no longer hard prerequisites — they're content tags in engram_tags table,
    # used only as soft rerank signals. Tag check removed per issue #039.

    return True
