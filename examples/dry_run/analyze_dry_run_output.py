#!/usr/bin/env python3
"""Dry Run Output Analysis

Demonstrates how to programmatically analyze dry-run output to extract
information about queries, schemas, and resource requirements.

Useful for:
- Automated analysis of benchmark complexity
- Comparing different benchmarks
- Generating reports
- CI/CD integration

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import json
from pathlib import Path


def analyze_dry_run_output(dry_run_dir: str):
    """Analyze dry run output and display key information.

    Args:
        dry_run_dir: Path to directory containing dry-run output
    """
    dry_run_path = Path(dry_run_dir)

    if not dry_run_path.exists():
        print(f"❌ Dry run directory not found: {dry_run_dir}")
        print("\nRun a dry-run first:")
        print(f"  benchbox run --dry-run {dry_run_dir} --platform duckdb --benchmark tpch --scale 0.01")
        return

    # Load summary
    summary_file = dry_run_path / "summary.json"
    if not summary_file.exists():
        print(f"❌ Summary file not found: {summary_file}")
        return

    with open(summary_file, encoding="utf-8") as f:
        summary = json.load(f)

    # Extract key information
    system = summary["system_profile"]
    benchmark = summary["benchmark_config"]

    print("=" * 60)
    print("Dry Run Analysis")
    print("=" * 60)

    print("\nSystem:")
    print(f"  - OS: {system['os']}")
    print(f"  - Memory: {system['memory_gb']:.1f} GB")
    print(f"  - CPU Cores: {system.get('cpu_cores', 'N/A')}")

    print("\nBenchmark:")
    print(f"  - Name: {benchmark['name']}")
    print(f"  - Scale Factor: {benchmark['scale_factor']}")

    # Analyze queries
    queries_dir = dry_run_path / "queries"
    if queries_dir.exists():
        query_files = list(queries_dir.glob("*.sql"))
        print("\nQueries:")
        print(f"  - Total: {len(query_files)}")

        # Analyze complexity for first few queries
        print("\n  Complexity analysis:")
        for query_file in query_files[:5]:
            with open(query_file, encoding="utf-8") as f:
                content = f.read()
                joins = content.upper().count("JOIN")
                complexity = "High" if joins > 3 else "Medium" if joins > 1 else "Low"
                print(f"    - {query_file.name}: {joins} joins, complexity: {complexity}")

        if len(query_files) > 5:
            print(f"    ... and {len(query_files) - 5} more queries")

    # Resource estimates
    if "resource_estimates" in summary:
        resources = summary["resource_estimates"]
        print("\nResource Estimates:")
        print(f"  - Memory: ~{resources.get('estimated_memory_mb', 'N/A')} MB")
        print(f"  - Storage: ~{resources.get('estimated_storage_mb', 'N/A')} MB")

    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        analyze_dry_run_output(sys.argv[1])
    else:
        # Example usage
        print("Usage: python analyze_dry_run_output.py <dry_run_directory>")
        print("\nExample:")
        print("  python analyze_dry_run_output.py ./tpch_preview")
        print("\nOr run directly:")
        analyze_dry_run_output("./dry_run_preview")
