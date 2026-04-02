"""CLI command to pre-download TPC answer files to the local cache."""

from __future__ import annotations

import sys

import click

from benchbox.cli.shared import console


@click.command("download-answers")
@click.option(
    "--benchmark",
    type=click.Choice(["tpch", "tpcds", "all"], case_sensitive=False),
    default="all",
    show_default=True,
    help="Which benchmark's answer files to download.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Re-download even if files already exist in cache.",
)
@click.option(
    "--show-cache-dir",
    is_flag=True,
    default=False,
    help="Print the cache directory path and exit. With --benchmark tpch/tpcds prints that benchmark's subdirectory; with 'all' (default) prints the parent cache directory.",
)
def download_answers(benchmark: str, force: bool, show_cache_dir: bool) -> None:
    """Pre-download TPC answer files for offline validation.

    Answer files are required for row-count validation of TPC-H and TPC-DS
    benchmark results. They are included in source distributions but not in
    wheel installs. This command downloads them on-demand to a local cache.

    The cache directory is $XDG_CACHE_HOME/benchbox/answers/ (or
    ~/.cache/benchbox/answers/ if XDG_CACHE_HOME is not set).

    Set BENCHBOX_ANSWERS_URL to override the default download URL.
    Set BENCHBOX_NO_DOWNLOAD=1 to disable all automatic downloads.

    Examples:
        benchbox download-answers                        # Download both TPC-H and TPC-DS
        benchbox download-answers --benchmark tpch       # TPC-H only
        benchbox download-answers --benchmark tpcds      # TPC-DS only
        benchbox download-answers --force                # Re-download even if cached
        benchbox download-answers --show-cache-dir       # Print cache location
    """
    from benchbox.core.expected_results.download import (
        download_all_answers,
        download_tpcds_answers,
        download_tpch_answers,
        get_answers_base_url,
        get_cache_dir,
        get_tpcds_cache_dir,
        get_tpch_cache_dir,
        is_download_disabled,
    )

    if show_cache_dir:
        benchmark_lower = benchmark.lower()
        if benchmark_lower == "tpch":
            console.print(str(get_tpch_cache_dir()))
        elif benchmark_lower == "tpcds":
            console.print(str(get_tpcds_cache_dir()))
        else:
            console.print(str(get_cache_dir()))
        return

    if is_download_disabled():
        console.print("[yellow]BENCHBOX_NO_DOWNLOAD is set — downloads are disabled.[/yellow]")
        return

    console.print(f"[dim]Source URL: {get_answers_base_url()}[/dim]")
    console.print()

    benchmark_lower = benchmark.lower()
    failed = False

    if benchmark_lower == "all":
        # Use download_all_answers to fetch the checksum manifest only once
        console.print("[bold]Downloading TPC-H and TPC-DS answer files...[/bold]")
        results = download_all_answers(force=force)
        for key, label in [("tpch", "TPC-H"), ("tpcds", "TPC-DS")]:
            if results[key] is not None:
                console.print(f"[green]✓ {label} answers cached at {results[key]}[/green]")
            else:
                console.print(
                    f"[red]✗ {label} answer download failed. Check network connectivity and BENCHBOX_ANSWERS_URL.[/red]"
                )
                failed = True
    elif benchmark_lower == "tpch":
        console.print("[bold]Downloading TPC-H answer files...[/bold]")
        result = download_tpch_answers(force=force)
        if result is not None:
            console.print(f"[green]✓ TPC-H answers cached at {result}[/green]")
        else:
            console.print(
                "[red]✗ TPC-H answer download failed. Check network connectivity and BENCHBOX_ANSWERS_URL.[/red]"
            )
            failed = True
    elif benchmark_lower == "tpcds":
        console.print("[bold]Downloading TPC-DS answer files...[/bold]")
        result = download_tpcds_answers(force=force)
        if result is not None:
            console.print(f"[green]✓ TPC-DS answers cached at {result}[/green]")
        else:
            console.print(
                "[red]✗ TPC-DS answer download failed. Check network connectivity and BENCHBOX_ANSWERS_URL.[/red]"
            )
            failed = True

    if failed:
        sys.exit(1)


__all__ = ["download_answers"]
