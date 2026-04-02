"""Calculate TPC-H QphH composite metric command."""

from __future__ import annotations

import click

from benchbox.cli.shared import console


@click.command("calculate-qphh", hidden=True, deprecated=True)
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
def calculate_qphh(ctx, power_results, throughput_results, scale_factor, output_format, output_file):
    """Calculate TPC-H QphH@Size composite metric.

    DEPRECATED: Use 'benchbox metrics qphh' instead.

    Migration: Replace 'benchbox calculate-qphh --power-results X --throughput-results Y'
    with 'benchbox metrics qphh --power-results X --throughput-results Y'

    Calculate the official TPC-H QphH@Size (Queries per Hour) composite
    metric from power test and throughput test results according to TPC-H
    specification.

    Formula: QphH@Size = sqrt(Power@Size × Throughput@Size)
    Where:
        Power@Size = 3600 × SF / Power_Test_Time
        Throughput@Size = Num_Streams × 3600 × SF / Throughput_Test_Time

    Examples:
        # Calculate QphH from test results
        benchbox calculate-qphh \\
          --power-results results/power/results.json \\
          --throughput-results results/throughput/results.json

        # Specify scale factor explicitly
        benchbox calculate-qphh \\
          --power-results power.json \\
          --throughput-results throughput.json \\
          --scale-factor 100

        # Export to JSON
        benchbox calculate-qphh \\
          --power-results power.json \\
          --throughput-results throughput.json \\
          --format json --output qphh.json
    """
    # Show deprecation warning
    console.print(
        "[yellow]DeprecationWarning: 'benchbox calculate-qphh' is deprecated. "
        "Use 'benchbox metrics qphh' instead.[/yellow]"
    )
    console.print()

    from benchbox.cli.commands.metrics import _compute_qphh_result, _emit_qphh_output

    result = _compute_qphh_result(power_results, throughput_results, scale_factor)
    _emit_qphh_output(result, output_format, output_file)


__all__ = ["calculate_qphh"]
