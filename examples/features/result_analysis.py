#!/usr/bin/env python3

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH


def generate_sample_results():
    print("=" * 70)
    print("GENERATING SAMPLE RESULTS")
    print("=" * 70)
    print()
    print("Creating two benchmark runs for comparison...")
    print("  Run 1: Baseline (small scale factor)")
    print("  Run 2: Recent (same benchmark, simulated variation)")
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/analysis"),
        force_regenerate=False,
    )

    benchmark.generate_data()

    print("Running baseline benchmark...")
    adapter = DuckDBAdapter(database_path=":memory:")
    baseline_results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
        query_subset=["1", "3", "6", "12", "14"],
    )

    baseline_output = Path("./benchmark_runs/features/analysis/baseline")
    baseline_output.mkdir(parents=True, exist_ok=True)
    baseline_file = baseline_output / "results.json"

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(baseline_results.model_dump(), f, indent=2)

    print(f"✓ Baseline saved to {baseline_file}")
    print()

    print("Running recent benchmark...")
    recent_results = adapter.run_benchmark(
        benchmark, test_execution_type="power", query_subset=["1", "3", "6", "12", "14"]
    )

    recent_output = Path("./benchmark_runs/features/analysis/recent")
    recent_output.mkdir(parents=True, exist_ok=True)
    recent_file = recent_output / "results.json"

    with open(recent_file, "w", encoding="utf-8") as f:
        json.dump(recent_results.model_dump(), f, indent=2)

    print(f"✓ Recent saved to {recent_file}")
    print()

    return baseline_file, recent_file


def load_results(result_path: Path) -> dict[str, Any]:
    with open(result_path, encoding="utf-8") as f:
        return json.load(f)


def compare_overall_metrics(baseline: dict[str, Any], recent: dict[str, Any]):
    print("=" * 70)
    print("OVERALL METRICS COMPARISON")
    print("=" * 70)
    print()

    baseline_time = baseline.get("total_execution_time", 0)
    recent_time = recent.get("total_execution_time", 0)

    time_diff = recent_time - baseline_time
    percent_change = (time_diff / baseline_time * 100) if baseline_time > 0 else 0

    print("Total Execution Time:")
    print(f"  Baseline:      {baseline_time:.2f}s")
    print(f"  Recent:        {recent_time:.2f}s")
    print(f"  Difference:    {time_diff:+.2f}s ({percent_change:+.1f}%)")

    if percent_change > 5:
        print(f"  ⚠️  REGRESSION: {percent_change:.1f}% slower")
    elif percent_change < -5:
        print(f"  ✓ IMPROVEMENT: {-percent_change:.1f}% faster")
    else:
        print("  ✓ STABLE: Within 5% tolerance")

    print()

    baseline_queries = baseline.get("total_queries", 0)
    recent_queries = recent.get("total_queries", 0)

    print("Query Count:")
    print(f"  Baseline:      {baseline_queries}")
    print(f"  Recent:        {recent_queries}")

    if baseline_queries != recent_queries:
        print("  ⚠️  Query count mismatch!")

    print()


def compare_query_results(baseline: dict[str, Any], recent: dict[str, Any]):
    print("=" * 70)
    print("QUERY-BY-QUERY COMPARISON")
    print("=" * 70)
    print()

    baseline_queries = {q["query_name"]: q for q in baseline.get("query_results", [])}

    recent_queries = {q["query_name"]: q for q in recent.get("query_results", [])}

    print(f"{'Query':<10} {'Baseline':<12} {'Recent':<12} {'Change':<12} {'Status':<15}")
    print("-" * 70)

    regressions = []
    improvements = []
    stable = []

    for query_name in sorted(baseline_queries.keys()):
        if query_name not in recent_queries:
            print(f"{query_name:<10} {'Present':<12} {'MISSING':<12} {'N/A':<12} {'⚠️  MISSING':<15}")
            continue

        baseline_q = baseline_queries[query_name]
        recent_q = recent_queries[query_name]

        baseline_time = baseline_q.get("execution_time", 0)
        recent_time = recent_q.get("execution_time", 0)

        if baseline_time > 0:
            time_diff = recent_time - baseline_time
            percent_change = (time_diff / baseline_time) * 100

            if percent_change > 10:
                status = "⚠️  REGRESSION"
                regressions.append((query_name, percent_change))
            elif percent_change < -10:
                status = "✓ IMPROVED"
                improvements.append((query_name, -percent_change))
            else:
                status = "✓ STABLE"
                stable.append(query_name)

            print(
                f"{query_name:<10} {baseline_time:>10.3f}s {recent_time:>10.3f}s {percent_change:>+10.1f}% {status:<15}"
            )

    print("-" * 70)
    print()

    total = len(baseline_queries)
    print("Summary:")
    print(f"  Total queries:        {total}")
    print(f"  Regressions (>10%):   {len(regressions)} ({len(regressions) / total * 100:.0f}%)")
    print(f"  Improvements (>10%):  {len(improvements)} ({len(improvements) / total * 100:.0f}%)")
    print(f"  Stable (±10%):        {len(stable)} ({len(stable) / total * 100:.0f}%)")
    print()

    if regressions:
        print("⚠️  Worst Regressions:")
        for query_name, percent in sorted(regressions, key=lambda x: x[1], reverse=True)[:3]:
            print(f"    {query_name}: {percent:+.1f}%")
        print()

    if improvements:
        print("✓ Best Improvements:")
        for query_name, percent in sorted(improvements, key=lambda x: x[1], reverse=True)[:3]:
            print(f"    {query_name}: {percent:.1f}% faster")
        print()

    return regressions, improvements, stable


