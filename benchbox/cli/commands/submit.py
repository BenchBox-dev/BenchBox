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

_DEFAULT_SERVICE_URL = "https://api.benchbox.dev/v1"
_VISIBILITY_CHOICES = ("public", "unlisted", "private")

# Static checklist (Option B from
# dry-run-followup-package-canonical-contributing): the four required steps
# are inlined so an offline contributor can complete a submission, and the
# canonical URL is included for the full guide. Drift risk is real but
# bounded; the pinned regression test in tests/unit/cli/commands/test_submit.py
# asserts the four required tokens stay present.
_CONTRIBUTING_TEXT = """\
# Contributing a Benchmark Result

Thank you for contributing to the BenchBox community results dataset!

This is a packaged checklist. The full guide lives at:
https://docs.benchbox.dev/contributing-results

## Quick checklist

1. Fork https://github.com/joeharris76/BenchBox (or use your existing fork).
2. Copy the contents of `bundle/` into `results-data/bundles/` in your fork.
3. Copy `submission-manifest.json` alongside the bundle files.
4. Regenerate the corpus inventory before you commit:

       uv run -- python scripts/generate_corpus_inventory.py --write

5. (Optional) Validate the bundle locally before pushing:

       uv run -- python scripts/validate_submission.py path/to/bundle.json

6. Open a pull request against the **`published-results`** branch (NOT
   `main`) with the title:
   `results: <benchmark> <platform> sf<scale>`
7. CI (Validate Submission) verifies the bundle hash against the manifest
   and posts a summary comment on your PR.

## Questions?

Open an issue or start a discussion at
https://github.com/joeharris76/BenchBox.

For the full guide (trust labels, quality expectations, troubleshooting),
see https://docs.benchbox.dev/contributing-results.
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


def _resolve_submitted_by(explicit: str | None) -> str:
    """Resolve the manifest's submitted_by field.

    Precedence: explicit --submitted-by > git config user.name > "" (with warning).
    The empty case stays a soft warning, not a hard failure: anonymous
    submissions are valid.
    """
    if explicit:
        return explicit.strip()
    from_git = _get_git_username()
    if from_git:
        return from_git
    console.print(
        "[yellow]warning:[/yellow] submitted_by is empty - "
        "set `git config user.name <name>` or pass `--submitted-by NAME`."
    )
    return ""


def _compute_file_hash(file_path: Path) -> str:
    """Compute SHA-256 of a single file's contents."""
    h = hashlib.sha256()
    try:
        h.update(file_path.read_bytes())
    except PermissionError:
        raise PermissionError(f"Cannot read file for hashing: {file_path}") from None
    return h.hexdigest()


def _dispatch_service_mode(
    ctx: click.Context,
    *,
    source_path: Path,
    companions: list[Path],
    service_url: str,
    visibility: str,
    idempotency_key: str | None,
    wait: bool,
    dry_run: bool,
) -> None:
    """Phase 3 hosted-API submission path.

    Currently a skeleton: --dry-run is fully supported (validates the
    bundle, prints what would be uploaded, no credentials needed). The
    real upload + auth + status-polling flow is the work in
    `integrate-benchbox-cli-submit-and-service-auth` w4-w8 and lands
    once the hosted ingest API is available.

    Hash contract for the dry-run: the values printed are SHA-256 of the
    on-disk source files as-is. The Phase 2 PR-package path
    (--output mode) hashes the same bytes after a `shutil.copy2` into
    `bundle/`, so the hashes are byte-identical there. If a future
    iteration of the real-upload path canonicalises (re-serialises) the
    bundle JSON before sending, this dry-run hash will diverge from the
    sent hash. In that case, hoist the canonicalisation step ahead of
    `_compute_file_hash` here so the dry-run reports what the server
    will actually receive.
    """
    bundle_size = source_path.stat().st_size
    bundle_hash = _compute_file_hash(source_path)
    companion_hashes = {comp.name: _compute_file_hash(comp) for comp in companions}

    if dry_run:
        console.print("\n[bold]Dry-run - would upload:[/bold]")
        console.print(f"  Service URL:      {service_url}")
        console.print(f"  Bundle file:      {source_path.name} ({bundle_size:,} bytes)")
        console.print(f"  Bundle hash:      {bundle_hash}")
        if companions:
            console.print("  Companions:")
            for comp in companions:
                console.print(f"    {comp.name}  {companion_hashes[comp.name]}")
        else:
            console.print("  Companions:       (none)")
        console.print(f"  Visibility:       {visibility}")
        console.print(f"  Idempotency key:  {idempotency_key or '(auto-generated at upload time)'}")
        console.print(f"  Wait for accept:  {wait}")
        console.print("\n[yellow]Dry-run complete - no bytes sent.[/yellow]")
        return

    # Real upload path is not yet implemented. Surface that explicitly
    # rather than silently no-op or partially-execute.
    console.print(
        "\n[red]Hosted submission upload is not yet implemented.[/red]\n"
        "  --service --dry-run works today; the live upload + auth flow lands\n"
        "  in `integrate-benchbox-cli-submit-and-service-auth` w4-w8, gated\n"
        "  on the Phase 3 promotion metrics in\n"
        "  _project/analysis/phase-3-promotion-metrics.md."
    )
    ctx.exit(1)


