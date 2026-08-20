"""Aggregate multiple benchmark results into trends."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import click

from benchbox.cli.shared import console
from benchbox.core.results.metrics import geometric_mean_ms, percentile_ms


@click.command("aggregate")
@click.option(
    "--input-dir",
    type=click.Path(exists=True),
    required=True,
    help="Directory containing result JSON files",
)
@click.option(
    "--output-file",
    type=click.Path(),
    required=True,
    help="Output CSV file path for aggregated trends",
)
@click.option(
    "--benchmark",
    type=str,
    help="Filter by benchmark name",
)
@click.option(
    "--platform",
    type=str,
    help="Filter by platform name",
)
@click.pass_context
def aggregate(ctx, input_dir, output_file, benchmark, platform):
    """Aggregate multiple benchmark results into performance trends.

    Scan a directory for benchmark result files and aggregate timing metrics
    into a CSV file suitable for tracking performance over time or generating
    visualizations.

    Output includes: timestamp, benchmark, platform, scale, geometric mean,
    total time, and per-query statistics (p50, p95, p99).

    Examples:
        # Aggregate all results in directory
        benchbox aggregate --input-dir benchmark_runs/ --output-file trends.csv

        # Filter by benchmark
        benchbox aggregate \\
          --input-dir benchmark_runs/ \\
          --output-file tpch_trends.csv \\
          --benchmark tpch

        # Filter by platform
        benchbox aggregate \\
          --input-dir benchmark_runs/ \\
          --output-file duckdb_trends.csv \\
          --platform duckdb
    """
    input_path = Path(input_dir)
    output_path = Path(output_file)

    result_files = list(input_path.glob("**/*.json"))

    if not result_files:
        console.print(f"[yellow]No JSON result files found in {input_dir}[/yellow]")
        sys.exit(1)

    console.print(f"[blue]Found {len(result_files)} result files[/blue]")

    aggregated_data = _collect_aggregated_data(result_files, benchmark, platform)

    if not aggregated_data:
        console.print("[yellow]No results matched the filters[/yellow]")
        if benchmark:
            console.print(f"  Benchmark filter: {benchmark}")
        if platform:
            console.print(f"  Platform filter: {platform}")
        sys.exit(1)

    aggregated_data.sort(key=lambda x: x["timestamp"])
    _write_aggregated_csv(output_path, aggregated_data)


def _collect_aggregated_data(
    result_files: list[Path],
    benchmark: str | None,
    platform: str | None,
) -> list[dict]:
    """Load and aggregate timing data from result files."""
    aggregated_data: list[dict] = []

    for result_file in result_files:
        try:
            with open(result_file, encoding="utf-8") as f:
                data = json.load(f)

            row = _extract_result_row(data, result_file)
            if row is None:
                continue

            if benchmark and benchmark.lower() not in row["benchmark"].lower():
                continue
            if platform and platform.lower() not in row["platform"].lower():
                continue

            aggregated_data.append(row)

        except Exception as e:
            console.print(f"[yellow]Warning: Failed to process {result_file.name}: {e}[/yellow]")
            continue

    return aggregated_data


def _extract_result_row(data: dict, result_file: Path) -> dict | None:
    """Extract a single aggregation row from a result file's JSON data."""
    execution = data.get("execution", {})
    benchmark_info = data.get("benchmark", {})
    configuration = data.get("configuration", {})
    results = data.get("results", {})

    bm_name = benchmark_info.get("name", "unknown")
    plat_name = execution.get("platform", "unknown")

    timestamp = execution.get("timestamp", "")
    scale_factor = configuration.get("scale_factor", 0)
    duration_ms = execution.get("duration_ms", 0)

    query_details = results.get("queries", {}).get("details", [])
    times_ms = _successful_query_times_ms(query_details)

    return {
        "timestamp": timestamp,
        "benchmark": bm_name,
        "platform": plat_name,
        "scale_factor": scale_factor,
        "total_time_s": duration_ms / 1000.0,
        # Statistics come from benchbox.core.results.metrics so that a CLI
        # aggregate row and an MCP analytics response over the same bundles
        # report the same numbers.
        "geometric_mean_ms": geometric_mean_ms(times_ms),
        "p50_ms": percentile_ms(times_ms, 0.50),
        "p95_ms": percentile_ms(times_ms, 0.95),
        "p99_ms": percentile_ms(times_ms, 0.99),
        "num_queries": len(query_details),
        "file": result_file.name,
    }


def _successful_query_times_ms(query_details: list[dict]) -> list[float]:
    """Return execution times for successful queries with a positive duration."""
    return [
        query["timing"]["execution_ms"]
        for query in query_details
        if query.get("status") == "SUCCESS" and query.get("timing", {}).get("execution_ms", 0) > 0
    ]


def _write_aggregated_csv(output_path: Path, aggregated_data: list[dict]) -> None:
    """Write aggregated data to CSV file."""
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="", encoding="utf-8") as csvfile:
            fieldnames = [
                "timestamp",
                "benchmark",
                "platform",
                "scale_factor",
                "total_time_s",
                "geometric_mean_ms",
                "p50_ms",
                "p95_ms",
                "p99_ms",
                "num_queries",
                "file",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for row in aggregated_data:
                writer.writerow(row)

        console.print("\n[bold green]✓ Aggregation complete![/bold green]")
        console.print(f"Aggregated {len(aggregated_data)} results")
        console.print(f"Output: {output_path.absolute()}")

    except Exception as e:
        console.print(f"[red]Error writing output file: {e}[/red]")
        sys.exit(1)


__all__ = ["aggregate"]
