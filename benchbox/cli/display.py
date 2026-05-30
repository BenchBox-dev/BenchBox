"""System-profile CLI display helpers.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from benchbox.core.schemas import SystemProfile
from benchbox.utils.printing import quiet_console


class StandardDisplays:
    """Standardized display components for CLI."""

    def __init__(self, console: Console | None = None):
        self.console = console or quiet_console

    def show_system_profile(self, profile: SystemProfile, detailed: bool = False) -> None:
        """Display system profile in standardized format."""
        table = Table(title="System Information", show_header=True, header_style="bold magenta")
        table.add_column("Property", style="cyan", width=25)
        table.add_column("Value", style="white")

        # Basic information
        table.add_row("OS", f"{profile.os_name} {profile.os_version}")
        table.add_row("Architecture", profile.architecture)
        table.add_row("CPU", profile.cpu_model)
        table.add_row(
            "CPU Cores",
            f"{profile.cpu_cores_physical} physical, {profile.cpu_cores_logical} logical",
        )
        table.add_row(
            "Memory",
            f"{profile.memory_total_gb:.1f} GB total, {profile.memory_available_gb:.1f} GB available",
        )
        table.add_row("Python", profile.python_version)

        if detailed:
            table.add_row("Disk Space", f"{profile.disk_space_gb:.1f} GB free")
            if profile.hostname:
                table.add_row("Hostname", profile.hostname)
            table.add_row("Timestamp", profile.timestamp.strftime("%Y-%m-%d %H:%M:%S"))

        self.console.print(table)


def create_display_manager(console: Console | None = None) -> StandardDisplays:
    """Factory function to create display manager."""
    return StandardDisplays(console)


def show_system_info(profile: SystemProfile, console: Console | None = None, detailed: bool = False) -> None:
    """Convenience function to show system information."""
    display = create_display_manager(console)
    display.show_system_profile(profile, detailed)
