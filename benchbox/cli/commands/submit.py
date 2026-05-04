"""Result submission command implementation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

import click

import benchbox
from benchbox.cli.shared import console
from benchbox.cli.submit_auth import (
    DEFAULT_SERVICE_URL as _DEFAULT_SERVICE_URL,
    SubmissionAuthError,
    refresh_submission_token,
    resolve_submission_token,
)
from benchbox.cli.submit_service import (
    HostedSubmitError,
    HostedSubmitResult,
    HostedSubmitUnauthorized,
    submit_hosted_bundle,
)
from benchbox.core.results.loader import (
    ResultLoadError,
    UnsupportedSchemaError,
    find_latest_result,
    load_result_file,
)
from benchbox.core.results.status import result_non_clean_reason
from benchbox.core.results.submission_history import record_hosted_submission

# Submission manifest phase - indicates the result schema generation (v2.0 = phase 2).
_SUBMISSION_PHASE = 2

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
3. Copy the generated `<result>.manifest.json` alongside the bundle files.
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


def _build_submission_manifest(
    *,
    source_path: Path,
    companions: list[Path],
    result,
    submitted_by: str | None,
    submission_path: str,
) -> dict:
    """Build the shared submission manifest envelope for PR and hosted modes."""

    return {
        "submission_tool_version": f"benchbox/{benchbox.__version__}",
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "bundle_file": source_path.name,
        "bundle_hash": _compute_file_hash(source_path),
        "companion_hashes": {comp.name: _compute_file_hash(comp) for comp in companions},
        "benchmark": result.benchmark_name,
        "platform": result.platform,
        "scale_factor": result.scale_factor,
        "phase": _SUBMISSION_PHASE,
        "submission_path": submission_path,
        "submitted_by": _resolve_submitted_by(submitted_by),
    }


def _load_submission_validator_module() -> ModuleType:
    # Resolve only against the installed package's repo root so packaged installs
    # never load `scripts/validate_submission.py` from an arbitrary current
    # working directory (security: arbitrary code execution surface).
    repo_root = Path(__file__).resolve().parents[3]
    validator_path = repo_root / "scripts" / "validate_submission.py"

    if not validator_path.is_file():
        raise FileNotFoundError(f"scripts/validate_submission.py not found at {validator_path}")

    spec = importlib.util.spec_from_file_location("_benchbox_submission_validator", validator_path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(f"scripts/validate_submission.py at {validator_path} has no loader")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_submission_bundle_for_dry_run(ctx: click.Context, source_path: Path) -> None:
    """Run the same local bundle validator used by published-results CI.

    When the validator script is not available (typical for packaged wheel
    installs that don't ship ``scripts/``), downgrade to a soft warning so
    ``--dry-run`` still emits its preview output. Hard exit is reserved for
    the case where the validator is found but errors during execution.
    """

    try:
        validator = _load_submission_validator_module()
        validate_bundles = validator.validate_bundles
        format_summary = validator.format_summary
    except FileNotFoundError:
        console.print(
            "\n[yellow]Dry-run preview without schema validation:[/yellow] "
            "scripts/validate_submission.py is not packaged with this install."
        )
        console.print("[dim]Run from a BenchBox source checkout for full local schema validation.[/dim]")
        return
    except Exception as exc:
        console.print(
            f"\n[red]Submission validation unavailable:[/red] could not load scripts.validate_submission ({exc})."
        )
        console.print("[dim]Run this command from a BenchBox source checkout with the validator script present.[/dim]")
        ctx.exit(1)
        return

    try:
        validation_results = validate_bundles([source_path])
    except Exception as exc:
        console.print(f"\n[red]Submission validation failed to run:[/red] {exc}")
        ctx.exit(1)
        return

    if not validation_results:
        console.print(f"\n[red]Submission validation failed:[/red] no bundle file validated for {source_path}.")
        ctx.exit(1)
        return

    if any(not result.ok for result in validation_results):
        console.print("\n[red]Submission validation failed:[/red]")
        console.print(format_summary(validation_results))
        ctx.exit(1)
        return


def _dispatch_service_mode(
    ctx: click.Context,
    *,
    source_path: Path,
    companions: list[Path],
    result,
    service_url: str,
    visibility: str,
    idempotency_key: str | None,
    wait: bool,
    dry_run: bool,
    submitted_by: str | None,
) -> None:
    """Phase 3 hosted-API submission path.

    --dry-run is fully supported: it validates the bundle, prints what
    would be uploaded, and needs no credentials. The real path resolves
    auth, uploads the canonical bundle, and optionally polls for hosted
    publication status.

    Dry-run validation policy: `submit()` runs the same
    ``scripts/validate_submission.py`` bundle checks used by
    published-results CI before dispatching into this mode. The real hosted
    upload still relies on server-side validation so older clients are not
    blocked by develop-tip validator changes after credentials have already
    been configured.

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

    try:
        token = resolve_submission_token(service_url)
    except SubmissionAuthError as exc:
        console.print(f"\n[red]Authentication required:[/red] {exc}")
        ctx.exit(1)
        return

    manifest = _build_submission_manifest(
        source_path=source_path,
        companions=companions,
        result=result,
        submitted_by=submitted_by,
        submission_path="hosted-service",
    )

    console.print("\n[bold]Uploading submission bundle:[/bold]")
    console.print(f"  Service URL:      {service_url}")
    console.print(f"  Bundle file:      {source_path.name} ({bundle_size:,} bytes)")
    console.print(f"  Bundle hash:      {bundle_hash}")
    console.print(f"  Visibility:       {visibility}")

    try:
        upload_result = submit_hosted_bundle(
            service_url=service_url,
            token=token.token,
            source_path=source_path,
            companions=companions,
            manifest=manifest,
            bundle_hash=bundle_hash,
            visibility=visibility,
            idempotency_key=idempotency_key,
            wait=wait,
        )
    except HostedSubmitUnauthorized:
        try:
            refreshed_token = refresh_submission_token(service_url)
            upload_result = submit_hosted_bundle(
                service_url=service_url,
                token=refreshed_token.token,
                source_path=source_path,
                companions=companions,
                manifest=manifest,
                bundle_hash=bundle_hash,
                visibility=visibility,
                idempotency_key=idempotency_key,
                wait=wait,
            )
        except (HostedSubmitError, SubmissionAuthError) as exc:
            console.print(f"\n[red]Hosted submission failed:[/red] {exc}")
            ctx.exit(1)
            return
    except HostedSubmitError as exc:
        console.print(f"\n[red]Hosted submission failed:[/red] {exc}")
        ctx.exit(1)
        return

    try:
        history_path = record_hosted_submission(
            result_file=source_path,
            service_url=service_url,
            manifest=manifest,
            status=upload_result.status,
            idempotency_key=upload_result.idempotency_key,
            submission_id=upload_result.submission_id,
            public_result_id=upload_result.public_result_id,
            public_url=upload_result.public_url,
        )
    except OSError as exc:
        console.print(f"[yellow]warning:[/yellow] could not save hosted submission history: {exc}")
        history_path = None

    _print_service_result(upload_result, wait=wait)
    if history_path is not None:
        console.print(f"  History:          {history_path}")


def _print_service_result(result: HostedSubmitResult, *, wait: bool) -> None:
    is_terminal = result.status in {"already_published", "published"} or result.public_url is not None
    if is_terminal:
        console.print("\n[bold green]Hosted submission complete.[/bold green]")
    else:
        console.print("\n[bold green]Hosted submission accepted.[/bold green]")
    console.print(f"  Status:           {result.status}")
    if result.submission_id:
        console.print(f"  Submission ID:    {result.submission_id}")
    console.print(f"  Idempotency key:  {result.idempotency_key}")
    if result.status_history:
        console.print(f"  Status history:   {' -> '.join(result.status_history)}")
    if result.public_url:
        console.print(f"  Public URL:       {result.public_url}")
    elif not wait and result.submission_id:
        console.print("  Next step:        rerun with --wait to poll for the public URL")


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

        # Print exact result paths, then package one for PR contribution
        benchbox results --paths
        benchbox submit benchmark_runs/results/tpch_sf001_duckdb_20260401_120000.json --output ./submission

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

    non_clean_reason = result_non_clean_reason(result)
    if non_clean_reason:
        console.print(
            f"\n[red]❌ Submission refused: result is not a clean pass ({non_clean_reason})[/red]\n"
            "   Query-level failures remain visible in the result artifact, but\n"
            "   partial runs are not eligible for public submission or leaderboard display."
        )
        ctx.exit(1)
        return

    companions = [
        p
        for suffix in (".plans.json", ".tuning.json")
        if (p := source_path.with_name(source_path.stem + suffix)).exists()
    ]

    if dry_run:
        _validate_submission_bundle_for_dry_run(ctx, source_path)

    if service_url is not None:
        _dispatch_service_mode(
            ctx,
            source_path=source_path,
            companions=companions,
            result=result,
            service_url=service_url,
            visibility=visibility,
            idempotency_key=idempotency_key,
            wait=wait,
            dry_run=dry_run,
            submitted_by=submitted_by,
        )
        return

    output_path = Path(output_dir)
    bundle_dir = output_path / "bundle"
    # Per-bundle manifest filename: <bundle_stem>.manifest.json so two
    # contributors submitting the same week cannot collide on a single
    # `submission-manifest.json`. Readers (validate_submission.py,
    # generate_corpus_inventory.py, explorer_pipeline) glob *.manifest.json
    # and fall back to the legacy filename for backwards-compat.
    manifest_path = output_path / f"{source_path.stem}.manifest.json"
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

    # Per-file hashes are the contract used by scripts/validate_submission.py;
    # using a directory-level hash would not survive copying into
    # results-data/bundles/ where other bundles already live.
    manifest = _build_submission_manifest(
        source_path=source_path,
        companions=companions,
        result=result,
        submitted_by=submitted_by,
        submission_path="PR-based",
    )

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
