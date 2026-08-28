#!/usr/bin/env python3
"""Demonstrate running same benchmark on multiple platforms.

This example shows how to:
- Run identical benchmarks across different database platforms
- Compare performance characteristics between platforms
- Make informed platform selection decisions
- Handle platform-specific configurations

Usage:
    python features/multi_platform.py

Key Concepts:
    - Platform iteration and comparison
    - Result collection across platforms
    - Performance comparison metrics
    - Platform selection criteria
    - Handling platform-specific features
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add parent directory to path for imports
_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.platforms.sqlite import SQLiteAdapter
from benchbox.tpch import TPCH


def run_on_platform(platform_name: str, adapter, benchmark):
    """Run benchmark on a specific platform.

    This demonstrates the common pattern for running benchmarks
    across different platforms with identical configurations.

    Args:
        platform_name: Human-readable platform name
        adapter: Platform-specific adapter instance
        benchmark: Benchmark to execute

    Returns:
        Benchmark results
    """
    print(f"Running on {platform_name}...")
    print(f"  Benchmark: {benchmark.name}")
    print(f"  Scale factor: {benchmark.scale_factor}")
    print()

    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    print(f"✓ {platform_name} Complete!")
    print(f"  Total time: {results.total_execution_time:.2f}s")
    print(f"  Queries: {results.total_queries}")
    print(f"  Avg per query: {results.average_query_time:.2f}s")
    print()

    return results


def run_multi_platform_comparison():
    """Run same benchmark on multiple platforms for comparison.

    This demonstrates:
    - Running identical benchmarks across platforms
    - Collecting results from each platform
    - Comparing overall performance

    Note: This example uses local platforms (DuckDB, SQLite) that
    don't require credentials. For cloud platforms (Databricks,
    BigQuery, Snowflake), you would follow the same pattern but
    need to configure credentials.
    """
    print("=" * 70)
    print("MULTI-PLATFORM BENCHMARK COMPARISON")
    print("=" * 70)
    print()
    print("Running TPC-H benchmark on multiple platforms...")
    print("Platforms: DuckDB, SQLite")
    print()

    # Create benchmark (same for all platforms)
    benchmark = TPCH(
        scale_factor=0.01,  # Small scale for fast demonstration
        output_dir=Path("./benchmark_runs/features/multi_platform"),
        force_regenerate=False,
    )

    # Generate data once (reused across platforms)
    print("Generating benchmark data...")
    benchmark.generate_data()
    print("✓ Data generated (will be reused for all platforms)")
    print()

    # Results storage
    platform_results = {}

    # Platform 1: DuckDB
    print("=" * 70)
    print("PLATFORM 1: DuckDB")
    print("=" * 70)
    print("Characteristics: In-memory OLAP, columnar storage")
    print()

    duckdb_adapter = DuckDBAdapter(database_path=":memory:")
    platform_results["DuckDB"] = run_on_platform("DuckDB", duckdb_adapter, benchmark)

    # Platform 2: SQLite
    print("=" * 70)
    print("PLATFORM 2: SQLite")
    print("=" * 70)
    print("Characteristics: Row-oriented, embedded database")
    print()

    sqlite_db = Path("./benchmark_runs/features/multi_platform/sqlite.db")
    sqlite_db.parent.mkdir(parents=True, exist_ok=True)

    sqlite_adapter = SQLiteAdapter(database_path=str(sqlite_db), force_recreate=True)
    platform_results["SQLite"] = run_on_platform("SQLite", sqlite_adapter, benchmark)

    return platform_results


def compare_platforms(platform_results: dict):
    """Compare performance across platforms.

    This shows how to analyze and present multi-platform results
    for decision-making.

    Args:
        platform_results: Dictionary mapping platform names to results
    """
    print("=" * 70)
    print("PLATFORM COMPARISON")
    print("=" * 70)
    print()

    # Overall comparison
    print("Overall Performance:")
    print("-" * 70)
    print(f"{'Platform':<15} {'Total Time':<15} {'Avg Query':<15} {'Relative':<15}")
    print("-" * 70)

    # Find fastest for relative comparison
    fastest_time = min(r.total_execution_time for r in platform_results.values())

    for platform, results in sorted(platform_results.items(), key=lambda x: x[1].total_execution_time):
        total_time = results.total_execution_time
        avg_time = results.average_query_time
        relative = total_time / fastest_time if fastest_time > 0 else 1.0

        print(f"{platform:<15} {total_time:>10.2f}s    {avg_time:>10.3f}s    {relative:>10.2f}x")

    print("-" * 70)
    print()

    # Per-query comparison
    print("Per-Query Comparison (Top 5 queries):")
    print("-" * 70)

    # Get all query names (assuming same queries across platforms)
    first_platform = next(iter(platform_results.values()))
    query_names = [q.query_name for q in first_platform.query_results[:5]]

    # Header
    header = f"{'Query':<10}"
    for platform in platform_results:
        header += f"{platform:<15}"
    header += "Winner"
    print(header)
    print("-" * 70)

    # Query-by-query comparison
    for query_name in query_names:
        row = f"{query_name:<10}"
        query_times = {}

        for platform, results in platform_results.items():
            query_result = next((q for q in results.query_results if q.query_name == query_name), None)
            if query_result:
                time = query_result.execution_time
                query_times[platform] = time
                row += f"{time:>10.3f}s    "
            else:
                row += f"{'N/A':<15}"

        # Find winner (fastest)
        if query_times:
            winner = min(query_times.items(), key=lambda x: x[1])
            row += f"{winner[0]}"

        print(row)

    print("-" * 70)
    print()


def show_platform_characteristics():
    """Show key characteristics of different platforms."""
    print("=" * 70)
    print("PLATFORM CHARACTERISTICS")
    print("=" * 70)
    print()

    print("DuckDB:")
    print("  ✓ Optimized for: OLAP/Analytics workloads")
    print("  ✓ Storage: Columnar, optimized for aggregations")
    print("  ✓ Deployment: Embedded, no server required")
    print("  ✓ Best for: Data science, local analytics, development")
    print("  ✓ Scale: Single-machine, billions of rows")
    print()

    print("SQLite:")
    print("  ✓ Optimized for: Transactional workloads, small datasets")
    print("  ✓ Storage: Row-oriented, optimized for inserts/updates")
    print("  ✓ Deployment: Embedded, single file")
    print("  ✓ Best for: Applications, mobile, small analytical workloads")
    print("  ✓ Scale: Single-machine, millions of rows")
    print()

    print("ClickHouse (not in this demo):")
    print("  ✓ Optimized for: Real-time analytics, high throughput")
    print("  ✓ Storage: Columnar, compressed")
    print("  ✓ Deployment: Server-based, distributed")
    print("  ✓ Best for: Real-time dashboards, web analytics, logging")
    print("  ✓ Scale: Distributed, trillions of rows")
    print()

    print("Cloud Platforms (Databricks, BigQuery, Snowflake, Redshift):")
    print("  ✓ Optimized for: Large-scale analytics, multi-user")
    print("  ✓ Storage: Cloud object storage (S3, GCS, Azure Blob)")
    print("  ✓ Deployment: Fully managed, elastic scaling")
    print("  ✓ Best for: Enterprise data warehouses, production workloads")
    print("  ✓ Scale: Petabyte-scale")
    print()


def show_platform_selection_criteria():
    """Show criteria for selecting platforms."""
    print("=" * 70)
    print("PLATFORM SELECTION CRITERIA")
    print("=" * 70)
    print()

    print("Choose platform based on:")
    print()

    print("1. WORKLOAD TYPE")
    print("   • OLTP (transactional): SQLite, PostgreSQL, MySQL")
    print("   • OLAP (analytical): DuckDB, ClickHouse, cloud data warehouses")
    print("   • Mixed: PostgreSQL with columnar extensions")
    print()

    print("2. DATA VOLUME")
    print("   • < 10GB: SQLite, DuckDB (embedded)")
    print("   • 10GB - 1TB: DuckDB, ClickHouse, PostgreSQL")
    print("   • > 1TB: Cloud data warehouses (Snowflake, BigQuery, Databricks)")
    print()

    print("3. DEPLOYMENT MODEL")
    print("   • Embedded (no server): DuckDB, SQLite")
    print("   • Self-hosted: ClickHouse, PostgreSQL")
    print("   • Cloud-managed: Databricks, BigQuery, Snowflake, Redshift")
    print()

    print("4. COST CONSIDERATIONS")
    print("   • Development/testing: DuckDB, SQLite (free)")
    print("   • Production (self-hosted): ClickHouse (compute + storage costs)")
    print("   • Production (cloud): Pay-per-query or reserved capacity")
    print()

    print("5. PERFORMANCE REQUIREMENTS")
    print("   • Sub-second latency: In-memory platforms (DuckDB)")
    print("   • High throughput: Distributed platforms (ClickHouse, cloud)")
    print("   • Concurrent users: Cloud platforms with elastic scaling")
    print()


def show_cloud_platform_usage():
    """Show how to extend this example to cloud platforms."""
    print("=" * 70)
    print("EXTENDING TO CLOUD PLATFORMS")
    print("=" * 70)
    print()

    print("To run on cloud platforms, follow the same pattern:")
    print()

    print("1. DATABRICKS")
    print("""
