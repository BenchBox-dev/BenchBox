from __future__ import annotations

import argparse
from pathlib import Path

from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.examples import execute_example_dry_run
from benchbox.platforms.timescaledb import TimescaleDBAdapter
from benchbox.tsbs_devops import TSBSDevOps

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_ROOT = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "timescaledb"


def run_example(
    scale_factor: float = 0.01,
    *,
    host: str = "localhost",
    port: int = 5432,
    database: str = "benchbox_tsbs",
    username: str = "postgres",
    password: str | None = None,
    chunk_interval: str = "1 day",
    compression_enabled: bool = False,
    force_regenerate: bool = False,
    dry_run_output: Path | None = None,
) -> None:
    _OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if dry_run_output is not None:
        benchmark_config = BenchmarkConfig(
            name="tsbs_devops",
            display_name="TSBS DevOps",
            scale_factor=scale_factor,
            options={
                "force_regenerate": force_regenerate,
            },
            test_execution_type="power",
        )

        database_config = DatabaseConfig(
            type="timescaledb",
            name="timescaledb_tsbs_devops",
            options={
                "host": host,
                "port": port,
                "database": database,
                "username": username,
                "password": password,
                "chunk_interval": chunk_interval,
                "compression_enabled": compression_enabled,
                "force_recreate": force_regenerate,
            },
        )

        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="timescaledb_tsbs_devops",
        )
        return

    benchmark = TSBSDevOps(
        scale_factor=scale_factor,
        output_dir=_OUTPUT_ROOT / f"tsbs_devops_sf_{scale_factor}",
        force_regenerate=force_regenerate,
        verbose=False,
    )

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} data files under {benchmark.output_dir}")

    adapter = TimescaleDBAdapter(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        chunk_interval=chunk_interval,
        compression_enabled=compression_enabled,
        force_recreate=force_regenerate,
    )

    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    print("TSBS DevOps benchmark on TimescaleDB complete!")
    print(f"Queries executed: {results.total_queries}")
    print(f"Successful queries: {results.successful_queries}")
    print(f"Total execution time (s): {results.total_execution_time:.2f}")

    platform_info = adapter.get_platform_info()
    if "timescaledb_version" in platform_info:
        print(f"TimescaleDB version: {platform_info['timescaledb_version']}")
    print(f"Hypertables created: {len(adapter._hypertables)}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TSBS DevOps time-series benchmark on TimescaleDB")
    parser.add_argument(
        "--scale",
        type=float,
        default=0.01,
        help="Scale factor (0.01=10 hosts, 0.1=10 hosts, 1.0=100 hosts)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="TimescaleDB server hostname",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5432,
        help="TimescaleDB server port",
    )
    parser.add_argument(
        "--database",
        type=str,
        default="benchbox_tsbs",
        help="Database name",
    )
    parser.add_argument(
        "--username",
        type=str,
        default="postgres",
        help="Database username",
    )
    parser.add_argument(
        "--password",
        type=str,
        default=None,
        help="Database password",
    )
    parser.add_argument(
        "--chunk-interval",
        type=str,
        default="1 day",
        help="Chunk interval for hypertables (e.g., '1 hour', '1 day')",
    )
    parser.add_argument(
        "--compression",
        action="store_true",
        help="Enable compression on hypertables",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate data even if files already exist",
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
        chunk_interval=args.chunk_interval,
        compression_enabled=args.compression,
        force_regenerate=args.force,
        dry_run_output=Path(args.dry_run) if args.dry_run else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
