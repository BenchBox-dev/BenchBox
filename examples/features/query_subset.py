#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH


def run_full_suite():
    print("=" * 70)
    print("FULL SUITE: All 22 TPC-H Queries")
    print("=" * 70)
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/query_subset/full"),
        force_regenerate=False,
    )

    benchmark.generate_data()
    adapter = DuckDBAdapter(database_path=":memory:")

    print("Running all 22 queries...")
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    print("\n✓ Full Suite Complete")
    print(f"  Queries: {results.total_queries}")
    print(f"  Time: {results.total_execution_time:.2f}s")
    print("  Use case: Standard benchmark reporting")
    print()

    return results.total_execution_time


def run_smoke_test_subset():
    print("=" * 70)
    print("QUERY SUBSET 1: Smoke Test (2 queries)")
    print("=" * 70)
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/query_subset/smoke"),
        force_regenerate=False,
    )

    benchmark.generate_data()
    adapter = DuckDBAdapter(database_path=":memory:")

    smoke_test_queries = ["1", "6"]

    print(f"Running smoke test queries: {', '.join(f'Q{q}' for q in smoke_test_queries)}")
    print("Strategy: Fast, reliable queries for quick validation")
    print()

    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
        query_subset=smoke_test_queries,
    )

    print("\n✓ Smoke Test Complete")
    print(f"  Queries: {results.total_queries}")
    print(f"  Time: {results.total_execution_time:.2f}s")
    print("  Use case: CI/CD quick validation (< 10 seconds)")
    print()

    return results.total_execution_time


def run_representative_subset():
    print("=" * 70)
    print("QUERY SUBSET 2: Representative Sample (5 queries)")
    print("=" * 70)
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/query_subset/representative"),
        force_regenerate=False,
    )

    benchmark.generate_data()
    adapter = DuckDBAdapter(database_path=":memory:")

    representative_queries = ["1", "3", "6", "12", "14"]

    print(f"Running queries: {', '.join(f'Q{q}' for q in representative_queries)}")
    print("Strategy: Cover different query patterns")
    print("  Q1:  Simple aggregation")
    print("  Q3:  3-table join with GroupBy")
    print("  Q6:  Filter + aggregation")
    print("  Q12: Join with complex conditions")
    print("  Q14: Percentage calculation")
    print()

    results = adapter.run_benchmark(benchmark, test_execution_type="power", query_subset=representative_queries)

    print("\n✓ Representative Sample Complete")
    print(f"  Queries: {results.total_queries}")
    print(f"  Time: {results.total_execution_time:.2f}s")
    print("  Use case: Balanced performance testing")
    print()

    return results.total_execution_time


def run_specific_query_debug():
    print("=" * 70)
    print("QUERY SUBSET 3: Single Query Debug")
    print("=" * 70)
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/query_subset/debug"),
        force_regenerate=False,
    )

    benchmark.generate_data()
    adapter = DuckDBAdapter(database_path=":memory:")

    debug_query = ["17"]

    print(f"Debugging Query {debug_query[0]}")
    print("Strategy: Isolate single query for investigation")
    print("  • Run multiple times to get consistent timing")
    print("  • Use EXPLAIN to analyze query plan")
    print("  • Test different optimization approaches")
    print()

    results = adapter.run_benchmark(benchmark, test_execution_type="power", query_subset=debug_query)

    print("\n✓ Debug Run Complete")
    print(f"  Query: Q{debug_query[0]}")
    print(f"  Time: {results.total_execution_time:.2f}s")
    print("  Use case: Rapid iteration for query optimization")
    print()

    return results.total_execution_time


