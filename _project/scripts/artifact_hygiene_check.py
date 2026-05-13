"""Fail PRs that commit temporary review evidence as repository source."""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BLOCKED_PREFIXES = (
    "_project/audits/screenshots/",
    "_project/verification-logs/",
)

ALLOWED_PATHS = {
    "_project/verification-logs/README.md",
}

BLOCKED_PROJECT_EXTENSIONS = {
    ".bmp",
    ".db",
    ".docx",
    ".duckdb",
    ".err",
    ".gif",
    ".gz",
    ".jpeg",
    ".jpg",
    ".log",
    ".out",
    ".parquet",
    ".pdf",
    ".png",
    ".pptx",
    ".sqlite",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
    ".zst",
}


@dataclass(frozen=True)
class Finding:
    path: str
    reason: str


def run_git(args: list[str]) -> bytes:
    result = subprocess.run(["git", *args], capture_output=True, check=False)
    if result.returncode != 0:
        sys.stderr.buffer.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def tracked_paths() -> list[str]:
    raw = run_git(["ls-files", "-z"])
    return [path.decode() for path in raw.split(b"\0") if path]


def changed_paths(base_ref: str) -> list[str]:
    raw = run_git(["diff", "--name-status", "-z", "--diff-filter=ACMR", f"{base_ref}...HEAD"])
    fields = [field.decode() for field in raw.split(b"\0") if field]
    paths: list[str] = []
    index = 0
    while index < len(fields):
        status = fields[index]
        index += 1
        if status.startswith(("R", "C")):
            index += 1
        if index >= len(fields):
            break
        paths.append(fields[index])
        index += 1
    return paths


def classify(path: str) -> Finding | None:
    if path in ALLOWED_PATHS:
        return None

    for prefix in BLOCKED_PREFIXES:
        if path.startswith(prefix):
            return Finding(
                path=path,
                reason=f"temporary evidence under `{prefix}` must stay out of git",
            )

    suffix = Path(path).suffix.lower()
    if path.startswith("_project/") and suffix in BLOCKED_PROJECT_EXTENSIONS:
        return Finding(
            path=path,
            reason=f"`_project` {suffix} artifacts are temporary unless explicitly allowlisted",
        )

    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--all-tracked", action="store_true", help="scan every tracked path in HEAD")
    mode.add_argument("--base-ref", help="scan added/copied/modified/renamed paths against this ref")
    args = parser.parse_args()

    paths = tracked_paths() if args.all_tracked else changed_paths(args.base_ref)
    findings = sorted(filter(None, (classify(path) for path in paths)), key=lambda item: item.path)

    if not findings:
        print(f"Artifact hygiene passed ({len(paths)} path(s) checked).")
        return 0

    print("Artifact hygiene failed: temporary evidence is tracked.")
    print()
    for finding in findings[:200]:
        print(f"- {finding.path}: {finding.reason}")
    if len(findings) > 200:
        print(f"- ... {len(findings) - 200} more")
    print()
    print("Commit durable markdown/TODO summaries instead. Keep raw screenshots, logs,")
    print("browser reports, and generated binary evidence in /tmp, CI artifacts, or")
    print("BENCHBOX_OUTPUT_DIR.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
