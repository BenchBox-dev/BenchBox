#!/usr/bin/env python3
"""Validate the BenchBox results corpus against Phase 1 launch requirements.

Checks that manifest.json exists, all result entries have required fields,
no result has zero queries, no duplicate result IDs, and that each
benchmark×scale cohort has sufficient platform depth.

Usage:
    uv run -- python scripts/validate_corpus.py [OPTIONS]

Exit codes:
    0 - All validations passed
    1 - One or more validations failed
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {"benchmark", "platform", "scale_factor", "result_id", "submitted_at", "query_count"}


def load_manifest(data_dir: Path) -> list[dict] | None:
    """Load and parse manifest.json; return None with an error message on failure."""
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        print(
            f"Error: manifest.json not found in {data_dir}\n"
            "\nData directory not found. Run the static build pipeline first:\n"
            "  uv run -- python scripts/build_read_model.py\n"
            "\nIf results-explorer/public/data/ does not exist yet, generate the\n"
            "seed corpus first:\n"
            "  uv run -- python scripts/generate_seed_corpus.py",
            file=sys.stderr,
        )
        return None

    try:
        with manifest_path.open() as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Error: {manifest_path} contains invalid JSON: {exc}", file=sys.stderr)
        return None

    results = data if isinstance(data, list) else data.get("results", [])
    if not isinstance(results, list):
        print(
            'Error: manifest.json must contain a list of result entries (or {"results": [...]}).',
            file=sys.stderr,
        )
        return None

    return results


def check_required_fields(results: list[dict]) -> list[str]:
    errors: list[str] = []
    for i, entry in enumerate(results):
        missing = REQUIRED_FIELDS - entry.keys()
        if missing:
            rid = entry.get("result_id", f"<entry {i}>")
            errors.append(f"  result_id={rid!r}: missing fields {sorted(missing)}")
    return errors


def check_zero_query_count(results: list[dict]) -> list[str]:
    errors: list[str] = []
    for entry in results:
        if entry.get("query_count", -1) == 0:
            errors.append(f"  result_id={entry.get('result_id')!r}: query_count is 0")
    return errors


def check_duplicate_result_ids(results: list[dict]) -> list[str]:
    counts = Counter(entry.get("result_id") for entry in results if entry.get("result_id") is not None)
    return [f"  result_id={rid!r} appears {count} times" for rid, count in counts.items() if count > 1]


def build_cohorts(results: list[dict]) -> dict[tuple[str, str], set[str]]:
    cohorts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in results:
        benchmark = entry.get("benchmark", "")
        scale_factor = entry.get("scale_factor")
        platform = entry.get("platform", "")
        if benchmark and scale_factor is not None and platform:
            cohorts[(benchmark, str(scale_factor))].add(platform)
    return cohorts


def check_cohort_depth(
    cohorts: dict[tuple[str, str], set[str]],
    min_platforms: int,
) -> list[str]:
    errors: list[str] = []
    for (benchmark, scale), platforms in sorted(cohorts.items()):
        if len(platforms) < min_platforms:
            errors.append(f"  {benchmark} / {scale}: {len(platforms)} platform(s) - need {min_platforms}")
    return errors


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

PASS = "\u2713"
FAIL = "\u2717"


def print_cohort_table(
    cohorts: dict[tuple[str, str], set[str]],
    min_platforms: int,
) -> None:
    print(f"\nCohort Depth Check (min {min_platforms} platforms):")
    for (benchmark, scale), platforms in sorted(cohorts.items()):
        mark = PASS if len(platforms) >= min_platforms else FAIL
        label = f"{benchmark} / {scale}"
        print(f"  {label:<30} {len(platforms)} platforms {mark}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the BenchBox results corpus against Phase 1 launch requirements.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        default="results-explorer/public/data",
        metavar="PATH",
        help="Path to the explorer public data directory [default: results-explorer/public/data]",
    )
    parser.add_argument(
        "--min-platforms",
        type=int,
        default=3,
        metavar="N",
        help="Minimum platforms required per benchmark\u00d7scale cohort [default: 3]",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show per-cohort breakdown",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    # Resolve data dir relative to repo root (script lives in scripts/)
    repo_root = Path(__file__).resolve().parent.parent
    data_dir = Path(args.data_dir)
    if not data_dir.is_absolute():
        data_dir = repo_root / data_dir

    print("BenchBox Corpus Validator")
    print("=========================")
    print(f"Data directory: {args.data_dir}")

    results = load_manifest(data_dir)
    if results is None:
        return 1

    if not results:
        print("Error: manifest.json contains no result entries", file=sys.stderr)
        return 1

    benchmarks = sorted({r.get("benchmark") for r in results if r.get("benchmark")})
    scales = sorted({str(r["scale_factor"]) for r in results if r.get("scale_factor") is not None})
    cohorts = build_cohorts(results)

    print(f"Total results:  {len(results)}")
    print(f"Benchmarks:     {', '.join(benchmarks) or '(none)'}")
    print(f"Scale factors:  {', '.join(scales) or '(none)'}")
    print(f"Cohorts:        {len(cohorts)}")

    all_errors: list[str] = []

    field_errors = check_required_fields(results)
    if field_errors:
        all_errors.append("Required field check FAILED:")
        all_errors.extend(field_errors)

    zero_errors = check_zero_query_count(results)
    if zero_errors:
        all_errors.append("Zero query_count check FAILED:")
        all_errors.extend(zero_errors)

    dupe_errors = check_duplicate_result_ids(results)
    if dupe_errors:
        all_errors.append("Duplicate result_id check FAILED:")
        all_errors.extend(dupe_errors)

    depth_errors = check_cohort_depth(cohorts, args.min_platforms)

    if args.verbose or depth_errors:
        print_cohort_table(cohorts, args.min_platforms)

    if depth_errors:
        all_errors.append(f"Cohort depth check FAILED (need \u2265{args.min_platforms} platforms):")
        all_errors.extend(depth_errors)

    print()
    if all_errors:
        print("Validation: FAILED")
        print()
        for line in all_errors:
            print(line)
        return 1

    print("Validation: PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
