"""Benchmark management commands."""

import click
from rich.panel import Panel
from rich.text import Text

from benchbox.cli.benchmarks import BenchmarkManager
from benchbox.cli.shared import console


@click.group()
def benchmarks():
    """Manage benchmark suites."""


@benchmarks.command("list")
@click.pass_context
def list_benchmarks(ctx):
    """List available benchmark suites with descriptions and characteristics.

    Shows all supported benchmarks including TPC standards (TPC-H, TPC-DS, TPC-DI),
    industry benchmarks (ClickBench, H2ODB), academic benchmarks (SSB, AMPLab),
    and testing benchmarks (ReadPrimitives, WritePrimitives, TPC-Havoc).

    Examples:
        benchbox benchmarks list
    """
    console.print(Panel.fit(Text("Available Benchmarks", style="bold cyan"), style="cyan"))

    bench_manager = BenchmarkManager()
    bench_manager.list_available_benchmarks()


__all__ = ["benchmarks", "list_benchmarks"]