def show_query_selection_strategies():
    print("=" * 70)
    print("QUERY SELECTION STRATEGIES")
    print("=" * 70)
    print()

    print("1. SMOKE TEST (2-3 queries, < 10 seconds)")
    print("   Queries: 1, 6")
    print("   Purpose: Quick validation in CI/CD")
    print("   Pattern: Fastest, most reliable queries")
    print()

    print("2. REPRESENTATIVE SAMPLE (5-10 queries, < 1 minute)")
    print("   Queries: 1, 3, 6, 12, 14")
    print("   Purpose: Balanced performance testing")
    print("   Pattern: Cover different query types")
    print()

    print("3. COMPLEX QUERIES (3-5 queries, 1-5 minutes)")
    print("   Queries: 2, 9, 17, 20, 21")
    print("   Purpose: Stress test query optimizer")
    print("   Pattern: Most complex, slowest queries")
    print()

    print("4. JOIN-FOCUSED (8 queries, 2-5 minutes)")
    print("   Queries: 2, 3, 5, 7, 8, 9, 11, 13")
    print("   Purpose: Test join performance")
    print("   Pattern: Multi-table joins")
    print()

    print("5. AGGREGATION-FOCUSED (5 queries, 1-2 minutes)")
    print("   Queries: 1, 6, 12, 14, 15")
    print("   Purpose: Test aggregation performance")
    print("   Pattern: GROUP BY and aggregates")
    print()

    print("6. SINGLE QUERY DEBUG (1 query, seconds)")
    print("   Queries: Any specific query")
    print("   Purpose: Debug or optimize specific query")
    print("   Pattern: Rapid iteration")
    print()


def show_ci_cd_usage():
    print("=" * 70)
    print("CI/CD INTEGRATION EXAMPLE")
    print("=" * 70)
    print()

    print("GitHub Actions workflow:")
    print("-" * 70)
    print("""
# .github/workflows/benchmark.yml
name: Quick Benchmark Check

on: [pull_request]

jobs:
  smoke-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install BenchBox
        run: pip install benchbox

      - name: Run smoke test (< 30 seconds)
        run: |
          python examples/unified_runner.py \\
            --platform duckdb \\
            --benchmark tpch \\
            --scale 0.01 \\
            --phases power \\
            --queries 1,6 \\
            --quiet \\
            --formats json

      - name: Check for regressions
        run: python check_regression.py
    """)
    print()


def main() -> int:
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: QUERY SUBSET SELECTION")
    print("=" * 70)
    print()
    print("This example shows how to run specific queries instead of the")
    print("full benchmark suite for faster iteration and targeted testing.")
    print()

    full_time = run_full_suite()
    smoke_time = run_smoke_test_subset()
    representative_time = run_representative_subset()
    debug_time = run_specific_query_debug()

    print("=" * 70)
    print("TIME COMPARISON")
    print("=" * 70)
    print()
    print(f"Full suite (22 queries):        {full_time:.2f}s (100%)")
    print(f"Smoke test (2 queries):         {smoke_time:.2f}s ({smoke_time / full_time * 100:.0f}%)")
    print(f"Representative (5 queries):     {representative_time:.2f}s ({representative_time / full_time * 100:.0f}%)")
    print(f"Single query debug:             {debug_time:.2f}s ({debug_time / full_time * 100:.0f}%)")
    print()
    print(f"Time saved with smoke test: {(full_time - smoke_time) / full_time * 100:.0f}% faster!")
    print()

    show_query_selection_strategies()

    show_ci_cd_usage()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Run specific queries with query_subset parameter")
    print("  ✓ Choose queries for different purposes (smoke test, debug, etc.)")
    print("  ✓ Speed up development with targeted testing")
    print("  ✓ Integrate with CI/CD for fast validation")
    print()
    print("Next steps:")
    print("  • Use unified_runner.py with --queries flag:")
    print("    --queries 1,6              # Smoke test")
    print("    --queries 1,3,6,12,14      # Representative sample")
    print("    --queries 17               # Debug specific query")
    print()
    print("  • Try combining with other features:")
    print("    --queries 1,6 --dry-run ./preview  # Preview specific queries")
    print("    --queries 1,6 --tuning tuned  # Test optimization on subset")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
