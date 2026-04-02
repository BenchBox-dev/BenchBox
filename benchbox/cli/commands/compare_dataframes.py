"""Compare DataFrame platforms command implementation.

DEPRECATED: This command is deprecated. Use 'benchbox compare --run' instead.

Provides CLI for running cross-platform DataFrame benchmark comparisons
and SQL vs DataFrame performance analysis.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import click

from benchbox.cli.shared import console


def _show_deprecation_warning():
    """Show deprecation warning for compare-dataframes command."""
    warnings.warn(
        "The 'compare-dataframes' command is deprecated and will be removed in a future version. "
        "Use 'benchbox compare --run -p <platform1> -p <platform2>' instead.\n\n"
        "Migration examples:\n"
        "  OLD: benchbox compare-dataframes -p polars-df -p pandas-df\n"
        "  NEW: benchbox compare --run -p polars-df -p pandas-df\n\n"
        "  OLD: benchbox compare-dataframes -p polars-df --vs-sql duckdb\n"
        "  NEW: benchbox compare --run -p polars-df -p duckdb\n",
        DeprecationWarning,
        stacklevel=3,
    )


@click.command("compare-dataframes", hidden=True, deprecated=True)
@click.option(
    "--platforms",
    "-p",
    multiple=True,
    help="DataFrame platforms to compare (e.g., polars-df, pandas-df). Repeatable.",
)
@click.option(
    "--benchmark",
    "-b",
    default="tpch",
    show_default=True,
    type=click.Choice(["tpch"]),
    help="Benchmark to run",
)
@click.option(
    "--scale",
    "-s",
    default=0.01,
    show_default=True,
    type=float,
    help="Scale factor for benchmark data",
)
@click.option(
    "--queries",
    "-q",
    default=None,
    help="Comma-separated list of query IDs (e.g., Q1,Q3,Q6)",
)
@click.option(
    "--data-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Directory containing benchmark data",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    help="Output directory for results",
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "markdown", "text"]),
    default="text",
    show_default=True,
    help="Output format",
)
@click.option(
    "--vs-sql",
    type=click.Choice(["duckdb", "sqlite"]),
    default=None,
    help="Compare DataFrame platform against SQL (specify SQL platform)",
)
@click.option(
    "--warmup",
    default=1,
    show_default=True,
    type=int,
    help="Number of warmup iterations",
)
@click.option(
    "--iterations",
    default=3,
    show_default=True,
    type=int,
    help="Number of benchmark iterations",
)
@click.option(
    "--generate-charts",
    is_flag=True,
    help="Generate ASCII charts in output directory",
)
@click.option(
    "--theme",
    type=click.Choice(["light", "dark"]),
    default="light",
    help="Chart theme",
)
@click.option(
    "--list-platforms",
    is_flag=True,
    help="List available DataFrame platforms and exit",
)
@click.pass_context
def compare_dataframes(
    ctx,
    platforms,
    benchmark,
    scale,
    queries,
    data_dir,
    output,
    output_format,
    vs_sql,
    warmup,
    iterations,
    generate_charts,
    theme,
    list_platforms,
):
    """Compare DataFrame platform performance.

    Run benchmarks across multiple DataFrame platforms and generate comparison
    reports. Supports both cross-platform DataFrame comparisons and SQL vs
    DataFrame performance analysis.

    Examples:
        # List available platforms
        benchbox compare-dataframes --list-platforms

        # Compare Polars vs Pandas
        benchbox compare-dataframes -p polars-df -p pandas-df --scale 0.01

        # Compare specific queries
        benchbox compare-dataframes -p polars-df -p pandas-df -q Q1,Q6,Q10

        # Compare DataFrame vs SQL
        benchbox compare-dataframes -p polars-df --vs-sql duckdb

        # Generate markdown report
        benchbox compare-dataframes -p polars-df -p pandas-df --format markdown

        # Save results and generate charts
        benchbox compare-dataframes -p polars-df -p pandas-df -o ./results --generate-charts
    """
    # Show deprecation warning (unless just listing platforms)
    if not list_platforms:
        _show_deprecation_warning()
        console.print(
            "[yellow]⚠ DEPRECATED: This command is deprecated. Use 'benchbox compare --run' instead.[/yellow]\n"
        )

    from benchbox.core.dataframe.benchmark_suite import (
        BenchmarkConfig,
    )

    # List platforms mode
    if list_platforms:
        _list_available_platforms()
        return

    # Validate platforms specified
    if not platforms and not vs_sql:
        console.print("[red]Error: Specify at least one platform with --platforms or use --vs-sql[/red]")
        console.print("\nRun with --list-platforms to see available platforms")
        console.print("\n[bold]Examples:[/bold]")
        console.print("  benchbox compare-dataframes -p polars-df -p pandas-df")
        console.print("  benchbox compare-dataframes -p polars-df --vs-sql duckdb")
        sys.exit(1)

    # Parse query IDs
    query_ids = None
    if queries:
        query_ids = [q.strip() for q in queries.split(",")]

    # Create benchmark configuration
    config = BenchmarkConfig(
        scale_factor=scale,
        query_ids=query_ids,
        warmup_iterations=warmup,
        benchmark_iterations=iterations,
    )

    # Determine data directory
    if data_dir is None:
        sf_str = f"sf{scale}".replace(".", "")
        data_dir = Path(f"benchmark_runs/tpch/{sf_str}/data")

    if not data_dir.exists():
        console.print(f"[red]Error: Data directory not found: {data_dir}[/red]")
        console.print("\n[dim]Generate data first with:[/dim]")
        console.print(f"  benchbox run --platform duckdb --benchmark tpch --scale {scale}")
        sys.exit(1)

    # Run appropriate comparison
    if vs_sql:
        # SQL vs DataFrame comparison
        df_platform = platforms[0] if platforms else "polars-df"
        _run_sql_vs_dataframe(
            config=config,
            sql_platform=vs_sql,
            df_platform=df_platform,
            data_dir=data_dir,
            output_dir=output,
            output_format=output_format,
            generate_charts=generate_charts,
            theme=theme,
        )
    else:
        # Cross-platform DataFrame comparison
        _run_platform_comparison(
            config=config,
            platforms=list(platforms),
            data_dir=data_dir,
            output_dir=output,
            output_format=output_format,
            generate_charts=generate_charts,
            theme=theme,
        )


def _list_available_platforms():
    """List available DataFrame platforms."""
    from benchbox.core.dataframe.benchmark_suite import PLATFORM_CAPABILITIES
    from benchbox.platforms import list_available_dataframe_platforms

    console.print("\n[bold]DataFrame Platforms[/bold]\n")

    available = list_available_dataframe_platforms()

    # Group by availability
    installed = []
    not_installed = []

    for platform, is_available in available.items():
        cap = PLATFORM_CAPABILITIES.get(platform)
        family = cap.family if cap else "unknown"
        category = cap.category.value if cap else "unknown"

        features: list[str] = []
        if cap:
            if cap.supports_lazy:
                features.append("lazy")
            if cap.supports_streaming:
                features.append("streaming")
            if cap.supports_gpu:
                features.append("gpu")
            if cap.supports_distributed:
                features.append("distributed")

        info = {
            "name": platform,
            "family": family,
            "category": category,
            "features": features,
        }

        if is_available:
            installed.append(info)
        else:
            not_installed.append(info)

    # Display installed
    console.print("[green]Installed:[/green]")
    for p in installed:
        features = ", ".join(p["features"]) if p["features"] else "standard"
        console.print(f"  {p['name']:15s} ({p['family']:10s}, {p['category']:12s}) [{features}]")

    console.print()

    # Display not installed
    if not_installed:
        console.print("[dim]Not installed:[/dim]")
        for p in not_installed:
            console.print(f"  {p['name']:15s} ({p['family']:10s}, {p['category']:12s})")
        console.print()
        console.print("[dim]Install extras with: pip install benchbox[dataframe-<name>][/dim]")


def _run_platform_comparison(
    config,
    platforms: list[str],
    data_dir: Path,
    output_dir: Path | None,
    output_format: str,
    generate_charts: bool,
    theme: str,
):
    """Run cross-platform DataFrame comparison."""
    from benchbox.core.dataframe.benchmark_suite import (
        DataFrameBenchmarkSuite,
        DataFrameComparisonPlotter,
    )

    console.print("\n[bold]DataFrame Platform Comparison[/bold]")
    console.print(f"Platforms: {', '.join(platforms)}")
    console.print(f"Scale factor: {config.scale_factor}")
    console.print(f"Queries: {config.query_ids or 'all'}")
    console.print(f"Iterations: {config.benchmark_iterations}")
    console.print()

    suite = DataFrameBenchmarkSuite(config=config)

    # Verify platforms are available
    available = suite.get_available_platforms()
    for platform in platforms:
        if platform not in available:
            console.print(f"[yellow]Warning: Platform {platform} not available, skipping[/yellow]")

    platforms = [p for p in platforms if p in available]
    if not platforms:
        console.print("[red]Error: No available platforms to compare[/red]")
        sys.exit(1)

    # Run comparison
    console.print("[dim]Running benchmarks...[/dim]")
    try:
        results = suite.run_comparison(platforms=platforms, data_dir=data_dir)
    except Exception as e:
        console.print(f"[red]Benchmark failed: {e}[/red]")
        sys.exit(1)

    # Generate summary
    summary = suite.get_summary(results)

    # Output results
    if output_format == "text":
        _print_text_summary(results, summary)
    elif output_format == "json":
        import json

        data = {
            "config": {
                "scale_factor": config.scale_factor,
                "query_ids": config.query_ids,
                "iterations": config.benchmark_iterations,
            },
            "results": [r.to_dict() for r in results],
            "summary": summary.to_dict(),
        }
        _write_comparison_output(
            json.dumps(data, indent=2),
            output_dir=output_dir,
            filename="comparison.json",
            label="Results saved to",
        )
    elif output_format == "markdown":
        _write_comparison_output(
            suite._generate_markdown_report(results),
            output_dir=output_dir,
            filename="comparison.md",
            label="Report saved to",
        )

    # Generate charts if requested
    if generate_charts and output_dir:
        try:
            plotter = DataFrameComparisonPlotter(results, theme=theme)
            charts_dir = output_dir / "charts"
            exports = plotter.generate_charts(output_dir=charts_dir)
            if exports:
                chart_list = ", ".join(f"{ct}.txt" for ct in exports)
                console.print(f"[green]Charts generated in {charts_dir}: {chart_list}[/green]")
            else:
                console.print("[yellow]No charts generated (insufficient data)[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Chart generation failed: {e}[/yellow]")


def _write_comparison_output(content: str, output_dir: Path | None, filename: str, label: str) -> None:
    """Write comparison output to disk or print it directly."""
    if output_dir:
        output_path = output_dir / filename
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        console.print(f"[green]{label} {output_path}[/green]")
        return
    console.print(content)


def _run_sql_vs_dataframe(
    config,
    sql_platform: str,
    df_platform: str,
    data_dir: Path,
    output_dir: Path | None,
    output_format: str,
    generate_charts: bool,
    theme: str,
):
    """Run SQL vs DataFrame comparison."""
    from benchbox.core.dataframe.benchmark_suite import (
        SQLVsDataFrameBenchmark,
        SQLVsDataFramePlotter,
    )

    console.print("\n[bold]SQL vs DataFrame Comparison[/bold]")
    console.print(f"SQL Platform: {sql_platform}")
    console.print(f"DataFrame Platform: {df_platform}")
    console.print(f"Scale factor: {config.scale_factor}")
    console.print(f"Queries: {config.query_ids or 'all'}")
    console.print()

    benchmark = SQLVsDataFrameBenchmark(config=config)

    # Run comparison
    console.print("[dim]Running benchmarks...[/dim]")
    try:
        summary = benchmark.run_comparison(
            sql_platform=sql_platform,
            df_platform=df_platform,
            data_dir=data_dir,
        )
    except Exception as e:
        console.print(f"[red]Benchmark failed: {e}[/red]")
        sys.exit(1)

    # Output results
    if output_format == "text":
        _print_sql_vs_df_summary(summary)
    elif output_format == "json":
        import json

        output_str = json.dumps(summary.to_dict(), indent=2)
        if output_dir:
            output_path = output_dir / "sql_vs_dataframe.json"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(output_str, encoding="utf-8")
            console.print(f"[green]Results saved to {output_path}[/green]")
        else:
            console.print(output_str)
    elif output_format == "markdown":
        md_content = benchmark.generate_report(summary)
        if output_dir:
            output_path = output_dir / "sql_vs_dataframe.md"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path.write_text(md_content, encoding="utf-8")
            console.print(f"[green]Report saved to {output_path}[/green]")
        else:
            console.print(md_content)

    # Generate charts if requested
    if generate_charts and output_dir:
        try:
            plotter = SQLVsDataFramePlotter(summary, theme=theme)
            charts_dir = output_dir / "charts"
            exports = plotter.generate_charts(output_dir=charts_dir)
            if exports:
                chart_list = ", ".join(f"{ct}.txt" for ct in exports)
                console.print(f"[green]Charts generated in {charts_dir}: {chart_list}[/green]")
            else:
                console.print("[yellow]No charts generated (insufficient data)[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Chart generation failed: {e}[/yellow]")


def _print_text_summary(results, summary):
    """Print text summary of platform comparison."""
    console.print("\n" + "=" * 60)
    console.print("[bold]RESULTS[/bold]")
    console.print("=" * 60)

    console.print(f"\nFastest: [green]{summary.fastest_platform}[/green]")
    console.print(f"Slowest: [red]{summary.slowest_platform}[/red]")
    console.print()

    # Platform table
    console.print(f"{'Platform':15s} {'Geomean (ms)':>15s} {'Total (ms)':>15s} {'Success':>10s}")
    console.print("-" * 60)

    for result in sorted(results, key=lambda r: r.geometric_mean_ms or float("inf")):
        geomean = f"{result.geometric_mean_ms:.2f}" if result.geometric_mean_ms else "N/A"
        total = f"{result.total_time_ms:.2f}" if result.total_time_ms else "N/A"
        success = f"{result.success_rate:.0f}%"
        console.print(f"{result.platform:15s} {geomean:>15s} {total:>15s} {success:>10s}")

    console.print()

    # Query winners
    if summary.query_winners:
        console.print("[bold]Query Winners:[/bold]")
        for query_id, winner in sorted(summary.query_winners.items()):
            console.print(f"  {query_id}: {winner}")

    console.print("=" * 60)


def _print_sql_vs_df_summary(summary):
    """Print text summary of SQL vs DataFrame comparison."""
    console.print("\n" + "=" * 60)
    console.print("[bold]SQL vs DataFrame RESULTS[/bold]")
    console.print("=" * 60)

    console.print(f"\nSQL Platform: {summary.sql_platform}")
    console.print(f"DataFrame Platform: {summary.df_platform}")
    console.print()

    console.print(
        f"DataFrame faster: [green]{summary.df_faster_count}[/green] queries ({summary.df_wins_percentage:.1f}%)"
    )
    console.print(f"SQL faster: [yellow]{summary.sql_faster_count}[/yellow] queries")
    console.print(f"Average speedup: [bold]{summary.average_speedup:.2f}x[/bold]")
    console.print()

    # Query table
    console.print(f"{'Query':10s} {'SQL (ms)':>12s} {'DataFrame (ms)':>15s} {'Speedup':>10s}")
    console.print("-" * 60)

    for result in summary.query_results:
        if result.status == "SUCCESS":
            console.print(
                f"{result.query_id:10s} {result.sql_time_ms:>12.2f} {result.df_time_ms:>15.2f} {result.speedup:>10.2f}x"
            )
        else:
            console.print(f"{result.query_id:10s} [red]ERROR[/red]")

    console.print("=" * 60)


__all__ = ["compare_dataframes"]
