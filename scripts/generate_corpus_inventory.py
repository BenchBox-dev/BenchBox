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

# Canonical provenance vocabulary. Import the one source of truth when the full
# package is available; fall back to inline literals on the slim
# published-results branch (which runs this script without benchbox/). Keep the
# fallback in lockstep with benchbox/core/results/provenance.py.
try:
    from benchbox.core.results.provenance import DEFAULT_FUNDING, FUNDING_SOURCES, SOURCE_TO_TRUST_LABEL
except ImportError:  # pragma: no cover - slim published-results branch.
    FUNDING_SOURCES = ("employer", "personal", "free-trial", "vendor-sponsored", "grant", "unspecified")
    DEFAULT_FUNDING = "unspecified"
    SOURCE_TO_TRUST_LABEL = {
        "internal": "maintainer-run",
        "community": "community-submission",
        "vendor": "vendor-supplied",
    }

DEFAULT_TRUST_LABEL = SOURCE_TO_TRUST_LABEL["internal"]
COMMUNITY_TRUST_LABEL = SOURCE_TO_TRUST_LABEL["community"]
VENDOR_TRUST_LABEL = SOURCE_TO_TRUST_LABEL["vendor"]

# A bundle whose path lives under this directory component is maintainer-curated
# vendor-supplied output (gated by CODEOWNERS on the published-results branch);
# the submission validator enforces that only such bundles may carry the vendor
# result_source. See benchbox/validation/bundle.py::_validate_manifest_provenance.
VENDOR_SUBTREE_COMPONENT = "vendor"


def _normalize_funding(value: object) -> str:
    """Return a known funding value, defaulting unknown/empty to 'unspecified'."""
    token = str(value).strip().lower() if value is not None else ""
    return token if token in FUNDING_SOURCES else DEFAULT_FUNDING


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


def _is_vendor_subtree(bundle_path: Path, bundles_dir: Path) -> bool:
    """True when the bundle lives directly under the top-level ``vendor/`` subtree.

    Anchored to ``<bundles_dir>/vendor/...`` (the first path component under the
    bundles root), NOT any nested directory that merely happens to be named
    ``vendor`` — so the label surface matches a CODEOWNERS prefix of
    ``/results-data/bundles/vendor/``. This is the maintainer-controlled path;
    CODEOWNERS on the submission branch gates who may add to it (that gate is the
    enforced control — the trust label here is derived from the resulting path).
    """
    try:
        rel = bundle_path.relative_to(bundles_dir)
    except ValueError:
        return False
    return len(rel.parts) >= 2 and rel.parts[0] == VENDOR_SUBTREE_COMPONENT


def _bundle_trust_label(bundle_path: Path, bundles_dir: Path) -> str:
    """Resolve trust label from the bundle's location and sidecar presence.

    Precedence:
      1. vendor-supplied — bundle under the maintainer-controlled top-level
         ``vendor/`` subtree (see :func:`_is_vendor_subtree`).
      2. community-submission — a submission-manifest sidecar is present. Prefers
         the per-bundle name (`<stem>.manifest.json`); falls back to the legacy
         singleton (`submission-manifest.json`) so already-merged submissions
         keep their community label.
      3. maintainer-run — the default for maintainer-committed bundles.
    """
    if _is_vendor_subtree(bundle_path, bundles_dir):
        return VENDOR_TRUST_LABEL
    per_bundle = bundle_path.parent / f"{bundle_path.stem}{SUBMISSION_MANIFEST_SUFFIX}"
    legacy = bundle_path.parent / SUBMISSION_MANIFEST
    if per_bundle.is_file() or legacy.is_file():
        return COMMUNITY_TRUST_LABEL
    return DEFAULT_TRUST_LABEL


def _bundle_funding(bundle_path: Path, data: dict) -> str:
    """Resolve the funding value for a bundle.

    Precedence: the submission manifest sidecar's ``funding`` field (already
    resolved against ``--funding`` at submit time - see
    ``benchbox/cli/commands/submit.py``, which prefers the explicit CLI
    override over the bundle's own declared value), then the bundle's own
    ``provenance.funding`` block, then ``unspecified``.
    """
    for name in (f"{bundle_path.stem}{SUBMISSION_MANIFEST_SUFFIX}", SUBMISSION_MANIFEST):
        sidecar = bundle_path.parent / name
        if sidecar.is_file():
            try:
                manifest = json.loads(sidecar.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                break
            if isinstance(manifest, dict) and manifest.get("funding"):
                return _normalize_funding(manifest.get("funding"))
            break

    provenance = data.get("provenance")
    if isinstance(provenance, dict) and provenance.get("funding"):
        return _normalize_funding(provenance.get("funding"))

    return DEFAULT_FUNDING


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
        "trust_label": _bundle_trust_label(bundle_path, bundles_dir),
        "funding": _bundle_funding(bundle_path, data),
        "bundle_sha256": _bundle_hash(bundle_path),
    }


def _is_public_benchmark(benchmark_id: str) -> bool:
    """Return whether a bundle should be included in the public corpus inventory."""
    try:
        from benchbox.core.benchmark_registry import get_benchmark_surface
    except ImportError:
        return True
    return get_benchmark_surface(benchmark_id) == "public"


def generate_inventory(bundles_dir: Path) -> dict:
    """Generate the full inventory dict."""
    bundle_paths = discover_bundles(bundles_dir)
    entries = []
    for path in bundle_paths:
        entry = extract_metadata(path, bundles_dir)
        if _is_public_benchmark(entry["benchmark"]):
            entries.append(entry)

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
    by_funding = Counter(entry["funding"] for entry in entries)

    return {
        "schema_version": "2.3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bundles": entries,
        "cohorts": cohorts,
        "summary": {
            "total_bundles": len(entries),
            "by_benchmark": dict(sorted(by_benchmark.items())),
            "by_platform": dict(sorted(by_platform.items())),
            "by_trust_label": dict(sorted(by_trust_label.items())),
            "by_funding": dict(sorted(by_funding.items())),
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
