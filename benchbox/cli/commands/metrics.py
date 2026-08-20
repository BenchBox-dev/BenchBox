"""Metrics command group for benchmark performance calculations."""

from __future__ import annotations

import json
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

    Formula: QphH@Size = geometric_mean(Power@Size, Throughput@Size)
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
    """Auto-detect or validate scale factor from result data.

    Thin CLI wrapper over :meth:`benchbox.core.results.metrics.TPCMetricsCalculator.resolve_scale_factor`.
    Converts ``ValueError`` to the CLI's console+exit behaviour to keep
    user-facing messages unchanged.
    """
    from benchbox.core.results.metrics import TPCMetricsCalculator

    try:
        return TPCMetricsCalculator.resolve_scale_factor(power_data, throughput_data, scale_factor)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


def _derive_tpc_metrics(
    power_data: dict, throughput_data: dict, scale_factor: float
) -> tuple[float | None, float | None, float | None, float | None]:
    """Extract or derive Power@Size and Throughput@Size metrics.

    Thin CLI wrapper over :meth:`benchbox.core.results.metrics.TPCMetricsCalculator.derive_tpc_metrics`.
    """
    from benchbox.core.results.metrics import TPCMetricsCalculator

    return TPCMetricsCalculator.derive_tpc_metrics(power_data, throughput_data, scale_factor)


def _compute_qphh_result(power_results: str, throughput_results: str, scale_factor: float | None) -> dict:
    """Compute the QphH result dictionary from power and throughput result files.

    CLI keeps file I/O and output/error handling; derivation and composition
    are delegated to :meth:`benchbox.core.results.metrics.TPCMetricsCalculator.compute_qphh_result`.
    """
    power_data, throughput_data = _load_result_files(power_results, throughput_results)
    from benchbox.core.results.metrics import TPCMetricsCalculator

    try:
        return TPCMetricsCalculator.compute_qphh_result(power_data, throughput_data, scale_factor)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


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
    lines.append("Formula: QphH@Size = geometric_mean(Power@Size, Throughput@Size)")
    lines.append("  Power@Size = 3600 × SF / Power_Test_Time")
    lines.append("  Throughput@Size = Num_Streams × 3600 × SF / Throughput_Test_Time")
    lines.append("")

    return "\n".join(lines)


__all__ = ["metrics_group", "qphh", "_compute_qphh_result", "_emit_qphh_output"]
