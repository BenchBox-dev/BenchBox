"""CLI command group for the results explorer static build pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import click

from benchbox.cli.shared import console
from benchbox.core.explorer_pipeline.contract import EXPLORER_BUILD_CONTRACT


@click.group("explorer")
def explorer_group() -> None:
    """Manage the results explorer static build pipeline."""


@explorer_group.command("build")
@click.option(
    "--data-dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Root data directory containing bundles/ sub-directory.",
)
@click.option(
    "--output",
    "output_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Output directory for results.duckdb and copied bundles.",
)
@click.option(
    "--trust-label",
    default="maintainer-run",
    show_default=True,
    help="Trust label to attach to every result entry.",
)
@click.option(
    "--visibility",
    default="public-curated",
    show_default=True,
    help="Visibility label to attach to every result entry.",
)
def explorer_build(
    data_dir: Path,
    output_dir: Path,
    trust_label: str,
    visibility: str,
) -> None:
    """Build the results explorer static dataset from schema-v2 bundles.

    Scans DATA_DIR/bundles/ for result JSON files, transforms them into the
    explorer read model, and writes the output to OUTPUT_DIR:

    \b
    - results.duckdb          DuckDB-WASM queryable snapshot
    - bundles/{id}.json       copied source bundles for download/audit links

    Examples:

    \b
      benchbox explorer build \\
        --data-dir results-data/ \\
        --output results-explorer/public/data/

    \b
      benchbox explorer build \\
        --data-dir results-data/ \\
        --output results-explorer/public/data/ \\
        --trust-label community-submission \\
        --visibility public-self-reported
    """
    from benchbox.core.explorer_pipeline.pipeline import ExplorerPipeline

    console.print("[bold]Explorer build[/bold]")
    console.print(f"  Data dir:    [cyan]{data_dir}[/cyan]")
    console.print(f"  Output dir:  [cyan]{output_dir}[/cyan]")
    console.print(f"  Trust label: [dim]{trust_label}[/dim]")
    console.print(f"  Visibility:  [dim]{visibility}[/dim]")
    console.print()

    pipeline = ExplorerPipeline()
    try:
        stats = pipeline.run(
            data_dir=data_dir,
            output_dir=output_dir,
            trust_label=trust_label,
            visibility=visibility,
        )
        skipped_note = f" ({stats.skipped} skipped)" if stats.skipped else ""
        console.print(
            f"[green]Done.[/green] Processed {stats.processed} result(s){skipped_note} "
            f"across {stats.cohorts} cohort(s) → {stats.output_dir}"
        )
    except Exception as exc:
        console.print(f"[red]Pipeline failed: {exc}[/red]")
        raise SystemExit(1) from exc


@explorer_group.command("build-contract", hidden=True)
def explorer_build_contract() -> None:
    """Emit the stable contract metadata for explorer-build integrations."""

    click.echo(json.dumps(EXPLORER_BUILD_CONTRACT))


__all__ = ["explorer_group"]
