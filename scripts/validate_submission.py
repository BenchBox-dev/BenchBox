#!/usr/bin/env python3
"""CLI wrapper for public submission bundle validation.

Usage:
    uv run -- python scripts/validate_submission.py results-data/bundles/
    uv run -- python scripts/validate_submission.py path/to/bundle1.json path/to/bundle2.json
"""

from __future__ import annotations

import importlib.util
import json
import re
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

try:
    from benchbox.core.results.anonymization import find_public_path_leaks
except ImportError:  # pragma: no cover - published-results keeps a slim package mirror.
    _PRIVATE_LOCAL_PATH_RE = re.compile(
        r"(?<![A-Za-z0-9_])(?:"
        r"(?:~|/Users|/home|/root|/private/var|/var/folders|/var/run|/Volumes)/[^\s'\",;)]*"
        r"|[A-Za-z]:\\Users\\[^\s'\",;)]*"
        r")",
        flags=re.IGNORECASE,
    )

    def find_public_path_leaks(value, key_path=()):
        """Slim-branch fallback for the shared public path privacy contract.

        Must stay behaviourally identical to
        ``benchbox.core.results.anonymization.find_public_path_leaks``. This
        copy is the one that actually runs on ``published-results``: the
        slim-branch allowlist in
        ``.github/workflows/sync-results-data-to-published.yml`` mirrors this
        file and ``benchbox/validation/bundle.py`` but not the canonical
        module, so the import above always fails there. A key check added only
        upstream would leave the real public-corpus gate blind to it.
        """
        if isinstance(value, dict):
            leaks = []
            for key, child in value.items():
                # Elide a leaking key in its own report and in every
                # descendant's path; the raw key is itself the private path.
                label = str(key)
                if isinstance(key, str) and _PRIVATE_LOCAL_PATH_RE.search(key):
                    label = "<key>"
                    leaks.append(".".join((*key_path, label)))
                leaks.extend(find_public_path_leaks(child, (*key_path, label)))
            return leaks
        if isinstance(value, (list, tuple)):
            return [
                leak
                for index, child in enumerate(value)
                for leak in find_public_path_leaks(child, (*key_path, str(index)))
            ]
        if isinstance(value, str) and _PRIVATE_LOCAL_PATH_RE.search(value):
            return [".".join(key_path) or "<root>"]
        return []


__all__ = [
    "ValidationResult",
    "discover_bundles",
    "format_pr_comment",
    "format_summary",
    "main",
    "validate_bundles",
]


_PUBLIC_COMPANION_SUFFIXES = (".plans.json", ".tuning.json", ".applied.json", ".manifest.json")


def _public_json_surfaces(bundle_path: Path) -> list[Path]:
    """Return a primary bundle plus its JSON companions for privacy scanning."""
    candidates = [bundle_path]
    try:
        siblings = {path.name.lower(): path for path in bundle_path.parent.iterdir() if path.is_file()}
    except OSError:
        siblings = {}
    for suffix in _PUBLIC_COMPANION_SUFFIXES:
        candidate = siblings.get(f"{bundle_path.stem}{suffix}".lower())
        if candidate is not None:
            candidates.append(candidate)
    legacy_manifest = bundle_path.parent / "submission-manifest.json"
    if legacy_manifest.is_file():
        candidates.append(legacy_manifest)
    return list(dict.fromkeys(candidates))


def _append_public_privacy_errors(paths: list[Path], results: list[ValidationResult]) -> None:
    """Fail closed when any public JSON surface contains a private absolute path."""
    by_path = {Path(result.path): result for result in results}
    for bundle_path in paths:
        result = by_path.get(bundle_path)
        if result is None:
            continue
        for surface in _public_json_surfaces(bundle_path):
            try:
                raw_text = surface.read_text(encoding="utf-8")
            except OSError as exc:
                result.error(f"Cannot read public JSON surface {surface.name}: {exc}")
                continue
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError:
                if surface != bundle_path:
                    result.error(f"Malformed public companion JSON: {surface.name}")
                raw_leaks = sorted(set(find_public_path_leaks(raw_text)))
                if raw_leaks:
                    result.error(f"Public privacy contract rejects private absolute paths in malformed {surface.name}")
                continue
            leaks = sorted(set(find_public_path_leaks(payload)))
            if leaks:
                result.error(
                    f"Public privacy contract rejects private absolute paths in {surface.name} "
                    f"at field(s): {', '.join(leaks)}"
                )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    pr_comment_path: Path | None = None
    require_manifest = False
    allow_partial_validation = False
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
        if args[i] == "--allow-partial-validation":
            # Trusted maintainer mirror only: seed corpus includes partial
            # cohorts. Community CI must not pass this flag.
            allow_partial_validation = True
            i += 1
            continue
        positional.append(args[i])
        i += 1

    if not positional:
        print(
            "Usage: validate_submission.py [--pr-comment <path>] [--require-manifest] "
            "[--allow-partial-validation] <dir-or-files...>",
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

    results = validate_bundles(
        paths,
        require_manifest=require_manifest,
        allow_partial_validation=allow_partial_validation,
    )
    _append_public_privacy_errors(paths, results)
    print(format_summary(results))

    if pr_comment_path is not None:
        try:
            pr_comment_path.write_text(format_pr_comment(results), encoding="utf-8")
        except OSError as exc:
            print(f"Warning: failed to write PR comment file: {exc}", file=sys.stderr)

    return 1 if any(not result.ok for result in results) else 0


if __name__ == "__main__":
    sys.exit(main())
