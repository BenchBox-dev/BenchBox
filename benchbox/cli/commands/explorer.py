"""CLI command group for the results explorer static build pipeline."""

from __future__ import annotations

import json
from pathlib import Path

import click
from pydantic import ValidationError

from benchbox.cli.shared import console
from benchbox.core.explorer_pipeline.contract import EXPLORER_BUILD_CONTRACT
from benchbox.core.explorer_pipeline.models import DetailResult
from benchbox.core.explorer_pipeline.transformer import (
    build_comparison_artifact,
    comparison_artifact_hash,
)


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
    help="Output directory for generated artifacts (manifest, details, duckdb).",
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
    - manifest.json          navigation index
    - results.duckdb         DuckDB-WASM queryable snapshot
    - bundles/{id}.json      copied source bundles

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
        pipeline.run(
            data_dir=data_dir,
            output_dir=output_dir,
            trust_label=trust_label,
            visibility=visibility,
        )
        # Count artifacts written
        manifest_path = output_dir / "manifest.json"
        total = 0
        if manifest_path.exists():
            with open(manifest_path, encoding="utf-8") as fh:
                total = json.load(fh).get("total_results", 0)

        console.print(f"[green]Done.[/green] Processed {total} result(s) → {output_dir}")
    except Exception as exc:
        console.print(f"[red]Pipeline failed: {exc}[/red]")
        raise SystemExit(1) from exc


@explorer_group.command("build-contract", hidden=True)
def explorer_build_contract() -> None:
    """Emit the stable contract metadata for explorer-build integrations."""

    click.echo(json.dumps(EXPLORER_BUILD_CONTRACT))


def _comparison_artifact_path(result_ids: list[str], out_dir: Path) -> Path:
    """Compute the deterministic output path for a comparison artifact.

    Hash: sha256(sorted_result_ids_csv)[:16]  - same algorithm used by
    the explorer frontend to locate the artifact.
    """
    return out_dir / f"{comparison_artifact_hash(result_ids)}.json"


@explorer_group.command("build-comparison")
@click.option(
    "--data-dir",
    required=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Root data directory containing details/ sub-directory.",
)
@click.option(
    "--ids",
    required=True,
    help="Comma-separated result IDs to include in the comparison.",
)
@click.option(
    "--out",
    "out_dir",
    required=True,
    type=click.Path(file_okay=False, path_type=Path),
    help="Directory to write the comparison artifact JSON file.",
)
def explorer_build_comparison(
    data_dir: Path,
    ids: str,
    out_dir: Path,
) -> None:
    """Build a pre-computed comparison artifact for an ordered set of result IDs.

    Reads per-result detail JSON files from DATA_DIR/details/ and writes a
    single pre-computed ComparisonArtifact to OUT_DIR/<hash16>.json.

    The output filename is deterministic: sha256(sorted_result_ids_csv)[:16].json.
    The explorer frontend computes the same hash to locate the artifact.

    \b
    Examples:

    \b
      benchbox explorer build-comparison \\
        --data-dir results-explorer/public/data/ \\
        --ids r1,r2,r3 \\
        --out results-explorer/public/data/compare/

    \b
      benchbox explorer build-comparison \\
        --data-dir results-data/ \\
        --ids tpch-duckdb-sf0.1-20260101-abc12345,tpch-sqlite-sf0.1-20260101-def67890 \\
        --out results-explorer/public/data/compare/
    """
    result_ids = [rid.strip() for rid in ids.split(",") if rid.strip()]
    if len(result_ids) < 2:
        console.print("[red]Error: --ids requires at least 2 result IDs.[/red]")
        raise SystemExit(1)

    # Load detail files
    details_dir = data_dir / "details"
    loaded = []
    for rid in result_ids:
        detail_path = details_dir / f"{rid}.json"
        if not detail_path.exists():
            console.print(f"[red]Detail file not found: {detail_path}[/red]")
            raise SystemExit(1)
        try:
            with open(detail_path, encoding="utf-8") as fh:
                detail_data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            console.print(f"[red]Failed to read {detail_path}: {exc}[/red]")
            raise SystemExit(1) from exc
        loaded.append(detail_data)

    try:
        detail_results = [DetailResult.model_validate(d) for d in loaded]
    except ValidationError as exc:
        console.print(f"[red]Detail validation failed: {exc}[/red]")
        raise SystemExit(1) from exc

    try:
        artifact = build_comparison_artifact(detail_results)
    except ValueError as exc:
        console.print(f"[red]Cannot build comparison: {exc}[/red]")
        raise SystemExit(1) from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = _comparison_artifact_path(result_ids, out_dir)

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(artifact.model_dump_json())

    console.print(f"[green]Done.[/green] Comparison artifact → {out_path}")
    console.print(f"  benchmark: {artifact.benchmark}  SF{artifact.scale_factor:g}")
    console.print(f"  rows: {len(artifact.rows)}  queries: {len(artifact.query_cells)}")
    if artifact.comparability_warnings:
        for w in artifact.comparability_warnings:
            console.print(f"  [yellow]⚠[/yellow]  {w.message}")


__all__ = ["explorer_group"]
