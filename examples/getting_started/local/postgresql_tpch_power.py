from __future__ import annotations

import argparse
from pathlib import Path

from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.examples import execute_example_dry_run
from benchbox.platforms.postgresql import PostgreSQLAdapter
from benchbox.tpch import TPCH

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_ROOT = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "postgresql"


def run_example(
    scale_factor: float = 0.01,
    *,
    host: str = "localhost",
    port: int = 5432,
    database: str = "benchbox_tpch",
    username: str = "postgres",
    password: str | None = None,
    schema: str = "public",
    work_mem: str = "256MB",
    force_regenerate: bool = False,
    dry_run_output: Path | None = None,
) -> None:
    _OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if dry_run_output is not None:
        benchmark_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=scale_factor,
            options={
                "force_regenerate": force_regenerate,
            },
            test_execution_type="power",
        )

        database_config = DatabaseConfig(
            type="postgresql",
            name="postgresql_tpch_power",
            options={
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "password": password,
                "schema": schema,
                "work_mem": work_mem,
                "force_recreate": force_regenerate,
            },
        )

        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="postgresql_tpch_power",
        )
        return

    benchmark = TPCH(
        scale_factor=scale_factor,
        output_dir=_OUTPUT_ROOT / f"tpch_sf_{scale_factor}",
        force_regenerate=force_regenerate,
        verbose=False,
    )

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} data files under {benchmark.output_dir}")

    adapter = PostgreSQLAdapter(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        schema=schema,
        work_mem=work_mem,
        force_recreate=force_regenerate,
    )

    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    print("TPC-H power test on PostgreSQL complete!")
    print(f"Queries executed: {results.total_queries}")
    print(f"Successful queries: {results.successful_queries}")
    print(f"Total execution time (s): {results.total_execution_time:.2f}")

    platform_info = adapter.get_platform_info()
    if "platform_version" in platform_info:
        print(f"PostgreSQL version: {platform_info['platform_version']}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TPC-H benchmark on PostgreSQL (power test)")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.01,
        help="Benchmark scale factor (0.01=~10MB, 0.1=~100MB, 1.0=~1GB)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="PostgreSQL server hostname",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5432,
        help="PostgreSQL server port",
    )
    parser.add_argument(
        "--database",
        type=str,
        default="benchbox_tpch",
        help="Database name (will be created if it doesn't exist)",
    )
    parser.add_argument(
        "--username",
        type=str,
        default="postgres",
        help="PostgreSQL username",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="PostgreSQL password (or use PGPASSWORD env var)",
    )
    parser.add_argument(
        "--schema",
        type=str,
        default="public",
        help="Schema to use for benchmark tables",
    )
    parser.add_argument(
        "--work-mem",
        type=str,
        default="256MB",
        help="PostgreSQL work_mem setting for sorts/hashes",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate data and recreate database even if they exist",
    )
    parser.add_argument(
        "--dry-run",
        type=str,
        metavar="OUTPUT_DIR",
        help="Preview the run plan without executing queries",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_example(
        scale_factor=args.scale,
        host=args.host,
        port=args.port,
        database=args.database,
        username=args.username,
        password=args.password,
        schema=args.schema,
        work_mem=args.work_mem,
        force_regenerate=args.force,
        dry_run_output=Path(args.dry_run) if args.dry_run else None,
    )
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
