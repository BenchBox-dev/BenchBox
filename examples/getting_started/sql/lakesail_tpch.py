"""Run TPC-H on LakeSail Sail via Spark Connect (SQL mode).

LakeSail Sail is a Rust-based, drop-in replacement for Apache Spark built on
DataFusion. It uses the standard Spark Connect protocol (sc://), so you can
connect with the regular PySpark client library -- no proprietary SDK needed.

Key characteristics:
- 4x faster execution with 94% lower hardware costs vs Apache Spark (TPC-H SF100)
- Zero rewrite migration: standard PySpark client via Spark Connect protocol
- Dual execution modes: multi-threaded single-host or distributed cluster
- Built on DataFusion with Rust workers

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
    python examples/getting_started/sql/lakesail_tpch.py

    # Custom endpoint (e.g., remote cluster)
    export SAIL_ENDPOINT=sc://sail-cluster.example.com:50051
    python examples/getting_started/sql/lakesail_tpch.py

    # Preview without execution
    python examples/getting_started/sql/lakesail_tpch.py --dry-run ./preview

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.core.system import SystemProfiler
from benchbox.examples import execute_example_dry_run

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "lakesail"


def _build_configs(scale_factor: float) -> tuple[BenchmarkConfig, DatabaseConfig]:
    """Build benchmark and database configurations for LakeSail Sail.

    LakeSail Sail Concepts:

    1. SPARK CONNECT PROTOCOL
       - Standard PySpark client connects via sc:// URL
       - No proprietary drivers or SDK required
       - Same API as Apache Spark -- queries run on Sail's DataFusion engine

    2. DEPLOYMENT MODES
       - Local: Single-host, multi-threaded execution (default)
       - Distributed: Multiple Rust workers for large-scale workloads
       - Both modes expose the same Spark Connect endpoint

    3. TABLE FORMAT
       - Default: Parquet (columnar, efficient for analytics)
       - Also supports ORC format
       - Tables created via Spark SQL DDL

    4. PERFORMANCE TUNING
       - Adaptive Query Execution (AQE) enabled by default
       - Shuffle partitions configurable (default: 200)
       - Result cache disabled by default for accurate benchmarking
    """
    # Read optional configuration from environment
    endpoint = os.getenv("SAIL_ENDPOINT", "sc://localhost:50051")
    sail_mode = os.getenv("SAIL_MODE", "local")
    sail_workers = os.getenv("SAIL_WORKERS")

    # Step 1: Benchmark configuration
    # TPC-H includes 22 queries across 8 tables (customer, orders, lineitem, etc.)
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=scale_factor,
        test_execution_type="power",
        options={"enable_preflight_validation": False},
    )

    # Step 2: Database configuration for LakeSail Sail
    database_config = DatabaseConfig(
        type="lakesail",
        name="lakesail_tpch",
        options={
            # Spark Connect endpoint (required -- points to running Sail server)
            "endpoint": endpoint,
            # Application name (appears in Sail server logs)
            "app_name": "BenchBox-LakeSail-Example",
            # Deployment mode: local (single-host) or distributed (cluster)
            "sail_mode": sail_mode,
            # Worker count for distributed mode (omit for local)
            "sail_workers": int(sail_workers) if sail_workers else None,
            # Table storage format
            "table_format": "parquet",
            # Resource configuration
            "driver_memory": "4g",
            "shuffle_partitions": 200,
            # Enable Adaptive Query Execution for optimal performance
            "adaptive_enabled": True,
            # disable_cache defaults to True for LakeSail; session-level cache suppression is safe,
            # and the adapter skips the unsupported Spark Connect clearCache() call.
        },
    )

    return benchmark_config, database_config


def run_example(scale_factor: float = 0.01, *, dry_run_output: Path | None = None) -> None:
    """Execute TPC-H benchmark on LakeSail Sail via SQL.

    LakeSail Sail provides:
    - Spark-compatible SQL execution on a DataFusion engine
    - Local mode for development and small-scale testing
    - Distributed mode for production workloads
    - No JVM overhead -- pure Rust execution
    """
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    benchmark_config, database_config = _build_configs(scale_factor)

    # Dry-run mode: generate SQL artifacts without connecting to Sail server
    if dry_run_output is not None:
        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="lakesail_tpch",
        )
        print()
        print("Dry-run complete! Review SQL files before running on LakeSail Sail.")
        print()
        print("Before running:")
        print("1. Start a Sail server: sail-server start (or via Docker)")
        print(f"2. Verify server is reachable at {database_config.options.get('endpoint')}")
        print("3. Review generated SQL for Spark dialect compatibility")
        return

    # Normal execution mode

    # Step 3: Collect system profile for result metadata
    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()

    # Step 4: Create orchestrator and run benchmark
    # The orchestrator handles: data generation -> schema creation -> data loading -> query execution
    orchestrator = BenchmarkOrchestrator(base_dir=str(_OUTPUT_DIR))

    result = orchestrator.execute_benchmark(
        config=benchmark_config,
        system_profile=system_profile,
        database_config=database_config,
        phases_to_run=["generate", "load", "power"],
    )

    # Step 5: Display results
    print(f"Benchmark completed at scale factor {scale_factor} with {result.successful_queries} successful queries")
    print(f"Total runtime (s): {result.total_execution_time:.2f}")
    print()
    print("Results saved to:", _OUTPUT_DIR)
    print()
    print("Next steps:")
    print("- Review results.json for detailed query timings")
    print("- Compare with Apache Spark to measure Sail's performance advantage")
    print("- Try distributed mode for larger scale factors (SF=10+)")
    print("- Run the DataFrame variant: lakesail_df_tpch.py")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TPC-H on LakeSail Sail (SQL mode)")
    parser.add_argument("--scale", type=float, default=0.01, help="Benchmark scale factor")
    parser.add_argument(
        "--dry-run",
        type=str,
        metavar="OUTPUT_DIR",
        help="Preview without executing; write artifacts to OUTPUT_DIR.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_example(
        scale_factor=args.scale,
        dry_run_output=Path(args.dry_run) if args.dry_run else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
