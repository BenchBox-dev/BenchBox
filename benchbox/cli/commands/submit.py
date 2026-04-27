"""Result submission command implementation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import click

import benchbox
from benchbox.cli.shared import console
from benchbox.core.results.loader import (
    ResultLoadError,
    UnsupportedSchemaError,
    find_latest_result,
    load_result_file,
)

# Submission manifest phase - indicates the result schema generation (v2.0 = phase 2).
_SUBMISSION_PHASE = 2

_CONTRIBUTING_TEXT = """\
# Contributing a Benchmark Result

Thank you for contributing to the BenchBox community results dataset!

## How to open the PR

1. Fork https://github.com/joeharris76/BenchBox (or use your existing fork)
2. Copy the contents of `bundle/` into `results-data/bundles/` in your fork
3. Copy `submission-manifest.json` alongside the bundle files
4. Open a pull request with the title:
   `results: <benchmark> <platform> sf<scale>`
5. The CI will validate the bundle hash against the manifest automatically

## Questions?

Open an issue at https://github.com/joeharris76/BenchBox or start a discussion.
"""


def _get_git_username() -> str:
    """Return the git config user.name, or empty string if unavailable."""
    try:
        result = subprocess.run(
            ["git", "config", "user.name"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 of a single file's contents."""
    h = hashlib.sha256()
    try:
        h.update(file_path.read_bytes())
    except PermissionError:
        raise PermissionError(f"Cannot read file for hashing: {file_path}") from None
    return h.hexdigest()


