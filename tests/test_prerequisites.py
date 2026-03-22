"""Tests for prerequisite checking logic."""

import pytest
from src.search.environment import check_prerequisites


def test_no_prerequisites_always_passes():
    """Engrams without prerequisites should always match."""
    assert check_prerequisites(None, {"os": "darwin", "repo": "test"}) is True
    assert check_prerequisites({}, {"os": "darwin", "repo": "test"}) is True


def test_os_prerequisite():
    """OS prerequisite should match correctly."""
    prereqs = {"os": ["darwin"]}
    assert check_prerequisites(prereqs, {"os": "darwin"}) is True
    assert check_prerequisites(prereqs, {"os": "linux"}) is False


def test_repo_prerequisite_is_soft():
    """Repo prerequisites are no longer a hard gate — repo is a soft signal via content tags.

    prerequisites.repos is kept for metadata but does not block retrieval.
    """
    prereqs = {"repos": ["app-repo"]}

    # Should pass regardless of repo context
    assert check_prerequisites(prereqs, {"repo": "app-repo"}) is True
    assert check_prerequisites(prereqs, {"repo": "other-repo"}) is True
    assert check_prerequisites(prereqs, {"repo": None}) is True
    assert check_prerequisites(prereqs, {}) is True


def test_multiple_repos_soft():
    """Repo prerequisites should always pass (soft signal only)."""
    prereqs = {"repos": ["app-repo", "platform"]}
    assert check_prerequisites(prereqs, {"repo": "app-repo"}) is True
    assert check_prerequisites(prereqs, {"repo": "platform"}) is True
    assert check_prerequisites(prereqs, {"repo": "other"}) is True
    assert check_prerequisites(prereqs, {"repo": None}) is True


def test_mcp_servers_prerequisite():
    """MCP server prerequisites should match correctly."""
    prereqs = {"mcp_servers": ["figma"]}
    assert check_prerequisites(prereqs, {"mcp_servers": ["figma", "engrammar"]}) is True
    assert check_prerequisites(prereqs, {"mcp_servers": ["engrammar"]}) is False
    assert check_prerequisites(prereqs, {"mcp_servers": []}) is False


def test_paths_prerequisite():
    """Path prerequisites should match directory boundaries, not raw prefixes."""
    prereqs = {"paths": ["/Users/test/work/acme"]}
    assert check_prerequisites(prereqs, {"cwd": "/Users/test/work/acme/app-repo"}) is True
    assert check_prerequisites(prereqs, {"cwd": "/Users/test/work/acme"}) is True
    assert check_prerequisites(prereqs, {"cwd": "/Users/test/work/other"}) is False
    # Issue #23: must not match prefix collisions like /work/app vs /work/application
    assert check_prerequisites(prereqs, {"cwd": "/Users/test/work/acme-other"}) is False
    assert check_prerequisites(prereqs, {"cwd": "/Users/test/work/acmeee"}) is False


def test_combined_prerequisites():
    """Multiple prerequisites should all be required (AND logic)."""
    prereqs = {
        "os": ["darwin"],
        "repos": ["app-repo"],
        "mcp_servers": ["figma"]
    }

    env_all_match = {
        "os": "darwin",
        "repo": "app-repo",
        "mcp_servers": ["figma"]
    }
    assert check_prerequisites(prereqs, env_all_match) is True

    # Missing one prerequisite should fail (OS and MCP are still hard gates)
    env_wrong_os = {**env_all_match, "os": "linux"}
    assert check_prerequisites(prereqs, env_wrong_os) is False

    # Repo is a soft signal — no longer blocks
    env_no_repo = {**env_all_match, "repo": None}
    assert check_prerequisites(prereqs, env_no_repo) is True

    env_no_mcp = {**env_all_match, "mcp_servers": []}
    assert check_prerequisites(prereqs, env_no_mcp) is False


def test_json_string_prerequisites():
    """Should handle JSON string prerequisites (for compatibility)."""
    import json
    prereqs_dict = {"repos": ["app-repo"]}
    prereqs_json = json.dumps(prereqs_dict)

    # Repo is soft — both should pass
    assert check_prerequisites(prereqs_json, {"repo": "app-repo"}) is True
    assert check_prerequisites(prereqs_json, {"repo": None}) is True


def test_invalid_prerequisites_format():
    """Invalid prerequisite formats should be treated as no prerequisites."""
    assert check_prerequisites("invalid json", {"repo": "test"}) is True
    assert check_prerequisites(123, {"repo": "test"}) is True
    assert check_prerequisites([], {"repo": "test"}) is True
