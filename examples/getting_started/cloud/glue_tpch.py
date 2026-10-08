from __future__ import annotations

import argparse
import os
from pathlib import Path

from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.core.config import BenchmarkConfig, DatabaseConfig
from benchbox.core.system import SystemProfiler
from benchbox.examples import execute_example_dry_run

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_OUTPUT_DIR = _PROJECT_ROOT / "benchmark_runs" / "getting_started" / "glue"


def _require_env(var_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        raise RuntimeError(
            f"Missing environment variable {var_name}. Set AWS/Glue configuration before running this example."
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

    staging_dir = _require_env("GLUE_S3_STAGING_DIR")
    job_role = _require_env("GLUE_JOB_ROLE")

    database_config = DatabaseConfig(
        type="glue",
        name="glue_tpch",
        options={
            "s3_staging_dir": staging_dir,
            "job_role": job_role,
            "region": os.getenv("AWS_REGION", "us-east-1"),
            "database": os.getenv("GLUE_DATABASE", "benchbox"),
            "worker_type": os.getenv("GLUE_WORKER_TYPE", "G.1X"),
            "number_of_workers": int(os.getenv("GLUE_NUM_WORKERS", "2")),
            "glue_version": os.getenv("GLUE_VERSION", "4.0"),
            "aws_profile": os.getenv("AWS_PROFILE"),
            "default_format": "parquet",
            "compression": "snappy",
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
            filename_prefix="glue_tpch",
        )
        print()
        print("Dry-run complete! Review SQL files before running on AWS Glue.")
        print()
        print("Cost estimation (Glue charges ~$0.44/DPU-hour):")
        print(f"- TPC-H SF={scale_factor}:")
        num_workers = int(os.getenv("GLUE_NUM_WORKERS", "2"))
        worker_type = os.getenv("GLUE_WORKER_TYPE", "G.1X")
        dpu_per_worker = 2.0 if worker_type == "G.2X" else 1.0
        total_dpu = num_workers * dpu_per_worker
        minutes_per_query = 2 if scale_factor >= 1.0 else 1
        hours = (22 * minutes_per_query) / 60
        cost = hours * total_dpu * 0.44
        print(f"  - {num_workers}x {worker_type} workers: ~${cost:.2f} for full benchmark")
        print()
        print("Before running:")
        print("1. Verify S3 bucket exists and is accessible")
        print("2. Check IAM role has Glue and S3 permissions")
        print("3. Review query translations in generated SQL files")
        print("4. Monitor job progress in AWS Glue console")
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
    print("- Review results.json for query timings")
    print("- Check Glue console for job history and DPU usage")
    print("- Compare with other platforms using result_analysis.py")
    print("- Clean up S3 data: aws s3 rm --recursive s3://bucket/benchbox/")
    print()
    print("Cost optimization tips:")
    print("- Use G.025X workers for development/testing")
    print("- Increase workers for larger scale factors")
    print("- Monitor DPU utilization in Glue metrics")
    print("- Use Spark UI to identify bottlenecks")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run TPC-H on AWS Glue")
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
