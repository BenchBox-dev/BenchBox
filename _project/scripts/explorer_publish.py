"""Maintainer entry point for publishing the Results Explorer read model."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

# `_project/` is a PEP 420 implicit namespace package (no `__init__.py`) and is
# excluded from the wheel build (see `tool.setuptools.packages.find` in
# `pyproject.toml`). When this script is invoked as
# `python _project/scripts/explorer_publish.py`, only the script's own directory
# lands on sys.path, so `_project.scripts.explorer_pipeline.*` imports below
# would fail. Insert the repo root so the namespace package resolves.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from benchbox.cli.shared import console
from _project.scripts.explorer_pipeline.contract import EXPLORER_BUILD_CONTRACT


@click.group()
def explorer_publish() -> None:
    """Manage the Results Explorer static build pipeline."""


@explorer_publish.command("build")
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
      uv run -- python _project/scripts/explorer_publish.py build \\
        --data-dir results-data/ \\
        --output results-explorer/public/data/

    \b
      uv run -- python _project/scripts/explorer_publish.py build \\
        --data-dir results-data/ \\
        --output results-explorer/public/data/ \\
        --trust-label community-submission \\
        --visibility public-self-reported
    """
    from _project.scripts.explorer_pipeline.pipeline import ExplorerPipeline

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


@explorer_publish.command("build-contract", hidden=True)
def explorer_build_contract() -> None:
    """Emit the stable contract metadata for explorer-build integrations."""

    click.echo(json.dumps(EXPLORER_BUILD_CONTRACT))


def main() -> None:
    """Script entry point."""
    explorer_publish()


if __name__ == "__main__":
    main()


__all__ = ["explorer_build", "explorer_build_contract", "explorer_publish", "main"]
