#!/usr/bin/env python3
"""Automated pg_duckdb vs native DuckDB comparison report.

Compares benchmark results from pg_duckdb and native DuckDB using the
existing PlatformComparison infrastructure. Adds pg_duckdb-specific
overhead annotations: per-query overhead %, geometric mean overhead,
and winner highlights.

Works with pre-existing result files or can orchestrate live runs via
the benchbox CLI.

Exit codes:
  0 - Comparison completed successfully
  1 - Error (missing files, incompatible results, etc.)

Usage:
  # Compare pre-existing result files
  uv run -- python scripts/compare_pg_duckdb.py \\
    --pg-duckdb-results results/pg_duckdb_tpch_sf1.json \\
    --duckdb-results results/duckdb_tpch_sf1.json

  # Orchestrate live runs then compare
  uv run -- python scripts/compare_pg_duckdb.py \\
    --benchmark tpch --scale-factor 1.0

  # Output as JSON
  uv run -- python scripts/compare_pg_duckdb.py \\
    --pg-duckdb-results pg.json --duckdb-results duck.json --format json

  # Dry run (show execution plan)
  uv run -- python scripts/compare_pg_duckdb.py --dry-run --benchmark tpch
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Comparison logic (wraps PlatformComparison)
# ---------------------------------------------------------------------------


def _load_and_compare(pg_duckdb_path: Path, duckdb_path: Path) -> dict:
    """Load two result files and run PlatformComparison.

    Returns a dict with the comparison report and overhead annotations.
    """
    from benchbox.core.analysis.comparison import PlatformComparison

    comparison = PlatformComparison.from_files([str(pg_duckdb_path), str(duckdb_path)])
    report = comparison.compare()

    return _annotate_overhead(report, pg_duckdb_path, duckdb_path)


def _annotate_overhead(report, pg_duckdb_path: Path, duckdb_path: Path) -> dict:
    """Add pg_duckdb-specific overhead annotations to a ComparisonReport.

    Calculates:
    - Per-query overhead % (how much slower pg_duckdb is vs native DuckDB)
    - Geometric mean overhead across all queries
    - Queries where pg_duckdb wins (if any)
    """
    # Find which platform name corresponds to pg_duckdb vs duckdb
    pg_duckdb_name = None
    duckdb_name = None
    for platform in report.platforms:
        lower = platform.lower().replace("_", "").replace("-", "")
        if "pgduckdb" in lower or "pg_duckdb" in platform.lower():
            pg_duckdb_name = platform
        elif lower in ("duckdb",) or (platform.lower().startswith("duckdb") and "pg" not in platform.lower()):
            duckdb_name = platform

    # If we can't identify platforms by name, use file-based heuristic
    if not pg_duckdb_name or not duckdb_name:
        platforms = list(report.platforms)
        if len(platforms) == 2:
            # Assume first file = pg_duckdb, second = duckdb based on arg order
            pg_duckdb_name = platforms[0]
            duckdb_name = platforms[1]
        else:
            return {
                "report": report.to_dict(),
                "error": f"Cannot identify pg_duckdb vs DuckDB among platforms: {platforms}",
            }

    # Calculate per-query overhead
    query_overheads = []
    pg_wins = []
    duckdb_wins = []

    for query_id, qc in report.query_comparisons.items():
        pg_time = qc.metrics.get(pg_duckdb_name, {}).get("median", 0)
        dk_time = qc.metrics.get(duckdb_name, {}).get("median", 0)

        if dk_time > 0 and pg_time > 0:
            overhead_pct = ((pg_time - dk_time) / dk_time) * 100
            ratio = pg_time / dk_time
            query_overheads.append(
                {
                    "query_id": query_id,
                    "pg_duckdb_ms": round(pg_time, 1),
                    "duckdb_ms": round(dk_time, 1),
                    "overhead_pct": round(overhead_pct, 1),
                    "ratio": round(ratio, 3),
                }
            )
            if pg_time < dk_time:
                pg_wins.append(query_id)
            elif dk_time < pg_time:
                duckdb_wins.append(query_id)

    # Geometric mean overhead
    ratios = [q["ratio"] for q in query_overheads if q["ratio"] > 0]
    geomean_overhead = 0.0
    if ratios:
        log_sum = sum(math.log(r) for r in ratios)
        geomean_overhead = math.exp(log_sum / len(ratios))

    return {
        "report": report.to_dict(),
        "overhead_analysis": {
            "pg_duckdb_platform": pg_duckdb_name,
            "duckdb_platform": duckdb_name,
            "geometric_mean_overhead": round(geomean_overhead, 3),
            "geometric_mean_overhead_pct": round((geomean_overhead - 1) * 100, 1),
            "total_queries": len(query_overheads),
            "pg_duckdb_wins": len(pg_wins),
            "duckdb_wins": len(duckdb_wins),
            "ties": len(query_overheads) - len(pg_wins) - len(duckdb_wins),
            "pg_duckdb_winning_queries": sorted(pg_wins),
            "duckdb_winning_queries": sorted(duckdb_wins),
            "per_query": sorted(query_overheads, key=lambda q: q["overhead_pct"], reverse=True),
        },
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def format_table_report(annotated: dict) -> str:
    """Format the annotated comparison as a human-readable table."""
    if "error" in annotated:
        return f"Error: {annotated['error']}"

    oa = annotated["overhead_analysis"]
    lines = [
        "pg_duckdb vs Native DuckDB Comparison Report",
        f"  pg_duckdb platform: {oa['pg_duckdb_platform']}",
        f"  DuckDB platform:    {oa['duckdb_platform']}",
        "",
        f"  Geometric mean overhead: {oa['geometric_mean_overhead']:.3f}x ({oa['geometric_mean_overhead_pct']:+.1f}%)",
        f"  pg_duckdb wins: {oa['pg_duckdb_wins']} | DuckDB wins: {oa['duckdb_wins']} | Ties: {oa['ties']}",
        "",
    ]

    if oa["pg_duckdb_winning_queries"]:
        lines.append(f"  Queries where pg_duckdb is FASTER: {', '.join(oa['pg_duckdb_winning_queries'])}")

    lines.extend(
        [
            "",
            "Per-Query Overhead (sorted by overhead %, highest first):",
            f"  {'Query':<10} {'pg_duckdb':>12} {'DuckDB':>12} {'Overhead':>10} {'Ratio':>8}",
            f"  {'-' * 10} {'-' * 12} {'-' * 12} {'-' * 10} {'-' * 8}",
        ]
    )

    for q in oa["per_query"]:
        overhead_str = f"{q['overhead_pct']:+.1f}%"
        winner = ""
        if q["overhead_pct"] < 0:
            winner = " <<<"  # pg_duckdb wins
        lines.append(
            f"  {q['query_id']:<10} {q['pg_duckdb_ms']:>10.1f}ms {q['duckdb_ms']:>10.1f}ms "
            f"{overhead_str:>10} {q['ratio']:>7.3f}x{winner}"
        )

    # Add insights from PlatformComparison
    report = annotated["report"]
    if report.get("insights"):
        lines.extend(["", "Insights (from PlatformComparison):"])
        for insight in report["insights"][:5]:
            lines.append(f"  - {insight}")

    return "\n".join(lines)


def format_json_report(annotated: dict) -> str:
    """Format the annotated comparison as JSON."""
    return json.dumps(annotated, indent=2, default=str)


# ---------------------------------------------------------------------------
# Live run orchestration
# ---------------------------------------------------------------------------


def _run_benchbox(platform: str, benchmark: str, scale_factor: float) -> Path | None:
    """Run a benchmark via the benchbox CLI and return the result file path."""
    cmd = [
        "uv",
        "run",
        "benchbox",
        "run",
        "--platform",
        platform,
        "--benchmark",
        benchmark,
        "--scale",
        str(scale_factor),
    ]

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        if result.returncode != 0:
            print(f"Error running {platform}: {result.stderr}", file=sys.stderr)
            return None
    except subprocess.TimeoutExpired:
        print(f"Error: {platform} benchmark timed out after 1 hour", file=sys.stderr)
        return None

    # Find the most recent result file for this platform
    results_dir = Path("benchmark_runs/results")
    if not results_dir.exists():
        print(f"Error: results directory not found at {results_dir}", file=sys.stderr)
        return None

    pattern = f"*{platform}*{benchmark}*.json"
    files = sorted(results_dir.glob(pattern), key=lambda f: f.stat().st_mtime, reverse=True)
    if files:
        return files[0]

    # Broader search
    files = sorted(results_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in files[:5]:
        try:
            data = json.loads(f.read_text())
            if data.get("platform", {}).get("name", "").lower().replace("_", "") == platform.replace("_", ""):
                return f
        except (json.JSONDecodeError, KeyError):
            continue

    print(f"Error: Could not find result file for {platform}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare pg_duckdb vs native DuckDB benchmark results.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  # Compare pre-existing result files
  %(prog)s --pg-duckdb-results pg.json --duckdb-results duck.json

  # Orchestrate live runs
  %(prog)s --benchmark tpch --scale-factor 1.0

  # JSON output
  %(prog)s --pg-duckdb-results pg.json --duckdb-results duck.json --format json

  # Dry run
  %(prog)s --dry-run --benchmark tpch
""",
    )
    # Pre-existing result files
    parser.add_argument("--pg-duckdb-results", type=Path, default=None, help="Path to pg_duckdb result JSON file")
    parser.add_argument("--duckdb-results", type=Path, default=None, help="Path to native DuckDB result JSON file")

    # Live run options
    parser.add_argument("--benchmark", default="tpch", help="Benchmark to run (default: tpch)")
    parser.add_argument("--scale-factor", type=float, default=1.0, help="Scale factor for live runs (default: 1.0)")

    # Output options
    parser.add_argument("--format", choices=["table", "json"], default="table", help="Output format (default: table)")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output file (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", help="Show execution plan without running")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.dry_run:
        lines = [
            "pg_duckdb vs DuckDB Comparison - Dry Run",
            f"  Benchmark:    {args.benchmark}",
            f"  Scale factor: {args.scale_factor}",
            "",
            "Execution plan:",
        ]
        if args.pg_duckdb_results and args.duckdb_results:
            lines.append(f"  1. Load pg_duckdb results from {args.pg_duckdb_results}")
            lines.append(f"  2. Load DuckDB results from {args.duckdb_results}")
        else:
            lines.append(f"  1. Run benchbox: platform=pg_duckdb, benchmark={args.benchmark}, SF={args.scale_factor}")
            lines.append(f"  2. Run benchbox: platform=duckdb, benchmark={args.benchmark}, SF={args.scale_factor}")
        lines.extend(
            [
                "  3. Feed both result files to PlatformComparison.from_files()",
                "  4. Compute per-query overhead %, geometric mean overhead",
                "  5. Output comparison report",
            ]
        )
        print("\n".join(lines))
        return 0

    # Determine result file paths
    pg_duckdb_path = args.pg_duckdb_results
    duckdb_path = args.duckdb_results

    if not pg_duckdb_path or not duckdb_path:
        # Need to orchestrate live runs
        if not pg_duckdb_path:
            print("No pg_duckdb result file provided, running live benchmark...", file=sys.stderr)
            pg_duckdb_path = _run_benchbox("pg_duckdb", args.benchmark, args.scale_factor)
            if not pg_duckdb_path:
                return 1

        if not duckdb_path:
            print("No DuckDB result file provided, running live benchmark...", file=sys.stderr)
            duckdb_path = _run_benchbox("duckdb", args.benchmark, args.scale_factor)
            if not duckdb_path:
                return 1

    # Validate files exist
    for path, name in [(pg_duckdb_path, "pg_duckdb"), (duckdb_path, "duckdb")]:
        if not path.exists():
            print(f"Error: {name} result file not found: {path}", file=sys.stderr)
            return 1

    # Run comparison
    try:
        annotated = _load_and_compare(pg_duckdb_path, duckdb_path)
    except Exception as e:
        print(f"Error during comparison: {e}", file=sys.stderr)
        return 1

    # Format output
    if args.format == "json":
        output = format_json_report(annotated)
    else:
        output = format_table_report(annotated)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output)
        print(f"Wrote report to {args.output}", file=sys.stderr)
    else:
        print(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
