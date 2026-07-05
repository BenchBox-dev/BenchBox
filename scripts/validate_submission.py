#!/usr/bin/env python3
"""CLI wrapper for public submission bundle validation.

Usage:
    uv run -- python scripts/validate_submission.py results-data/bundles/
    uv run -- python scripts/validate_submission.py path/to/bundle1.json path/to/bundle2.json
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# `uv run --no-project -- python scripts/validate_submission.py` executes with
# scripts/ on sys.path, not the checkout root. Add the root explicitly so the
# mirrored `benchbox.validation` package is importable without installing BenchBox.
CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
if str(CHECKOUT_ROOT) not in sys.path:
    sys.path.insert(0, str(CHECKOUT_ROOT))

try:
    from benchbox.validation.bundle import (
        ValidationResult,
        discover_bundles,
        format_pr_comment,
        format_summary,
        validate_bundles,
    )
except ImportError:
    bundle_path = CHECKOUT_ROOT / "benchbox" / "validation" / "bundle.py"
    spec = importlib.util.spec_from_file_location("_benchbox_validation_bundle", bundle_path)
    if spec is None or spec.loader is None:
        raise
    bundle = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = bundle
    spec.loader.exec_module(bundle)

    ValidationResult = bundle.ValidationResult
    discover_bundles = bundle.discover_bundles
    format_pr_comment = bundle.format_pr_comment
    format_summary = bundle.format_summary
    validate_bundles = bundle.validate_bundles

__all__ = [
    "ValidationResult",
    "discover_bundles",
    "format_pr_comment",
    "format_summary",
    "main",
    "validate_bundles",
]


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    pr_comment_path: Path | None = None
    require_manifest = False
    positional: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--pr-comment" and i + 1 < len(args):
            pr_comment_path = Path(args[i + 1])
            i += 2
            continue
        if args[i] == "--require-manifest":
            require_manifest = True
            i += 1
            continue
        positional.append(args[i])
        i += 1

    if not positional:
        print(
            "Usage: validate_submission.py [--pr-comment <path>] [--require-manifest] <dir-or-files...>",
            file=sys.stderr,
        )
        return 1

    paths: list[Path] = []
    for arg in positional:
        path = Path(arg)
        if path.is_dir():
            paths.extend(discover_bundles(path))
        elif path.is_file():
            paths.append(path)
        else:
            print(f"Warning: {arg} does not exist, skipping", file=sys.stderr)

    if not paths:
        print("No bundle files found.", file=sys.stderr)
        return 1

    results = validate_bundles(paths, require_manifest=require_manifest)
    print(format_summary(results))

    if pr_comment_path is not None:
        try:
            pr_comment_path.write_text(format_pr_comment(results), encoding="utf-8")
        except OSError as exc:
            print(f"Warning: failed to write PR comment file: {exc}", file=sys.stderr)

    return 1 if any(not result.ok for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
