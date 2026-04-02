"""Compare query plans command implementation."""

from __future__ import annotations

import json
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from benchbox.cli.shared import console
from benchbox.core.query_plans.comparison import (
    PlanComparisonSummary,
    compare_query_plans,
    generate_plan_comparison_summary,
)
from benchbox.core.query_plans.visualization import render_comparison
from benchbox.core.results.loader import load_result_file
from benchbox.core.results.models import BenchmarkResults


@click.command("compare-plans", hidden=True, deprecated=True)
@click.option(
    "--run1",
    "run1_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to first benchmark results JSON file",
)
@click.option(
    "--run2",
    "run2_path",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to second benchmark results JSON file",
)
@click.option(
    "--query-id",
    help="Query ID to compare (e.g., 'q05', '1'). If not specified, compares all queries.",
)
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "json", "html"], case_sensitive=False),
    default="text",
    help="Output format (text, json, or html)",
)
@click.option(
    "--output-file",
    "output_file",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Write output to file instead of stdout",
)
@click.option(
    "--threshold",
    type=float,
    default=0.0,
    help="Only show queries with similarity below this threshold (0.0-1.0)",
)
@click.option(
    "--summary",
    "show_summary",
    is_flag=True,
    help="Show comparison summary with performance correlation",
)
@click.option(
    "--regression-threshold",
    type=float,
    default=20.0,
    help="Performance degradation threshold for regression detection (default 20%%)",
)
@click.pass_context
def compare_plans(
    ctx,
    run1_path: Path,
    run2_path: Path,
    query_id: str | None,
    output_format: str,
    output_file: Path | None,
    threshold: float,
    show_summary: bool,
    regression_threshold: float,
):
    """Compare query plans between benchmark runs.

    DEPRECATED: This command is deprecated. Use 'benchbox compare --include-plans' instead.

    Migration examples:
        # OLD: benchbox compare-plans --run1 before.json --run2 after.json
        # NEW: benchbox compare before.json after.json --include-plans

        # OLD: benchbox compare-plans --run1 before.json --run2 after.json --threshold 0.9
        # NEW: benchbox compare before.json after.json --include-plans --plan-threshold 0.9

    Original functionality:

    Compares query plans from two different benchmark runs. Plans must have been
    captured using --capture-plans during the benchmarks. Useful for:

    - Cross-platform comparison (DuckDB vs DataFusion)
    - Cross-run regression detection (before vs after optimization)
    - Plan analysis (understanding optimizer choices)

    Examples:
        # Compare single query between two runs
        benchbox compare-plans --run1 run_a.json --run2 run_b.json --query-id q05

        # Compare all queries and show only regressions (< 90% similar)
        benchbox compare-plans --run1 before.json --run2 after.json --threshold 0.9

        # Show summary with performance correlation
        benchbox compare-plans --run1 before.json --run2 after.json --summary

        # Export comparison as JSON
        benchbox compare-plans --run1 run_a.json --run2 run_b.json --output json

        # Generate HTML report to file
        benchbox compare-plans --run1 before.json --run2 after.json --output html --output-file report.html
    """
    try:
        # Load both benchmark results (also loads companion .plans.json if present)
        results1, _ = load_result_file(run1_path)
        results2, _ = load_result_file(run2_path)

        # Handle summary mode
        if show_summary:
            summary = generate_plan_comparison_summary(
                results1,
                results2,
                regression_threshold_pct=regression_threshold,
            )
            if output_format == "json":
                output = _output_summary_json(summary, return_string=output_file is not None)
            elif output_format == "html":
                output = _output_summary_html(summary)
            else:
                output = _output_summary_text(summary, return_string=output_file is not None)

            if output_file:
                output_file.write_text(output)
                console.print(f"[green]Report written to:[/green] {output_file}")
            return

        # Get query IDs to compare
        if query_id:
            query_ids = [query_id]
        else:
            # Find common queries between both runs
            queries1 = set()
            for phase_results in results1.phases.values():
                for exec_result in phase_results.queries:
                    queries1.add(exec_result.query_id)

            queries2 = set()
            for phase_results in results2.phases.values():
                for exec_result in phase_results.queries:
                    queries2.add(exec_result.query_id)

            query_ids = sorted(queries1 & queries2)

            if not query_ids:
                console.print("[yellow]Warning:[/yellow] No common queries found between runs")
                ctx.exit(1)

        # Compare plans
        comparisons = []
        for qid in query_ids:
            # Find executions in both runs
            exec1 = _find_query_execution(results1, qid)
            exec2 = _find_query_execution(results2, qid)

            if not exec1 or not exec2:
                if query_id:  # Only warn if specific query was requested
                    console.print(f"[yellow]Warning:[/yellow] Query '{qid}' not found in both runs")
                continue

            # Check if plans were captured
            plan1 = getattr(exec1, "query_plan", None)
            plan2 = getattr(exec2, "query_plan", None)

            if not plan1 or not plan2:
                if query_id:  # Only warn if specific query was requested
                    console.print(f"[yellow]Warning:[/yellow] Query '{qid}' missing plan in one or both runs")
                continue

            # Compare plans
            comparison = compare_query_plans(plan1, plan2)

            # Apply threshold filter
            if comparison.similarity.overall_similarity < threshold:
                comparisons.append((qid, comparison))
            elif not query_id and threshold == 0.0:
                # Include all if no threshold and comparing all queries
                comparisons.append((qid, comparison))

        if not comparisons:
            if threshold > 0.0:
                console.print(f"[green]Success:[/green] All queries have similarity >= {threshold:.1%}")
            else:
                console.print("[yellow]No plans available for comparison[/yellow]")
            return

        # Output results
        if output_format == "json":
            output = _output_json(comparisons, return_string=output_file is not None)
        elif output_format == "html":
            output = _output_html(comparisons, query_id is not None, results1, results2)
        else:
            output = _output_text(comparisons, query_id is not None, return_string=output_file is not None)

        if output_file:
            output_file.write_text(output)
            console.print(f"[green]Report written to:[/green] {output_file}")

    except FileNotFoundError as e:
        console.print(f"[red]Error:[/red] Results file not found: {e.filename}")
        ctx.exit(1)
    except json.JSONDecodeError as e:
        console.print(f"[red]Error:[/red] Invalid JSON in results file: {e}")
        ctx.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        if ctx.obj and ctx.obj.get("verbose"):
            raise
        ctx.exit(1)


