#!/usr/bin/env python3
"""Verify canonical JoinOrder corpus backfill bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from benchbox.core.data_fetch import load_manifest

EXPECTED_LOGICAL_QUERY_COUNT = 113
EXPECTED_MEASUREMENT_RUNS = 3
EXPECTED_MEASUREMENT_ROWS = EXPECTED_LOGICAL_QUERY_COUNT * EXPECTED_MEASUREMENT_RUNS
DEFAULT_STAGED_DIR = Path("~/Developer/benchmark_runs/submissions/uat_joinorder_canonical_corpus_20260512").expanduser()
DEFAULT_CORPUS_DIR = Path("results-data/bundles")


def _discover_bundles(root: Path) -> list[Path]:
    bundle_root = root / "bundle" if (root / "bundle").is_dir() else root
    return [
        path
        for path in sorted(bundle_root.glob("joinorder_sf1_*.json"))
        if not path.name.endswith(".manifest.json")
        and not path.name.endswith(".plans.json")
        and not path.name.endswith(".tuning.json")
    ]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level JSON value must be an object")
    return data


def _manifest_path(bundle_path: Path, root: Path) -> Path:
    sibling = bundle_path.with_name(f"{bundle_path.stem}.manifest.json")
    if sibling.is_file():
        return sibling
    parent = root.parent if root.name == "bundle" else root
    return parent / f"{bundle_path.stem}.manifest.json"


def _validate_submission_manifest(bundle_path: Path, root: Path, errors: list[str]) -> None:
    manifest_path = _manifest_path(bundle_path, root)
    if not manifest_path.is_file():
        errors.append(f"{bundle_path}: missing manifest sidecar {manifest_path}")
        return
    manifest = _load_json(manifest_path)
    if manifest.get("bundle_file") != bundle_path.name:
        errors.append(f"{manifest_path}: bundle_file does not match {bundle_path.name}")
    expected_hash = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    if manifest.get("bundle_hash") != expected_hash:
        errors.append(f"{manifest_path}: bundle_hash mismatch")


def _failed_query_ids(queries: list[Any]) -> list[str]:
    failed = []
    for query in queries:
        if not isinstance(query, dict):
            failed.append("<non-object>")
            continue
        if str(query.get("status", "")).upper() != "SUCCESS":
            failed.append(str(query.get("id", "<missing-id>")))
    return failed


def _query_ids(queries: list[dict[str, Any]]) -> set[str]:
    return {str(query.get("id", "")) for query in queries if query.get("id")}


def _validate_bundle(bundle_path: Path, root: Path, expected_identity: dict[str, str], errors: list[str]) -> None:
    data = _load_json(bundle_path)
    benchmark = data.get("benchmark")
    if not isinstance(benchmark, dict):
        errors.append(f"{bundle_path}: benchmark block missing or invalid")
        return

    if benchmark.get("id") != "joinorder":
        errors.append(f"{bundle_path}: benchmark.id is {benchmark.get('id')!r}")
    if float(benchmark.get("scale_factor", 0)) != 1.0:
        errors.append(f"{bundle_path}: benchmark.scale_factor is {benchmark.get('scale_factor')!r}")
    for key, expected in expected_identity.items():
        if benchmark.get(key) != expected:
            errors.append(f"{bundle_path}: benchmark.{key} is {benchmark.get(key)!r}, expected {expected!r}")

    queries = data.get("queries")
    if not isinstance(queries, list):
        errors.append(f"{bundle_path}: queries must be a list")
        return
    query_objects = [query for query in queries if isinstance(query, dict)]
    measurements = [query for query in query_objects if query.get("run_type") == "measurement"]
    warmups = [query for query in query_objects if query.get("run_type") == "warmup"]

    summary_queries = data.get("summary", {}).get("queries", {})
    if int(summary_queries.get("total", -1)) != EXPECTED_MEASUREMENT_ROWS:
        errors.append(f"{bundle_path}: summary.queries.total is {summary_queries.get('total')!r}")
    if int(summary_queries.get("passed", -1)) != EXPECTED_MEASUREMENT_ROWS:
        errors.append(f"{bundle_path}: summary.queries.passed is {summary_queries.get('passed')!r}")
    if int(summary_queries.get("failed", -1)) != 0:
        errors.append(f"{bundle_path}: summary.queries.failed is {summary_queries.get('failed')!r}")
    if len(measurements) != EXPECTED_MEASUREMENT_ROWS:
        errors.append(f"{bundle_path}: measurement row count is {len(measurements)}")
    if len(_query_ids(measurements)) != EXPECTED_LOGICAL_QUERY_COUNT:
        errors.append(f"{bundle_path}: measurement query coverage is {len(_query_ids(measurements))}")
    if warmups and len(_query_ids(warmups)) != EXPECTED_LOGICAL_QUERY_COUNT:
        errors.append(f"{bundle_path}: warmup query coverage is {len(_query_ids(warmups))}")
    failed_queries = _failed_query_ids(queries)
    if failed_queries:
        errors.append(f"{bundle_path}: failed/non-success query ids: {', '.join(failed_queries[:10])}")

    _validate_submission_manifest(bundle_path, root, errors)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-dir", type=Path, default=DEFAULT_STAGED_DIR)
    parser.add_argument("--corpus-dir", type=Path, default=DEFAULT_CORPUS_DIR)
    parser.add_argument("--skip-staged", action="store_true")
    parser.add_argument("--skip-corpus", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest = load_manifest("benchbox/core/joinorder/data_manifest.toml")
    expected_identity = {
        "dataset_version": manifest.dataset_version,
        "manifest_hash": manifest.manifest_hash,
        "data_archive_hash": manifest.data_archive_hash,
    }
    roots = []
    if not args.skip_staged:
        roots.append(args.staged_dir.expanduser())
    if not args.skip_corpus:
        roots.append(args.corpus_dir)

    errors: list[str] = []
    checked = 0
    for root in roots:
        if not root.exists():
            errors.append(f"{root}: directory does not exist")
            continue
        bundles = _discover_bundles(root)
        if not bundles:
            errors.append(f"{root}: no canonical joinorder bundles found")
            continue
        bundle_root = root / "bundle" if (root / "bundle").is_dir() else root
        for bundle_path in bundles:
            checked += 1
            _validate_bundle(bundle_path, bundle_root, expected_identity, errors)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"all canonical JoinOrder bundles pass ({checked} checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
