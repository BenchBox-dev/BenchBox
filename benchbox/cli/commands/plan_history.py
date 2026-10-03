from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from benchbox.cli.shared import console
from benchbox.core.query_plans.history import PlanHistory


@click.command(
    "plan-history",
    help=(
        "Show plan evolution history for a query.\n"
        "\n"
        "Displays how a query's execution plan has changed across benchmark runs.\n"
        "Use this to identify:\n"
        "\n"
        "- When plan changes occurred\n"
        "- How plan changes correlate with performance\n"
        "- Plan flapping (unstable optimizer behavior)\n"
        "\n"
        "\b\n"
        "Examples:\n"
        "    # Show history for query q05\n"
        "    benchbox plan-history --query-id q05 --history-dir ./plan_history\n"
        "\n"
        "\b\n"
        "    # Check for plan instability\n"
        "    benchbox plan-history --query-id q05 --history-dir ./plan_history --check-flapping"
    ),
)
@click.option(
    "--query-id",
    required=True,
    help="Query ID to show history for (e.g., 'q05', '1')",
)
@click.option(
    "--history-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing plan history files",
)
@click.option(
    "--limit",
    type=int,
    default=20,
    help="Maximum number of entries to show (default: 20)",
)
@click.option(
    "--check-flapping",
    is_flag=True,
    help="Check for plan flapping (unstable plans)",
)
@click.option(
    "--platform",
    default=None,
    help="Only show history for this platform (e.g. 'duckdb'). "
    "Multi-platform histories must not be compared as one sequence.",
)
@click.pass_context
def plan_history(
    ctx,
    query_id: str,
    history_dir: Path,
    limit: int,
    check_flapping: bool,
    platform: str | None,
):
    try:
        history = PlanHistory(history_dir)

        if history.get_run_count() == 0:
            console.print("[yellow]No history data found in the specified directory[/yellow]")
            ctx.exit(1)

        entries = history.query_plan_history(query_id, platform=platform)

        if not entries:
            scope = f" for platform '{platform}'" if platform else ""
            console.print(f"[yellow]No history found for query '{query_id}'{scope}[/yellow]")
            ctx.exit(1)

        display_entries = entries[-limit:]

        title_scope = f" (platform: {platform})" if platform else ""
        console.print(f"[bold]Plan History for {query_id}{title_scope}[/bold]")
        console.print(f"Total runs: {len(entries)}, showing last {len(display_entries)}")
        if platform is None:
            mixed = sorted({e.platform for e in entries})
            if len(mixed) > 1:
                console.print(
                    f"[yellow]Note: {len(mixed)} platforms in this lineage "
                    f"({', '.join(mixed)}); pass --platform to compare within one engine[/yellow]"
                )
        console.print()

        table = Table(show_header=True)
        table.add_column("Run ID", style="cyan", no_wrap=True)
        table.add_column("Timestamp", no_wrap=True)
        table.add_column("Fingerprint", no_wrap=True)
        table.add_column("Time (ms)", justify="right")
        table.add_column("Version", justify="right")

        versions = history.get_plan_version_history(query_id, platform=platform)
        version_map = {entries[i].run_id: versions[i][1] for i in range(len(entries))}

        prev_version: int | str | None = None
        for entry in display_entries:
            fp_short = entry.fingerprint[:12] + "..."
            version = version_map.get(entry.run_id, "?")

            if prev_version is not None and version != prev_version:
                fp_display = f"[yellow]{fp_short}[/yellow]"
                version_display = f"[yellow]v{version}[/yellow]"
            else:
                fp_display = fp_short
                version_display = f"v{version}"

            table.add_row(
                entry.run_id,
                entry.timestamp[:19],
                fp_display,
                f"{entry.execution_time_ms:.2f}",
                version_display,
            )
            prev_version = version

        console.print(table)

        unique_plans = history.count_unique_plans(query_id, platform=platform)
        ordered_versions = [versions[i][1] for i in range(len(entries))]
        plan_changes = sum(1 for a, b in zip(ordered_versions, ordered_versions[1:]) if a != b)
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Unique plans: {unique_plans}")
        console.print(f"  Plan changes: {plan_changes}")

        if check_flapping:
            console.print()
            is_flapping = history.detect_plan_flapping(query_id, platform=platform)
            if is_flapping:
                console.print("[bold red]⚠️  WARNING: Plan flapping detected![/bold red]")
                console.print("    The query plan changes frequently across runs.")
                console.print("    This may indicate optimizer instability.")
            else:
                console.print("[green]✓ No plan flapping detected[/green]")

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if ctx.obj and ctx.obj.get("verbose"):
            raise
        ctx.exit(1)


__all__ = ["plan_history"]