def _find_query_execution(results: BenchmarkResults, query_id: str):
    """Find query execution by ID in results."""
    for phase_results in results.phases.values():
        for exec_result in phase_results.queries:
            if exec_result.query_id == query_id:
                return exec_result
    return None


def _output_text(comparisons: list, single_query: bool, return_string: bool = False) -> str | None:
    """Output comparisons in text format."""
    if single_query:
        # Detailed output for single query
        query_id, comparison = comparisons[0]
        output = render_comparison(comparison)
        if return_string:
            return str(output)
        console.print(output)
        return None

    # Summary table for multiple queries
    table = Table(title="Query Plan Comparison Summary", show_header=True)
    table.add_column("Query", style="cyan", no_wrap=True)
    table.add_column("Similarity", justify="right", style="green")
    table.add_column("Type Diff", justify="right")
    table.add_column("Prop Diff", justify="right")
    table.add_column("Struct Diff", justify="right")
    table.add_column("Status")

    for query_id, comparison in comparisons:
        sim = comparison.similarity

        # Determine status
        if sim.overall_similarity >= 0.95:
            status = "[green]✓ Nearly Identical[/green]"
        elif sim.overall_similarity >= 0.75:
            status = "[blue]≈ Very Similar[/blue]"
        elif sim.overall_similarity >= 0.50:
            status = "[yellow]~ Somewhat Similar[/yellow]"
        else:
            status = "[red]✗ Different[/red]"

        table.add_row(
            query_id,
            f"{sim.overall_similarity:.1%}",
            str(sim.type_mismatches) if sim.type_mismatches > 0 else "-",
            str(sim.property_mismatches) if sim.property_mismatches > 0 else "-",
            str(sim.structure_mismatches) if sim.structure_mismatches > 0 else "-",
            status,
        )

    # Summary statistics
    total = len(comparisons)
    identical = sum(1 for _, c in comparisons if c.similarity.overall_similarity >= 0.95)
    similar = sum(1 for _, c in comparisons if 0.75 <= c.similarity.overall_similarity < 0.95)
    different = sum(1 for _, c in comparisons if c.similarity.overall_similarity < 0.50)

    if return_string:
        from io import StringIO

        string_console = Console(file=StringIO(), force_terminal=True)
        string_console.print(table)
        string_console.print()
        string_console.print(f"[bold]Summary:[/bold] {total} queries compared")
        string_console.print(f"  Nearly Identical (≥95%): {identical}")
        string_console.print(f"  Very Similar (75-95%):   {similar}")
        string_console.print(f"  Different (<50%):        {different}")
        return string_console.file.getvalue()

    console.print(table)
    console.print()
    console.print(f"[bold]Summary:[/bold] {total} queries compared")
    console.print(f"  Nearly Identical (≥95%): {identical}")
    console.print(f"  Very Similar (75-95%):   {similar}")
    console.print(f"  Different (<50%):        {different}")
    return None


