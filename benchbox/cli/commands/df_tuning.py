"""Deprecated df-tuning compatibility command group."""

import click

from benchbox.cli.commands.tuning_group import (
    _create_profile_config as _create_profile_config,
    init as tuning_init,
    list_platforms as tuning_platforms,
    show_defaults as tuning_defaults,
    validate_config as tuning_validate,
)
from benchbox.cli.shared import console

DATAFRAME_PLATFORMS = ["polars", "pandas", "dask", "modin", "cudf"]
PROFILES = ["default", "optimized", "streaming", "memory-constrained", "gpu"]


@click.group("df-tuning", hidden=True)
def df_tuning_group():
    """Deprecated DataFrame tuning commands. Use `benchbox tuning` instead."""
    console.print("[yellow]Warning: 'df-tuning' is deprecated. Use 'benchbox tuning' commands instead.[/yellow]\n")


@df_tuning_group.command("create-sample")
@click.option("--platform", type=click.Choice(DATAFRAME_PLATFORMS, case_sensitive=False), required=True)
@click.option("--profile", type=click.Choice(PROFILES), default="default")
@click.option("--output", type=str, default=None)
@click.option("--smart-defaults", is_flag=True)
@click.pass_context
def create_sample(ctx, platform, profile, output, smart_defaults):
    """Create a sample deprecated DataFrame tuning configuration."""
    ctx.invoke(
        tuning_init,
        platform=platform,
        mode="dataframe",
        profile=profile,
        output=output or f"{platform.lower()}_{profile.replace('-', '_')}.yaml",
        smart_defaults=smart_defaults,
    )


@df_tuning_group.command("validate")
@click.argument("config_file", type=click.Path(exists=True))
@click.option("--platform", type=click.Choice(DATAFRAME_PLATFORMS, case_sensitive=False), required=True)
@click.pass_context
def validate(ctx, config_file, platform):
    """Validate a deprecated DataFrame tuning file."""
    ctx.invoke(tuning_validate, config_file=config_file, platform=platform)


@df_tuning_group.command("show-defaults")
@click.option("--platform", type=click.Choice(DATAFRAME_PLATFORMS, case_sensitive=False), required=True)
@click.pass_context
def show_defaults(ctx, platform):
    """Show smart defaults for a DataFrame platform."""
    ctx.invoke(tuning_defaults, platform=platform)


@df_tuning_group.command("list-platforms")
@click.pass_context
def list_platforms(ctx):
    """List DataFrame tuning platforms."""
    ctx.invoke(tuning_platforms)
