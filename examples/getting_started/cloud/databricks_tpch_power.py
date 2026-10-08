from __future__ import annotations

import argparse
import os
from pathlib import Path

from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.core.system import SystemProfiler
from benchbox.examples import execute_example_dry_run

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "databricks"


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(
            f"Missing environment variable {var_name}. Set Databricks credentials before running this example."
        )
    return value


def _build_configs(scale_factor: float) -> tuple[BenchmarkConfig, DatabaseConfig]:
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        scale_factor=scale_factor,
        test_execution_type="power",
        options={"enable_preflight_validation": False},
    )

    database_config = DatabaseConfig(
        type="databricks",
        name="databricks_tpch_power",
        options={
            "server_hostname": _require_env("DATABRICKS_HOST"),
            "http_path": _require_env("DATABRICKS_HTTP_PATH"),
            "access_token": _require_env("DATABRICKS_TOKEN"),
            "catalog": os.getenv("DATABRICKS_CATALOG", "workspace"),
            "schema": os.getenv("DATABRICKS_SCHEMA", "benchbox"),
            "staging_root": os.getenv("DATABRICKS_STAGING_ROOT"),
        },
    )

    return benchmark_config, database_config


def run_example(scale_factor: float = 0.01, *, dry_run_output: Path | None = None) -> None:
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    benchmark_config, database_config = _build_configs(scale_factor)

    if dry_run_output is not None:
        execute_example_dry_run(
            benchmark_config=benchmark_config,
            database_config=database_config,
            output_dir=Path(dry_run_output),
            filename_prefix="databricks_tpch_power",
        )
        print()
        print("Dry-run complete! Review SQL files before running on Databricks.")
        print()
        print("Cost considerations:")
        print("- Databricks charges per DBU (Databricks Unit)")
        print("- SQL Warehouse costs ~$0.22-0.55 per DBU-hour")
        print("- TPC-H SF=0.01: ~0.01-0.1 DBU (< $0.01)")
        print("- TPC-H SF=1.0: ~0.1-1.0 DBU (~$0.05-0.50)")
        print("- Use Serverless for on-demand, Classic for predictable costs")
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
    print("- Review results.json for detailed metrics")
    print("- Check Databricks SQL History for query execution details")
    print("- Compare with other platforms using result_analysis.py")
    print("- Cleanup: DROP SCHEMA benchbox CASCADE (if temporary)")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TPC-H on Databricks (power test)")
    parser.add_argument("--scale", type=float, default=0.01, help="Benchmark scale factor")
    parser.add_argument(
        "--dry-run",
        type=str,
        metavar="OUTPUT_DIR",
        help="Preview the Databricks run plan without executing; artifacts are written to OUTPUT_DIR.",
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
