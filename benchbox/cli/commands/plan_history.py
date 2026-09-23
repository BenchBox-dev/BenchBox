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
    """Show plan evolution history for a query.

    Displays how a query's execution plan has changed across benchmark runs.
    Use this to identify:

    - When plan changes occurred
    - How plan changes correlate with performance
    - Plan flapping (unstable optimizer behavior)

    \b
    Examples:
        # Show history for query q05
        benchbox plan-history --query-id q05 --history-dir ./plan_history

    \b
        # Check for plan instability
        benchbox plan-history --query-id q05 --history-dir ./plan_history --check-flapping
    """
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

        # Show limited entries
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

        # Get version history (version-aware: a fingerprint_version encoding
        # bump alone is not a plan change, and cross-platform fingerprints
        # are never compared when --platform filters the lineage).
        versions = history.get_plan_version_history(query_id, platform=platform)
        version_map = {entries[i].run_id: versions[i][1] for i in range(len(entries))}

        prev_version: int | str | None = None
        for entry in display_entries:
            fp_short = entry.fingerprint[:12] + "..."
            version = version_map.get(entry.run_id, "?")

            # Highlight genuine plan changes (version bumps), not raw
            # fingerprint inequality: a v1->v2 re-encoding of the same plan
            # keeps the version and must not highlight.
            if prev_version is not None and version != prev_version:
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
            prev_version = version

        console.print(table)

        # Summary statistics (identity-aware: distinct logical plans — version
        # numbers identify change episodes, so an A -> B -> A flap must not
        # count three; changes count version transitions in the lineage).
        unique_plans = history.count_unique_plans(query_id, platform=platform)
        ordered_versions = [versions[i][1] for i in range(len(entries))]
        plan_changes = sum(1 for a, b in zip(ordered_versions, ordered_versions[1:]) if a != b)
        console.print()
        console.print("[bold]Summary:[/bold]")
        console.print(f"  Unique plans: {unique_plans}")
        console.print(f"  Plan changes: {plan_changes}")

        # Flapping detection
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
