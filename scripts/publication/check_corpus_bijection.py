#!/usr/bin/env python3
"""Enforce a zero-skip corpus path-to-result-id bijection (A4 w2, A9 review follow-ups).

The check is fail-closed:

  * ``--accepted-ref`` gives the authoritative accepted-path set (git ls-tree).
  * ``--bundles-dir`` is an *independent* cross-check: its basenames must be
    symmetric-difference-empty against the accepted ref (not a fallback).
  * ``--artifact`` (a DuckDB / SQLite read model) is compared 1:1 against the
    ``result_id`` recomputed from every accepted bundle. A missing artifact is a
    hard failure whenever one is expected (``--require-artifact`` or an explicit
    ``--artifact`` path).
  * ``--ledger-seed`` supplies the only permitted omissions: ``published_only``
    paths may be absent from the artifact, ``legacy_overlay`` result ids may be
    present without a matching accepted path.

Usage:
  uv run python scripts/publication/check_corpus_bijection.py \
    --accepted-ref origin/published-results \
    --bundles-dir downloaded-corpus/ \
    --artifact assembled-site/results/data/results.duckdb --require-artifact
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORPUS_PREFIX = "results-data/bundles/"
IGNORED_SUFFIXES = (".manifest.json", ".applied.json", ".plans.json", ".tuning.json", ".gitkeep")
_DEFAULT_ARTIFACT = ROOT / "publication/out/site/results/data/results.duckdb"


class BijectionError(RuntimeError):
    """Raised when the corpus bijection cannot be established."""


def _is_primary_bundle(path: str) -> bool:
    return path.endswith(".json") and not any(path.endswith(sfx) for sfx in IGNORED_SUFFIXES)


def accepted_paths_from_ref(ref: str) -> list[str]:
    """Every primary bundle path in the git tree at *ref*."""
    try:
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "--", CORPUS_PREFIX],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise BijectionError(f"git ls-tree failed on ref {ref!r}: {exc.stderr.strip() or exc}") from exc
    paths = sorted(
        p.strip() for p in out.splitlines() if p.strip().startswith(CORPUS_PREFIX) and _is_primary_bundle(p.strip())
    )
    if not paths:
        raise BijectionError(f"accepted ref {ref!r} contains no primary bundles (no vacuous pass)")
    return paths


def bundle_files_in_dir(bundles_dir: Path) -> dict[str, Path]:
    """Map basename -> file path for every primary bundle under *bundles_dir* (recursive)."""
    mapping: dict[str, Path] = {}
    for p in sorted(bundles_dir.rglob("*.json")):
        if not _is_primary_bundle(p.name):
            continue
        if p.name in mapping:
            raise BijectionError(f"duplicate bundle basename in {bundles_dir}: {p.name}")
        mapping[p.name] = p
    return mapping


def load_dispositions(ledger_seed: Path) -> dict[str, str]:
    if not ledger_seed.is_file():
        return {}
    data = json.loads(ledger_seed.read_text(encoding="utf-8"))
    return dict(data.get("dispositions", {}))


def recompute_result_id(bundle_path: Path) -> str:
    from _project.scripts.explorer_pipeline.transformer import BundleTransformer

    return BundleTransformer().result_id_from_bundle(bundle_path)


def read_published_result_ids(artifact_path: Path) -> list[str]:
    """Published ``result_id`` values from a DuckDB or SQLite artifact."""
    try:
        import duckdb

        con = duckdb.connect(str(artifact_path), read_only=True)
        try:
            tables = {t[0] for t in con.execute("SHOW TABLES").fetchall()}
            if "results" in tables:
                return [str(r[0]) for r in con.execute("SELECT result_id FROM results").fetchall()]
        finally:
            con.close()
    except BijectionError:
        raise
    except Exception:
        pass

    try:
        con = sqlite3.connect(str(artifact_path))
        try:
            cur = con.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {t[0] for t in cur.fetchall()}
            if "results" in tables:
                cur.execute("SELECT result_id FROM results")
                return [str(r[0]) for r in cur.fetchall()]
        finally:
            con.close()
    except Exception:
        pass

    raise BijectionError(f"artifact {artifact_path} has no readable 'results' table")


def check_bijection(
    accepted_bundles: list[str],
    published_records: list[str],
    dispositions: dict[str, str] | None = None,
) -> tuple[bool, list[str]]:
    """Pure set-level bijection: every accepted entry appears in the published set.

    An accepted entry may be absent only when it carries an explicit disposition.
    Used both by the artifact stage of :func:`check` and by callers that already
    hold the two identifier sets.
    """
    dispositions = dispositions or {}
    published_set = set(published_records)
    unaccounted = sorted(b for b in set(accepted_bundles) if b not in published_set and b not in dispositions)
    errors: list[str] = []
    if unaccounted:
        errors.append(
            f"Zero-skip bijection violation: {len(unaccounted)} accepted entries omitted "
            f"without an explicit disposition: {unaccounted[:5]}"
        )
    return not errors, errors


def check(
    accepted_ref: str,
    bundles_dir: Path,
    artifact: Path | None,
    ledger_seed: Path,
) -> list[str]:
    errors: list[str] = []
    accepted = accepted_paths_from_ref(accepted_ref)
    accepted_names = {Path(p).name for p in accepted}
    print(f"Accepted ref {accepted_ref}: {len(accepted)} primary bundle(s)")

    # (c) independent cross-check: bundles-dir vs ref, symmetric difference empty.
    dir_map = bundle_files_in_dir(bundles_dir)
    if not dir_map:
        raise BijectionError(f"--bundles-dir {bundles_dir} contains no primary bundles")
    only_ref = sorted(accepted_names - set(dir_map))
    only_dir = sorted(set(dir_map) - accepted_names)
    if only_ref or only_dir:
        errors.append(
            f"bundles-dir vs accepted-ref mismatch: {len(only_ref)} only in ref "
            f"({only_ref[:3]}), {len(only_dir)} only in dir ({only_dir[:3]})"
        )
        return errors

    dispositions = load_dispositions(ledger_seed)

    # Recompute the result_id for every accepted bundle from its published bytes.
    rid_to_path: dict[str, str] = {}
    for path in accepted:
        rid = recompute_result_id(dir_map[Path(path).name])
        if rid in rid_to_path:
            errors.append(f"result_id collision: {rid} <- {rid_to_path[rid]} and {path}")
            continue
        rid_to_path[rid] = path
    if errors:
        return errors

    if artifact is None:
        print("No artifact supplied; path cross-check and result_id derivation passed.")
        return errors
    if not artifact.exists():
        raise BijectionError(f"expected DuckDB artifact not found: {artifact}")

    published = read_published_result_ids(artifact)
    published_set = set(published)
    print(f"Artifact {artifact}: {len(published)} published record(s)")
    if len(published) != len(published_set):
        errors.append(f"artifact contains {len(published) - len(published_set)} duplicate result_id row(s)")

    allowed_missing = {p for p, d in dispositions.items() if d == "published_only"}
    allowed_extra_paths = {p for p, d in dispositions.items() if d == "legacy_overlay"}

    unaccounted_skips = sorted(
        path for rid, path in rid_to_path.items() if rid not in published_set and path not in allowed_missing
    )
    if unaccounted_skips:
        errors.append(
            f"zero-skip violation: {len(unaccounted_skips)} accepted bundle(s) absent from the artifact "
            f"without a published_only disposition: {unaccounted_skips[:5]}"
        )

    accepted_rids = set(rid_to_path)
    unaccounted_extras = sorted(
        rid for rid in published_set if rid not in accepted_rids and rid_to_path.get(rid) not in allowed_extra_paths
    )
    if unaccounted_extras:
        errors.append(
            f"untraceable publication: {len(unaccounted_extras)} artifact result_id(s) with no accepted "
            f"bundle and no legacy_overlay disposition: {unaccounted_extras[:5]}"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check corpus path-to-result-id bijection")
    parser.add_argument("--accepted-ref", default="origin/published-results", help="Git ref for accepted corpus")
    parser.add_argument("--artifact", type=Path, default=None, help="DuckDB/SQLite read model to check 1:1")
    parser.add_argument("--require-artifact", action="store_true", help="Fail if --artifact is absent or unreadable")
    parser.add_argument("--bundles-dir", type=Path, default=ROOT / "results-data/bundles")
    parser.add_argument("--ledger-seed", type=Path, default=ROOT / "publication/ledger-seed.json")
    args = parser.parse_args(argv)

    artifact_expected = args.require_artifact or args.artifact is not None
    artifact = args.artifact if args.artifact is not None else _DEFAULT_ARTIFACT

    try:
        if artifact_expected and not artifact.exists():
            raise BijectionError(f"expected DuckDB artifact not found: {artifact}")
        errors = check(
            accepted_ref=args.accepted_ref,
            bundles_dir=args.bundles_dir,
            artifact=artifact if artifact.exists() else None,
            ledger_seed=args.ledger_seed,
        )
    except BijectionError as exc:
        print(f"❌ Corpus bijection check FAILED: {exc}")
        return 1

    if errors:
        print("❌ Corpus bijection check FAILED:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("✅ Corpus bijection verified: 1:1 match with zero unapproved skips.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
