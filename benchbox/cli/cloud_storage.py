# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import sys
from typing import Optional

from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from benchbox.core.platform_registry import PlatformRegistry
from benchbox.utils.cloud_storage import is_cloud_path
from benchbox.utils.printing import quiet_console

console = quiet_console


def prompt_cloud_output_location(
    platform_name: str,
    benchmark_name: str,
    scale_factor: float,
    non_interactive: bool = False,
    default_output: Optional[str] = None,
) -> Optional[str]:
    if not PlatformRegistry.requires_cloud_storage(platform_name):
        return None

    if non_interactive or not sys.stdin.isatty():
        return None

    console.print()
    console.print(
        Panel.fit(
            f"[bold yellow]Cloud Storage Configuration Required[/bold yellow]\n\n"
            f"The {platform_name.upper()} platform requires a cloud storage location "
            f"for staging benchmark data.",
            style="yellow",
            title="⚠️  Cloud Platform Detected",
        )
    )

    examples = PlatformRegistry.get_cloud_path_examples(platform_name)
    if examples:
        console.print(f"\n[bold cyan]Example paths for {platform_name.upper()}:[/bold cyan]")
        for example in examples:
            console.print(f"  • [dim]{example}[/dim]")

    _display_platform_guidance(platform_name)

    console.print()

    if default_output:
        console.print("[bold cyan]Configured Default Location:[/bold cyan]")
        console.print(f"  {default_output}")
        console.print()

        use_default = Confirm.ask(
            "Use this location?",
            default=True,
        )

        if use_default:
            console.print(f"[green]✓[/green] Using configured default: [cyan]{default_output}[/cyan]")
            return default_output

        console.print("[dim]You can enter a different location below...[/dim]")
        console.print()

    wants_cloud = Confirm.ask(
        "Do you want to specify a cloud output location now?",
        default=True,
    )

    if not wants_cloud:
        console.print("[yellow]⚠️  Warning: Benchmark will likely fail without cloud output location[/yellow]")
        console.print("[dim]You can add --output <cloud-path> when running the command manually[/dim]")
        return None

    return _prompt_and_validate_cloud_path(default_output)


def _prompt_and_validate_cloud_path(default_output: Optional[str]) -> Optional[str]:
    while True:
        cloud_path = Prompt.ask("\n[bold]Enter cloud storage path[/bold]", default=default_output or "")

        if not cloud_path:
            console.print("[red]❌ Cloud path cannot be empty[/red]")
            if not Confirm.ask("Try again?", default=True):
                return None
            continue

        if not is_cloud_path(cloud_path):
            console.print(f"[yellow]⚠️  Warning: '{cloud_path}' doesn't look like a cloud path[/yellow]")
            console.print("[dim]Expected formats: s3://, gs://, abfss://, dbfs:/Volumes/...[/dim]")
            if not Confirm.ask("Use this path anyway?", default=False):
                continue

        console.print(f"\n[green]✓[/green] Will use: [cyan]{cloud_path}[/cyan]")
        if Confirm.ask("Is this correct?", default=True):
            return cloud_path


def _display_platform_guidance(platform_name: str) -> None:
    guidance = {
        "databricks": [
            "",
            "[bold]Unity Catalog Volume:[/bold]",
            "  dbfs:/Volumes/<catalog>/<schema>/<volume>/<path>",
            "",
            "[bold]External Cloud Storage:[/bold]",
            "  S3:    s3://<bucket>/<path>",
            "  Azure: abfss://<container>@<storage>.dfs.core.windows.net/<path>",
            "  GCS:   gs://<bucket>/<path>",
            "",
            "[dim]Note: Ensure the volume/bucket exists and the cluster has access permissions[/dim]",
        ],
        "bigquery": [
            "",
            "[bold]Google Cloud Storage:[/bold]",
            "  gs://<bucket>/<path>",
            "",
            "[dim]Note: Ensure the bucket exists and the service account has[/dim]",
            "[dim]storage.objects.create permission[/dim]",
        ],
        "snowflake": [
            "",
            "[bold]External Stage Locations:[/bold]",
            "  S3:   s3://<bucket>/<path>",
            "  Azure: azure://<container>/<path>",
            "  GCS:   gcs://<bucket>/<path>",
            "",
            "[dim]Note: Create an external stage pointing to this location first[/dim]",
        ],
        "redshift": [
            "",
            "[bold]S3 Staging Location:[/bold]",
            "  s3://<bucket>/<path>",
            "",
            "[dim]Note: Ensure the bucket exists and the cluster IAM role has[/dim]",
            "[dim]s3:PutObject permission[/dim]",
        ],
    }

    platform_guidance = guidance.get(platform_name.lower())
    if platform_guidance:
        for line in platform_guidance:
            console.print(line)
