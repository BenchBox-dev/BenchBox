"""Deprecated create-sample-tuning compatibility command."""

import click

from benchbox.cli.commands.tuning_group import init as tuning_init
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
    ctx.invoke(tuning_init, platform=platform, mode="sql", profile="default", output=output, smart_defaults=False)
