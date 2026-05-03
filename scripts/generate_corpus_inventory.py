#!/usr/bin/env python3
"""Generate `results-data/corpus-inventory.json` from schema-v2 bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BUNDLES_DIR = Path("results-data/bundles")
INVENTORY_PATH = Path("results-data/corpus-inventory.json")

SKIP_NAMES = {"corpus-inventory.json", "submission-manifest.json"}
COMPANION_SUFFIXES = (".plans.json", ".tuning.json")
SUBMISSION_MANIFEST = "submission-manifest.json"
SUBMISSION_MANIFEST_SUFFIX = ".manifest.json"
COMMUNITY_TRUST_LABEL = "community-submission"
DEFAULT_TRUST_LABEL = "maintainer-run"


def discover_bundles(bundles_dir: Path) -> list[Path]:
    """Find all primary bundle JSON files."""
    return [
        path
        for path in sorted(bundles_dir.rglob("*.json"))
        if path.name not in SKIP_NAMES
        and not any(path.name.endswith(s) for s in COMPANION_SUFFIXES)
        and not path.name.endswith(SUBMISSION_MANIFEST_SUFFIX)
    ]


def _bundle_hash(bundle_path: Path) -> str:
    """Compute the SHA-256 of a bundle JSON file."""
    return hashlib.sha256(bundle_path.read_bytes()).hexdigest()


def _bundle_trust_label(bundle_path: Path) -> str:
    """Resolve trust label using the established sidecar-presence contract.

    Prefers the per-bundle name (`<stem>.manifest.json`); falls back to the
    legacy singleton (`submission-manifest.json`) so already-merged
    submissions keep their community label.
    """
    per_bundle = bundle_path.parent / f"{bundle_path.stem}{SUBMISSION_MANIFEST_SUFFIX}"
    legacy = bundle_path.parent / SUBMISSION_MANIFEST
    if per_bundle.is_file() or legacy.is_file():
        return COMMUNITY_TRUST_LABEL
    return DEFAULT_TRUST_LABEL


def _query_count(bundle_data: dict) -> int:
    summary = bundle_data.get("summary", {})
    queries = summary.get("queries", {})
    if isinstance(queries, dict) and "total" in queries:
        return int(queries["total"])
    return len(bundle_data.get("queries", []))


def extract_metadata(bundle_path: Path, bundles_dir: Path) -> dict:
    """Extract inventory metadata from a bundle file."""
    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed bundle JSON: {bundle_path}") from exc

    benchmark = data.get("benchmark", {})
    platform = data.get("platform", {})
    run = data.get("run", {})
    rel_path = bundle_path.relative_to(bundles_dir).as_posix()

    return {
        "file": rel_path,
        "benchmark": benchmark.get("id", "unknown"),
        "benchmark_name": benchmark.get("name", benchmark.get("id", "unknown")),
        "platform": platform.get("name", "unknown"),
        "platform_version": platform.get("version", "unknown"),
        "scale_factor": benchmark.get("scale_factor", 0),
        "timestamp": run.get("timestamp"),
        "query_count": _query_count(data),
        "trust_label": _bundle_trust_label(bundle_path),
        "bundle_sha256": _bundle_hash(bundle_path),
    }


def generate_inventory(bundles_dir: Path) -> dict:
    """Generate the full inventory dict."""
    bundle_paths = discover_bundles(bundles_dir)
    entries = [extract_metadata(p, bundles_dir) for p in bundle_paths]

    entries.sort(
        key=lambda e: (
            e["benchmark"],
            e["platform"],
            str(e["scale_factor"]),
            e.get("timestamp") or "",
            e["file"],
        )
    )

    cohorts: dict[str, list[str]] = {}
    cohort_members: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in entries:
        key = (entry["benchmark"], str(entry["scale_factor"]))
        cohort_members[key].add(entry["platform"])

    for (benchmark, scale_factor), platforms in sorted(cohort_members.items()):
        cohorts[f"{benchmark}@sf{scale_factor}"] = sorted(platforms)

    by_benchmark = Counter(entry["benchmark"] for entry in entries)
    by_platform = Counter(entry["platform"] for entry in entries)
    by_trust_label = Counter(entry["trust_label"] for entry in entries)

    return {
        "schema_version": "2.2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bundles": entries,
        "cohorts": cohorts,
        "summary": {
            "total_bundles": len(entries),
            "by_benchmark": dict(sorted(by_benchmark.items())),
            "by_platform": dict(sorted(by_platform.items())),
            "by_trust_label": dict(sorted(by_trust_label.items())),
        },
    }


def _normalized_inventory(inventory: dict) -> dict:
    """Normalize away timestamp-only drift for deterministic comparisons."""
    normalized = dict(inventory)
    normalized.pop("generated_at", None)
    return normalized


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Fail if the on-disk inventory is stale.")
    mode.add_argument("--write", action="store_true", help="Write the regenerated inventory to disk.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    check_mode = args.check

    if not BUNDLES_DIR.is_dir():
        print(f"Error: {BUNDLES_DIR} not found", file=sys.stderr)
        return 1

    inventory = generate_inventory(BUNDLES_DIR)

    if check_mode:
        if not INVENTORY_PATH.exists():
            print("FAIL: corpus-inventory.json does not exist", file=sys.stderr)
            return 1

        existing = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
        if _normalized_inventory(existing) == _normalized_inventory(inventory):
            print(f"OK: corpus-inventory.json is up-to-date ({len(inventory['bundles'])} bundles)")
            return 0

        existing_files = {e["file"] for e in existing.get("bundles", [])}
        new_files = {e["file"] for e in inventory["bundles"]}
        added = sorted(new_files - existing_files)
        removed = sorted(existing_files - new_files)
        if added:
            print(f"Missing from inventory: {added}", file=sys.stderr)
        if removed:
            print(f"Stale in inventory: {removed}", file=sys.stderr)
        print(
            "FAIL: corpus-inventory.json is out of date. Run: uv run -- python scripts/generate_corpus_inventory.py --write",
            file=sys.stderr,
        )
        return 1

    INVENTORY_PATH.write_text(
        json.dumps(inventory, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Generated {INVENTORY_PATH} with {len(inventory['bundles'])} bundles")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