def _output_json(comparisons: list, return_string: bool = False) -> str | None:
    """Output comparisons in JSON format."""
    output = []
    for query_id, comparison in comparisons:
        output.append(
            {
                "query_id": query_id,
                "plans_identical": comparison.plans_identical,
                "fingerprints_match": comparison.fingerprints_match,
                "similarity": {
                    "overall": comparison.similarity.overall_similarity,
                    "structural": comparison.similarity.structural_similarity,
                    "operator": comparison.similarity.operator_similarity,
                    "property": comparison.similarity.property_similarity,
                },
                "differences": {
                    "type_mismatches": comparison.similarity.type_mismatches,
                    "property_mismatches": comparison.similarity.property_mismatches,
                    "structure_mismatches": comparison.similarity.structure_mismatches,
                },
                "summary": comparison.summary,
            }
        )

    if return_string:
        return json.dumps(output, indent=2)
    console.print_json(data=output)
    return None


def _output_summary_text(summary: PlanComparisonSummary, return_string: bool = False) -> str | None:
    """Output comparison summary in text format."""
    lines = [
        "=" * 60,
        "PLAN COMPARISON SUMMARY",
        "=" * 60,
        "",
        "Runs Compared:",
        f"  Baseline: {summary.baseline_run_id}",
        f"  Current:  {summary.current_run_id}",
        "",
        "Plan Changes:",
        f"  Plans Compared: {summary.plans_compared}",
        f"  Unchanged:      {summary.plans_unchanged}",
        f"  Changed:        {summary.plans_changed}",
    ]

    if summary.plans_changed > 0:
        lines.append("")
        lines.append("Structural Differences:")
        for diff in summary.structural_differences:
            if diff.change_type == "unchanged":
                continue
            lines.append(f"  {diff.query_id}: {diff.change_type} ({diff.similarity:.1%})")
            lines.append(f"    {diff.details[:80]}")

    regressions = [c for c in summary.performance_correlations if c.is_regression]
    lines.append("")
    if regressions:
        lines.append(f"REGRESSIONS DETECTED: {len(regressions)}")
        for reg in regressions:
            lines.append(
                f"  {reg.query_id}: {reg.baseline_time_ms:.2f}ms -> {reg.current_time_ms:.2f}ms (+{reg.perf_change_pct:.1f}%)"
            )
    else:
        lines.append("No regressions detected")

    text_output = "\n".join(lines)

    if return_string:
        return text_output

    _render_summary_rich(summary, regressions)
    return None


