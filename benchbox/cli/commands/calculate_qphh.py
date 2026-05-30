"""Deprecated calculate-qphh compatibility command."""

import click

from benchbox.cli.shared import console


@click.command("calculate-qphh", hidden=True, deprecated=True)
@click.option("--power-results", type=click.Path(exists=True), required=True, help="Path to power results JSON")
@click.option(
    "--throughput-results",
    type=click.Path(exists=True),
    required=True,
    help="Path to throughput results JSON",
)
@click.option("--scale-factor", type=float, help="Scale factor, auto-detected when omitted")
@click.option("--format", "output_format", type=click.Choice(["text", "json"], case_sensitive=False), default="text")
@click.option("--output", "output_file", type=click.Path(), help="Save output to file")
def calculate_qphh(power_results, throughput_results, scale_factor, output_format, output_file):
    """Calculate TPC-H QphH@Size. Deprecated; use `benchbox metrics qphh`."""
    console.print(
        "[yellow]DeprecationWarning: 'benchbox calculate-qphh' is deprecated. "
        "Use 'benchbox metrics qphh' instead.[/yellow]\n"
    )

    from benchbox.cli.commands.metrics import _compute_qphh_result, _emit_qphh_output

    _emit_qphh_output(_compute_qphh_result(power_results, throughput_results, scale_factor), output_format, output_file)
