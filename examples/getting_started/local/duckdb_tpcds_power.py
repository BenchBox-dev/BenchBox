from __future__ import annotations

import argparse
from pathlib import Path

from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.examples import execute_example_dry_run
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpcds import TPCDS

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_ROOT = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "duckdb"


def run_example(
    scale_factor: float = 0.01,
    *,
    force_regenerate: bool = False,
    dry_run_output: Path | None = None,
) -> None:
    _OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    if dry_run_output is not None:
        benchmark_config = BenchmarkConfig(
            name="tpcds",
            display_name="TPC-DS",
            scale_factor=scale_factor,
            options={
                "force_regenerate": force_regenerate,
            },
            test_execution_type="power",
        )

        database_config = DatabaseConfig(
            type="duckdb",
            name="duckdb_tpcds_power",
            options={
                "database_path": ":memory:",
                "force_recreate": force_regenerate,
            },
        )

        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="duckdb_tpcds_power",
        )
        return

    benchmark = TPCDS(
        scale_factor=scale_factor,
        output_dir=_OUTPUT_ROOT / f"tpcds_sf_{scale_factor}",
        force_regenerate=force_regenerate,
        verbose=False,
    )

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} data files under {benchmark.output_dir}")

    adapter = DuckDBAdapter(database_path=":memory:", force_recreate=force_regenerate)

    results = adapter.run_benchmark(benchmark, test_execution_type="power")

    print("Power test complete!")
    print(f"Queries executed: {results.total_queries}")
    print(f"Successful queries: {results.successful_queries}")
    print(f"Total execution time (s): {results.total_execution_time:.2f}")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TPC-DS DuckDB power test (minimal example)")
    parser.add_argument(
        "--scale", type=float, default=0.01, help="Benchmark scale factor (minimum 0.01; increase for larger runs)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate data even if files already exist and recreate the DuckDB database",
    )
    parser.add_argument(
        "--dry-run",
        type=str,
        metavar="OUTPUT_DIR",
        help="Preview the run plan without executing queries; artifacts are written to OUTPUT_DIR.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    run_example(
        scale_factor=args.scale,
        force_regenerate=args.force,
        dry_run_output=Path(args.dry_run) if args.dry_run else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
