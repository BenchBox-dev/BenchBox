#!/usr/bin/env python3
"""Validate `develop_sha` frontmatter on audit Markdown files."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


class AuditShaError(Exception):
    """Raised when an audit SHA check fails."""


@dataclass(frozen=True)
class Frontmatter:
    """Parsed YAML-frontmatter envelope."""

    start_line: int
    end_line: int
    fields: dict[str, str]


def run_git(args: list[str]) -> str:
    """Run a git command and return stripped stdout."""
    result = subprocess.run(
        ["git", *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        command = " ".join(["git", *args])
        raise AuditShaError(f"{command} failed: {detail}")
    return result.stdout.strip()


def git_ok(args: list[str]) -> bool:
    """Return whether a git command exits successfully."""
    return (
        subprocess.run(
            ["git", *args],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        ).returncode
        == 0
    )


def _strip_scalar(value: str) -> str:
    """Extract a simple YAML scalar value from a frontmatter line."""
    value = value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value.strip()


def parse_frontmatter(path: Path) -> Frontmatter | None:
    """Parse the leading frontmatter block, if present.

    The audit contract only needs a simple `develop_sha: <sha>` scalar, so this
    intentionally avoids full Markdown/YAML linting.
    """
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return None

    end_index: int | None = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = index
            break
    if end_index is None:
        raise AuditShaError(f"{path}: frontmatter starts with --- but has no closing ---")

    fields: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        fields[key.strip()] = _strip_scalar(value)

    return Frontmatter(start_line=0, end_line=end_index, fields=fields)


def validate_audit(path: Path, target_ref: str, require_current: int | None = None) -> tuple[str, int | None]:
    """Validate one audit file and return `(develop_sha, distance)`.

    `distance` is the number of commits between the stamped SHA and the target
    ref when freshness checking is requested; otherwise it is omitted.
    """
    if not path.exists():
        raise AuditShaError(f"{path}: file does not exist")
    if not path.is_file():
        raise AuditShaError(f"{path}: not a regular file")

    frontmatter = parse_frontmatter(path)
    if frontmatter is None:
        raise AuditShaError(f"{path}: missing YAML frontmatter with required develop_sha")

    develop_sha = frontmatter.fields.get("develop_sha", "").strip()
    if not develop_sha:
        raise AuditShaError(f"{path}: missing required develop_sha frontmatter field")
    if not SHA_RE.fullmatch(develop_sha):
        raise AuditShaError(f"{path}: develop_sha must be a full 40-character commit SHA, got {develop_sha!r}")

    if not git_ok(["cat-file", "-e", f"{develop_sha}^{{commit}}"]):
        raise AuditShaError(f"{path}: develop_sha {develop_sha} is not a local commit object")

    try:
        target_sha = run_git(["rev-parse", "--verify", f"{target_ref}^{{commit}}"])
    except AuditShaError as exc:
        raise AuditShaError(f"{path}: target ref {target_ref!r} is not available ({exc})") from exc

    if not git_ok(["merge-base", "--is-ancestor", develop_sha, target_sha]):
        raise AuditShaError(f"{path}: develop_sha {develop_sha} is not reachable from {target_ref} ({target_sha})")

    distance: int | None = None
    if require_current is not None:
        if require_current < 0:
            raise AuditShaError("--require-current must be non-negative")
        distance_text = run_git(["rev-list", "--count", f"{develop_sha}..{target_sha}"])
        distance = int(distance_text)
        if distance > require_current:
            raise AuditShaError(
                f"{path}: develop_sha {develop_sha} is {distance} commits behind {target_ref}; "
                f"allowed distance is {require_current}"
            )

    return develop_sha.lower(), distance


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path, help="Audit Markdown file(s) to validate")
    parser.add_argument(
        "--target-ref",
        default="origin/develop",
        help="Git ref the stamped develop_sha must be reachable from (default: origin/develop)",
    )
    parser.add_argument(
        "--require-current",
        type=int,
        metavar="N",
        help="Require develop_sha to be within N commits of --target-ref",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = build_parser().parse_args(argv)
    try:
        for file_path in args.files:
            develop_sha, distance = validate_audit(file_path, args.target_ref, args.require_current)
            suffix = f" distance={distance}" if distance is not None else ""
            print(f"OK {file_path}: develop_sha={develop_sha} target_ref={args.target_ref}{suffix}")
    except AuditShaError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
