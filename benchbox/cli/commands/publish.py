"""benchbox publish command — publish schema-v2 result bundles to storage.

Publishes an already-exported result bundle to a local directory or cloud
storage prefix. Tracks each publication in a persistent metadata store
(~/.benchbox/published.json) so publication history survives process restart.

Distinct from ``benchbox export``, which serialises live BenchmarkResults
objects to disk. ``benchbox publish`` operates on already-exported files and
adds addressability, deduplication, and persistent tracking on top.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path

import click

from benchbox.cli.shared import console
from benchbox.core.publishing.bundle_publisher import COMPANION_SUFFIXES, VALID_LABELS, BundlePublisher
from benchbox.core.publishing.store import PublicationStore

# ---------------------------------------------------------------------------
# publish group
# ---------------------------------------------------------------------------


@click.group("publish")
def publish() -> None:
    """Publish and track schema-v2 result bundles.

    Copies an already-exported result bundle to a storage destination and
    records a durable reference in the publication history. Distinct from
    'benchbox export', which serialises live benchmark results to disk.

    \b
    Backends and reference types:
      local path         -> file:///abs/path/to/bundle.json
      s3://bucket/prefix -> s3://bucket/prefix/bundle.json
      gs://bucket/prefix -> gs://bucket/prefix/bundle.json
      abfss://...        -> abfss://.../bundle.json

    \b
    Examples:
      benchbox publish results/tpch_sf1_duckdb.json
      benchbox publish results/tpch_sf1_duckdb.json --target /mnt/shared/benchbox
      benchbox publish results/tpch_sf1_duckdb.json --target s3://my-bucket/benchbox
      benchbox publish list
      benchbox publish show abc123def456
      benchbox publish remove abc123def456
    """


# ---------------------------------------------------------------------------
# publish <result-file>
# ---------------------------------------------------------------------------


@publish.command("run")
@click.argument("result_file", required=False, type=click.Path())
@click.option(
    "--target",
    default="benchmark_runs/published",
    show_default=True,
    help="Destination directory or cloud URI (s3://, gs://, abfss://).",
)
@click.option(
    "--label",
    type=click.Choice(list(VALID_LABELS), case_sensitive=False),
    default="maintainer-run",
    show_default=True,
    help="Trust / provenance label for this publication.",
)
@click.option(
    "--last",
    is_flag=True,
    help="Publish the most recent result file.",
)
@click.option("--benchmark", type=str, help="Filter by benchmark name when using --last.")
@click.option("--platform", type=str, help="Filter by platform name when using --last.")
@click.option("--dry-run", is_flag=True, help="Preview without publishing.")
@click.pass_context
def publish_run(ctx, result_file, target, label, last, benchmark, platform, dry_run):
    """Publish a schema-v2 result bundle to a storage destination.

    RESULT_FILE: Path to the primary .json result file (optional; use --last for auto-select).
    """
    source_path = _resolve_source(result_file, last, benchmark, platform)
    if source_path is None:
        return

    if dry_run:
        console.print(f"[bold]Dry run — would publish:[/bold] {source_path}")
        console.print(f"  Target:  {target}")
        console.print(f"  Label:   {label}")
        companion_count = _count_companions(source_path)
        if companion_count:
            console.print(f"  + {companion_count} companion file(s) (.plans.json, .tuning.json)")
        return

    store = PublicationStore()
    publisher = BundlePublisher(destination=target, store=store, label=label)
    result = publisher.publish(source_path)

    if not result.success:
        for err in result.errors:
            console.print(f"[red]Error:[/red] {err}")
        raise SystemExit(1)

    if result.errors:
        # Success but with warnings (e.g., store write failed)
        for err in result.errors:
            console.print(f"[yellow]Warning:[/yellow] {err}")

    console.print(f"[green]Published:[/green] {source_path.name}")
    if result.record:
        console.print(f"  ID:        {result.record.pub_id}")
    console.print(f"  Reference: {result.reference}")
    console.print(f"  Label:     {label}")

    companion_count = _count_companions(source_path)
    if companion_count:
        console.print(f"  + {companion_count} companion file(s) also published")


# ---------------------------------------------------------------------------
# publish list
# ---------------------------------------------------------------------------


@publish.command("list")
@click.option("--benchmark", type=str, help="Filter by benchmark name.")
@click.option("--platform", type=str, help="Filter by platform name.")
@click.option("--label", type=str, help="Filter by label.")
def publish_list(benchmark, platform, label):
    """List published artifacts from the publication history."""
    store = PublicationStore()
    records = store.list_all()

    if benchmark:
        records = [r for r in records if benchmark.lower() in r.benchmark.lower()]
    if platform:
        records = [r for r in records if platform.lower() in r.platform.lower()]
    if label:
        records = [r for r in records if r.label == label]

    if not records:
        console.print("[yellow]No publications found.[/yellow]")
        console.print("[dim]Tip: Use 'benchbox publish results/your-result.json' to publish a result.[/dim]")
        return

    console.print(f"\n[bold]Published artifacts ({len(records)} total)[/bold]")
    console.print(f"Store: [dim]{store.store_path}[/dim]\n")

    try:
        from rich.table import Table

        table = Table(show_header=True)
        table.add_column("ID", style="cyan", width=14)
        table.add_column("Benchmark", style="green")
        table.add_column("Platform", style="blue")
        table.add_column("Label", style="dim")
        table.add_column("Published At", style="dim")
        table.add_column("Reference", style="dim")

        for rec in records:
            ts = rec.published_at[:19].replace("T", " ") if rec.published_at else ""
            ref = rec.reference
            if len(ref) > 60:
                ref = "..." + ref[-57:]
            table.add_row(rec.pub_id, rec.benchmark, rec.platform, rec.label, ts, ref)

        console.print(table)
    except Exception:
        # Fallback if rich is not available in this context
        for rec in records:
            ts = rec.published_at[:19].replace("T", " ") if rec.published_at else ""
            console.print(f"  {rec.pub_id}  {rec.benchmark}/{rec.platform}  {ts}")
            console.print(f"    -> {rec.reference}")


# ---------------------------------------------------------------------------
# publish show <id>
# ---------------------------------------------------------------------------


@publish.command("show")
@click.argument("pub_id")
def publish_show(pub_id):
    """Show details of a published artifact by ID."""
    store = PublicationStore()
    rec = store.get(pub_id)

    if rec is None:
        console.print(f"[red]No publication found with ID: {pub_id}[/red]")
        raise SystemExit(1)

    console.print(f"\n[bold]Publication {rec.pub_id}[/bold]")
    console.print(f"  Benchmark:    {rec.benchmark or '(unknown)'}")
    console.print(f"  Platform:     {rec.platform or '(unknown)'}")
    console.print(f"  Scale factor: {rec.scale_factor}")
    console.print(f"  Label:        {rec.label}")
    console.print(f"  Published at: {rec.published_at}")
    console.print(f"  Source:       {rec.source_path}")
    console.print(f"  Destination:  {rec.destination}")
    console.print(f"  Reference:    {rec.reference}")


# ---------------------------------------------------------------------------
# publish remove <id>
# ---------------------------------------------------------------------------


@publish.command("remove")
@click.argument("pub_id")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
def publish_remove(pub_id, yes):
    """Remove a publication record.

    This removes the metadata entry only. The underlying artifact files are
    NOT deleted from the destination.

    PUB_ID: The publication ID to remove (from 'benchbox publish list').
    """
    store = PublicationStore()
    rec = store.get(pub_id)

    if rec is None:
        console.print(f"[red]No publication found with ID: {pub_id}[/red]")
        raise SystemExit(1)

    console.print("[bold]Publication to remove:[/bold]")
    console.print(f"  ID:        {rec.pub_id}")
    console.print(f"  Benchmark: {rec.benchmark}/{rec.platform}")
    console.print(f"  Reference: {rec.reference}")
    console.print("[dim]Note: artifact files are NOT deleted from the destination.[/dim]")

    if not yes:
        if not click.confirm("\nRemove this publication record?", default=False):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    store.remove(pub_id)
    console.print(f"[green]Removed publication {pub_id}[/green]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_source(
    result_file: str | None,
    last: bool,
    benchmark: str | None,
    platform: str | None,
) -> Path | None:
    """Resolve the source bundle path from arguments."""
    if result_file:
        path = Path(result_file)
        if not path.exists():
            console.print(f"[red]File not found: {result_file}[/red]")
            return None
        return path

    if last:
        from benchbox.core.results.loader import find_latest_result

        default_results_dir = Path("benchmark_runs/results")
        path = find_latest_result(default_results_dir, benchmark=benchmark, platform=platform)
        if not path:
            console.print("[yellow]No results found.[/yellow]")
            if benchmark or platform:
                filters = []
                if benchmark:
                    filters.append(f"benchmark={benchmark}")
                if platform:
                    filters.append(f"platform={platform}")
                console.print(f"  Filters: {', '.join(filters)}")
            return None
        console.print(f"[blue]Using latest result:[/blue] {path.name}")
        return path

    console.print("[yellow]Please specify a result file or use --last.[/yellow]")
    console.print("\n[bold]Examples:[/bold]")
    console.print("  benchbox publish run results/tpch_sf1_duckdb.json")
    console.print("  benchbox publish run --last --benchmark tpch")
    console.print("  benchbox publish list")
    return None


def _count_companions(source: Path) -> int:
    """Count companion files beside a bundle."""
    stem = source.stem
    return sum(1 for s in COMPANION_SUFFIXES if (source.parent / (stem + s)).exists())


# ---------------------------------------------------------------------------
# Programmatic entry point for benchbox run --publish
# ---------------------------------------------------------------------------


def publish_bundle(
    source_bundle: Path,
    target: str = "benchmark_runs/published",
    label: str = "maintainer-run",
    quiet: bool = False,
) -> str | None:
    """Publish a bundle programmatically (used by benchbox run --publish).

    Args:
        source_bundle: Path to the primary .json result bundle.
        target: Destination directory or cloud URI.
        label: Trust label.
        quiet: If True, suppress non-error output.

    Returns:
        The durable reference string on success, or None on failure.
    """
    store = PublicationStore()
    publisher = BundlePublisher(destination=target, store=store, label=label)
    result = publisher.publish(source_bundle)

    if not result.success:
        for err in result.errors:
            console.print(f"[red]Publish error:[/red] {err}")
        return None

    if result.errors and not quiet:
        for err in result.errors:
            console.print(f"[yellow]Publish warning:[/yellow] {err}")

    if not quiet:
        console.print(f"[green]Published:[/green] {result.reference}")

    return result.reference


__all__ = ["publish", "publish_bundle"]
