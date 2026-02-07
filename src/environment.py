"""Environment detection for filtering lessons by prerequisites."""

import json
import os
import platform
import subprocess


def detect_environment():
    """Detect current environment context.

    Returns dict with:
        os: "darwin" | "linux" | "windows"
        repo: repository name from git remote (e.g. "app-repo")
        cwd: current working directory
        mcp_servers: list of configured MCP server names
        tools: list of available CLI tools
    """
    env = {
        "os": platform.system().lower(),
        "repo": _detect_repo(),
        "cwd": os.getcwd(),
        "mcp_servers": _detect_mcp_servers(),
    }
    return env


def _detect_repo():
    """Get repository name from git remote origin."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=2
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
    """Get list of configured MCP server names from Claude settings."""
    try:
        settings_path = os.path.expanduser("~/.claude/settings.json")
        if os.path.exists(settings_path):
            with open(settings_path, "r") as f:
                settings = json.load(f)
            servers = settings.get("mcpServers", {})
            return list(servers.keys())
    except Exception:
        pass
    return []


def check_prerequisites(prerequisites, env=None):
    """Check if current environment meets lesson prerequisites.

    Args:
        prerequisites: dict with optional keys: os, repo, repos, mcp_servers, requires
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

    # Check repo
    req_repos = prerequisites.get("repos") or prerequisites.get("repo")
    if req_repos:
        if isinstance(req_repos, str):
            req_repos = [req_repos]
        if env["repo"] and env["repo"] not in req_repos:
            return False

    # Check MCP servers
    req_mcp = prerequisites.get("mcp_servers")
    if req_mcp:
        if isinstance(req_mcp, str):
            req_mcp = [req_mcp]
        available = set(env.get("mcp_servers", []))
        if not all(s in available for s in req_mcp):
            return False

    return True
