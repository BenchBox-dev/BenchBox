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


CORPUS_RELATIVE_ROOT = "results-data/bundles"
_CORPUS_ROOT_PARTS = ("results-data", "bundles")
_CORPUS_METADATA_SUFFIXES = (".plans.json", ".tuning.json", ".applied.json", ".manifest.json")
_CORPUS_METADATA_FILENAMES = ("corpus-inventory.json", "submission-manifest.json")
# JSON-named files that are NOT corpus data: package/TS manifests and other
# executable or tool surfaces that must not ride into the corpus tree even
# though they end in ``.json``. This is a bounded set of non-data types, not a
# deny-list of executables; every other file is a primary result bundle.
_CORPUS_NON_DATA_JSON = {
    "package.json",
    "package-lock.json",
    "npm-shrinkwrap.json",
    "tsconfig.json",
    "composer.json",
    "composer.lock",
}


def _is_allowed_corpus_data_name(name: str) -> bool:
    """Return whether a corpus leaf name is an explicitly supported data type."""
    lower = name.lower()
    if lower in _CORPUS_METADATA_FILENAMES or lower.endswith(_CORPUS_METADATA_SUFFIXES):
        return True
    if lower.endswith(".json"):
        return lower not in _CORPUS_NON_DATA_JSON
    return False


def corpus_permit_rejections(changed_paths) -> list[str]:
    """Reject any changed corpus path that is not an explicitly allowed data file.

    Positive allowlist (see A2 anti-pattern: never a deny-list of executables).
    A path is allowed only when ALL hold:

      - it is inside ``results-data/bundles/``;
      - it is a plain relative leaf with no traversal (``..``, absolute, empty);
      - every component is a normal directory name (no dot-prefixed hidden
        control dirs such as ``.github``);
      - the final name is a ``.json`` data file (bundle, companion, sidecar
        manifest, or the inventory) - never a workflow, script, package, or
        other executable surface;
      - on disk it is a regular file, not a symlink, and carries no executable
        mode bit.

    Changed paths are read from CI's diff, so this guard runs on the PR's
    changed file set, not just on bundles that happen to be discovered.
    """
    rejections: list[str] = []
    for raw in changed_paths:
        path = Path(raw).as_posix().rstrip("/")
        if not path or path == CORPUS_RELATIVE_ROOT:
            continue
        parts = tuple(part for part in Path(path).parts if part)

        # Hostile input fails closed regardless of where it points: a changed
        # path is never trusted to escape the tree or be absolute.
        if Path(path).is_absolute():
            rejections.append(f"{raw}: absolute paths are not allowed")
            continue
        if any(part == ".." for part in parts):
            rejections.append(f"{raw}: path traversal is not allowed")
            continue

        if parts[: len(_CORPUS_ROOT_PARTS)] != _CORPUS_ROOT_PARTS:
            continue  # not a corpus path - outside this gate's authority

        fail = None
        if not _is_allowed_corpus_data_name(parts[-1]):
            fail = "only supported corpus data files (.json bundles/companions/manifests) are allowed"
        else:
            name = parts[-1].lower()
            if name.startswith(".") or any(comp.startswith(".") for comp in parts[len(_CORPUS_ROOT_PARTS) : -1]):
                fail = "hidden control directories and files are not allowed in the corpus tree"
        if fail:
            rejections.append(f"{raw}: {fail}")
            continue

        real = Path(path)
        try:
            if real.is_symlink():
                rejections.append(f"{raw}: symlinks are not allowed in the corpus tree")
            elif not real.is_file():
                rejections.append(f"{raw}: not a regular file")
            elif executable_mode(real):
                rejections.append(f"{raw}: executable file is not allowed in the corpus tree")
        except OSError as exc:
            rejections.append(f"{raw}: cannot inspect ({exc})")
    return rejections


def executable_mode(path: Path) -> bool:
    """Return True when any owner/group/other execute bit is set.

    Git records executable intent as mode ``100755``. A benign bundle that was
    accidentally committed executable would be surfaced here; legitimate corpus
    data files must be plain ``100644``.
    """
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    return bool(mode & 0o111)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    pr_comment_path: Path | None = None
    corpus_changed_paths_path: Path | None = None
    require_manifest = False
    allow_partial_validation = False
    positional: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--pr-comment" and i + 1 < len(args):
            pr_comment_path = Path(args[i + 1])
            i += 2
            continue
        if args[i] == "--corpus-changed-paths" and i + 1 < len(args):
            corpus_changed_paths_path = Path(args[i + 1])
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

    if not positional and corpus_changed_paths_path is None:
        print(
            "Usage: validate_submission.py [--pr-comment <path>] [--require-manifest] "
            "[--allow-partial-validation] [--corpus-changed-paths <file>] <dir-or-files...>",
            file=sys.stderr,
        )
        return 1

    rejected: list[str] = []
    if corpus_changed_paths_path is not None:
        try:
            changed_paths = [
                line for line in corpus_changed_paths_path.read_text(encoding="utf-8").splitlines() if line.strip()
            ]
        except OSError as exc:
            print(f"Error: cannot read --corpus-changed-paths file: {exc}", file=sys.stderr)
            return 1
        rejected = corpus_permit_rejections(changed_paths)

    paths: list[Path] = []
    for arg in positional:
        path = Path(arg)
        if path.is_dir():
            paths.extend(discover_bundles(path))
        elif path.is_file():
            paths.append(path)
        else:
            print(f"Warning: {arg} does not exist, skipping", file=sys.stderr)

    results: list[ValidationResult] = []
    if paths:
        results = validate_bundles(
            paths,
            require_manifest=require_manifest,
            allow_partial_validation=allow_partial_validation,
        )
        _append_public_privacy_errors(paths, results)
    else:
        print("No bundle files found.", file=sys.stderr)

    failed = bool(rejected) or any(not result.ok for result in results)
    for reason in rejected:
        print(f"ERROR: disallowed corpus path: {reason}")
    print(format_summary(results))

    if pr_comment_path is not None:
        try:
            pr_comment_path.write_text(format_pr_comment(results), encoding="utf-8")
        except OSError as exc:
            print(f"Warning: failed to write PR comment file: {exc}", file=sys.stderr)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