def detect_regressions(baseline: dict[str, Any], recent: dict[str, Any], threshold: float = 10.0):
    print("=" * 70)
    print(f"REGRESSION DETECTION (Threshold: {threshold}%)")
    print("=" * 70)
    print()

    baseline_time = baseline.get("total_execution_time", 0)
    recent_time = recent.get("total_execution_time", 0)

    if baseline_time == 0:
        print("⚠️  Cannot detect regressions: baseline time is 0")
        return False

    percent_change = ((recent_time - baseline_time) / baseline_time) * 100

    print(f"Overall Performance Change: {percent_change:+.1f}%")

    if percent_change > threshold:
        print(f"❌ REGRESSION DETECTED: {percent_change:.1f}% slower than baseline")
        print(f"   Baseline: {baseline_time:.2f}s")
        print(f"   Recent:   {recent_time:.2f}s")
        print()
        print("Recommended actions:")
        print("  1. Review recent code changes")
        print("  2. Check for environmental factors (resource contention)")
        print("  3. Run again to verify it's not a transient issue")
        print("  4. Analyze query-by-query results to isolate problem")
        print()
        return True
    else:
        print(f"✓ No regression detected (within {threshold}% threshold)")
        print()
        return False


def show_result_format():
    print("=" * 70)
    print("RESULT JSON FORMAT")
    print("=" * 70)
    print()

    print("Result files contain:")
    print("""
{
  "benchmark_name": "tpch",
  "platform": "duckdb",
  "timestamp": "2024-01-15T10:30:00",
  "total_execution_time": 12.45,
  "total_queries": 22,
  "average_query_time": 0.57,
  "query_results": [
    {
      "query_name": "Q1",
      "execution_time": 0.234,
      "status": "success",
      "rows_returned": 4
    },
    ...
  ],
  "configuration": {
    "scale_factor": 1.0,
    "test_execution_type": "power"
  }
}
    """)


def show_analysis_strategies():
    print("=" * 70)
    print("ANALYSIS STRATEGIES")
    print("=" * 70)
    print()

    print("1. CI/CD REGRESSION DETECTION")
    print("   Compare: Current PR vs main branch")
    print("   Threshold: 10-20% overall, 25-50% per-query")
    print("   Action: Fail build if regression detected")
    print()

    print("2. PERFORMANCE TREND ANALYSIS")
    print("   Compare: Multiple runs over time (daily/weekly)")
    print("   Threshold: Look for trends, not single-point changes")
    print("   Action: Alert if consistent degradation over 3+ runs")
    print()

    print("3. PLATFORM COMPARISON")
    print("   Compare: Same benchmark on different platforms")
    print("   Threshold: N/A (absolute comparison)")
    print("   Action: Document relative performance characteristics")
    print()

    print("4. OPTIMIZATION VALIDATION")
    print("   Compare: Before/after optimization")
    print("   Threshold: Look for improvements in target queries")
    print("   Action: Verify optimization achieved desired effect")
    print()

    print("5. SCALE FACTOR ANALYSIS")
    print("   Compare: Same benchmark at different scales")
    print("   Threshold: Check for linear/sub-linear scaling")
    print("   Action: Identify queries that don't scale well")
    print()


def main() -> int:
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: RESULT ANALYSIS")
    print("=" * 70)
    print()
    print("This example shows how to load and compare benchmark results")
    print("to detect regressions and analyze performance changes.")
    print()

    baseline_file, recent_file = generate_sample_results()

    print("=" * 70)
    print("LOADING RESULTS")
    print("=" * 70)
    print()
    print(f"Loading baseline from: {baseline_file}")
    print(f"Loading recent from:   {recent_file}")
    print()

    baseline = load_results(baseline_file)
    recent = load_results(recent_file)

    compare_overall_metrics(baseline, recent)

    compare_query_results(baseline, recent)

    has_regression = detect_regressions(baseline, recent, threshold=10.0)

    show_result_format()

    show_analysis_strategies()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Load benchmark results from JSON files")
    print("  ✓ Compare overall performance metrics")
    print("  ✓ Analyze query-by-query changes")
    print("  ✓ Detect performance regressions")
    print("  ✓ Choose appropriate analysis strategies")
    print()
    print("Next steps:")
    print("  • Integrate with CI/CD:")
    print("    if detect_regressions(baseline, recent, threshold=15):")
    print("        sys.exit(1)  # Fail build")
    print()
    print("  • Track trends over time:")
    print("    results = [load_results(f) for f in result_files]")
    print("    plot_performance_trend(results)")
    print()
    print("  • Compare across platforms:")
    print("    duckdb_results = load_results('duckdb/results.json')")
    print("    clickhouse_results = load_results('clickhouse/results.json')")
    print("    compare_platforms(duckdb_results, clickhouse_results)")
    print()
    print("  • Use with unified_runner.py:")
    print("    python unified_runner.py ... --formats json")
    print("    python result_analysis.py baseline.json recent.json")
    print()

    return 1 if has_regression else 0


if __name__ == "__main__":
    raise SystemExit(main())
