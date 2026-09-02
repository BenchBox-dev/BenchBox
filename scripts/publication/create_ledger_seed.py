#!/usr/bin/env python3
"""Generate a set-preserving corpus seed and disposition ledger from origin/published-results (A9 w1).

Usage:
  uv run python scripts/publication/create_ledger_seed.py --accepted-ref origin/published-results --output publication/ledger-seed.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PREFIX = "results-data/bundles/"
IGNORED_SUFFIXES = (".manifest.json", ".applied.json", ".plans.json", ".tuning.json", ".gitkeep")
SCHEMA_VERSION = 1


def list_accepted_bundles(ref: str, repo_root: Path = ROOT) -> list[str]:
    """List all primary JSON bundle paths in the git tree at *ref*."""
    try:
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", ref, "--", CORPUS_PREFIX],
            cwd=repo_root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as exc:
        print(f"error: git ls-tree failed on ref '{ref}': {exc}", file=sys.stderr)
        return []

    bundles: list[str] = []
    for line in out.splitlines():
        p = line.strip()
        if not p or not p.endswith(".json"):
            continue
        if any(p.endswith(sfx) for sfx in IGNORED_SUFFIXES):
            continue
        bundles.append(p)
    return sorted(bundles)


def classify_dispositions(
    paths: list[str],
    published_only: list[str] | None = None,
    legacy_overlay: list[str] | None = None,
) -> dict[str, str]:
    """Classify each path into a disposition."""
    po_set = set(published_only or [])
    lo_set = set(legacy_overlay or [])
    dispositions: dict[str, str] = {}
    for p in paths:
        if p in lo_set:
            dispositions[p] = "legacy_overlay"
        elif p in po_set:
            dispositions[p] = "published_only"
        else:
            dispositions[p] = "accepted"
    return dispositions


def build_seed(
    ref: str,
    repo_root: Path = ROOT,
    published_only: list[str] | None = None,
    legacy_overlay: list[str] | None = None,
) -> dict:
    """Build the full seed JSON structure."""
    bundles = list_accepted_bundles(ref, repo_root=repo_root)
    if not bundles:
        raise SystemExit("error: accepted corpus is empty (ref or tree has no primary bundles)")

    dispositions = classify_dispositions(bundles, published_only=published_only, legacy_overlay=legacy_overlay)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": ref,
        "bidirectional": False,
        "union": bundles,
        "dispositions": dispositions,
        "count": len(bundles),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate set-preserving corpus seed and disposition ledger.")
    parser.add_argument(
        "--accepted-ref",
        default="origin/published-results",
        help="Git ref for accepted published-results (default: origin/published-results)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "publication" / "ledger-seed.json",
        help="Output path for the seed JSON (default: publication/ledger-seed.json)",
    )
    parser.add_argument(
        "--published-only",
        nargs="*",
        default=[],
        help="Paths to mark as published_only disposition",
    )
    parser.add_argument(
        "--legacy-overlay",
        nargs="*",
        default=[],
        help="Paths to mark as legacy_overlay disposition",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help="Repository root directory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()

    seed = build_seed(
        ref=args.accepted_ref,
        repo_root=repo_root,
        published_only=args.published_only or None,
        legacy_overlay=args.legacy_overlay or None,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    print(f"Seed written to {args.output} ({seed['count']} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
