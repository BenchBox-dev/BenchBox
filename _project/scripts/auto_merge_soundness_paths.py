#!/usr/bin/env python3
"""Shared soundness-path predicate for auto-merge gating."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable

SOUNDNESS_PREFIXES = (
    "benchbox/core/equivalence/",
    "benchbox/core/query_plans/parsers/",
)
_VALIDATION_RE = re.compile(r"^benchbox/core/(?:.+/)?validation\.py$")


def normalize_path(path: str) -> str:
    """Normalize a git path for predicate checks."""
    return path.strip().replace("\\", "/")


def is_soundness_path(path: str) -> bool:
    """Return True when *path* needs review before auto-merge."""
    normalized = normalize_path(path)
    if not normalized:
        return False
    return _VALIDATION_RE.match(normalized) is not None or normalized.startswith(SOUNDNESS_PREFIXES)


def any_soundness_path(paths: Iterable[str]) -> bool:
    """Return True if any path intersects the review-required soundness surface."""
    return any(is_soundness_path(path) for path in paths)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", help="Read newline-delimited paths from stdin.")
    parser.add_argument("--paths-file", help="Read newline-delimited paths from a file.")
    parser.add_argument(
        "--format",
        choices=("plain", "shell", "github-output"),
        default="plain",
        help="Output format. Default prints true/false.",
    )
    return parser.parse_args(argv)


def _read_paths(args: argparse.Namespace) -> list[str]:
    if args.stdin:
        return list(sys.stdin)
    if args.paths_file:
        with open(args.paths_file, encoding="utf-8") as fh:
            return list(fh)
    raise SystemExit("Provide --stdin or --paths-file.")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    result = any_soundness_path(_read_paths(args))
    value = "true" if result else "false"
    if args.format == "github-output":
        print(f"soundness_path={value}")
    elif args.format == "shell":
        print(f"SOUNDNESS_PATH={value}")
    else:
        print(value)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
