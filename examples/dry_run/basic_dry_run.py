#!/usr/bin/env python3
"""Basic Dry Run Preview

Demonstrates how to use BenchBox dry-run mode to preview benchmark
configurations, queries, and resource estimates without executing them.

This is essential for:
- Development and debugging
- Cost estimation before cloud execution
- Documentation generation
- Understanding benchmark complexity

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from pathlib import Path

from benchbox.cli.database import DatabaseConfig
from benchbox.cli.dryrun import DryRunExecutor
from benchbox.cli.system import SystemProfiler
from benchbox.core.config import BenchmarkConfig


def main():
    """Execute a basic dry run and display results."""
    print("=" * 60)
    print("BenchBox Dry Run Example")
    print("=" * 60)

    # Setup dry run configuration
    preview_dir = Path("./dry_run_preview")
    print(f"\nPreview directory: {preview_dir}")

    # Setup and execute dry run
    dry_run = DryRunExecutor(preview_dir)
    result = dry_run.execute_dry_run(
        benchmark_config=BenchmarkConfig(name="tpch", scale_factor=0.01),
        system_profile=SystemProfiler().get_system_profile(),
        database_config=DatabaseConfig(platform="duckdb"),
    )

    # Display results
    print("\n Dry Run Results:")
    print(f"  - Extracted {len(result.queries)} queries")
    print(f"  - Memory estimate: {result.resource_estimates.estimated_memory_mb} MB")
    print(f"  - Storage estimate: {result.resource_estimates.estimated_storage_mb} MB")

    # Show where output was saved
    print("\n Preview artifacts saved to:")
    print(f"  - Summary: {preview_dir / 'summary.json'}")
    print(f"  - Queries: {preview_dir / 'queries/'}")
    print(f"  - Schema: {preview_dir / 'schema.sql'}")

    print("\n✅ Dry run complete!")
    print("\nNext steps:")
    print(f"  1. Review queries in {preview_dir / 'queries/'}")
    print("  2. Check summary.json for resource estimates")
    print("  3. Run with: benchbox run --platform duckdb --benchmark tpch --scale 0.01")


if __name__ == "__main__":
    main()
