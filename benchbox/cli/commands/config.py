"""Configuration validation command implementation."""

from pathlib import Path

import click

from benchbox.cli.config import ConfigManager
from benchbox.cli.shared import console


@click.command("validate")
@click.option("--config", type=str, help="Configuration file path (optional)")
@click.pass_context
def validate(ctx, config):
    """Validate BenchBox configuration files for syntax and completeness.

    Checks configuration file syntax, validates platform settings, and verifies
    that required options are properly specified.

    \b
    Examples:
        benchbox validate                    # Validate default configuration
        benchbox validate --config custom.yaml  # Validate specific config file
    """
    try:
        config_manager = (
            ConfigManager(config_path=Path(config).expanduser(), strict=True) if config else ctx.obj["config"]
        )
        if not config_manager.validate_config():
            raise click.ClickException("Configuration validation failed")
    except (OSError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    console.print("[green]✅ Configuration is valid[/green]")


__all__ = ["validate"]
