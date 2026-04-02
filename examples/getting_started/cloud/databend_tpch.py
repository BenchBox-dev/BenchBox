"""Run TPC-H on Databend (cloud-native or self-hosted).

Databend is a cloud-native, Rust-based data warehouse with Snowflake-compatible
SQL and compute/storage separation on object storage (S3, GCS, Azure Blob, MinIO).
BenchBox connects via the databend-driver Python package and uses the Snowflake
dialect as a SQLGlot translation proxy for SQL compatibility.

Databend supports two deployment modes:

- **Databend Cloud**: Managed service at https://www.databend.com
  - Authentication via host, username, and password
  - Warehouse-scoped compute (similar to Snowflake)
  - SSL enabled by default (port 443)

- **Self-hosted**: User-managed cluster with object storage backend
  - Typically runs on port 8000 (HTTP, no SSL)
  - Requires MinIO or S3-compatible storage for data persistence
  - DSN-based connection: databend+http://user:pass@host:port/database?sslmode=disable

Prerequisites:
    1. Databend Cloud account or self-hosted Databend instance
    2. databend-driver Python package installed (>=0.28.0)
    3. Database user with CREATE/DROP/INSERT/SELECT privileges

Required environment variables (choose one approach):

    Option A - Individual parameters:
        DATABEND_HOST            Databend hostname or IP address
        DATABEND_USER            Database username (default: benchbox)
        DATABEND_PASSWORD        Database password

    Option B - DSN string:
        DATABEND_DSN             Full DSN (e.g., databend+http://user:pass@host:port/db?sslmode=disable)

Optional environment variables:
    DATABEND_DATABASE        Target database name (default: benchbox)
    DATABEND_PORT            Connection port (default: 443 for cloud, 8000 for self-hosted)
    DATABEND_WAREHOUSE       Databend Cloud warehouse name

Installation:
    uv add databend-driver

Usage:
    # Databend Cloud
    export DATABEND_HOST=tenant--warehouse.gw.databend.com
    export DATABEND_USER=benchbox
    export DATABEND_PASSWORD=your_password

    python examples/getting_started/cloud/databend_tpch.py

    # Self-hosted via DSN
    export DATABEND_DSN=databend+http://benchbox:benchbox@localhost:8000/benchbox?sslmode=disable

    python examples/getting_started/cloud/databend_tpch.py

    # Preview without execution
    python examples/getting_started/cloud/databend_tpch.py --dry-run ./preview
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
_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "databend"


def _build_configs(scale_factor: float) -> tuple[BenchmarkConfig, DatabaseConfig]:
    """Build benchmark and database configurations for Databend.

    Databend Concepts:

    1. COMPUTE/STORAGE SEPARATION
       - Compute nodes run queries; storage is on object storage (S3, MinIO, etc.)
       - Cloud: Warehouses provide isolated compute resources
       - Self-hosted: Single or multi-node clusters backed by object storage

    2. SNOWFLAKE-COMPATIBLE SQL
       - Databend claims ~100% Snowflake SQL compatibility
       - BenchBox uses Snowflake dialect via SQLGlot as translation proxy
       - CHAR(n) types are converted to VARCHAR(n) for Databend compatibility

    3. CLUSTERING KEYS
       - Similar to Snowflake clustering keys
       - CLUSTER BY clause optimizes data layout for frequent query patterns
       - Applied via tuning configuration at table creation or post-creation

    4. AUTHENTICATION
       - Cloud: Host + username + password (SSL on port 443)
       - Self-hosted: DSN-based or individual params (HTTP on port 8000)
       - Credentials should always be provided via environment variables
    """
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=scale_factor,
        test_execution_type="power",
        options={"enable_preflight_validation": False},
    )

    # Build connection options from environment variables
    dsn = os.getenv("DATABEND_DSN")

    options: dict[str, object] = {}

    if dsn:
        # DSN takes precedence over individual parameters
        options["dsn"] = dsn
    else:
        # Individual parameters with env var fallbacks
        host = os.getenv("DATABEND_HOST")
        if not host:
            raise RuntimeError(
                "Missing Databend connection configuration. Set either:\n"
                "  DATABEND_DSN=databend+http://user:pass@host:port/db?sslmode=disable\n"
                "or:\n"
                "  DATABEND_HOST=<hostname>\n"
                "  DATABEND_USER=<username>\n"
                "  DATABEND_PASSWORD=<password>"
            )
        options["host"] = host
        options["username"] = os.getenv("DATABEND_USER", "benchbox")
        options["password"] = os.getenv("DATABEND_PASSWORD", "")

        port = os.getenv("DATABEND_PORT")
        if port:
            options["port"] = int(port)

    # Optional configuration
    options["database"] = os.getenv("DATABEND_DATABASE", "benchbox")

    warehouse = os.getenv("DATABEND_WAREHOUSE")
    if warehouse:
        options["warehouse"] = warehouse

    database_config = DatabaseConfig(
        type="databend",
        name="databend_tpch",
        options=options,
    )

    return benchmark_config, database_config


def run_example(scale_factor: float = 0.01, *, dry_run_output: Path | None = None) -> None:
    """Execute TPC-H benchmark on Databend.

    Databend provides:
    - Cloud-native compute/storage separation on object storage
    - Snowflake-compatible SQL for broad query compatibility
    - Vectorized Rust query engine for analytical performance
    - Automatic micro-partitioning and statistics collection
    """
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    benchmark_config, database_config = _build_configs(scale_factor)

    if dry_run_output is not None:
        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="databend_tpch",
        )
        print()
        print("Dry-run complete! Review SQL files before running on Databend.")
        print()
        print("Deployment options:")
        print("- Databend Cloud: https://www.databend.com (managed, SSL on port 443)")
        print("- Self-hosted: docker run -p 8000:8000 datafuselabs/databend:latest")
        print()
        print("Before running:")
        print("1. Verify Databend is accessible at the configured host and port")
        print("2. Database will be created automatically if it doesn't exist")
        print("3. Review query translations (Snowflake dialect) in generated SQL files")
        print("4. For self-hosted: ensure object storage backend is configured")
        return

    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()

    orchestrator = BenchmarkOrchestrator(base_dir=str(_OUTPUT_DIR))

    result = orchestrator.execute_benchmark(
        config=benchmark_config,
        system_profile=system_profile,
        database_config=database_config,
        phases_to_run=["generate", "load", "power"],
    )

    print(f"Benchmark completed at scale factor {scale_factor} with {result.successful_queries} successful queries")
    print(f"Total runtime (s): {result.total_execution_time:.2f}")
    print()
    print("Results saved to:", _OUTPUT_DIR)
    print()
    print("Next steps:")
    print("- Review results.json for detailed query timings")
    print("- Try larger scale factors for distributed performance testing")
    print("- Compare with other cloud OLAP platforms (Snowflake, ClickHouse Cloud)")
    print("- For Databend Cloud: check warehouse activity in the web console")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TPC-H on Databend")
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