@click.command("submit")
@click.argument("result_file", required=False, type=click.Path(exists=True))
@click.option(
    "--last",
    is_flag=True,
    help="Use most recent result file",
)
@click.option(
    "--benchmark",
    type=str,
    help="Filter by benchmark name (with --last)",
)
@click.option(
    "--platform",
    type=str,
    help="Filter by platform name (with --last)",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(),
    default="submission",
    show_default=True,
    help="Output directory for submission package",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be packaged without writing files",
)
@click.pass_context
def submit(ctx, result_file, last, benchmark, platform, output_dir, dry_run):
    """Package a benchmark result bundle for contribution to the hosted results platform.

    Creates an output directory with the canonical bundle + submission manifest
    ready for opening a PR against results-data/.

    RESULT_FILE: Path to result JSON file (optional)

    Examples:
        # Package specific result
        benchbox submit results/tpch_sf1_duckdb.json

        # Package most recent result
        benchbox submit --last

        # Package most recent TPC-H result
        benchbox submit --last --benchmark tpch

        # Preview what would be packaged
        benchbox submit --last --dry-run

        # Use a custom output directory
        benchbox submit --last --output ./my-submission

    Note: benchbox submit packages results for PR contribution.
          benchbox publish copies results to local or cloud storage.
          These are different operations with different workflows.
    """
    if result_file:
        source_path = Path(result_file)
    elif last:
        default_results_dir = Path("benchmark_runs/results")
        source_path = find_latest_result(
            default_results_dir,
            benchmark=benchmark,
            platform=platform,
        )

        if not source_path:
            console.print("[yellow]No results found[/yellow]")
            if benchmark or platform:
                filters = []
                if benchmark:
                    filters.append(f"benchmark={benchmark}")
                if platform:
                    filters.append(f"platform={platform}")
                console.print(f"  Filters: {', '.join(filters)}")
            console.print("\n[dim]Tip: Run a benchmark first or check benchmark_runs/results/[/dim]")
            ctx.exit(1)
            return

        console.print(f"[blue]Using latest result:[/blue] {source_path.name}")
    else:
        console.print("[yellow]Please specify a result file or use --last[/yellow]")
        console.print("\n[bold]Examples:[/bold]")
        console.print("  benchbox submit result.json")
        console.print("  benchbox submit --last")
        console.print("  benchbox submit --last --benchmark tpch --dry-run")
        console.print("\n[dim]Tip: Use 'benchbox results' to see available result files[/dim]")
        ctx.exit(1)
        return

    try:
        result, _raw = load_result_file(source_path)
        console.print(f"[green]✓[/green] Loaded: {result.benchmark_name} ({result.platform})")
        console.print(
            f"  Scale: {result.scale_factor}, Queries: {result.total_queries}, Duration: {result.duration_seconds:.2f}s"
        )
    except FileNotFoundError:
        console.print(f"[red]Error: Result file not found: {source_path}[/red]")
        ctx.exit(1)
        return
    except UnsupportedSchemaError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("[dim]Only schema version 2.0 is currently supported for submission[/dim]")
        ctx.exit(1)
        return
    except ResultLoadError as e:
        console.print(f"[red]Error loading result file: {e}[/red]")
        console.print("[dim]The file may be corrupted or in an invalid format[/dim]")
        ctx.exit(1)
        return
    except Exception as e:
        console.print(f"[red]Unexpected error: {e}[/red]")
        ctx.exit(1)
        return

    # Compliance guardrail: refuse submission of unofficial results.
    # Unofficial TPC-DS runs (subscale or non-standard SF) must not be submitted
    # as they are not valid TPC-DS comparable results.
    _compliance_class = getattr(result, "compliance_class", None)
    _unofficial_classes = {"unofficial_nonstandard", "unofficial_subscale"}
    if _compliance_class in _unofficial_classes:
        console.print(
            f"\n[red]❌ Submission refused: compliance_class={_compliance_class}[/red]\n"
            "   This result was produced with an unofficial TPC-DS configuration and\n"
            "   must not be submitted as a comparable result. Only results with\n"
            "   compliance_class=official may be submitted.\n"
            "   See _sources/tpcds-subscale-contract.md for details."
        )
        ctx.exit(1)
        return

    companions = [
        p
        for suffix in (".plans.json", ".tuning.json")
        if (p := source_path.with_name(source_path.stem + suffix)).exists()
    ]

    output_path = Path(output_dir)
    bundle_dir = output_path / "bundle"
    manifest_path = output_path / "submission-manifest.json"
    contributing_path = output_path / "CONTRIBUTING.md"

    if dry_run:
        console.print("\n[bold]Dry-run - would create:[/bold]")
        console.print(f"  {bundle_dir / source_path.name}")
        for comp in companions:
            console.print(f"  {bundle_dir / comp.name}")
        console.print(f"  {manifest_path}")
        console.print(f"  {contributing_path}")
        console.print("[yellow]Dry-run complete - no files written[/yellow]")
        return

    bundle_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(source_path, bundle_dir / source_path.name)
    for comp in companions:
        shutil.copy2(comp, bundle_dir / comp.name)

    # Per-file hashes — bundle_hash covers the primary bundle JSON only,
    # companion_hashes maps each companion's filename to its SHA-256.
    # Per-file is the contract used by scripts/validate_submission.py;
    # using a directory-level hash here would not survive the user
    # copying the files into results-data/bundles/ where 13+ other
    # bundles already live.
    bundle_hash = _compute_file_hash(bundle_dir / source_path.name)
    companion_hashes = {comp.name: _compute_file_hash(bundle_dir / comp.name) for comp in companions}

    manifest = {
        "submission_tool_version": f"benchbox/{benchbox.__version__}",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "bundle_file": source_path.name,
        "bundle_hash": bundle_hash,
        "companion_hashes": companion_hashes,
        "benchmark": result.benchmark_name,
        "platform": result.platform,
        "scale_factor": result.scale_factor,
        "phase": _SUBMISSION_PHASE,
        "submission_path": "PR-based",
        "submitted_by": _get_git_username(),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    contributing_path.write_text(_CONTRIBUTING_TEXT, encoding="utf-8")

    console.print("\n[bold green]✓ Submission package created![/bold green]")
    console.print(f"  {bundle_dir / source_path.name}")
    for comp in companions:
        console.print(f"  {bundle_dir / comp.name}")
    console.print(f"  {manifest_path.name}")
    console.print(f"  {contributing_path.name}")
    console.print(f"\n[dim]Output: {output_path.absolute()}[/dim]")
    console.print("\n[bold]Next step:[/bold] Open a PR against results-data/ using the files above.")
    console.print("[dim]See CONTRIBUTING.md in the output directory for instructions.[/dim]")


__all__ = ["submit"]
