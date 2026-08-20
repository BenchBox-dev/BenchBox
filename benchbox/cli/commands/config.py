"""Configuration validation command implementation."""

import click

from benchbox.cli.shared import console


@click.command("validate")
@click.option("--config", type=str, help="Configuration file path (optional)")
@click.pass_context
def validate(ctx, config):
    """Validate BenchBox configuration files for syntax and completeness.

    Checks configuration file syntax, validates platform settings, and verifies
    that required options are properly specified.

    Examples:
        benchbox validate                    # Validate default configuration
        benchbox validate --config custom.yaml  # Validate specific config file
    """
    config_manager = ctx.obj["config"]
    if config_manager.validate_config():
        console.print("[green]✅ Configuration is valid[/green]")
    else:
        console.print("[red]❌ Configuration validation failed[/red]")


__all__ = ["validate"]
