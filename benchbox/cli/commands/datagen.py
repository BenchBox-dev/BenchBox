"""Data generation command implementation."""

from __future__ import annotations

import click

from benchbox.cli.commands.run import run
from benchbox.cli.shared import console


@click.command("datagen")
@click.option(
    "--benchmark",
    type=str,
    required=True,
    help="Benchmark name (e.g., tpch, tpcds, clickbench)",
)
@click.option(
    "--scale",
    type=float,
    required=True,
    help="Scale factor for data generation",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(),
    help="Output directory for generated data",
)
@click.option(
    "--format",
    "data_format",
    type=click.Choice(["parquet", "csv", "json"], case_sensitive=False),
    default="parquet",
    help="Data format (default: parquet)",
)
@click.option(
    "--seed",
    type=int,
    help="Random seed for reproducible data generation",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Enable verbose logging",
)
@click.pass_context
def datagen(ctx, benchmark, scale, output_dir, data_format, seed, verbose):
    """Generate benchmark data without running queries.

    Standalone data generation command that generates benchmark data files
    without loading or executing queries. Useful for pre-generating data
    that can be reused across multiple benchmark runs.

    This is a convenience wrapper for: benchbox run --phases generate

    Examples:
        # Generate TPC-H data at scale factor 0.1
        benchbox datagen --benchmark tpch --scale 0.1 --output ./data/tpch_0.1

        # Generate TPC-DS data with specific seed
        benchbox datagen --benchmark tpcds --scale 1 --seed 42 --output ./data/tpcds_1

        # Generate ClickBench data
        benchbox datagen --benchmark clickbench --scale 1 --output ./data/clickbench

        # Generate with verbose logging
        benchbox datagen --benchmark tpch --scale 0.01 --output ./data --verbose
    """
    console.print("[bold blue]Running data generation...[/bold blue]")
    console.print(f"Benchmark: {benchmark}, Scale: {scale}")

    if output_dir:
        console.print(f"Output: {output_dir}")

    # Build arguments for the run command
    # We use a dummy platform since --phases generate doesn't actually connect to a platform
    run_args = [
        "--platform",
        "duckdb",  # Dummy platform (not used for generate phase)
        "--benchmark",
        benchmark,
        "--scale",
        str(scale),
        "--phases",
        "generate",
    ]

    if output_dir:
        run_args.extend(["--output", output_dir])

    if seed is not None:
        run_args.extend(["--seed", str(seed)])

    if verbose:
        run_args.append("--verbose")

    # Note: data_format is not directly supported by run command yet
    # This would need to be added to the run command implementation
    if data_format and data_format != "parquet":
        console.print(
            f"[yellow]Note: Format '{data_format}' requested but may not be supported. "
            "Default format will be used.[/yellow]"
        )

    # Invoke the run command with generate phase
    ctx.invoke(run, **_parse_run_args(run_args))


def _parse_run_args(args: list[str]) -> dict:
    """Parse run command arguments into a dict for context.invoke()."""
    parsed = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--"):
            key = arg[2:].replace("-", "_")
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                value = args[i + 1]
                i += 2
                # Convert types
                if key == "scale":
                    parsed[key] = float(value)
                elif key == "seed":
                    parsed[key] = int(value)
                else:
                    parsed[key] = value
            else:
                # Boolean flag
                parsed[key] = True
                i += 1
        else:
            i += 1

    return parsed


__all__ = ["datagen"]
