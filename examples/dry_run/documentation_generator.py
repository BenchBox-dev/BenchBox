#!/usr/bin/env python3
"""Documentation Generation with Dry Run

Demonstrates how to automatically generate benchmark documentation
using dry-run output. Creates markdown documentation with query
counts, table schemas, and resource requirements.

Useful for:
- Automated documentation generation
- Benchmark comparison reports
- Project documentation
- Platform evaluation

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import json
import shutil
import subprocess
from pathlib import Path


def generate_benchmark_documentation(benchmark_name: str, output_dir: str = "./docs"):
    """Generate benchmark documentation from dry run output.

    Args:
        benchmark_name: Name of benchmark (e.g., 'tpch', 'tpcds', 'ssb')
        output_dir: Directory to save generated documentation

    Returns:
        Path to generated documentation file
    """
    dry_run_dir = f"./temp_dry_run_{benchmark_name}"

    print(f"Generating documentation for {benchmark_name}...")

    # Execute dry run
    print("  1. Running dry-run...")
    try:
        subprocess.run(
            [
                "benchbox",
                "run",
                "--dry-run",
                dry_run_dir,
                "--platform",
                "duckdb",
                "--benchmark",
                benchmark_name,
                "--scale",
                "0.01",
            ],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Dry-run failed: {e}")
        return None

    # Load results and generate markdown
    print("  2. Analyzing results...")
    with open(Path(dry_run_dir) / "summary.json", encoding="utf-8") as f:
        summary = json.load(f)

    doc_content = [
        f"# {benchmark_name.upper()} Benchmark Documentation",
        "",
        "*Generated from BenchBox dry run analysis*",
        "",
        "## Overview",
        "",
        f"- **Query Count**: {len(summary.get('queries', {}))}",
        f"- **Table Count**: {len(summary.get('schema_info', {}).get('tables', {}))}",
    ]

    # Add resource requirements if available
    if "resource_estimates" in summary:
        resources = summary["resource_estimates"]
        doc_content.extend(
            [
                "",
                "## Resource Requirements",
                "",
                f"- **Memory**: ~{resources.get('estimated_memory_mb', 'N/A')} MB",
                f"- **Storage**: ~{resources.get('estimated_storage_mb', 'N/A')} MB",
            ]
        )

    # Add table information
    if "schema_info" in summary and "tables" in summary["schema_info"]:
        tables = summary["schema_info"]["tables"]
        doc_content.extend(["", "## Tables", ""])
        for table_name, table_info in tables.items():
            doc_content.append(f"- **{table_name}**: {table_info.get('column_count', 'N/A')} columns")

    # Add query list
    if "queries" in summary:
        queries = summary["queries"]
        doc_content.extend(["", "## Queries", ""])
        for query_id in sorted(queries.keys()):
            doc_content.append(f"- Query {query_id}")

    # Write documentation
    print("  3. Writing documentation...")
    doc_file = Path(output_dir) / f"{benchmark_name.lower()}_benchmark.md"
    doc_file.parent.mkdir(parents=True, exist_ok=True)
    doc_file.write_text("\n".join(doc_content))

    # Cleanup
    print("  4. Cleaning up...")
    if Path(dry_run_dir).exists():
        shutil.rmtree(dry_run_dir)

    print(f"✅ Documentation generated: {doc_file}")
    return doc_file


if __name__ == "__main__":
    import sys

    # Parse command line arguments
    if len(sys.argv) > 1:
        benchmarks = sys.argv[1:]
    else:
        benchmarks = ["tpch", "ssb"]
        print("Generating documentation for default benchmarks: tpch, ssb")
        print("Usage: python documentation_generator.py <benchmark1> <benchmark2> ...\n")

    # Generate docs for multiple benchmarks
    print("=" * 60)
    print("BenchBox Documentation Generator")
    print("=" * 60)

    output_dir = "./generated_docs"
    generated_files = []

    for benchmark in benchmarks:
        doc_file = generate_benchmark_documentation(benchmark, output_dir)
        if doc_file:
            generated_files.append(doc_file)
        print()

    # Summary
    print("=" * 60)
    print(f"Generated {len(generated_files)} documentation files:")
    for f in generated_files:
        print(f"  - {f}")
    print("=" * 60)