def _render_summary_rich(summary: PlanComparisonSummary, regressions: list) -> None:
    """Render comparison summary using Rich console formatting."""
    console.print(Panel.fit("[bold]Plan Comparison Summary[/bold]", border_style="blue"))
    console.print()
    console.print("[bold]Runs Compared:[/bold]")
    console.print(f"  Baseline: {summary.baseline_run_id}")
    console.print(f"  Current:  {summary.current_run_id}")

    console.print()
    console.print("[bold]Plan Changes:[/bold]")
    console.print(f"  Plans Compared: {summary.plans_compared}")
    console.print(f"  Unchanged:      {summary.plans_unchanged}")
    console.print(f"  Changed:        {summary.plans_changed}")

    if summary.plans_changed > 0:
        console.print()
        console.print("[bold]Structural Differences:[/bold]")
        table = Table(show_header=True)
        table.add_column("Query", style="cyan", no_wrap=True)
        table.add_column("Change Type", no_wrap=True)
        table.add_column("Similarity", justify="right")
        table.add_column("Details")

        for diff in summary.structural_differences:
            if diff.change_type == "unchanged":
                continue
            change_style = {
                "structure_change": "[red]Structure[/red]",
                "type_change": "[yellow]Type[/yellow]",
                "property_change": "[blue]Property[/blue]",
            }.get(diff.change_type, diff.change_type)
            table.add_row(
                diff.query_id,
                change_style,
                f"{diff.similarity:.1%}",
                diff.details[:60] + "..." if len(diff.details) > 60 else diff.details,
            )

        console.print(table)

    if regressions:
        console.print()
        console.print(f"[bold red]Regressions Detected: {len(regressions)}[/bold red]")
        table = Table(show_header=True)
        table.add_column("Query", style="cyan", no_wrap=True)
        table.add_column("Baseline (ms)", justify="right")
        table.add_column("Current (ms)", justify="right")
        table.add_column("Change", justify="right")

        for reg in regressions:
            change_str = f"[red]+{reg.perf_change_pct:.1f}%[/red]"
            table.add_row(
                reg.query_id,
                f"{reg.baseline_time_ms:.2f}",
                f"{reg.current_time_ms:.2f}",
                change_str,
            )

        console.print(table)
    else:
        console.print()
        console.print("[green]No regressions detected[/green]")


def _output_summary_json(summary: PlanComparisonSummary, return_string: bool = False) -> str | None:
    """Output comparison summary in JSON format."""
    if return_string:
        return json.dumps(summary.to_dict(), indent=2)
    console.print_json(data=summary.to_dict())
    return None


