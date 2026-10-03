import click
from rich.panel import Panel
from rich.text import Text

from benchbox.cli.shared import console
from benchbox.cli.system import SystemProfiler


@click.command(
    "profile",
    help=(
        "Profile the current system and provide optimization recommendations.\n"
        "\n"
        "Analyzes CPU, memory, disk space, and system configuration to recommend\n"
        "appropriate scale factors and benchmark configurations.\n"
        "\n"
        "\b\n"
        "Examples:\n"
        "    benchbox profile"
    ),
)
@click.pass_context
def profile(ctx):
    console.print(Panel.fit(Text("System Profile", style="bold green"), style="green"))

    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()
    profiler.display_profile(system_profile, detailed=True)


__all__ = ["profile"]
