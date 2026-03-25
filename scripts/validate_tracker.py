#!/usr/bin/env python3
"""Validate task and issue tracker consistency."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent

INDEX_PATH_RE = re.compile(r"`((?:tasks|issues)/[^`\n]+\.md)`")
RELATED_ISSUE_RE = re.compile(r"Related issue:\s*`([^`\n]+)`")


@dataclass(frozen=True)
class IndexedRef:
    path: str
    section: str | None
    line: int


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _is_placeholder(rel_path: str) -> bool:
    return any(token in rel_path for token in ("[priority]-NNN-slug", "[severity]-NNN-slug"))


def _extract_status(text: str) -> str | None:
    for line in text.splitlines()[:20]:
        if "Status:" in line:
            return line.split("Status:", 1)[1].replace("*", "").strip()
    return None


def _parse_index(rel_path: str, section_map: dict[str, str]) -> list[IndexedRef]:
    refs: list[IndexedRef] = []
    current_section = None

    for line_no, line in enumerate(_read(rel_path).splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("## "):
            current_section = section_map.get(stripped[3:].strip(), current_section)

        for match in INDEX_PATH_RE.finditer(line):
            indexed_path = match.group(1)
            if _is_placeholder(indexed_path):
                continue
            refs.append(IndexedRef(indexed_path, current_section, line_no))

    return refs


def _collect_files(*patterns: str) -> list[str]:
    paths: list[str] = []
    for pattern in patterns:
        paths.extend(str(path.relative_to(ROOT)).replace("\\", "/") for path in ROOT.glob(pattern))
    return sorted(paths)


def _check_index(
    errors: list[str],
    index_rel_path: str,
    refs: list[IndexedRef],
    expected_prefixes: dict[str, str],
    actual_paths: list[str],
) -> None:
    indexed_paths = {ref.path for ref in refs}

    for ref in refs:
        ref_path = ROOT / ref.path
        if not ref_path.exists():
            errors.append(f"{index_rel_path}:{ref.line}: referenced path does not exist: {ref.path}")
            continue

        expected_prefix = expected_prefixes.get(ref.section or "")
        if expected_prefix and not ref.path.startswith(expected_prefix):
            errors.append(
                f"{index_rel_path}:{ref.line}: path {ref.path} is listed under {ref.section!r} "
                f"but does not live under {expected_prefix}"
            )

    for actual_path in actual_paths:
        if actual_path not in indexed_paths:
            errors.append(f"{index_rel_path}: file on disk is missing from index: {actual_path}")


def _check_status(errors: list[str], rel_path: str) -> None:
    text = _read(rel_path)
    status = _extract_status(text)
    lowered = status.lower() if status else None

    if rel_path.startswith("tasks/open/") and lowered and lowered.startswith(("completed", "complete", "done", "resolved", "closed")):
        errors.append(f"{rel_path}: open task has incompatible status header: {status}")
    elif rel_path.startswith("tasks/completed/") and lowered and lowered.startswith("open"):
        errors.append(f"{rel_path}: completed task still says Open")
    elif rel_path.startswith("issues/open/") and lowered and lowered.startswith(("resolved", "closed", "completed", "done")):
        errors.append(f"{rel_path}: open issue has incompatible status header: {status}")
    elif rel_path.startswith("issues/resolved/") and lowered and lowered.startswith("open"):
        errors.append(f"{rel_path}: resolved issue still says Open")

    if "Partially implemented" in text and rel_path.startswith("tasks/open/") and lowered and not lowered.startswith("open"):
        errors.append(f"{rel_path}: partial-progress note requires Status: Open")


def _check_related_issue_paths(errors: list[str], rel_paths: list[str]) -> None:
    for rel_path in rel_paths:
        text = _read(rel_path)
        for match in RELATED_ISSUE_RE.finditer(text):
            issue_path = match.group(1)
            if _is_placeholder(issue_path):
                continue
            if not (ROOT / issue_path).exists():
                errors.append(f"{rel_path}: related issue path does not exist: {issue_path}")


def main() -> int:
    errors: list[str] = []

    task_refs = _parse_index(
        "tasks/tasks.md",
        {
            "Open Tasks": "open",
            "Completed Tasks": "completed",
            "Ideas": "ideas",
        },
    )
    issue_refs = _parse_index(
        "issues/ISSUES.md",
        {
            "Open Issues by Severity": "open",
            "Resolved / Closed": "resolved",
        },
    )

    task_files = _collect_files("tasks/open/*/task.md", "tasks/completed/*/task.md", "tasks/ideas/*.md")
    issue_files = _collect_files("issues/open/*/issue.md", "issues/resolved/*/issue.md")

    _check_index(
        errors,
        "tasks/tasks.md",
        task_refs,
        {
            "open": "tasks/open/",
            "completed": "tasks/completed/",
            "ideas": "tasks/ideas/",
        },
        task_files,
    )
    _check_index(
        errors,
        "issues/ISSUES.md",
        issue_refs,
        {
            "open": "issues/open/",
            "resolved": "issues/resolved/",
        },
        issue_files,
    )

    for rel_path in task_files + issue_files:
        if rel_path.startswith("tasks/ideas/"):
            continue
        _check_status(errors, rel_path)

    _check_related_issue_paths(errors, task_files + issue_files)

    if errors:
        print("Tracker validation failed:")
        for error in sorted(errors):
            print(f"- {error}")
        return 1

    print(
        "Tracker validation passed: "
        f"{len(task_refs)} indexed task refs, {len(issue_refs)} indexed issue refs, "
        f"{len(task_files) + len(issue_files)} tracked files checked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
