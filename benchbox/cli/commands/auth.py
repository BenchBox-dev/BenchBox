"""Hosted submission authentication commands."""

from __future__ import annotations

import click

from benchbox.cli.shared import console
from benchbox.cli.submit_auth import (
    DEFAULT_SERVICE_URL,
    SubmissionAuthError,
    SubmissionAuthStore,
    get_submission_auth_status,
    normalize_service_url,
    refresh_submission_token,
)


@click.group("auth")
def auth() -> None:
    """Manage hosted result-submission credentials."""


@auth.command("login")
@click.option(
    "--service",
    "service_url",
    default=DEFAULT_SERVICE_URL,
    show_default=True,
    help="Hosted results service URL.",
)
@click.option(
    "--token",
    default=None,
    help=(
        "Token to store. Prefer the prompt or BENCHBOX_SUBMIT_TOKEN; "
        "command-line values may be stored in shell history or process listings."
    ),
)
@click.pass_context
def login(ctx: click.Context, service_url: str, token: str | None) -> None:
    """Store a hosted results service token in the OS keyring."""

    store = SubmissionAuthStore()
    try:
        if token is None:
            refresh_submission_token(service_url, store=store)
        else:
            store.save_token(service_url, token)
    except SubmissionAuthError as exc:
        console.print(f"[red]Authentication setup failed:[/red] {exc}")
        ctx.exit(1)
        return

    console.print("[green]Hosted submission credentials saved.[/green]")
    console.print(f"  Service URL: {normalize_service_url(service_url)}")


@auth.command("status")
@click.option(
    "--service",
    "service_url",
    default=DEFAULT_SERVICE_URL,
    show_default=True,
    help="Hosted results service URL.",
)
@click.pass_context
def status(ctx: click.Context, service_url: str) -> None:
    """Show whether hosted submission credentials are available."""

    try:
        auth_status = get_submission_auth_status(service_url)
    except SubmissionAuthError as exc:
        console.print(f"[red]Could not inspect hosted submission credentials:[/red] {exc}")
        ctx.exit(1)
        return

    console.print(f"Service URL: {auth_status.service_url}")
    if auth_status.authenticated:
        console.print(f"[green]Authenticated[/green] via {auth_status.source}")
    else:
        console.print("[yellow]Not authenticated[/yellow]")
        console.print("Run `benchbox auth login` or set BENCHBOX_SUBMIT_TOKEN.")
        console.print("[dim]BENCHBOX_SERVICE_TOKEN is also accepted as a fallback.[/dim]")


@auth.command("refresh")
@click.option(
    "--service",
    "service_url",
    default=DEFAULT_SERVICE_URL,
    show_default=True,
    help="Hosted results service URL.",
)
@click.pass_context
def refresh(ctx: click.Context, service_url: str) -> None:
    """Replace the stored hosted results service token."""

    try:
        refresh_submission_token(service_url)
    except SubmissionAuthError as exc:
        console.print(f"[red]Authentication refresh failed:[/red] {exc}")
        ctx.exit(1)
        return

    console.print("[green]Hosted submission credentials refreshed.[/green]")
    console.print(f"  Service URL: {normalize_service_url(service_url)}")


@auth.command("logout")
@click.option(
    "--service",
    "service_url",
    default=DEFAULT_SERVICE_URL,
    show_default=True,
    help="Hosted results service URL.",
)
@click.pass_context
def logout(ctx: click.Context, service_url: str) -> None:
    """Remove the stored hosted results service token from the OS keyring."""

    store = SubmissionAuthStore()
    try:
        deleted = store.delete_token(service_url)
        current_status = get_submission_auth_status(service_url, store=store)
    except SubmissionAuthError as exc:
        console.print(f"[red]Authentication logout failed:[/red] {exc}")
        ctx.exit(1)
        return

    if deleted:
        console.print("[green]Hosted submission credentials removed.[/green]")
    else:
        console.print("[yellow]No stored hosted submission credentials found.[/yellow]")

    if current_status.authenticated and current_status.source and current_status.source.startswith("environment:"):
        console.print(f"[yellow]Environment token still active via {current_status.source}.[/yellow]")


__all__ = ["auth"]
