"""Setup command for interactive platform credentials configuration.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import click
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm
from rich.table import Table

from benchbox.cli.shared import console
from benchbox.security.credentials import CredentialManager, CredentialStatus

SUPPORTED_SETUP_PLATFORMS = ("databricks", "snowflake", "bigquery", "redshift", "athena", "motherduck")

PLATFORM_DISPLAY_NAMES = {
    "athena": "Athena",
    "bigquery": "Bigquery",
    "databricks": "Databricks",
    "motherduck": "MotherDuck",
    "redshift": "Redshift",
    "snowflake": "Snowflake",
}


@click.command("setup")
@click.option(
    "--platform",
    type=click.Choice(SUPPORTED_SETUP_PLATFORMS, case_sensitive=False),
    help="Platform to configure",
)
@click.option("--validate-only", is_flag=True, help="Validate existing credentials without modifying")
@click.option("--list-platforms", "list_platforms_flag", is_flag=True, help="List platforms requiring credentials")
@click.option("--status", "show_status", is_flag=True, help="Show credential status for all platforms")
@click.option("--remove", is_flag=True, help="Remove credentials for the specified platform")
@click.option("--diagnose", is_flag=True, help="Run diagnostics on platform connectivity (Redshift only)")
@click.pass_context
def setup_credentials(ctx, platform, validate_only, list_platforms_flag, show_status, remove, diagnose):
    """Interactive setup for cloud platform credentials.

    Guides you through setting up authentication for Databricks, Snowflake,
    BigQuery, Redshift, Athena, and MotherDuck platforms. Most platforms use
    secure local credential storage; MotherDuck validates MOTHERDUCK_TOKEN
    without storing the token.

    Examples:
        benchbox setup --platform databricks    # Interactive Databricks setup
        benchbox setup --platform motherduck    # Validate MOTHERDUCK_TOKEN
        benchbox setup --list-platforms         # Show all platforms
        benchbox setup --status                 # Check credential status
        benchbox setup --platform databricks --validate-only  # Validate only
        benchbox setup --platform redshift --diagnose         # Run connectivity diagnostics
        benchbox setup --platform databricks --remove         # Remove credentials
    """
    from benchbox.utils.dependencies import DEPENDENCY_GROUPS

    cred_manager = CredentialManager()

    # Handle list platforms
    if list_platforms_flag:
        _list_platforms(cred_manager)
        return

    # Handle status display
    if show_status:
        _show_credential_status(cred_manager)
        return

    # Require platform for other operations
    if not platform:
        console.print("[red]❌ Error: --platform is required[/red]")
        console.print(f"\nAvailable platforms: {', '.join(SUPPORTED_SETUP_PLATFORMS)}")
        console.print("\nUse: benchbox setup --platform <name>")
        console.print("Or:  benchbox setup --list-platforms")
        return

    platform_lower = platform.lower()

    # Handle remove operation
    if remove:
        _remove_credentials(cred_manager, platform_lower)
        return

    # Handle diagnose operation
    if diagnose:
        _diagnose_platform(cred_manager, platform_lower)
        return

    # Handle validate-only operation
    if validate_only:
        _validate_credentials(cred_manager, platform_lower)
        return

    # Check if dependencies are installed
    if platform_lower in DEPENDENCY_GROUPS:
        from benchbox.utils.dependencies import check_platform_dependencies

        available, missing = check_platform_dependencies(platform_lower)
        if not available:
            from benchbox.utils.dependencies import get_install_command

            console.print(f"[red]❌ Missing dependencies for {platform}:[/red]")
            console.print(f"   {', '.join(missing)}")
            console.print("\n[yellow]Install with:[/yellow]")
            console.print(f"   {escape(get_install_command(platform_lower))}")
            return

    # Interactive setup
    run_platform_credential_setup(platform_lower, console, show_welcome=True)


def _list_platforms(cred_manager: CredentialManager):
    """List all supported platforms with setup instructions."""
    console.print("\n[bold]Cloud Platforms Requiring Credentials:[/bold]\n")

    platforms_info = [
        {
            "name": "Databricks",
            "key": "databricks",
            "description": "Lakehouse platform with Unity Catalog",
            "required": ["server_hostname", "http_path", "access_token"],
        },
        {
            "name": "Snowflake",
            "key": "snowflake",
            "description": "Cloud data warehouse",
            "required": ["account", "user", "password", "warehouse"],
        },
        {
            "name": "BigQuery",
            "key": "bigquery",
            "description": "Google Cloud data warehouse",
            "required": ["project_id", "credentials_file"],
        },
        {
            "name": "Redshift",
            "key": "redshift",
            "description": "Amazon data warehouse",
            "required": ["host", "port", "database", "user", "password"],
        },
        {
            "name": "Athena",
            "key": "athena",
            "description": "AWS serverless query-on-S3",
            "required": ["s3_staging_dir", "region"],
        },
        {
            "name": "MotherDuck",
            "key": "motherduck",
            "description": "Serverless DuckDB cloud",
            "required": ["MOTHERDUCK_TOKEN", "database"],
        },
    ]

    # Get current status
    current_platforms = cred_manager.list_platforms()

    for platform_info in platforms_info:
        key = platform_info["key"]
        status = current_platforms.get(key, CredentialStatus.MISSING)

        # Status indicator
        if status == CredentialStatus.VALID:
            status_icon = "[green]✅ Configured[/green]"
        elif status == CredentialStatus.INVALID:
            status_icon = "[red]❌ Invalid[/red]"
        elif status == CredentialStatus.NOT_VALIDATED:
            status_icon = "[yellow]⚠️  Not validated[/yellow]"
        else:
            status_icon = "[dim]○ Not configured[/dim]"

        console.print(f"{status_icon} [bold]{platform_info['name']}[/bold] - {platform_info['description']}")
        console.print(f"   Required: {', '.join(platform_info['required'])}")
        console.print(f"   Setup: [cyan]benchbox setup --platform {key}[/cyan]\n")


def _show_credential_status(cred_manager: CredentialManager):
    """Show detailed credential status for all platforms."""
    platforms = cred_manager.list_platforms()

    if not platforms:
        console.print("[yellow]No credentials configured yet.[/yellow]")
        console.print("\nUse: benchbox setup --platform <name>")
        return

    console.print("\n[bold]Credential Status:[/bold]\n")

    table = Table(show_header=True, box=None)
    table.add_column("Platform", style="bold")
    table.add_column("Status")
    table.add_column("Last Updated")
    table.add_column("Last Validated")

    for platform_name, status in platforms.items():
        creds = cred_manager.get_platform_credentials(platform_name)

        # Status with icon
        if status == CredentialStatus.VALID:
            status_str = "[green]✅ Valid[/green]"
        elif status == CredentialStatus.INVALID:
            status_str = "[red]❌ Invalid[/red]"
        elif status == CredentialStatus.NOT_VALIDATED:
            status_str = "[yellow]⚠️  Not validated[/yellow]"
        else:
            status_str = "[dim]○ Unknown[/dim]"

        last_updated = creds.get("last_updated", "Never") if creds else "Never"
        last_validated = creds.get("last_validated", "Never") if creds else "Never"

        # Format timestamps
        if last_updated != "Never":
            last_updated = last_updated.split("T")[0]
        if last_validated != "Never":
            last_validated = last_validated.split("T")[0]

        table.add_row(_platform_display_name(platform_name), status_str, last_updated, last_validated)

    console.print(table)
    console.print("\n[dim]Validate credentials: benchbox setup --platform <name> --validate-only[/dim]")


def _remove_credentials(cred_manager: CredentialManager, platform: str):
    """Remove credentials for a platform."""
    if not cred_manager.has_credentials(platform):
        console.print(f"[yellow]No credentials found for {platform}[/yellow]")
        return

    if not Confirm.ask(f"Remove credentials for {platform}?"):
        console.print("[yellow]Cancelled[/yellow]")
        return

    cred_manager.remove_platform_credentials(platform)
    cred_manager.save_credentials()

    console.print(f"[green]✅ Removed credentials for {platform}[/green]")


def _diagnose_platform(cred_manager: CredentialManager, platform: str):
    """Run diagnostics on platform connectivity."""
    if platform != "redshift":
        console.print(f"[yellow]❌ Diagnostics not available for {platform} yet[/yellow]")
        console.print("[dim]Currently only supported for Redshift[/dim]")
        return

    if not cred_manager.has_credentials(platform):
        console.print(f"[red]❌ No credentials found for {platform}[/red]")
        console.print(f"\nSetup credentials: benchbox setup --platform {platform}")
        return

    console.print(f"\n[bold]Running diagnostics for {platform}...[/bold]\n")

    # Import Redshift-specific diagnostic helpers
    try:
        from benchbox.platforms.credentials.redshift import (
            _diagnose_redshift_connectivity,
            _format_diagnostic_output,
            _format_remediation_steps,
            _test_tcp_connectivity,
        )

        creds = cred_manager.get_platform_credentials(platform)
        assert creds is not None  # Validated by has_credentials check above
        host = creds["host"]
        port = creds.get("port", 5439)
        aws_access_key_id = creds.get("aws_access_key_id")
        aws_secret_access_key = creds.get("aws_secret_access_key")
        aws_region = creds.get("aws_region", "us-east-1")

        # Test TCP connectivity
        console.print("[dim]Testing network connectivity...[/dim]")
        tcp_reachable, tcp_error = _test_tcp_connectivity(host, port, timeout=10)

        if tcp_reachable:
            console.print("[green]✓ TCP connection successful[/green]")
        else:
            console.print(f"[red]✗ TCP connection failed: {tcp_error}[/red]")

        # Run AWS API diagnostics
        diagnostics = _diagnose_redshift_connectivity(host, port, aws_access_key_id, aws_secret_access_key, aws_region)

        # Display diagnostic results
        _format_diagnostic_output(console, host, port, aws_region, diagnostics)

        # Show remediation steps if there are issues
        if not tcp_reachable or diagnostics.get("publicly_accessible") is False:
            _format_remediation_steps(console, host, port, aws_region, diagnostics, tcp_reachable)
        else:
            console.print("\n[green]✓ No obvious connectivity issues detected[/green]")
            console.print("\nIf you're still having connection issues, try:")
            console.print("  benchbox setup --platform redshift --validate-only")

    except ImportError as e:
        console.print(f"[red]❌ Diagnostic module not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Diagnostic failed: {e}[/red]")


def _validate_credentials(cred_manager: CredentialManager, platform: str):
    """Validate existing credentials for a platform."""
    if platform != "motherduck" and not cred_manager.has_credentials(platform):
        console.print(f"[red]❌ No credentials found for {platform}[/red]")
        console.print(f"\nSetup credentials: benchbox setup --platform {platform}")
        return

    console.print(f"\n[bold]Validating {platform} credentials...[/bold]\n")

    # Get platform-specific validator
    try:
        if platform == "databricks":
            from benchbox.platforms.databricks.credentials import validate_databricks_credentials

            success, error = validate_databricks_credentials(cred_manager)
        elif platform == "snowflake":
            from benchbox.platforms.credentials.snowflake import validate_snowflake_credentials

            success, error = validate_snowflake_credentials(cred_manager)
        elif platform == "bigquery":
            from benchbox.platforms.credentials.bigquery import validate_bigquery_credentials

            success, error = validate_bigquery_credentials(cred_manager)
        elif platform == "redshift":
            from benchbox.platforms.credentials.redshift import validate_redshift_credentials

            success, error = validate_redshift_credentials(cred_manager, console)
        elif platform == "athena":
            from benchbox.platforms.credentials.athena import validate_athena_credentials

            success, error = validate_athena_credentials(cred_manager, console)
        elif platform == "motherduck":
            from benchbox.platforms.credentials.motherduck import validate_motherduck_credentials

            success, error = validate_motherduck_credentials(cred_manager)
        else:
            console.print(f"[red]❌ Validation not implemented for {platform}[/red]")
            return

        if success:
            if platform == "motherduck" and not cred_manager.has_credentials(platform):
                from benchbox.platforms.credentials.motherduck import (
                    DEFAULT_MOTHERDUCK_DATABASE,
                    MOTHERDUCK_TOKEN_ENV,
                )

                cred_manager.set_platform_credentials(
                    "motherduck",
                    {
                        "database": DEFAULT_MOTHERDUCK_DATABASE,
                        "token_env_var": MOTHERDUCK_TOKEN_ENV,
                    },
                    CredentialStatus.NOT_VALIDATED,
                )
            cred_manager.update_validation_status(platform, CredentialStatus.VALID)
            cred_manager.save_credentials()
            console.print(f"[green]✅ {_platform_display_name(platform)} credentials are valid[/green]")
        else:
            cred_manager.update_validation_status(platform, CredentialStatus.INVALID, error)
            cred_manager.save_credentials()
            console.print(f"[red]❌ {_platform_display_name(platform)} credentials are invalid[/red]")
            if error:
                console.print(f"   Error: {error}")

    except ImportError as e:
        console.print(f"[red]❌ Validation module not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]❌ Validation failed: {e}[/red]")


def run_platform_credential_setup(platform: str, console_obj, show_welcome: bool = True) -> bool:
    """Run interactive credential setup for a platform.

    Args:
        platform: Platform name (snowflake, bigquery, databricks, redshift)
        console_obj: Console object for output
        show_welcome: Whether to show welcome panel (False when called from run command)

    Returns:
        True if credentials were successfully set up and validated, False otherwise
    """
    cred_manager = CredentialManager()

    # Display welcome panel
    if show_welcome:
        platform_name = _platform_display_name(platform)
        welcome_text = f"[bold]{platform_name} Credentials Setup[/bold]\n\n"
        welcome_text += f"BenchBox will guide you through setting up {platform_name} credentials."
        console_obj.print(Panel(welcome_text, border_style="blue"))

    # Get platform-specific setup handler
    try:
        if platform == "databricks":
            from benchbox.platforms.databricks.credentials import setup_databricks_credentials

            setup_databricks_credentials(cred_manager, console_obj)
            # Check if credentials were saved (successful setup)
            return cred_manager.has_credentials(platform)
        elif platform == "snowflake":
            from benchbox.platforms.credentials.snowflake import setup_snowflake_credentials

            setup_snowflake_credentials(cred_manager, console_obj)
            return cred_manager.has_credentials(platform)
        elif platform == "bigquery":
            from benchbox.platforms.credentials.bigquery import setup_bigquery_credentials

            setup_bigquery_credentials(cred_manager, console_obj)
            return cred_manager.has_credentials(platform)
        elif platform == "redshift":
            from benchbox.platforms.credentials.redshift import setup_redshift_credentials

            setup_redshift_credentials(cred_manager, console_obj)
            return cred_manager.has_credentials(platform)
        elif platform == "athena":
            from benchbox.platforms.credentials.athena import setup_athena_credentials

            setup_athena_credentials(cred_manager, console_obj)
            return cred_manager.has_credentials(platform)
        elif platform == "motherduck":
            from benchbox.platforms.credentials.motherduck import setup_motherduck_credentials

            return setup_motherduck_credentials(cred_manager, console_obj)
        else:
            console_obj.print(f"[red]❌ Setup not implemented for {platform}[/red]")
            return False

    except ImportError as e:
        console_obj.print(f"[red]❌ Setup module not available: {e}[/red]")
        console_obj.print("\nThis platform may not have guided setup yet.")
        console_obj.print("Check documentation for manual setup instructions.")
        return False
    except Exception as e:
        console_obj.print(f"[red]❌ Setup failed: {e}[/red]")
        return False


def _platform_display_name(platform: str) -> str:
    """Return a user-facing platform name."""
    return PLATFORM_DISPLAY_NAMES.get(platform.lower(), platform.capitalize())


__all__ = ["setup_credentials", "run_platform_credential_setup"]
