"""Deprecated run-official compatibility command."""

import sys

import click

from benchbox.cli.commands.run import run
from benchbox.cli.shared import console

TPC_ALLOWED_SCALE_FACTORS = {1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000}


@click.command("run-official", hidden=True, deprecated=True)
@click.argument("benchmark", type=click.Choice(["tpch", "tpcds"], case_sensitive=False))
@click.option("--platform", type=str, required=True, help="Platform to run on")
@click.option("--scale", type=float, required=True, help="TPC scale factor")
@click.option("--phases", type=str, required=True, help="Test phases, comma-separated")
@click.option("--streams", type=int, help="Concurrent streams for throughput")
@click.option("--seed", type=int, help="Random seed for reproducible official runs")
@click.option("--output", "output_dir", type=click.Path(), help="Output directory")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.option("--validate-results", is_flag=True, help="Enable result validation")
@click.pass_context
def run_official(ctx, benchmark, platform, scale, phases, streams, seed, output_dir, verbose, validate_results):
    """Run TPC-compliant official benchmark tests. Deprecated; use `benchbox run --official`."""
    console.print(
        "[yellow]DeprecationWarning: 'benchbox run-official' is deprecated. "
        "Use 'benchbox run --official' instead.[/yellow]\n"
    )

    if scale not in TPC_ALLOWED_SCALE_FACTORS:
        console.print(f"[red]Error: Scale factor {scale} is not TPC-compliant[/red]")
        console.print(f"Allowed scale factors: {sorted(TPC_ALLOWED_SCALE_FACTORS)}")
        sys.exit(1)

    if seed is None:
        console.print("[yellow]Warning: No seed specified. Official TPC runs require a random seed.[/yellow]")
        console.print("Use --seed <N> for reproducible results")

    if "throughput" in {phase.strip().lower() for phase in phases.split(",")} and streams is None:
        console.print("[red]Error: --streams is required for throughput test[/red]")
        sys.exit(1)

    _print_official_summary(benchmark, platform, scale, phases, streams, seed)
    run_args = _run_args(benchmark, platform, scale, phases, seed, output_dir, verbose, validate_results)

    if streams:
        console.print(
            f"[yellow]Note: Stream configuration ({streams} streams) will be applied "
            "if supported by the benchmark[/yellow]"
        )

    try:
        ctx.invoke(run, **run_args)
    except Exception as e:
        console.print(f"[red]Benchmark execution failed: {e}[/red]")
        sys.exit(1)


def _print_official_summary(benchmark, platform, scale, phases, streams, seed) -> None:
    console.print("[bold blue]TPC-Compliant Official Benchmark Run[/bold blue]")
    for label, value in [
        ("Benchmark", f"TPC-{benchmark.upper()}"),
        ("Platform", platform),
        ("Scale Factor", scale),
        ("Phases", phases),
        ("Streams", streams),
        ("Seed", seed),
    ]:
        if value is not None:
            console.print(f"{label}: {value}")
    console.print("")


def _run_args(benchmark, platform, scale, phases, seed, output_dir, verbose, validate_results) -> dict:
    args = {
        "platform": platform,
        "benchmark": benchmark,
        "scale": scale,
        "phases": phases,
        "official": True,
    }
    optional = {
        "seed": seed,
        "output": output_dir,
        "verbose": True if verbose else None,
        "validate_results": True if validate_results else None,
    }
    args.update({key: value for key, value in optional.items() if value is not None})
    return args
