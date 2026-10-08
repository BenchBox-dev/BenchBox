# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from rich.prompt import Confirm, Prompt

if TYPE_CHECKING:
    from rich.console import Console

    from benchbox.security.credentials import CredentialManager
    from benchbox.utils.printing import QuietConsoleProxy


def prompt_default_output_location(
    *,
    cred_manager: CredentialManager,
    console: Union[Console, QuietConsoleProxy],
    credentials: dict,
    platform_name: str,
    path_scheme: str,
    storage_label: str,
    permission_note: str,
    bucket: Optional[str] = None,
) -> None:
    from benchbox.security.credentials import CredentialStatus
    from benchbox.utils.cloud_storage import is_cloud_path

    console.print("\n[bold]Default Output Location (Optional):[/bold]")
    console.print("Configure a default cloud path for benchmark data storage.")
    console.print("This prevents needing to specify --output for every run.\n")

    wants_default = Confirm.ask("Configure default output location?", default=True)

    if not wants_default:
        console.print("[dim]You can add --output <cloud-path> when running benchmarks[/dim]\n")
        return

    console.print(f"\n[bold cyan]Example paths for {platform_name}:[/bold cyan]")
    if bucket:
        console.print(f"  • [dim]{path_scheme}{bucket}/benchbox-data[/dim] (using your staging bucket)")
        console.print(f"  • [dim]{path_scheme}{bucket}/data[/dim]")
    else:
        console.print(f"  • [dim]{path_scheme}my-bucket/benchbox-data[/dim]")
        console.print(f"  • [dim]{path_scheme}my-bucket/data[/dim]")

    console.print(f"\n[bold]{storage_label}:[/bold]")
    console.print(f"  {path_scheme}<bucket>/<path>")
    console.print(f"\n[dim]Note: Ensure the bucket exists and {permission_note}[/dim]\n")

    suggested_default = f"{path_scheme}{bucket}/benchbox-data" if bucket else ""

    while True:
        cloud_path = Prompt.ask("[bold]Enter default cloud storage path[/bold]", default=suggested_default)

        if not cloud_path:
            console.print("[yellow]Skipping default output location[/yellow]\n")
            return

        if not is_cloud_path(cloud_path):
            console.print(f"[yellow]⚠️  Warning: '{cloud_path}' doesn't look like a cloud path[/yellow]")
            console.print(f"[dim]Expected format: {path_scheme}<bucket>/<path>[/dim]")
            proceed = Confirm.ask("Use this path anyway?", default=False)
            if not proceed:
                continue

        console.print(f"\n[green]✓[/green] Will use: [cyan]{cloud_path}[/cyan]")
        confirmed = Confirm.ask("Is this correct?", default=True)
        if confirmed:
            credentials["default_output_location"] = cloud_path
            cred_manager.set_platform_credentials(platform_name.lower(), credentials, CredentialStatus.VALID)
            cred_manager.save_credentials()
            console.print("[green]✅ Default output location saved![/green]\n")
            return
