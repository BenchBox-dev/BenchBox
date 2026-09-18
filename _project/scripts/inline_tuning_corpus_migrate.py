#!/usr/bin/env python
"""Fold retired tuning companions into their corpus bundles.

The requested tuning and the applied ledger used to ship beside a bundle as
``{stem}.tuning.json`` and ``{stem}.applied.json``. They now live in the
bundle's ``platform.tuning`` block, and nothing writes the companions any more.
Corpus bundles published before that change still carry them, so this moves the
evidence into the bundle, removes the companion files, and re-points the
submission manifest that pins their hashes.

The move is value-preserving and never re-anonymizes: the companions in the
corpus are already public artifacts, and ``inline_tuning_artifacts`` only
relocates fields. Re-running is safe -- a bundle with no companions left is
skipped.

Usage::

    uv run -- python _project/scripts/inline_tuning_corpus_migrate.py [--check]

``--check`` reports what would change and exits non-zero if anything would,
which is what CI needs to prove the corpus is already migrated.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from benchbox.core.results.canonical_json import canonical_json_text  # noqa: E402
from benchbox.core.results.schema import inline_tuning_artifacts  # noqa: E402

CORPUS_ROOT = REPO_ROOT / "results-data" / "bundles"
RETIRED_SUFFIXES = (".tuning.json", ".applied.json")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read {path.name}: {exc}") from exc
    return payload if isinstance(payload, dict) else None


def _primary_bundles(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.json")
        if not path.name.endswith((".manifest.json", ".plans.json", *RETIRED_SUFFIXES))
    )


def migrate_bundle(bundle_path: Path, *, check: bool) -> list[str]:
    """Fold one bundle's companions inline. Returns a list of change descriptions."""
    tuning_path = bundle_path.with_name(f"{bundle_path.stem}.tuning.json")
    applied_path = bundle_path.with_name(f"{bundle_path.stem}.applied.json")
    tuning = _load(tuning_path)
    if tuning is None and tuning_path.is_file():
        raise SystemExit(f"Companion is not a JSON object: {tuning_path.name}")
    applied = _load(applied_path)
    if applied is None and applied_path.is_file():
        raise SystemExit(f"Companion is not a JSON object: {applied_path.name}")
    if tuning is None and applied is None:
        return []

    bundle = _load(bundle_path)
    if bundle is None:
        raise SystemExit(f"Primary bundle is not a JSON object: {bundle_path.name}")

    inline_tuning_artifacts(bundle, tuning, applied)
    changes = [f"{bundle_path.name}: inlined {' + '.join(p.name for p in (tuning_path, applied_path) if p.is_file())}"]

    if check:
        return changes

    bundle_path.write_text(canonical_json_text(bundle), encoding="utf-8")
    for path in (tuning_path, applied_path):
        if path.is_file():
            path.unlink()

    manifest_path = bundle_path.with_name(f"{bundle_path.stem}.manifest.json")
    manifest = _load(manifest_path)
    if manifest is not None:
        # The manifest pins a per-file hash and errors on a declared companion
        # that is not on disk, so the retired entries have to go and the bundle
        # hash has to follow the rewritten content.
        manifest["bundle_hash"] = _sha256(bundle_path)
        companions = manifest.get("companion_hashes")
        if isinstance(companions, dict):
            for suffix in RETIRED_SUFFIXES:
                companions.pop(f"{bundle_path.stem}{suffix}", None)
            manifest["companion_hashes"] = companions
        manifest_path.write_text(canonical_json_text(manifest), encoding="utf-8")
        changes.append(f"{manifest_path.name}: re-pinned bundle hash, dropped retired companion entries")
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report pending changes without writing")
    parser.add_argument("--root", type=Path, default=CORPUS_ROOT, help="corpus bundles directory")
    args = parser.parse_args(argv)

    if not args.root.is_dir():
        print(f"No corpus directory at {args.root}", file=sys.stderr)
        return 2

    changes: list[str] = []
    for bundle_path in _primary_bundles(args.root):
        changes.extend(migrate_bundle(bundle_path, check=args.check))

    if not changes:
        print("Corpus already migrated: no retired tuning companions found.")
        return 0

    for line in changes:
        print(("WOULD CHANGE " if args.check else "CHANGED ") + line)
    print(f"{len(changes)} change(s)")
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