from benchbox.platforms.databricks import DatabricksAdapter

adapter = DatabricksAdapter(
    server_hostname="your-workspace.cloud.databricks.com",
    http_path="/sql/1.0/warehouses/abc123",
    catalog="main",
    schema="benchmarks"
)

results = adapter.run_benchmark(benchmark, test_execution_type="power")
    """)

    print("2. BIGQUERY")
    print("""
from benchbox.platforms.bigquery import BigQueryAdapter

adapter = BigQueryAdapter(
    project_id="your-project",
    dataset_id="benchmarks"
)

results = adapter.run_benchmark(benchmark, test_execution_type="power")
    """)

    print("3. SNOWFLAKE")
    print("""
from benchbox.platforms.snowflake import SnowflakeAdapter

adapter = SnowflakeAdapter(
    account="your-account",
    warehouse="COMPUTE_WH",
    database="BENCHMARKS",
    schema="PUBLIC"
)

results = adapter.run_benchmark(benchmark, test_execution_type="power")
    """)

    print("4. Using unified_runner.py (RECOMMENDED)")
    print("""
# Compare DuckDB vs Databricks
python unified_runner.py --platform duckdb --benchmark tpch --scale 1.0 \\
    --phases power --output-dir ./results/duckdb

python unified_runner.py --platform databricks --benchmark tpch --scale 1.0 \\
    --phases power --output-dir ./results/databricks

