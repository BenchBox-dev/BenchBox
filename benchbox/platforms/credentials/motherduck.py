"""MotherDuck credential setup and validation.

MotherDuck authentication is intentionally environment-driven: BenchBox
requires ``MOTHERDUCK_TOKEN`` for actual runs and does not persist the token
to ``~/.benchbox/credentials.yaml``.  The setup wizard may accept a masked
one-time token so users can validate it, but only non-secret metadata is saved.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
import re
from typing import Optional, Union

from rich.console import Console

from benchbox.platforms.credentials.helpers import prompt_secure_field, prompt_with_default
from benchbox.security.credentials import CredentialManager, CredentialStatus
from benchbox.utils.printing import QuietConsoleProxy

MOTHERDUCK_TOKEN_ENV = "MOTHERDUCK_TOKEN"
DEFAULT_MOTHERDUCK_DATABASE = "benchbox"


def setup_motherduck_credentials(cred_manager: CredentialManager, console: Union[Console, QuietConsoleProxy]) -> bool:
    """Interactive setup for MotherDuck connection validation.

    The token is never written to the credential store.  If the environment
    already provides ``MOTHERDUCK_TOKEN``, the stored status can be marked valid.
    If the user enters a one-time token at the prompt, BenchBox validates it and
    saves only the selected database plus the expected env-var name.
    """
    console.print("\n[bold]You'll need:[/bold]")
    console.print(f"  - A MotherDuck access token in {MOTHERDUCK_TOKEN_ENV}")
    console.print("  - A target MotherDuck database name")
    console.print("\n[dim]Create a token at: https://app.motherduck.com/token-request[/dim]\n")

    existing_creds = cred_manager.get_platform_credentials("motherduck") or {}
    current_database = existing_creds.get("database")

    database = prompt_with_default(
        "MotherDuck database name",
        current_value=current_database,
        default_if_none=DEFAULT_MOTHERDUCK_DATABASE,
    )
    if not database:
        console.print("[red]MotherDuck database name is required[/red]")
        return False

    env_token = os.environ.get(MOTHERDUCK_TOKEN_ENV)
    if env_token:
        console.print(f"[green]Found {MOTHERDUCK_TOKEN_ENV} in the environment.[/green]")
        token = env_token
        token_is_persistent = True
    else:
        console.print(f"[yellow]{MOTHERDUCK_TOKEN_ENV} is not set in this shell.[/yellow]")
        console.print("[dim]BenchBox will validate a one-time token here, but it will not save the token.[/dim]")
        token = prompt_secure_field("MotherDuck token", current_value=None, console=console)
        token_is_persistent = False

    if not token:
        console.print(f"[red]{MOTHERDUCK_TOKEN_ENV} is required for MotherDuck.[/red]")
        console.print(f"[dim]Set it before running benchmarks: export {MOTHERDUCK_TOKEN_ENV}=<your-token>[/dim]")
        return False

    credentials = {
        "database": database,
        "token_env_var": MOTHERDUCK_TOKEN_ENV,
    }
    cred_manager.set_platform_credentials("motherduck", credentials, CredentialStatus.NOT_VALIDATED)

    console.print("\n[bold]Validating MotherDuck connection...[/bold]")
    success, error = validate_motherduck_credentials(cred_manager, token=token, database=database)

    if success:
        if not token_is_persistent:
            os.environ[MOTHERDUCK_TOKEN_ENV] = token

        status = CredentialStatus.VALID if token_is_persistent else CredentialStatus.NOT_VALIDATED
        cred_manager.update_validation_status("motherduck", status)
        cred_manager.save_credentials()

        console.print("\n[green]MotherDuck connection validated.[/green]")
        console.print(f"   Database: [cyan]{database}[/cyan]")
        console.print(f"   Token source: [cyan]{MOTHERDUCK_TOKEN_ENV}[/cyan]")
        if token_is_persistent:
            console.print("   Status: [green]Ready to use[/green]\n")
        else:
            console.print("   Status: [yellow]Token was validated for this setup run only[/yellow]")
            console.print(f"   Export {MOTHERDUCK_TOKEN_ENV} before running benchmarks.\n")
        console.print("[bold]Try it:[/bold]")
        console.print("  benchbox run --platform motherduck --benchmark tpch --scale 0.01")
        return True
    else:
        cred_manager.update_validation_status("motherduck", CredentialStatus.INVALID, error)
        cred_manager.save_credentials()

        console.print("\n[red]MotherDuck validation failed[/red]")
        if error:
            console.print(f"   Error: {error}")
        console.print(f"\n[yellow]Set {MOTHERDUCK_TOKEN_ENV} and run:[/yellow]")
        console.print("  benchbox setup --platform motherduck --validate-only")
        return False


def validate_motherduck_credentials(
    cred_manager: CredentialManager,
    *,
    token: Optional[str] = None,
    database: Optional[str] = None,
) -> tuple[bool, Optional[str]]:
    """Validate MotherDuck credentials by opening a test connection.

    Args:
        cred_manager: Credential manager instance.
        token: Optional one-time token supplied by the setup wizard.
        database: Optional database override supplied by the setup wizard.

    Returns:
        Tuple of ``(success, error_message)``.
    """
    creds = cred_manager.get_platform_credentials("motherduck") or {}
    resolved_token = token or os.environ.get(MOTHERDUCK_TOKEN_ENV)
    resolved_database = database or creds.get("database") or DEFAULT_MOTHERDUCK_DATABASE

    if not resolved_token:
        return False, f"{MOTHERDUCK_TOKEN_ENV} is not set"

    adapter = None
    try:
        from benchbox.platforms.motherduck import MotherDuckAdapter

        adapter = MotherDuckAdapter(token=resolved_token, database=resolved_database)
        adapter.create_connection()
        return True, None
    except Exception as exc:
        return False, _redact_token(str(exc), resolved_token)
    finally:
        if adapter is not None:
            adapter.close_connection()


def _redact_token(message: str, token: str) -> str:
    """Remove MotherDuck token material from connection errors."""
    redacted = message.replace(token, "****") if token else message
    return re.sub(r"motherduck_token=[^&\s]+", "motherduck_token=****", redacted)


__all__ = [
    "DEFAULT_MOTHERDUCK_DATABASE",
    "MOTHERDUCK_TOKEN_ENV",
    "setup_motherduck_credentials",
    "validate_motherduck_credentials",
]