def _print_submission_summary(
    *,
    bundle_dir: Path,
    source_path: Path,
    companions: list[Path],
    manifest_path: Path,
    contributing_path: Path,
    output_path: Path,
    result,
    dry_run: bool,
) -> None:
    """Print the file list + next-step commands for the contributor.

    Same shape for dry-run and real-run so contributors see exactly
    what the real run will print before they commit. Dry-run swaps
    only the header and the trailing footer; the file list and
    next-steps block are identical (the commands reference the paths
    the real run would create — useful as a preview).
    """
    if dry_run:
        console.print("\n[bold]Dry-run preview — would create:[/bold]")
    else:
        console.print("\n[bold green]✓ Submission package created![/bold green]")

    bundle_filename = source_path.name
    bundle_target = f"results-data/bundles/{bundle_filename}"

    console.print(f"  {bundle_dir / bundle_filename}")
    for comp in companions:
        console.print(f"  {bundle_dir / comp.name}")
    console.print(f"  {manifest_path}")
    console.print(f"  {contributing_path}")

    if not dry_run:
        console.print(f"\n[dim]Output: {output_path.absolute()}[/dim]")

    pr_title = f"results: {result.benchmark_name} {result.platform} sf{result.scale_factor}"
    console.print("\n[bold]Next steps:[/bold]")
    console.print(f"  1. cp [cyan]{bundle_dir / bundle_filename}[/cyan] [cyan]{bundle_target}[/cyan]")
    for comp in companions:
        console.print(f"     cp [cyan]{bundle_dir / comp.name}[/cyan] [cyan]results-data/bundles/{comp.name}[/cyan]")
    console.print(f"     cp [cyan]{manifest_path}[/cyan] [cyan]results-data/bundles/{manifest_path.name}[/cyan]")
    console.print("  2. uv run -- python scripts/generate_corpus_inventory.py --write")
    console.print(f"  3. uv run -- python scripts/validate_submission.py {bundle_target}")
    console.print(f"  4. PR title:  [cyan]{pr_title}[/cyan]")
    console.print("     PR target: [cyan]published-results[/cyan]")
    console.print("[dim]Full guide: https://docs.benchbox.dev/contributing-results[/dim]")

    if dry_run:
        console.print("\n[yellow](dry run; no files written)[/yellow]")


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
    help="Phase 2 mode: output directory for the PR-package",
)
@click.option(
    "--service",
    "service_url",
    is_flag=False,
    flag_value=_DEFAULT_SERVICE_URL,
    default=None,
    help=(
        "Phase 3 mode: submit to the hosted ingest API. Without a value, "
        f"uses {_DEFAULT_SERVICE_URL}. Without this flag, --output runs."
    ),
)
@click.option(
    "--visibility",
    type=click.Choice(_VISIBILITY_CHOICES),
    default="public",
    show_default=True,
    help="Phase 3 only: visibility of the submitted result.",
)
@click.option(
    "--idempotency-key",
    type=str,
    default=None,
    help="Phase 3 only: override the auto-generated key. Useful for resumable retries.",
)
@click.option(
    "--wait/--no-wait",
    default=True,
    help="Phase 3 only: wait for ingest to finish and print the public URL. [default: --wait]",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Preview what would be packaged or uploaded without writing files / sending bytes.",
)
@click.option(
    "--submitted-by",
    "submitted_by",
    type=str,
    default=None,
    help=(
        "Override the manifest's submitted_by field. "
        "Precedence: this flag > git config user.name > empty (with warning)."
    ),
)
@click.pass_context
def submit(
    ctx,
    result_file,
    last,
    benchmark,
    platform,
    output_dir,
    service_url,
    visibility,
    idempotency_key,
    wait,
    dry_run,
    submitted_by,
):
    """Submit a benchmark result bundle to the BenchBox results platform.

    Two modes, selected by the flag set:

      --output PATH (Phase 2, default)
        Package the canonical bundle + submission manifest into PATH ready
        for opening a PR against the BenchBox repository's results-data/
        directory. No network. No credentials. Existing v0.2.x behavior.

      --service [URL] (Phase 3)
        Upload the canonical bundle to a hosted ingest API. Requires
        authentication via 'benchbox auth login'. With --dry-run, validates
        the bundle and prints what would be uploaded - no credentials
        needed for the dry-run path.

    RESULT_FILE: Path to result JSON file (optional; with --last, picked
    from history).

    Examples:
        # Package most recent result for PR contribution (Phase 2; default)
        benchbox submit --last

        # Submit most recent result to the hosted platform (Phase 3)
        benchbox submit --last --service

        # Submit a specific bundle to a non-default service URL
        benchbox submit results/tpch_sf01_duckdb.json --service https://staging.benchbox.dev/v1

        # Preview what would be uploaded without sending bytes
        benchbox submit --last --service --dry-run

    Note: benchbox submit shares results publicly. To copy a result to
    storage you control (local path, S3, etc.), use 'benchbox publish'.
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

    if service_url is not None:
        _dispatch_service_mode(
            ctx,
            source_path=source_path,
            companions=companions,
            service_url=service_url,
            visibility=visibility,
            idempotency_key=idempotency_key,
            wait=wait,
            dry_run=dry_run,
        )
        return

    output_path = Path(output_dir)
    bundle_dir = output_path / "bundle"
    manifest_path = output_path / "submission-manifest.json"
    contributing_path = output_path / "CONTRIBUTING.md"

    if dry_run:
        _print_submission_summary(
            bundle_dir=bundle_dir,
            source_path=source_path,
            companions=companions,
            manifest_path=manifest_path,
            contributing_path=contributing_path,
            output_path=output_path,
            result=result,
            dry_run=True,
        )
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
        "submitted_by": _resolve_submitted_by(submitted_by),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    contributing_path.write_text(_CONTRIBUTING_TEXT, encoding="utf-8")

    _print_submission_summary(
        bundle_dir=bundle_dir,
        source_path=source_path,
        companions=companions,
        manifest_path=manifest_path,
        contributing_path=contributing_path,
        output_path=output_path,
        result=result,
        dry_run=False,
    )


__all__ = ["submit"]
