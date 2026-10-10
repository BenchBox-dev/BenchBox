#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

import json
from pathlib import Path


def analyze_dry_run_output(dry_run_dir: str):
    dry_run_path = Path(dry_run_dir)

    if not dry_run_path.exists():
        print(f"❌ Dry run directory not found: {dry_run_dir}")
        print("\nRun a dry-run first:")
        print(f"  benchbox run --dry-run {dry_run_dir} --platform duckdb --benchmark tpch --scale 0.01")
        return

    candidates = sorted(dry_run_path.glob("*.json"))
    if not candidates:
        print(f"❌ Summary file not found in: {dry_run_dir}")
        return
    summary_file = candidates[-1]
    with open(summary_file, encoding="utf-8") as f:
        summary = json.load(f)

    system = summary["system_profile"]
    benchmark = summary["benchmark_config"]

    print("=" * 60)
    print("Dry Run Analysis")
    print("=" * 60)

    print("\nSystem:")
    print(f"  - OS: {system['os_name']}")
    print(f"  - Memory: {system['memory_total_gb']:.1f} GB")
    print(f"  - CPU Cores: {system.get('cpu_cores_physical', 'N/A')}")

    print("\nBenchmark:")
    print(f"  - Name: {benchmark['name']}")
    print(f"  - Scale Factor: {benchmark['scale_factor']}")

    query_dirs = sorted(dry_run_path.glob("*_queries_*"))
    if query_dirs:
        query_files = list(query_dirs[0].glob("*.sql"))
        print("\nQueries:")
        print(f"  - Total: {len(query_files)}")

        print("\n  Complexity analysis:")
        for query_file in query_files[:5]:
            with open(query_file, encoding="utf-8") as f:
                content = f.read()
                joins = content.upper().count("JOIN")
                complexity = "High" if joins > 3 else "Medium" if joins > 1 else "Low"
                print(f"    - {query_file.name}: {joins} joins, complexity: {complexity}")

        if len(query_files) > 5:
            print(f"    ... and {len(query_files) - 5} more queries")

    if "estimated_resources" in summary:
        resources = summary["estimated_resources"]
        print("\nResource Estimates:")
        print(f"  - Memory: ~{resources.get('estimated_memory_usage_mb', 'N/A')} MB")
        print(f"  - Data: ~{resources.get('estimated_data_size_mb', 'N/A')} MB")

    print("\n✅ Analysis complete!")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        analyze_dry_run_output(sys.argv[1])
    else:
        print("Usage: python analyze_dry_run_output.py <dry_run_directory>")
        print("\nExample:")
        print("  python analyze_dry_run_output.py ./tpch_preview")
        print("\nOr run directly:")
        analyze_dry_run_output("./dry_run_preview")
