"""Dependency check command implementation."""

from collections.abc import Callable
from typing import Any

import click
from rich.markup import escape
from rich.table import Table

from benchbox.cli.shared import console


@click.command("check-deps")
@click.option("--platform", type=str, help="Check dependencies for specific platform")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed dependency information")
@click.option(
    "--matrix",
    "show_matrix",
    is_flag=True,
    help="Show installation matrix and exit",
)
@click.pass_context
def check_dependencies(ctx, platform, verbose, show_matrix):
    """Check dependency status and provide installation guidance.

    Verifies platform dependencies and provides installation commands for
    missing packages. Shows comprehensive installation matrix for all platforms.

    Examples:
        benchbox check-deps                      # Overview of all platforms
        benchbox check-deps --platform databricks # Check specific platform
        benchbox check-deps --matrix             # Show installation matrix
        benchbox check-deps --verbose            # Detailed guidance
    """
    from benchbox.utils.dependencies import (
        check_platform_dependencies,
        get_dependency_decision_tree,
        get_installation_matrix_rows,
        get_installation_recommendations,
        get_installation_scenarios,
        list_available_dependency_groups,
    )

    console.print("[bold blue]BenchBox Dependency Status[/bold blue]\n")

    if show_matrix:
        _show_matrix(get_installation_matrix_rows, get_installation_scenarios)
    elif platform:
        _show_platform(platform, verbose, list_available_dependency_groups, check_platform_dependencies)
    else:
        _show_overview(
            verbose,
            list_available_dependency_groups,
            check_platform_dependencies,
            get_dependency_decision_tree,
            get_installation_recommendations,
        )


def _show_matrix(
    get_installation_matrix_rows: Callable[[], list[tuple[str, str, str, str, str, str]]],
    get_installation_scenarios: Callable[[], list[Any]],
) -> None:
    """Display the installation matrix table."""
    table = Table(
        title="BenchBox Installation Matrix",
        box=None,
        show_header=True,
        show_lines=False,
    )
    table.add_column("Scenario", style="bold", no_wrap=True)
    table.add_column("Platforms", no_wrap=True)
    table.add_column("Extras", no_wrap=True)
    table.add_column("Installation Command", no_wrap=True)

    for name, platforms_text, extras, uv_cmd, _pip_cmd, _pipx_cmd in get_installation_matrix_rows():
        table.add_row(name, platforms_text, extras, escape(uv_cmd))

    console.print(table)
    console.print("\n[dim]Alternative installation methods:[/dim]")
    console.print('[dim]  • pip-compatible: uv pip install "benchbox[extras]"[/dim]')
    console.print('[dim]  • pip:  python -m pip install "benchbox[extras]"[/dim]')
    console.print('[dim]  • pipx: pipx install "benchbox[extras]"[/dim]')

    scenarios = get_installation_scenarios()
    multi_group = [s for s in scenarios if len(s.dependency_groups) > 1]
    if multi_group:
        example_cmd = "uv add benchbox --extra cloud --extra clickhouse"
        example_alt = 'uv pip install "benchbox[cloud,clickhouse]"'
        console.print(f"\n[dim]Tip: Combine extras with multiple --extra flags: {escape(example_cmd)}[/dim]")
        console.print(f"[dim]     Alternative: {escape(example_alt)}[/dim]")


def _show_platform(
    platform: str,
    verbose: bool,
    list_available_dependency_groups: Callable[[], dict[str, Any]],
    check_platform_dependencies: Callable[[str, list[str]], tuple[bool, list[str]]],
) -> None:
    """Display dependency status for a specific platform."""
    platform_lower = platform.lower()
    dep_groups = list_available_dependency_groups()

    if platform_lower not in dep_groups:
        console.print(f"[red]Unknown platform '{platform}'. Available platforms:[/red]")
        for name in dep_groups:
            if name not in ["all", "cloud"]:
                console.print(f"  • {name}")
        return

    dep_info = dep_groups[platform_lower]
    available, missing = check_platform_dependencies(platform_lower, dep_info.packages)

    if available:
        console.print(f"[green]✅ {platform} dependencies are installed[/green]")
    else:
        console.print(f"[red]❌ {platform} missing dependencies: {', '.join(missing)}[/red]")
        console.print(f"\nExtra: [yellow]{dep_info.extra_name}[/yellow]")
        console.print(dep_info.get_install_message())
        console.print("\nNeed help comparing extras? Run: benchbox check-deps --matrix")

    if verbose:
        console.print(f"\nDescription: {dep_info.description}")
        console.print(f"Use cases: {', '.join(dep_info.use_cases)}")
        console.print(f"Required packages: {', '.join(dep_info.packages)}")


def _show_overview(
    verbose: bool,
    list_available_dependency_groups: Callable[[], dict[str, Any]],
    check_platform_dependencies: Callable[[str, list[str]], tuple[bool, list[str]]],
    get_dependency_decision_tree: Callable[[], str],
    get_installation_recommendations: Callable[[], list[str]],
) -> None:
    """Display an overview of all platform dependency statuses."""
    dep_groups = list_available_dependency_groups()

    for name, info in dep_groups.items():
        if name in ["all", "cloud"]:
            continue

        available, missing = check_platform_dependencies(name, info.packages)
        status = "[green]✅[/green]" if available else "[red]❌[/red]"
        console.print(f"{status} {name.capitalize():<12} - {info.description}")

    console.print("\n" + escape(get_dependency_decision_tree()))

    if verbose:
        console.print("\n[bold]Installation Recommendations:[/bold]")
        for rec in get_installation_recommendations():
            console.print(f"  {rec}")


__all__ = ["check_dependencies"]
