import click
from rich.panel import Panel
from rich.text import Text

from benchbox.cli.benchmarks import BenchmarkManager
from benchbox.cli.shared import console


@click.group(help=("Manage benchmark suites."))
def benchmarks():
    pass


@benchmarks.command(
    "list",
    help=(
        "List available benchmark suites with descriptions and characteristics.\n"
        "\n"
        "Shows all supported benchmarks including TPC standards (TPC-H, TPC-DS, TPC-DI),\n"
        "industry benchmarks (ClickBench, H2ODB), academic benchmarks (SSB, AMPLab),\n"
        "and testing benchmarks (ReadPrimitives, WritePrimitives, TPC-Havoc).\n"
        "\n"
        "\b\n"
        "Examples:\n"
        "    benchbox benchmarks list"
    ),
)
@click.pass_context
def list_benchmarks(ctx):
    console.print(Panel.fit(Text("Available Benchmarks", style="bold cyan"), style="cyan"))

    bench_manager = BenchmarkManager()
    bench_manager.list_available_benchmarks()


__all__ = ["benchmarks", "list_benchmarks"]
