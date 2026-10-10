#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

from pathlib import Path

from benchbox.cli.dryrun import DryRunExecutor
from benchbox.cli.system import SystemProfiler
from benchbox.core.config import BenchmarkConfig
from benchbox.core.schemas import DatabaseConfig


def main():
    print("=" * 60)
    print("BenchBox Dry Run Example")
    print("=" * 60)

    preview_dir = Path("./dry_run_preview")
    print(f"\nPreview directory: {preview_dir}")

    dry_run = DryRunExecutor(preview_dir)
    result = dry_run.execute_dry_run(
        benchmark_config=BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01),
        system_profile=SystemProfiler().get_system_profile(),
        database_config=DatabaseConfig(type="duckdb", name="DuckDB"),
    )

    print("\n Dry Run Results:")
    print(f"  - Extracted {len(result.queries)} queries")
    print(f"  - Memory estimate: {result.estimated_resources.get('estimated_memory_usage_mb')} MB")
    print(f"  - Data size estimate: {result.estimated_resources.get('estimated_data_size_mb')} MB")

    saved = dry_run.save_dry_run_results(result, filename_prefix="tpch_duckdb")

    print("\n Preview artifacts saved to:")
    print(f"  - Summary: {saved['json'].name}")
    print(f"  - Queries: {saved['queries_dir'].name}/")
    print(f"  - Schema: {saved['schema'].name}")

    print("\n✅ Dry run complete!")
    print("\nNext steps:")
    print(f"  1. Review queries in {saved['queries_dir']}/")
    print("  2. Check the summary JSON for resource estimates")
    print("  3. Run with: benchbox run --platform duckdb --benchmark tpch --scale 0.01")


if __name__ == "__main__":
    main()
