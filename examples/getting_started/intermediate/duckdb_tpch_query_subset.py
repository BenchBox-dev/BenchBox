from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path

from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.examples import execute_example_dry_run
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_ROOT = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "duckdb"


def run_example(
    *,
    scale_factor: float = 0.01,
    queries: Iterable[str] = ("1", "6"),
    force_regenerate: bool = False,
    dry_run_output: Path | None = None,
) -> None:
    _OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    query_list = list(queries)

    if dry_run_output is not None:
        benchmark_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=scale_factor,
            queries=query_list,
            options={
                "force_regenerate": force_regenerate,
            },
        )

        database_config = DatabaseConfig(
            type="duckdb",
            name="duckdb_tpch_subset",
            options={
                "database_path": ":memory:",
                "force_recreate": force_regenerate,
            },
        )

        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="duckdb_tpch_subset",
        )
        return

    benchmark = TPCH(
        scale_factor=scale_factor,
        output_dir=_OUTPUT_ROOT / f"tpch_subset_sf_{scale_factor}",
        force_regenerate=force_regenerate,
        verbose=False,
    )

    benchmark.generate_data()

    adapter = DuckDBAdapter(database_path=":memory:", force_recreate=force_regenerate)

    results = adapter.run_benchmark(
        benchmark,
        test_execution_type="standard",
        query_subset=query_list,
    )

    print(f"Executed queries: {', '.join(query_list)}")
    print(f"Successful queries: {results.successful_queries}/{results.total_queries}")
    print(f"Average time per query (s): {results.average_query_time:.2f}")
    print()
    print("Time saved by using subset:")
    print("  Full TPC-H: 22 queries (estimated ~2-5 minutes at SF=0.01)")
    print(f"  Your subset: {len(query_list)} queries (completed in {results.total_execution_time:.2f}s)")
    print(f"  Speedup: ~{22 / len(query_list) if query_list else 1:.0f}x faster")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a subset of TPC-H queries on DuckDB")
    parser.add_argument("--scale", type=float, default=0.01, help="Benchmark scale factor")
    parser.add_argument(
        "--queries",
        type=str,
        default="1,6",
        help="Comma-separated list of TPC-H query IDs to execute",
    )
    parser.add_argument("--force", action="store_true", help="Regenerate data and recreate the database")
    parser.add_argument(
        "--dry-run",
        type=str,
        metavar="OUTPUT_DIR",
        help="Preview the targeted query subset without execution; artifacts are written to OUTPUT_DIR.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    query_ids = tuple(q.strip() for q in args.queries.split(",") if q.strip())
    run_example(
        scale_factor=args.scale,
        queries=query_ids,
        force_regenerate=args.force,
        dry_run_output=Path(args.dry_run) if args.dry_run else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
