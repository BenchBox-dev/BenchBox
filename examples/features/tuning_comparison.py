#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH


def run_baseline_benchmark():
    print("=" * 70)
    print("BASELINE: No Tuning (Default Settings)")
    print("=" * 70)
    print("Running with default database settings...")
    print("No optimizations applied")
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/tuning/baseline"),
        force_regenerate=False,
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")

    print("Executing queries with default settings...")
    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    print("\n✓ Baseline Complete!")
    print(f"  Total queries: {results.total_queries}")
    print(f"  Total time: {results.total_execution_time:.2f}s")
    print(f"  Average per query: {results.average_query_time:.2f}s")
    print("  Configuration: Default (no tuning)")
    print()

    return results


def run_tuned_benchmark():
    print("=" * 70)
    print("OPTIMIZED: With Tuning Configuration")
    print("=" * 70)
    print("Running with optimized settings...")
    print("Applying tuning configuration")
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/tuning/tuned"),
        force_regenerate=False,
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:")

    print("Executing queries with optimizations...")
    print("Note: DuckDB automatically applies many optimizations")
    print("In production, load tuning from YAML config file")
    print()

    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="power",
    )

    print("\n✓ Optimized Run Complete!")
    print(f"  Total queries: {results.total_queries}")
    print(f"  Total time: {results.total_execution_time:.2f}s")
    print(f"  Average per query: {results.average_query_time:.2f}s")
    print("  Configuration: Tuned")
    print()

    return results


def compare_results(baseline_results, tuned_results):
    print("=" * 70)
    print("PERFORMANCE COMPARISON")
    print("=" * 70)
    print()

    baseline_time = baseline_results.total_execution_time
    tuned_time = tuned_results.total_execution_time

    time_saved = baseline_time - tuned_time
    percent_improvement = (time_saved / baseline_time * 100) if baseline_time > 0 else 0

    print("Overall Performance:")
    print(f"  Baseline time:     {baseline_time:.2f}s")
    print(f"  Tuned time:        {tuned_time:.2f}s")
    print(f"  Time saved:        {time_saved:.2f}s")
    print(f"  Improvement:       {percent_improvement:.1f}%")
    print()

    print("Per-Query Breakdown:")
    print("-" * 70)
    print(f"{'Query':<10} {'Baseline':<15} {'Tuned':<15} {'Improvement':<15}")
    print("-" * 70)

    baseline_queries = {q.query_name: q for q in baseline_results.query_results}
    tuned_queries = {q.query_name: q for q in tuned_results.query_results}

    total_improvement = 0
    improved_queries = 0

    for query_name in sorted(baseline_queries.keys()):
        if query_name in tuned_queries:
            baseline_q = baseline_queries[query_name]
            tuned_q = tuned_queries[query_name]

            baseline_time = baseline_q.execution_time
            tuned_time = tuned_q.execution_time

            if baseline_time > 0:
                improvement = (baseline_time - tuned_time) / baseline_time * 100
                total_improvement += improvement
                if improvement > 0:
                    improved_queries += 1

                print(f"{query_name:<10} {baseline_time:>10.3f}s    {tuned_time:>10.3f}s    {improvement:>10.1f}%")

    print("-" * 70)
    print()

    total_queries = len(baseline_queries)
    avg_improvement = total_improvement / total_queries if total_queries > 0 else 0

    print("Summary:")
    print(f"  Total queries analyzed: {total_queries}")
    print(f"  Queries improved:       {improved_queries} ({improved_queries / total_queries * 100:.0f}%)")
    print(f"  Average improvement:    {avg_improvement:.1f}%")
    print()


def show_tuning_strategies():
    print("=" * 70)
    print("TUNING STRATEGIES")
    print("=" * 70)
    print()

    print("1. MEMORY TUNING")
    print("   Settings: work_mem, shared_buffers, temp_buffers")
    print("   Impact: Reduces disk I/O, speeds up sorting and hashing")
    print("   Best for: Large joins, aggregations, sorting operations")
    print()

    print("2. PARALLELISM")
    print("   Settings: max_parallel_workers, parallel_tuple_cost")
    print("   Impact: Distributes query execution across CPU cores")
    print("   Best for: Large scans, complex aggregations")
    print()

    print("3. QUERY PLANNER")
    print("   Settings: enable_hashjoin, enable_mergejoin, random_page_cost")
    print("   Impact: Influences query plan selection")
    print("   Best for: Complex multi-table joins")
    print()

    print("4. INDEXES")
    print("   Settings: Index creation on frequently filtered columns")
    print("   Impact: Speeds up selective queries")
    print("   Best for: Point queries, range scans")
    print("   Trade-off: Slower writes, increased storage")
    print()

    print("5. STATISTICS")
    print("   Settings: Statistics collection frequency and depth")
    print("   Impact: Better query plan selection")
    print("   Best for: Dynamic datasets with changing distributions")
    print()


def show_tuning_workflow():
    print("=" * 70)
    print("TUNING WORKFLOW")
    print("=" * 70)
    print()

    print("Step 1: ESTABLISH BASELINE")
    print("  python unified_runner.py --platform duckdb --benchmark tpch \\")
    print("    --scale 1.0 --phases power --tuning notuning \\")
    print("    --output-dir ./results/baseline")
    print()

    print("Step 2: IDENTIFY SLOW QUERIES")
    print("  Analyze baseline results to find optimization targets")
    print("  Focus on queries that take >1s or show high variance")
    print()

    print("Step 3: APPLY TUNING")
    print("  Edit tunings/duckdb/tpch_tuned.yaml with optimizations")
    print("  python unified_runner.py --platform duckdb --benchmark tpch \\")
    print("    --scale 1.0 --phases power --tuning tuned \\")
    print("    --output-dir ./results/tuned")
    print()

    print("Step 4: COMPARE RESULTS")
    print("  Use result_analysis.py to compare baseline vs tuned")
    print("  Identify which optimizations had the most impact")
    print()

    print("Step 5: ITERATE")
    print("  Refine tuning based on results")
    print("  Test on larger scale factors")
    print("  Validate on production-like workloads")
    print()


def main() -> int:
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: TUNING COMPARISON")
    print("=" * 70)
    print()
    print("This example shows how to compare baseline vs tuned performance")
    print("to quantify the impact of optimizations.")
    print()

    baseline_results = run_baseline_benchmark()
    tuned_results = run_tuned_benchmark()

    compare_results(baseline_results, tuned_results)

    show_tuning_strategies()

    show_tuning_workflow()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Run baseline benchmarks (no tuning)")
    print("  ✓ Run optimized benchmarks (with tuning)")
    print("  ✓ Compare results to quantify improvements")
    print("  ✓ Understand common tuning strategies")
    print("  ✓ Follow systematic tuning workflow")
    print()
    print("Next steps:")
    print("  • Use unified_runner.py with tuning modes:")
    print("    --tuning notuning    # Baseline")
    print("    --tuning tuned       # Optimized")
    print("    --tuning /path/to/custom.yaml  # Custom config")
    print()
    print("  • Create tuning configurations:")
    print("    See examples/tunings/{platform}/{benchmark}_tuned.yaml")
    print()
    print("  • Analyze results over time:")
    print("    See features/result_analysis.py for comparison tools")
    print()
    print("  • Combine with other features:")
    print("    --queries 2,9,17 --tuning tuned  # Focus on slow queries")
    print("    --dry-run ./preview --tuning tuned  # Preview tuning impact")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
