from __future__ import annotations

import argparse
import os
from pathlib import Path

from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.examples import execute_example_dry_run

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "bigquery_dry_run"


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(f"Missing environment variable {var_name}. Set it before running this example.")
    return value


def run_example(scale_factor: float = 0.01, *, dry_run_output: Path | None = None) -> None:
    output_dir = Path(dry_run_output) if dry_run_output else _OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=scale_factor,
        test_execution_type="power",
    )

    database_config = DatabaseConfig(
        type="bigquery",
        name="bigquery_tpch_preview",
        options={
            "project_id": _require_env("BIGQUERY_PROJECT"),
            "dataset": _require_env("BIGQUERY_DATASET"),
            "location": os.getenv("BIGQUERY_LOCATION", "US"),
        },
    )

    execute_example_dry_run(
        benchmark_config=benchmark_config,
        database_config=database_config,
        output_dir=output_dir,
        filename_prefix="bigquery_tpch",
    )

    print()
    print("Dry-run complete! Artifacts generated in:", output_dir)
    print()
    print("Next steps:")
    print("1. Review SQL files to verify query translations")
    print("2. Estimate costs using BigQuery Console:")
    print("   - Open BigQuery Console → Paste query → See cost estimate")
    print("3. Run actual benchmark:")
    print("   python examples/getting_started/cloud/bigquery_tpch_power.py")
    print()
    print("Cost estimation tips:")
    print("- BigQuery charges per query byte scanned")
    print("- TPC-H SF=0.01 (~10MB): ~$0.001-0.01 per query run")
    print("- TPC-H SF=1.0 (~1GB): ~$0.10-1.00 per query run")
    print("- Use partitioning/clustering to reduce costs")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview a BigQuery TPC-H run using DryRunExecutor")
    parser.add_argument("--scale", type=float, default=0.01, help="Benchmark scale factor")
    parser.add_argument(
        "--dry-run",
        type=str,
        metavar="OUTPUT_DIR",
        help="Override the default preview directory with OUTPUT_DIR.",
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
