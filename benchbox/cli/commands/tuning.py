"""Deprecated create-sample-tuning compatibility command."""

from pathlib import Path

import click

from benchbox.cli.shared import console


@click.command("create-sample-tuning", hidden=True)
@click.option("--platform", type=str, required=True, help="Target platform (duckdb, databricks, snowflake, etc.)")
@click.option("--output", type=str, default="tuning_config.yaml", help="Output file path")
@click.pass_context
def create_sample_tuning(ctx, platform, output):
    """Create a sample unified tuning configuration.

    DEPRECATED: Use `benchbox tuning init --platform <platform>` instead.

    Generates a YAML configuration file with platform-specific tuning options.

    Examples:
        benchbox tuning init --platform databricks
        benchbox tuning init --platform snowflake --output my-tuning.yaml
    """
    console.print(
        "[yellow]Warning: 'create-sample-tuning' is deprecated. Use 'benchbox tuning init' instead.[/yellow]\n"
    )
    output_path = Path(output)
    console.print(f"[bold cyan]Creating Sample Tuning Configuration for {platform.title()}[/bold cyan]")
    try:
        ctx.obj["config"].create_sample_unified_tuning_config(output_path, platform)
        console.print("\n[green]Tuning configuration created[/green]")
        console.print(f"File: [cyan]{output_path}[/cyan]")
        console.print(f"Platform: [yellow]{platform}[/yellow]")
        console.print("\nEdit this file to customize tuning settings for your benchmarks.")
    except Exception as e:
        console.print(f"[red]Failed to create tuning configuration: {e}[/red]")
        ctx.exit(1)
