"""Plan history command implementation."""

from __future__ import annotations

from pathlib import Path

import click
from rich.table import Table

from benchbox.cli.shared import console
from benchbox.core.query_plans.history import PlanHistory


@click.command("plan-history")
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
@click.pass_context
def plan_history(
    ctx,
    query_id: str,
    history_dir: Path,
    limit: int,
    check_flapping: bool,
):
    """Show plan evolution history for a query.

    Displays how a query's execution plan has changed across benchmark runs.
    Use this to identify:

    - When plan changes occurred
    - How plan changes correlate with performance
    - Plan flapping (unstable optimizer behavior)

    Examples:
        # Show history for query q05
        benchbox plan-history --query-id q05 --history-dir ./plan_history

        # Check for plan instability
        benchbox plan-history --query-id q05 --history-dir ./plan_history --check-flapping
    """
    try:
        history = PlanHistory(history_dir)

        if history.get_run_count() == 0:
            console.print("[yellow]No history data found in the specified directory[/yellow]")
            ctx.exit(1)

        entries = history.query_plan_history(query_id)

        if not entries:
            console.print(f"[yellow]No history found for query '{query_id}'[/yellow]")
            ctx.exit(1)

        # Show limited entries
        display_entries = entries[-limit:]

        console.print(f"[bold]Plan History for {query_id}[/bold]")
        console.print(f"Total runs: {len(entries)}, showing last {len(display_entries)}")
        console.print()

        table = Table(show_header=True)
        table.add_column("Run ID", style="cyan", no_wrap=True)
        table.add_column("Timestamp", no_wrap=True)
        table.add_column("Fingerprint", no_wrap=True)
        table.add_column("Time (ms)", justify="right")
        table.add_column("Version", justify="right")

        # Get version history
        versions = history.get_plan_version_history(query_id)
        version_map = {entries[i].run_id: versions[i][1] for i in range(len(entries))}

        prev_fp = None
        for entry in display_entries:
            fp_short = entry.fingerprint[:12] + "..."
            version = version_map.get(entry.run_id, "?")

            # Highlight plan changes
            if prev_fp is not None and entry.fingerprint != prev_fp:
                fp_display = f"[yellow]{fp_short}[/yellow]"
                version_display = f"[yellow]v{version}[/yellow]"
            else:
                fp_display = fp_short
                version_display = f"v{version}"

            table.add_row(
                entry.run_id,
                entry.timestamp[:19],  # Trim to date+time
                fp_display,
                f"{entry.execution_time_ms:.2f}",
                version_display,
            )
            prev_fp = entry.fingerprint

        console.print(table)

        # Summary statistics
        unique_fingerprints = len(set(e.fingerprint for e in entries))
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Unique plans: {unique_fingerprints}")
        console.print(f"  Plan changes: {unique_fingerprints - 1}")

        # Flapping detection
        if check_flapping:
            console.print()
            is_flapping = history.detect_plan_flapping(query_id)
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
