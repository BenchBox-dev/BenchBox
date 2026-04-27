"""SingleStore credentials setup and validation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
from typing import Optional, Union

from rich.console import Console
from rich.prompt import Confirm

from benchbox.platforms.credentials.helpers import prompt_secure_field, prompt_with_default
from benchbox.security.credentials import CredentialManager, CredentialStatus
from benchbox.utils.printing import QuietConsoleProxy


def setup_singlestore_credentials(cred_manager: CredentialManager, console: Union[Console, QuietConsoleProxy]) -> None:
    """Interactive setup for SingleStore credentials.

    Supports both SingleStore Helios (cloud) and self-managed deployments.

    Args:
        cred_manager: Credential manager instance
        console: Rich console for output
    """
    console.print("\n📋 [bold]You'll need:[/bold]")
    console.print("  • SingleStore hostname (Helios endpoint or self-managed host)")
    console.print("  • Port (default: 3306)")
    console.print("  • Username and password")
    console.print("  • Database name (will be created if it doesn't exist)\n")

    console.print("[dim]Need help? Visit: https://docs.singlestore.com/cloud/connecting-to-singlestore/[/dim]\n")

    existing_creds = cred_manager.get_platform_credentials("singlestore")

    if existing_creds:
        console.print("ℹ️  [cyan]Existing credentials found - updating configuration[/cyan]\n")
        auto_config = None
    else:
        auto_config = None
        try_auto = Confirm.ask("🔍 Attempt auto-detection from environment variables?", default=True)

        if try_auto:
            console.print("\n[dim]Checking environment variables...[/dim]")
            auto_config = _auto_detect_singlestore(console)

    if auto_config:
        host = auto_config.get("host")
        port = auto_config.get("port")
        username = auto_config.get("username")
        password = auto_config.get("password")
        database = auto_config.get("database")

        console.print(f"\n✅ Found host: [cyan]{host}[/cyan]")
        console.print(f"✅ Found username: [cyan]{username}[/cyan]")
        if database:
            console.print(f"✅ Found database: [cyan]{database}[/cyan]")
    else:
        console.print("\n[bold]SingleStore Configuration:[/bold]")

        current_host = existing_creds.get("host") if existing_creds else None
        current_port = existing_creds.get("port") if existing_creds else None
        current_username = existing_creds.get("username") if existing_creds else None
        current_password = existing_creds.get("password") if existing_creds else None
        current_database = existing_creds.get("database") if existing_creds else None

        host = prompt_with_default(
            "Host (e.g., xyz.singlestore.com or localhost)",
            current_value=current_host,
            default_if_none="localhost",
        )

        if not host:
            console.print("[red]❌ Host is required[/red]")
            return

        port_str = prompt_with_default(
            "Port",
            current_value=str(current_port) if current_port else None,
            default_if_none="3306",
        )
        try:
            port = int(port_str or "3306")
        except ValueError:
            console.print("[red]❌ Port must be a number[/red]")
            return

        username = prompt_with_default("Username", current_value=current_username, default_if_none="root")

        if not username:
            console.print("[red]❌ Username is required[/red]")
            return

        password = prompt_secure_field("Password", current_value=current_password, console=console)

        if password is None:
            console.print("[red]❌ Password is required[/red]")
            return

        database = prompt_with_default("Database name", current_value=current_database, default_if_none="benchbox")

        if not database:
            console.print("[red]❌ Database name is required[/red]")
            return

    credentials = {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "database": database,
    }

    console.print("\n🧪 [bold]Validating credentials...[/bold]")

    cred_manager.set_platform_credentials("singlestore", credentials, CredentialStatus.NOT_VALIDATED)

    success, error = validate_singlestore_credentials(cred_manager)

    if success:
        cred_manager.update_validation_status("singlestore", CredentialStatus.VALID)
        cred_manager.save_credentials()

        console.print("\n[green]✅ SingleStore credentials validated and saved![/green]")
        console.print(f"   Location: [cyan]{cred_manager.credentials_path}[/cyan]")
        console.print("   Status: [green]Ready to use[/green]\n")

        console.print("[bold]Try it:[/bold]")
        console.print("  benchbox run --platform singlestore --benchmark tpch --scale 0.01")
    else:
        cred_manager.update_validation_status("singlestore", CredentialStatus.INVALID, error)
        cred_manager.save_credentials()

        console.print("\n[red]❌ Validation failed[/red]")
        if error:
            console.print(f"   Error: {error}")
        console.print("\n[yellow]Credentials saved but marked as invalid.[/yellow]")
        console.print("Fix the issues and run: benchbox setup --platform singlestore --validate-only")


def validate_singlestore_credentials(cred_manager: CredentialManager) -> tuple[bool, Optional[str]]:
    """Validate SingleStore credentials by testing connection.

    Args:
        cred_manager: Credential manager instance

    Returns:
        Tuple of (success, error_message)
    """
    creds = cred_manager.get_platform_credentials("singlestore")

    if not creds:
        return False, "No credentials found"

    required_fields = ["host", "username", "password"]
    missing = [field for field in required_fields if creds.get(field) is None]

    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"

    try:
        import singlestoredb as s2
    except ImportError:
        return False, "singlestoredb not installed. Run: uv add singlestoredb"

    try:
        conn = s2.connect(
            host=creds["host"],
            port=int(creds.get("port", 3306)),
            user=creds["username"],
            password=creds["password"],
            connect_timeout=10,
        )

        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()

        try:
            cursor.execute("SELECT @@memsql_version")
            cursor.fetchall()
        except Exception:
            pass

        cursor.close()
        conn.close()

        return True, None

    except Exception as e:
        error_msg = str(e)
        if "access denied" in error_msg.lower() or "authentication" in error_msg.lower():
            return False, "Authentication failed. Check your username and password."
        elif "connection refused" in error_msg.lower() or "can't connect" in error_msg.lower():
            return False, f"Could not connect to {creds.get('host')}:{creds.get('port', 3306)}. Check host and port."
        else:
            return False, f"Connection failed: {error_msg}"


def _auto_detect_singlestore(console: Union[Console, QuietConsoleProxy]) -> Optional[dict]:
    """Attempt to auto-detect SingleStore configuration from environment variables.

    Args:
        console: Rich console for output

    Returns:
        Dictionary with detected config or None
    """
    env_vars = {
        "host": os.getenv("SINGLESTORE_HOST"),
        "port": os.getenv("SINGLESTORE_PORT", "3306"),
        "username": os.getenv("SINGLESTORE_USER") or os.getenv("SINGLESTORE_USERNAME"),
        "password": os.getenv("SINGLESTORE_PASSWORD"),
        "database": os.getenv("SINGLESTORE_DATABASE"),
    }

    required = ["host", "username", "password"]
    found_required = all(env_vars.get(field) for field in required)

    if not found_required:
        missing = [f"SINGLESTORE_{f.upper()}" for f in required if not env_vars.get(f)]
        console.print(f"  ⚠️  Missing environment variables: {', '.join(missing)}")
        return None

    try:
        env_vars["port"] = int(env_vars["port"])
    except (TypeError, ValueError):
        env_vars["port"] = 3306

    console.print("  ✓ Found all required environment variables")
    return env_vars


__all__ = ["setup_singlestore_credentials", "validate_singlestore_credentials"]
