#!/usr/bin/env python3
"""Sync and validate repo-local mirrors of shared Claude skills for Codex wrappers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEST_ROOT = REPO_ROOT / ".codex" / "shared-skills"
LOCK_PATH = REPO_ROOT / ".codex" / "shared-skills.lock.json"
WRAPPERS_ROOT = REPO_ROOT / ".codex" / "skills"


@dataclass(frozen=True)
class SyncSource:
    name: str
    src: Path
    dest: str


SOURCES: tuple[SyncSource, ...] = (
    SyncSource(name="global-code", src=Path.home() / ".claude" / "skills" / "code", dest="code"),
    SyncSource(name="global-test", src=Path.home() / ".claude" / "skills" / "test", dest="test"),
    SyncSource(name="global-docs", src=Path.home() / ".claude" / "skills" / "docs", dest="docs"),
    SyncSource(name="global-blog", src=Path.home() / ".claude" / "skills" / "blog", dest="blog"),
    SyncSource(name="global-todo", src=Path.home() / ".claude" / "skills" / "todo", dest="todo"),
    SyncSource(name="global-shared-frameworks", src=Path.home() / ".claude" / "skills" / "SHARED", dest="SHARED"),
    SyncSource(
        name="project-benchbox",
        src=REPO_ROOT / ".claude" / "skills" / "benchbox",
        dest="benchbox",
    ),
)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _list_mirror_files(root: Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    for file_path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = file_path.relative_to(root).as_posix()
        files.append({"path": rel, "sha256": _sha256(file_path)})
    return files


def _git_head(path: Path) -> str | None:
    try:
        output = subprocess.check_output(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return output.strip()


def _copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(
        src,
        dst,
        ignore=shutil.ignore_patterns(".DS_Store", "__pycache__", "*.pyc"),
    )


def sync() -> int:
    if DEST_ROOT.exists():
        shutil.rmtree(DEST_ROOT)
    DEST_ROOT.mkdir(parents=True, exist_ok=True)
    copied_sources: list[dict[str, str | None]] = []

    for source in SOURCES:
        if not source.src.exists():
            print(f"ERROR: missing source path: {source.src}", file=sys.stderr)
            return 1
        dest_path = DEST_ROOT / source.dest
        _copy_tree(source.src, dest_path)
        copied_sources.append(
            {
                "name": source.name,
                "source_path": str(source.src),
                "mirror_path": (Path(".codex/shared-skills") / source.dest).as_posix(),
                "source_git_head": _git_head(source.src),
            }
        )

    lock_payload = {
        "schema_version": 1,
        "generated_at_utc": _utc_now(),
        "mirror_root": ".codex/shared-skills",
        "sources": copied_sources,
        "files": _list_mirror_files(DEST_ROOT),
    }
    LOCK_PATH.write_text(json.dumps(lock_payload, indent=2) + "\n", encoding="utf-8")
    print(f"Synced shared skills to {DEST_ROOT}")
    print(f"Updated lock file {LOCK_PATH}")
    return 0


def _extract_canonical_sources() -> list[tuple[Path, str]]:
    pairs: list[tuple[Path, str]] = []
    pattern = re.compile(r"Canonical source:\s*`([^`]+)`")
    for skill_file in sorted(WRAPPERS_ROOT.glob("*/SKILL.md")):
        for line in skill_file.read_text(encoding="utf-8").splitlines():
            match = pattern.search(line)
            if match:
                pairs.append((skill_file, match.group(1).strip()))
                break
    return pairs


def _check_wrapper_portability() -> list[str]:
    errors: list[str] = []
    for skill_file, source in _extract_canonical_sources():
        if source.startswith("~") or source.startswith("/Users/") or source.startswith("/home/"):
            errors.append(f"{skill_file.relative_to(REPO_ROOT)} uses non-portable canonical source '{source}'")
            continue
        if source.startswith(".codex/") or source.startswith(".claude/"):
            target = REPO_ROOT / source
            if not target.exists():
                errors.append(f"{skill_file.relative_to(REPO_ROOT)} canonical source does not exist: {source}")
    return errors


def _check_lock_integrity() -> list[str]:
    errors: list[str] = []
    if not LOCK_PATH.exists():
        return [f"Missing lock file: {LOCK_PATH.relative_to(REPO_ROOT)}"]
    if not DEST_ROOT.exists():
        return [f"Missing mirror root: {DEST_ROOT.relative_to(REPO_ROOT)}"]

    try:
        lock_payload = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON lock file: {exc}"]

    locked_files = lock_payload.get("files")
    if not isinstance(locked_files, list):
        return ["Lock file missing 'files' array"]

    expected: dict[str, str] = {}
    for entry in locked_files:
        if not isinstance(entry, dict):
            errors.append("Lock file has non-object entry in files")
            continue
        path = entry.get("path")
        digest = entry.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            errors.append(f"Lock file entry missing path/sha256: {entry!r}")
            continue
        expected[path] = digest

    actual = {entry["path"]: entry["sha256"] for entry in _list_mirror_files(DEST_ROOT)}

    expected_only = sorted(set(expected) - set(actual))
    actual_only = sorted(set(actual) - set(expected))
    mismatched = sorted(path for path in set(expected) & set(actual) if expected[path] != actual[path])

    for path in expected_only:
        errors.append(f"Mirror missing file from lock: {path}")
    for path in actual_only:
        errors.append(f"Mirror has untracked file not in lock: {path}")
    for path in mismatched:
        errors.append(f"Checksum mismatch for {path}")

    return errors


def check() -> int:
    errors = []
    errors.extend(_check_wrapper_portability())
    errors.extend(_check_lock_integrity())
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Codex shared-skills portability check passed")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "check"), help="Operation to run")
    args = parser.parse_args()

    if args.command == "sync":
        return sync()
    if args.command == "check":
        return check()
    raise AssertionError(f"Unhandled command: {args.command}")


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    raise SystemExit(main())
