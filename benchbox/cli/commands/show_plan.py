"""Show query plan command implementation."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.panel import Panel

from benchbox.cli.shared import console
from benchbox.core.query_plans.visualization import (
    VisualizationOptions,
    render_plan,
    render_summary,
)
from benchbox.core.results.loader import iter_query_results, load_result_file
from benchbox.core.results.query_normalizer import normalize_query_id


def _find_query(results, query_id: str):
    """Find a query result whose ID matches after normalization.

    ``load_result_file`` returns already-normalized IDs from a real bundle's
    compact ``queries[].id`` field (e.g. ``q05``/``Q05`` -> ``05``), so a raw
    string comparison against the CLI's documented ``--query-id q05`` input
    would report "not found" even when the plan is present.
    """
    normalized_target = normalize_query_id(query_id)
    return next(
        (qr for qr in iter_query_results(results) if normalize_query_id(qr.get("query_id", "")) == normalized_target),
        None,
    )


@click.command("show-plan")
@click.option(
    "--run",
    "run_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to benchmark results JSON file",
)
@click.option(
    "--query-id",
    required=True,
    help="Query ID to show plan for (e.g., 'q05', '1')",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["tree", "summary", "json"], case_sensitive=False),
    default="tree",
    help="Output format",
)
@click.option(
    "--no-properties",
    is_flag=True,
    help="Hide operator properties in tree view",
)
@click.option(
    "--compact",
    is_flag=True,
    help="Use compact tree format",
)
@click.option(
    "--max-depth",
    type=int,
    help="Maximum tree depth to display",
)
@click.pass_context
def show_plan(
    ctx,
    run_path: Path,
    query_id: str,
    output_format: str,
    no_properties: bool,
    compact: bool,
    max_depth: int | None,
):
    """Display query plan as ASCII tree.

    Shows the logical query plan for a specific query from a benchmark run.
    The plan must have been captured using --capture-plans during the benchmark.

    Examples:
        # Show plan as tree
        benchbox show-plan --run results.json --query-id q05

        # Show summary statistics only
        benchbox show-plan --run results.json --query-id 1 --format summary

        # Export plan as JSON
        benchbox show-plan --run results.json --query-id q05 --format json

        # Compact tree view without properties
        benchbox show-plan --run results.json --query-id q05 --compact --no-properties
    """
    try:
        # Load benchmark results (also loads companion .plans.json if present)
        results, _ = load_result_file(run_path)

        # Find query execution
        query_exec = _find_query(results, query_id)

        if not query_exec:
            console.print(f"[red]Error:[/red] Query '{query_id}' not found in results")
            ctx.exit(1)

        # Check if plan was captured
        if query_exec.get("query_plan") is None:
            console.print(f"[yellow]Warning:[/yellow] No query plan captured for query '{query_id}'")
            console.print("Run benchmark with --capture-plans flag to capture query plans")
            ctx.exit(1)

        plan = query_exec["query_plan"]

        # Handle different output formats
        if output_format == "json":
            # Export as JSON
            output = json.dumps(plan.to_dict(), indent=2)
            console.print(output)

        elif output_format == "summary":
            # Show summary statistics
            output = render_summary(plan)
            console.print(Panel(output, title=f"Query Plan Summary: {query_id}", border_style="cyan"))

        else:  # tree
            # Show ASCII tree
            options = VisualizationOptions(
                show_properties=not no_properties,
                compact=compact,
                max_depth=max_depth,
            )
            output = render_plan(plan, options)
            console.print(Panel(output, title=f"Query Plan: {query_id}", border_style="green"))

    except FileNotFoundError:
        console.print(f"[red]Error:[/red] Results file not found: {run_path}")
        ctx.exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid JSON in results file: {e}")
        ctx.exit(1)
    except KeyError as e:
        console.print(f"[red]Error:[/red] Missing required field in results: {e}")
        ctx.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if ctx.obj and ctx.obj.get("verbose"):
            raise
        ctx.exit(1)


__all__ = ["show_plan"]
