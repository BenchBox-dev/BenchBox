"""Metrics command group for benchmark performance calculations."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import click

from benchbox.cli.shared import console


@click.group("metrics")
def metrics_group():
    """Calculate benchmark performance metrics.

    The metrics command group provides tools for calculating
    official TPC performance metrics from benchmark results.

    Available subcommands:

    \b
      qphh    Calculate TPC-H QphH@Size composite metric

    Examples:
        # Calculate TPC-H QphH metric
        benchbox metrics qphh \\
          --power-results power.json \\
          --throughput-results throughput.json
    """


@metrics_group.command("qphh")
@click.option(
    "--power-results",
    type=click.Path(exists=True),
    required=True,
    help="Path to power test results JSON file",
)
@click.option(
    "--throughput-results",
    type=click.Path(exists=True),
    required=True,
    help="Path to throughput test results JSON file",
)
@click.option(
    "--scale-factor",
    type=float,
    help="Scale factor used (auto-detected from results if not provided)",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format (default: text)",
)
@click.option(
    "--output",
    "output_file",
    type=click.Path(),
    help="Save output to file",
)
@click.pass_context
def qphh(ctx, power_results, throughput_results, scale_factor, output_format, output_file):
    """Calculate TPC-H QphH@Size composite metric.

    Calculate the official TPC-H QphH@Size (Queries per Hour) composite
    metric from power test and throughput test results according to TPC-H
    specification.

    Formula: QphH@Size = sqrt(Power@Size × Throughput@Size)
    Where:
        Power@Size = 3600 × SF / Power_Test_Time
        Throughput@Size = Num_Streams × 3600 × SF / Throughput_Test_Time

    Examples:
        # Calculate QphH from test results
        benchbox metrics qphh \\
          --power-results results/power/results.json \\
          --throughput-results results/throughput/results.json

        # Specify scale factor explicitly
        benchbox metrics qphh \\
          --power-results power.json \\
          --throughput-results throughput.json \\
          --scale-factor 100

        # Export to JSON
        benchbox metrics qphh \\
          --power-results power.json \\
          --throughput-results throughput.json \\
          --format json --output qphh.json
    """
    result = _compute_qphh_result(power_results, throughput_results, scale_factor)
    _emit_qphh_output(result, output_format, output_file)


def _load_result_files(power_results: str, throughput_results: str) -> tuple[dict, dict]:
    """Load and parse power and throughput result JSON files."""
    try:
        with open(Path(power_results), encoding="utf-8") as f:
            power_data = json.load(f)
        with open(Path(throughput_results), encoding="utf-8") as f:
            throughput_data = json.load(f)
        return power_data, throughput_data
    except FileNotFoundError as e:
        console.print(f"[red]Error: Result file not found: {e}[/red]")
        sys.exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error: Invalid JSON in result file: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Unexpected error loading files: {e}[/red]")
        sys.exit(1)


def _resolve_scale_factor(power_data: dict, throughput_data: dict, scale_factor: float | None) -> float:
    """Auto-detect or validate scale factor from result data."""
    if scale_factor is not None:
        return scale_factor

    sf_power = power_data.get("environment", {}).get("scale_factor")
    sf_throughput = throughput_data.get("environment", {}).get("scale_factor")

    if sf_power and sf_throughput:
        if sf_power != sf_throughput:
            console.print(f"[red]Error: Scale factor mismatch: power={sf_power}, throughput={sf_throughput}[/red]")
            sys.exit(1)
        return sf_power

    console.print("[red]Error: Could not auto-detect scale factor. Please specify --scale-factor[/red]")
    sys.exit(1)


def _derive_tpc_metrics(
    power_data: dict, throughput_data: dict, scale_factor: float
) -> tuple[float | None, float | None, float | None, float | None]:
    """Extract or derive Power@Size and Throughput@Size metrics.

    Returns:
        Tuple of (power_at_size, throughput_at_size, power_time, throughput_time)
    """
    power_metrics = power_data.get("summary", {}).get("tpc_metrics", {})
    throughput_metrics = throughput_data.get("summary", {}).get("tpc_metrics", {})

    power_time_ms = power_data.get("summary", {}).get("timing", {}).get("total_ms")
    throughput_time_ms = throughput_data.get("summary", {}).get("timing", {}).get("total_ms")
    power_time = (power_time_ms / 1000.0) if power_time_ms else None
    throughput_time = (throughput_time_ms / 1000.0) if throughput_time_ms else None

    power_at_size = power_metrics.get("power_at_size")
    throughput_at_size = throughput_metrics.get("throughput_at_size")

    _compliance_class = power_data.get("benchmark", {}).get("compliance_class")
    _is_subscale = _compliance_class == "unofficial_subscale"

    if power_at_size is None or throughput_at_size is None:
        from benchbox.core.results.metrics import TPCMetricsCalculator

        if power_at_size is None and not _is_subscale:
            power_query_times = [
                q["ms"] / 1000.0
                for q in power_data.get("queries", [])
                if q.get("run_type") == "measurement" and q.get("status") == "SUCCESS"
            ]
            if power_query_times:
                power_at_size = TPCMetricsCalculator.calculate_power_at_size(power_query_times, scale_factor)

        if throughput_at_size is None and not _is_subscale:
            t_summary = throughput_data.get("summary", {}).get("queries", {})
            total_queries = t_summary.get("total")
            t_time_ms = throughput_data.get("summary", {}).get("timing", {}).get("total_ms")
            if total_queries and t_time_ms:
                num_streams = throughput_data.get("run", {}).get("streams", 1)
                throughput_at_size = TPCMetricsCalculator.calculate_throughput_at_size(
                    total_queries,
                    t_time_ms / 1000.0,
                    scale_factor,
                    num_streams,
                )

    return power_at_size, throughput_at_size, power_time, throughput_time


def _compute_qphh_result(power_results: str, throughput_results: str, scale_factor: float | None) -> dict:
    """Compute the QphH result dictionary from power and throughput result files."""
    power_data, throughput_data = _load_result_files(power_results, throughput_results)
    scale_factor = _resolve_scale_factor(power_data, throughput_data, scale_factor)

    power_at_size, throughput_at_size, power_time, throughput_time = _derive_tpc_metrics(
        power_data, throughput_data, scale_factor
    )

    if power_at_size is None or throughput_at_size is None:
        console.print("[red]Error: Could not derive Power@Size or Throughput@Size from result files[/red]")
        sys.exit(1)

    num_streams = throughput_data.get("run", {}).get("streams") or throughput_data.get("environment", {}).get(
        "num_streams", 1
    )

    qphh_at_size = math.sqrt(power_at_size * throughput_at_size)

    return {
        "benchmark": "TPC-H",
        "scale_factor": scale_factor,
        "num_streams": num_streams,
        "power_test_time": power_time,
        "throughput_test_time": throughput_time,
        "power_at_size": power_at_size,
        "throughput_at_size": throughput_at_size,
        "qphh_at_size": qphh_at_size,
    }


def _emit_qphh_output(result: dict, output_format: str, output_file: str | None) -> None:
    """Format and emit QphH result to console or file."""
    if output_format == "text":
        content = _format_text_output(result)
    elif output_format == "json":
        content = json.dumps(result, indent=2)
    else:
        return

    if output_file:
        Path(output_file).write_text(content, encoding="utf-8")
        console.print(f"[green]Results saved to {output_file}[/green]")
    else:
        console.print(content)


def _format_text_output(result: dict) -> str:
    """Format QphH calculation as human-readable text."""
    lines = []

    lines.append("=" * 70)
    lines.append("TPC-H QphH@Size CALCULATION")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"Benchmark:        {result['benchmark']}")
    lines.append(f"Scale Factor:     {result['scale_factor']}")
    lines.append(f"Num Streams:      {result['num_streams']}")
    lines.append("")
    lines.append("-" * 70)
    lines.append("TEST EXECUTION TIMES")
    lines.append("-" * 70)
    power_time = result.get("power_test_time")
    throughput_time = result.get("throughput_test_time")
    if power_time is not None:
        lines.append(f"Power Test:       {power_time:.3f} seconds")
    else:
        lines.append("Power Test:       n/a")
    if throughput_time is not None:
        lines.append(f"Throughput Test:  {throughput_time:.3f} seconds")
    else:
        lines.append("Throughput Test:  n/a")
    lines.append("")
    lines.append("-" * 70)
    lines.append("TPC-H METRICS")
    lines.append("-" * 70)
    lines.append(f"Power@Size:       {result['power_at_size']:,.2f}")
    lines.append(f"Throughput@Size:  {result['throughput_at_size']:,.2f}")
    lines.append("")
    lines.append("=" * 70)
    lines.append(f"QphH@Size:        {result['qphh_at_size']:,.2f}")
    lines.append("=" * 70)
    lines.append("")
    lines.append("Formula: QphH@Size = sqrt(Power@Size × Throughput@Size)")
    lines.append("  Power@Size = 3600 × SF / Power_Test_Time")
    lines.append("  Throughput@Size = Num_Streams × 3600 × SF / Throughput_Test_Time")
    lines.append("")

    return "\n".join(lines)


__all__ = ["metrics_group", "qphh", "_compute_qphh_result", "_emit_qphh_output"]
