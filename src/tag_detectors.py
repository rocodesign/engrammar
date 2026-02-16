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


def detect_tags() -> list[str]:
    """Detect tags from multiple sources.

    Returns:
        Sorted list of unique tags detected from the environment.
    """
    tags = set()
    tags.update(_detect_from_git())
    tags.update(_detect_from_files())
    tags.update(_detect_from_package())
    tags.update(_detect_from_gemfile())
    tags.update(_detect_from_structure())
    return sorted(list(tags))


def _detect_from_git() -> Set[str]:
    """Detect tags from git remote URL."""
    tags = set()

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            timeout=2
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            for pattern, tag in GIT_REMOTE_PATTERNS:
                if pattern.search(url):
                    tags.add(tag)
    except Exception:
        pass

    return tags


def _detect_from_files() -> Set[str]:
    """Detect tags from presence of marker files in current directory."""
    tags = set()

    try:
        for filename, file_tags in FILE_MARKERS.items():
            if os.path.exists(filename):
                tags.update(file_tags)
    except Exception:
        pass

    return tags


def _detect_from_package() -> Set[str]:
    """Detect tags from package.json dependencies."""
    tags = set()

    try:
        if os.path.exists("package.json"):
            with open("package.json", "r") as f:
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


def _detect_from_gemfile() -> Set[str]:
    """Detect tags from Gemfile dependencies."""
    tags = set()

    try:
        if os.path.exists("Gemfile"):
            with open("Gemfile", "r") as f:
                content = f.read()

            # Simple pattern matching for gem declarations
            for gem_name, gem_tags in GEMFILE_DEPENDENCY_TAGS.items():
                if re.search(rf"gem\s+['\"]({gem_name})['\"]", content):
                    tags.update(gem_tags)
    except Exception:
        pass

    return tags


def _detect_from_structure() -> Set[str]:
    """Detect tags from directory structure."""
    tags = set()

    try:
        # Check for specific directories
        for dir_name, dir_tags in DIR_STRUCTURE_PATTERNS.items():
            if os.path.isdir(dir_name.rstrip("/")):
                tags.update(dir_tags)
    except Exception:
        pass

    return tags