def _output_summary_html(summary: PlanComparisonSummary) -> str:
    """Output comparison summary as HTML report."""
    regressions = [c for c in summary.performance_correlations if c.is_regression]

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Query Plan Comparison Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; margin: 40px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .summary-box {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .stat-card {{ background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; }}
        .stat-value {{ font-size: 2em; font-weight: bold; color: #007bff; }}
        .stat-label {{ color: #666; margin-top: 5px; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        tr:hover {{ background: #f8f9fa; }}
        .status-identical {{ color: #28a745; }}
        .status-similar {{ color: #007bff; }}
        .status-different {{ color: #dc3545; }}
        .regression {{ background: #fff3cd; }}
        .badge {{ display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 0.85em; }}
        .badge-structure {{ background: #dc3545; color: white; }}
        .badge-type {{ background: #ffc107; color: black; }}
        .badge-property {{ background: #17a2b8; color: white; }}
        .alert {{ padding: 15px; border-radius: 8px; margin: 20px 0; }}
        .alert-success {{ background: #d4edda; color: #155724; }}
        .alert-danger {{ background: #f8d7da; color: #721c24; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Query Plan Comparison Report</h1>

        <div class="summary-box">
            <div class="stat-card">
                <div class="stat-label">Baseline Run</div>
                <div style="font-size: 1.1em; color: #333;">{summary.baseline_run_id}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">Current Run</div>
                <div style="font-size: 1.1em; color: #333;">{summary.current_run_id}</div>
            </div>
        </div>

        <div class="summary-box">
            <div class="stat-card">
                <div class="stat-value">{summary.plans_compared}</div>
                <div class="stat-label">Plans Compared</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #28a745;">{summary.plans_unchanged}</div>
                <div class="stat-label">Unchanged</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #ffc107;">{summary.plans_changed}</div>
                <div class="stat-label">Changed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #dc3545;">{len(regressions)}</div>
                <div class="stat-label">Regressions</div>
            </div>
        </div>
"""

    # Structural differences table
    changed_diffs = [d for d in summary.structural_differences if d.change_type != "unchanged"]
    if changed_diffs:
        html += """
        <h2>Structural Differences</h2>
        <table>
            <thead>
                <tr>
                    <th>Query</th>
                    <th>Change Type</th>
                    <th>Similarity</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
"""
        for diff in changed_diffs:
            badge_class = {
                "structure_change": "badge-structure",
                "type_change": "badge-type",
                "property_change": "badge-property",
            }.get(diff.change_type, "")
            html += f"""
                <tr>
                    <td><strong>{diff.query_id}</strong></td>
                    <td><span class="badge {badge_class}">{diff.change_type.replace("_", " ").title()}</span></td>
                    <td>{diff.similarity:.1%}</td>
                    <td>{diff.details[:80]}{"..." if len(diff.details) > 80 else ""}</td>
                </tr>
"""
        html += """
            </tbody>
        </table>
"""

    # Regressions section
    if regressions:
        html += """
        <h2>Performance Regressions</h2>
        <div class="alert alert-danger">
            <strong>Warning:</strong> The following queries have plan changes AND performance degradation.
        </div>
        <table>
            <thead>
                <tr>
                    <th>Query</th>
                    <th>Baseline (ms)</th>
                    <th>Current (ms)</th>
                    <th>Change</th>
                </tr>
            </thead>
            <tbody>
"""
        for reg in regressions:
            html += f"""
                <tr class="regression">
                    <td><strong>{reg.query_id}</strong></td>
                    <td>{reg.baseline_time_ms:.2f}</td>
                    <td>{reg.current_time_ms:.2f}</td>
                    <td style="color: #dc3545;">+{reg.perf_change_pct:.1f}%</td>
                </tr>
"""
        html += """
            </tbody>
        </table>
"""
    else:
        html += """
        <div class="alert alert-success">
            <strong>No regressions detected.</strong> All plan changes do not correlate with significant performance degradation.
        </div>
"""

    html += """
        <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em;">
            Generated by BenchBox Query Plan Analysis
        </footer>
    </div>
</body>
</html>
"""
    return html


def _output_html(comparisons: list, single_query: bool, results1: BenchmarkResults, results2: BenchmarkResults) -> str:
    """Output comparisons as HTML report."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Query Plan Comparison</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif; margin: 40px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { color: #333; border-bottom: 2px solid #007bff; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        th { background: #f8f9fa; font-weight: 600; }
        tr:hover { background: #f8f9fa; }
        .status-identical { color: #28a745; }
        .status-similar { color: #007bff; }
        .status-different { color: #dc3545; }
        .summary-box { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 15px; margin: 20px 0; }
        .stat-card { background: #f8f9fa; padding: 15px; border-radius: 8px; text-align: center; }
        .stat-value { font-size: 1.5em; font-weight: bold; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Query Plan Comparison</h1>
"""

    # Summary stats
    total = len(comparisons)
    identical = sum(1 for _, c in comparisons if c.similarity.overall_similarity >= 0.95)
    similar = sum(1 for _, c in comparisons if 0.75 <= c.similarity.overall_similarity < 0.95)
    different = sum(1 for _, c in comparisons if c.similarity.overall_similarity < 0.50)

    html += f"""
        <div class="summary-box">
            <div class="stat-card">
                <div class="stat-value">{total}</div>
                <div>Total Compared</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #28a745;">{identical}</div>
                <div>Identical (>=95%)</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #007bff;">{similar}</div>
                <div>Similar (75-95%)</div>
            </div>
            <div class="stat-card">
                <div class="stat-value" style="color: #dc3545;">{different}</div>
                <div>Different (<50%)</div>
            </div>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Query</th>
                    <th>Similarity</th>
                    <th>Type Diff</th>
                    <th>Prop Diff</th>
                    <th>Struct Diff</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""

    for query_id, comparison in comparisons:
        sim = comparison.similarity
        if sim.overall_similarity >= 0.95:
            status = '<span class="status-identical">Nearly Identical</span>'
        elif sim.overall_similarity >= 0.75:
            status = '<span class="status-similar">Very Similar</span>'
        elif sim.overall_similarity >= 0.50:
            status = '<span style="color: #ffc107;">Somewhat Similar</span>'
        else:
            status = '<span class="status-different">Different</span>'

        html += f"""
                <tr>
                    <td><strong>{query_id}</strong></td>
                    <td>{sim.overall_similarity:.1%}</td>
                    <td>{sim.type_mismatches if sim.type_mismatches > 0 else "-"}</td>
                    <td>{sim.property_mismatches if sim.property_mismatches > 0 else "-"}</td>
                    <td>{sim.structure_mismatches if sim.structure_mismatches > 0 else "-"}</td>
                    <td>{status}</td>
                </tr>
"""

    html += """
            </tbody>
        </table>
        <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em;">
            Generated by BenchBox Query Plan Analysis
        </footer>
    </div>
</body>
</html>
"""
    return html


__all__ = ["compare_plans"]
