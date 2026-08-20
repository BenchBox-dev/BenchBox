"""System profiling command implementation."""

import click
from rich.panel import Panel
from rich.text import Text

from benchbox.cli.shared import console
from benchbox.cli.system import SystemProfiler


@click.command("profile")
@click.pass_context
def profile(ctx):
    """Profile the current system and provide optimization recommendations.

    Analyzes CPU, memory, disk space, and system configuration to recommend
    appropriate scale factors and benchmark configurations.

    Examples:
        benchbox profile
    """
    console.print(Panel.fit(Text("System Profile", style="bold green"), style="green"))

    profiler = SystemProfiler()
    system_profile = profiler.get_system_profile()
    profiler.display_profile(system_profile, detailed=True)


__all__ = ["profile"]
