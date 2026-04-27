"""Run TPC-H on LakeSail Sail using the PySpark DataFrame API.

This example benchmarks LakeSail Sail using the DataFrame API rather than SQL.
DataFrame queries are expressed as PySpark operations (filter, groupBy, agg, join)
and executed on Sail's DataFusion engine via Spark Connect.

Why DataFrame mode?
- Measures DataFrame API overhead vs raw SQL execution
- Tests PySpark API compatibility of the Sail engine
- Enables side-by-side comparison: run lakesail_tpch.py (SQL) and this script
  (DataFrame) at the same scale factor to see the difference

LakeSail Sail uses the standard Spark Connect protocol (sc://), so the same
PySpark client library works for both SQL and DataFrame modes -- no proprietary
SDK needed.

Prerequisites:
    1. A running LakeSail Sail server (local or cluster)
       - Local: `sail-server start` or Docker container
       - Cluster: Sail deployed with distributed workers
    2. PySpark client library installed

Installation:
    uv add benchbox --extra spark

Optional environment variables:
    SAIL_ENDPOINT      Spark Connect URL (default: sc://localhost:50051)
    SAIL_MODE          Deployment mode: local or distributed (default: local)
    SAIL_WORKERS       Worker count for distributed mode

Usage:
    # Start a local Sail server, then run:
    python examples/getting_started/dataframe/lakesail_df_tpch.py

    # Custom endpoint (e.g., remote cluster)
    export SAIL_ENDPOINT=sc://sail-cluster.example.com:50051
    python examples/getting_started/dataframe/lakesail_df_tpch.py

    # Dry-run mode (validate configuration without connecting)
    python examples/getting_started/dataframe/lakesail_df_tpch.py --dry-run

Example DataFrame Query (TPC-H Q1):
    ```python
    from pyspark.sql import functions as F

    def q1_builder(spark, tables):
        lineitem = spark.table("lineitem")
        return (
            lineitem
            .filter(F.col("l_shipdate") <= F.lit("1998-09-02"))
            .groupBy("l_returnflag", "l_linestatus")
            .agg(
                F.sum("l_quantity").alias("sum_qty"),
                F.sum("l_extendedprice").alias("sum_base_price"),
            )
            .orderBy("l_returnflag", "l_linestatus")
        )
    ```

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Add project root to path for local development
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.core.config import BenchmarkConfig, DatabaseConfig

_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "lakesail_df"


def _build_configs(scale_factor: float) -> tuple[BenchmarkConfig, DatabaseConfig]:
    """Build benchmark and database configurations for LakeSail DataFrame mode.

    LakeSail DataFrame Mode:
    - Uses the 'lakesail-df' platform type (DataFrame API execution)
    - Connects via Spark Connect, same as SQL mode
    - TPC-H queries expressed as PySpark DataFrame operations
    - Schema creation and data loading use SQL internally,
      then query execution switches to DataFrame API

    Comparison with SQL mode:
    - SQL mode (lakesail): Sends SQL strings to Sail for parsing and execution
    - DataFrame mode (lakesail-df): Builds query plans via PySpark API calls
    - Both use the same Sail DataFusion engine underneath

    Args:
        scale_factor: TPC-H scale factor (0.01, 0.1, 1, 10, etc.)

    Returns:
        Tuple of (BenchmarkConfig, DatabaseConfig)
    """
    # Read optional configuration from environment
    endpoint = os.getenv("SAIL_ENDPOINT", "sc://localhost:50051")
    sail_mode = os.getenv("SAIL_MODE", "local")
    sail_workers = os.getenv("SAIL_WORKERS")

    # Benchmark configuration
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=scale_factor,
        test_execution_type="power",
        options={"enable_preflight_validation": False},
    )

    # Database configuration for LakeSail DataFrame mode
    database_config = DatabaseConfig(
        type="lakesail-df",  # DataFrame mode adapter
        name="lakesail_df_tpch",
        options={
            # Spark Connect endpoint (points to running Sail server)
            "endpoint": endpoint,
            # Application name (appears in Sail server logs)
            "app_name": "BenchBox-LakeSail-DF-Example",
            # Deployment mode
            "sail_mode": sail_mode,
            "sail_workers": int(sail_workers) if sail_workers else None,
            # Execution mode: DataFrame API instead of SQL
            "execution_mode": "dataframe",
            # Table storage format (used during schema creation and data loading)
            "table_format": "parquet",
            # Resource configuration
            "driver_memory": "4g",
            "shuffle_partitions": 200,
            # Enable Adaptive Query Execution
            "adaptive_enabled": True,
            # disable_cache defaults to True for LakeSail; session-level cache suppression is safe,
            # and the adapter skips the unsupported Spark Connect clearCache() call.
        },
    )

    return benchmark_config, database_config


def run_example(scale_factor: float = 0.01, *, dry_run: bool = False) -> None:
    """Run TPC-H benchmark on LakeSail Sail using DataFrame API.

    Args:
        scale_factor: TPC-H scale factor (default: 0.01 = ~10MB)
        dry_run: If True, validate configuration without connecting to Sail server

    Execution flow:
    1. Generate TPC-H data locally (Parquet files)
    2. Create schema on Sail server via Spark SQL DDL
    3. Load data into Sail tables
    4. Execute TPC-H queries as PySpark DataFrame operations
    5. Collect and validate results
    """
    print("=" * 70)
    print("LakeSail Sail DataFrame TPC-H Benchmark")
    print("=" * 70)
    print()
    print("This example runs TPC-H queries using PySpark DataFrame API")
    print("on LakeSail Sail via Spark Connect protocol.")
    print()

    # Dry-run mode: validate configuration without connecting
    if dry_run:
        print("[DRY RUN] Validating configuration without connecting...")
        print()

        benchmark_config, database_config = _build_configs(scale_factor)
        print(f"  Platform: {database_config.type} (DataFrame mode)")
        print(f"  Benchmark: {benchmark_config.name}")
        print(f"  Scale Factor: {benchmark_config.scale_factor}")
        print(f"  Endpoint: {database_config.options.get('endpoint')}")
        print(f"  Sail Mode: {database_config.options.get('sail_mode')}")
        print()
        print("[OK] Configuration valid")
        print()
        print("To compare SQL vs DataFrame performance:")
        print("  1. Run SQL mode:       python examples/getting_started/sql/lakesail_tpch.py")
        print("  2. Run DataFrame mode: python examples/getting_started/dataframe/lakesail_df_tpch.py")
        print("  3. Compare results in benchmark_runs/getting_started/")
        return

    # Build configurations
    benchmark_config, database_config = _build_configs(scale_factor)

    print("Configuration:")
    print(f"  Endpoint: {database_config.options.get('endpoint')}")
    print(f"  Sail Mode: {database_config.options.get('sail_mode')}")
    print("  Execution Mode: DataFrame")
    print(f"  Scale Factor: {scale_factor}")
    print()

    # Create output directory
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Run benchmark via orchestrator
    print("Starting benchmark run...")
    print()

    orchestrator = BenchmarkOrchestrator(
        benchmark_config=benchmark_config,
        database_config=database_config,
        output_dir=_OUTPUT_DIR,
    )

    results = orchestrator.run()

    # Display results
    print()
    print("=" * 70)
    print("Results Summary")
    print("=" * 70)
    if results:
        print(f"  Total queries: {len(results.get('query_results', []))}")
        print("  Execution mode: DataFrame")
        if "total_time" in results:
            print(f"  Total time: {results['total_time']:.2f}s")
    print()
    print("Results saved to:", _OUTPUT_DIR)
    print()
    print("Next steps:")
    print("- Compare with SQL mode: run lakesail_tpch.py at the same scale factor")
    print("- Try larger scale factors to see how DataFrame overhead scales")
    print("- Review per-query timings in results.json")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TPC-H on LakeSail Sail (DataFrame mode)")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.01,
        help="TPC-H scale factor (default: 0.01)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration without connecting to Sail server",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_example(
        scale_factor=args.scale,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