# Then compare results
python features/result_analysis.py \\
    ./results/duckdb/results.json \\
    ./results/databricks/results.json
    """)


def main() -> int:
    """Demonstrate multi-platform comparison workflow."""
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: MULTI-PLATFORM COMPARISON")
    print("=" * 70)
    print()
    print("This example shows how to run the same benchmark on multiple")
    print("platforms to compare performance and make platform decisions.")
    print()

    # Run on multiple platforms
    platform_results = run_multi_platform_comparison()

    # Compare results
    compare_platforms(platform_results)

    # Show platform characteristics
    show_platform_characteristics()

    # Show selection criteria
    show_platform_selection_criteria()

    # Show cloud platform usage
    show_cloud_platform_usage()

    # Summary
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Run same benchmark on multiple platforms")
    print("  ✓ Compare performance across platforms")
    print("  ✓ Understand platform characteristics")
    print("  ✓ Apply platform selection criteria")
    print("  ✓ Extend to cloud platforms")
    print()
    print("Next steps:")
    print("  • Use unified_runner.py for platform comparison:")
    print("    for platform in duckdb clickhouse-local databricks; do")
    print("      python unified_runner.py --platform $platform \\")
    print("        --benchmark tpch --scale 1.0 --phases power \\")
    print("        --output-dir ./results/$platform")
    print("    done")
    print()
    print("  • Compare results with result_analysis.py:")
    print("    python features/result_analysis.py \\")
    print("      ./results/platform1/results.json \\")
    print("      ./results/platform2/results.json")
    print()
    print("  • Consider factors beyond performance:")
    print("    - Cost (compute, storage, egress)")
    print("    - Operational overhead (managed vs self-hosted)")
    print("    - Ecosystem integration (tools, connectors)")
    print("    - Team expertise and preferences")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
