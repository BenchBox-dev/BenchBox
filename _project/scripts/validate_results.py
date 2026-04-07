#!/usr/bin/env python3
"""Validate integrity of benchmark result JSON files.

Usage:
    uv run _project/scripts/validate_results.py <path> [options]

Arguments:
    path         Result file (.json) or directory

Options:
    --json           Machine-readable JSON output
    --verbose        Show all checks including PASSes (default: WARN+FAIL only)
    --fail-on-warn   Exit 1 if any WARNs present (default: only FAILs cause exit 2)
    --benchmark STR  Filter to benchmark (directory mode only)

Exit codes:
    0 = all PASS (or WARN-only without --fail-on-warn)
    1 = warnings present with --fail-on-warn
    2 = one or more FAILures
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from benchbox.core.results.integrity_validator import (
    IntegrityReport,
    validate_directory,
    validate_file,
)


def _print_report(report: IntegrityReport, *, verbose: bool = False) -> None:
    """Print a single report in tabular format."""
    print(f"File: {Path(report.file).name}")
    print(
        f"Benchmark: {report.benchmark_id} | "
        f"Platform: {report.platform} | "
        f"SF: {report.scale_factor} | "
        f"Status: {report.overall_status.value}"
    )
    print()
    print(f"{'CATEGORY':<16} {'CHECK':<30} {'STATUS':<6} MESSAGE")
    for c in report.checks:
        if verbose or c.status.value != "PASS":
            print(f"{c.category.value:<16} {c.name:<30} {c.status.value:<6} {c.message}")
    print()


def _print_aggregate(reports: list[IntegrityReport]) -> None:
    """Print aggregate summary for directory mode."""
    total = len(reports)
    pass_count = sum(1 for r in reports if r.overall_status.value == "PASS")
    warn_count = sum(1 for r in reports if r.overall_status.value == "WARN")
    fail_count = sum(1 for r in reports if r.overall_status.value == "FAIL")
    print("=" * 60)
    print(f"Aggregate: {total} files — {pass_count} PASS, {warn_count} WARN, {fail_count} FAIL")
    print("=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate benchmark result JSON files")
    parser.add_argument("path", help="Result file (.json) or directory")
    parser.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    parser.add_argument("--verbose", action="store_true", help="Show all checks including PASSes")
    parser.add_argument("--fail-on-warn", action="store_true", help="Exit 1 if any WARNs present")
    parser.add_argument("--benchmark", type=str, default=None, help="Filter to benchmark ID")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"Error: {args.path} not found", file=sys.stderr)
        return 2

    if target.is_file():
        reports = [validate_file(target)]
    else:
        reports = validate_directory(target)

    # Filter by benchmark if requested
    if args.benchmark:
        bm = args.benchmark.lower()
        reports = [r for r in reports if bm in r.benchmark_id.lower() or bm in r.platform.lower()]

    if not reports:
        print("No result files found.")
        return 0

    if args.json:
        output = []
        for r in reports:
            output.append(
                {
                    "file": r.file,
                    "benchmark_id": r.benchmark_id,
                    "platform": r.platform,
                    "scale_factor": r.scale_factor,
                    "overall_status": r.overall_status.value,
                    "summary": r.summary,
                    "checks": [
                        {
                            "category": c.category.value,
                            "name": c.name,
                            "status": c.status.value,
                            "message": c.message,
                            "details": c.details,
                        }
                        for c in r.checks
                    ],
                }
            )
        print(json.dumps(output, indent=2))
    else:
        for report in reports:
            _print_report(report, verbose=args.verbose)
        if len(reports) > 1:
            _print_aggregate(reports)

    # Determine exit code
    has_fails = any(r.overall_status.value == "FAIL" for r in reports)
    has_warns = any(r.overall_status.value == "WARN" for r in reports)

    if has_fails:
        return 2
    if has_warns and args.fail_on_warn:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
