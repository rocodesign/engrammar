"""Tag detection algorithms for environment classification."""

import json
import os
import re
import subprocess
from typing import Set

from .tag_patterns import (
    GIT_REMOTE_PATTERNS,
    FILE_MARKERS,
    DIR_STRUCTURE_PATTERNS,
    PACKAGE_DEPENDENCY_TAGS,
    GEMFILE_DEPENDENCY_TAGS,
)


def detect_tags(cwd=None) -> list[str]:
    """Detect tags from multiple sources.

    Args:
        cwd: override working directory for detection

    Returns:
        Sorted list of unique tags detected from the environment.
    """
    tags = set()
    tags.update(_detect_from_git(cwd=cwd))
    tags.update(_detect_from_files(cwd=cwd))
    tags.update(_detect_from_package(cwd=cwd))
    tags.update(_detect_from_gemfile(cwd=cwd))
    tags.update(_detect_from_structure(cwd=cwd))
    return sorted(list(tags))


def _detect_from_git(cwd=None) -> Set[str]:
    """Detect tags from git remote URL, including repo name."""
    tags = set()

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=cwd,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            for pattern, tag in GIT_REMOTE_PATTERNS:
                if pattern.search(url):
                    tags.add(tag)
            # Extract repo name as a tag (e.g. "repo:engrammar")
            repo_match = re.search(r"[/:]([^/]+?)(?:\.git)?$", url)
            if repo_match:
                repo_name = repo_match.group(1).lower()
                if repo_name:
                    tags.add(f"repo:{repo_name}")
    except Exception:
        pass

    return tags


def _resolve(path, cwd=None):
    """Resolve a relative path against cwd override."""
    if cwd:
        return os.path.join(cwd, path)
    return path


def _detect_from_files(cwd=None) -> Set[str]:
    """Detect tags from presence of marker files in current directory."""
    tags = set()

    try:
        for filename, file_tags in FILE_MARKERS.items():
            if os.path.exists(_resolve(filename, cwd)):
                tags.update(file_tags)
    except Exception:
        pass

    return tags


def _detect_from_package(cwd=None) -> Set[str]:
    """Detect tags from package.json dependencies."""
    tags = set()

    try:
        pkg_path = _resolve("package.json", cwd)
        if os.path.exists(pkg_path):
            with open(pkg_path, "r") as f:
                data = json.load(f)

            # Check all dependency sections
            all_deps = {}
            for section in ["dependencies", "devDependencies", "peerDependencies"]:
                all_deps.update(data.get(section, {}))

            # Match against patterns
            for dep_name in all_deps.keys():
                for pattern, dep_tags in PACKAGE_DEPENDENCY_TAGS.items():
                    # Exact match or prefix match for scoped packages
                    if dep_name == pattern or dep_name.startswith(pattern):
                        tags.update(dep_tags)
    except Exception:
        pass

    return tags


def _detect_from_gemfile(cwd=None) -> Set[str]:
    """Detect tags from Gemfile dependencies."""
    tags = set()

    try:
        gem_path = _resolve("Gemfile", cwd)
        if os.path.exists(gem_path):
            with open(gem_path, "r") as f:
                content = f.read()

            # Simple pattern matching for gem declarations
            for gem_name, gem_tags in GEMFILE_DEPENDENCY_TAGS.items():
                if re.search(rf"gem\s+['\"]({gem_name})['\"]", content):
                    tags.update(gem_tags)
    except Exception:
        pass

    return tags


def _detect_from_structure(cwd=None) -> Set[str]:
    """Detect tags from directory structure."""
    tags = set()

    try:
        # Check for specific directories
        for dir_name, dir_tags in DIR_STRUCTURE_PATTERNS.items():
            if os.path.isdir(_resolve(dir_name.rstrip("/"), cwd)):
                tags.update(dir_tags)
    except Exception:
        pass

    return tags
