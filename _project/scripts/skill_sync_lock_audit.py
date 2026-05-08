#!/usr/bin/env python3
"""Audit skill-sync.lock content changes and optional TODO scope alignment.

This is a review helper for skill PRs. Project-local skill mirrors under
``.claude/skills`` are intentionally gitignored, so the tracked diff often shows
only ``skill-sync.lock`` hash changes. This script turns those hashes back into
reviewable skill/file paths and can fail when changed skill files are outside a
source TODO's declared ``scope_limit.only_modify`` entries.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class SkillFileChange:
    """One changed file entry inside skill-sync.lock."""

    path: str
    old_sha: str | None
    new_sha: str | None
    old_size: int | None
    new_size: int | None


def _repo_root() -> Path:
    completed = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        text=True,
        capture_output=True,
    )
    return Path(completed.stdout.strip())


def _read_current_lock(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_git_lock(ref: str, *, repo_root: Path, path: str = "skill-sync.lock") -> dict[str, Any]:
    completed = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return json.loads(completed.stdout)


def diff_skill_files(old: dict[str, Any], new: dict[str, Any]) -> list[SkillFileChange]:
    """Return content hash/size changes by ``<skill>/<file>`` path.

    ``lockedAt`` / ``fetchedAt`` timestamp churn is intentionally ignored; only
    per-file content metadata matters for PR review scope.
    """
    changes: list[SkillFileChange] = []
    old_skills = old.get("skills", {})
    new_skills = new.get("skills", {})
    for skill_name in sorted(set(old_skills) | set(new_skills)):
        old_files = old_skills.get(skill_name, {}).get("files", {}) or {}
        new_files = new_skills.get(skill_name, {}).get("files", {}) or {}
        for rel_file in sorted(set(old_files) | set(new_files)):
            old_meta = old_files.get(rel_file, {}) or {}
            new_meta = new_files.get(rel_file, {}) or {}
            old_pair = (old_meta.get("sha256"), old_meta.get("size"))
            new_pair = (new_meta.get("sha256"), new_meta.get("size"))
            if old_pair == new_pair:
                continue
            changes.append(
                SkillFileChange(
                    path=f"{skill_name}/{rel_file}",
                    old_sha=old_pair[0],
                    new_sha=new_pair[0],
                    old_size=old_pair[1],
                    new_size=new_pair[1],
                )
            )
    return changes


def _skill_directories_from_locks(*locks: dict[str, Any]) -> set[str]:
    directories: set[str] = set()
    for lock in locks:
        skills = lock.get("skills", {}) or {}
        for skill_name, skill in skills.items():
            if not isinstance(skill_name, str):
                continue
            skill_prefix = skill_name.strip("/")
            if not skill_prefix:
                continue
            skill_parts = skill_prefix.split("/")
            for index in range(1, len(skill_parts) + 1):
                directories.add("/".join(skill_parts[:index]) + "/")

            files = skill.get("files", {}) or {}
            for rel_file in files:
                if not isinstance(rel_file, str):
                    continue
                full_parts = [*skill_parts, *rel_file.strip("/").split("/")]
                for index in range(1, len(full_parts)):
                    directories.add("/".join(full_parts[:index]) + "/")
    return directories


def _scope_path_to_skill_pattern(path: str, *, skill_directories: set[str] | None = None) -> str | None:
    """Map a TODO scope path like ``.claude/skills/code/SKILL.md`` to lock paths.

    Returned patterns are simple prefixes. A concrete file path is returned as
    itself; a directory path is returned with a trailing slash.
    """
    normalized = path.strip().strip('"').strip("'").lstrip("./")
    marker = "skills/"
    if marker not in normalized:
        return None
    after = normalized.split(marker, 1)[1]
    if not after:
        return None
    if after.endswith("/"):
        return after.rstrip("/") + "/"
    directory_pattern = after.rstrip("/") + "/"
    if skill_directories is not None and directory_pattern in skill_directories:
        return directory_pattern
    return after


def allowed_patterns_from_todo(todo_path: Path, *, skill_directories: set[str] | None = None) -> list[str]:
    """Extract allowed skill lock paths from a TODO's scope_limit.only_modify."""
    data = yaml.safe_load(todo_path.read_text(encoding="utf-8")) or {}
    scope = data.get("scope_limit", {}) or {}
    only_modify = scope.get("only_modify", []) or []
    patterns: list[str] = []
    for raw_path in only_modify:
        if not isinstance(raw_path, str):
            continue
        pattern = _scope_path_to_skill_pattern(raw_path, skill_directories=skill_directories)
        if pattern is not None:
            patterns.append(pattern)
    return patterns


def _is_allowed(change_path: str, patterns: list[str]) -> bool:
    if not patterns:
        return True
    for pattern in patterns:
        if pattern.endswith("/"):
            if change_path.startswith(pattern):
                return True
        elif change_path == pattern:
            return True
    return False


def _format_change(change: SkillFileChange) -> str:
    old = (change.old_sha or "<missing>")[:12]
    new = (change.new_sha or "<missing>")[:12]
    return f"{change.path}\t{old}:{change.old_size}\t{new}:{change.new_size}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/develop", help="Git ref to compare against (default: origin/develop)")
    parser.add_argument("--lock", default="skill-sync.lock", help="Path to current lock file")
    parser.add_argument("--todo", type=Path, help="TODO YAML whose scope_limit.only_modify gates skill changes")
    parser.add_argument(
        "--check", action="store_true", help="Exit non-zero when changed skill files are outside TODO scope"
    )
    args = parser.parse_args(argv)

    repo_root = _repo_root()
    old_lock = _read_git_lock(args.base, repo_root=repo_root, path=args.lock)
    new_lock = _read_current_lock(repo_root / args.lock)
    changes = diff_skill_files(old_lock, new_lock)

    if not changes:
        print("No skill content hash changes in skill-sync.lock")
        return 0

    skill_directories = _skill_directories_from_locks(old_lock, new_lock)
    patterns = allowed_patterns_from_todo(args.todo, skill_directories=skill_directories) if args.todo else []
    if patterns:
        print("Allowed skill paths from TODO scope:")
        for pattern in patterns:
            print(f"  {pattern}")
        print()

    print("Changed skill files (path\told_sha:size\tnew_sha:size):")
    for change in changes:
        prefix = "OK" if _is_allowed(change.path, patterns) else "OUT-OF-SCOPE"
        print(f"{prefix}\t{_format_change(change)}")

    out_of_scope = [change for change in changes if not _is_allowed(change.path, patterns)]
    if args.check and out_of_scope:
        print("\nOut-of-scope skill-sync.lock content changes detected.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
