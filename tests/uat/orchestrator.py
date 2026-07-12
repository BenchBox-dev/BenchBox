"""UAT sweep orchestrator: walks the YAML `phases:` list in order.

`run_sweep` is the entry point for `make uat-sweep CONFIG=...`. It
respects `dry_run:` (used by W10's structural-parity replay test).

Sequential platform execution discipline (UAT W3 line 222 in
_project/handoffs/results-explorer-uat-retrospective-20260502.md):
phases run in serial; the execute phase iterates platforms in serial
internally; no `parallel=True` knob anywhere.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tests.uat import cells_io, docker_assets, gate_summary, preflight_budget
from tests.uat.config import UATConfig, disk_gate_disabled_warning, load_config
from tests.uat.phases import (
    execute as exec_phase,
    preflight as preflight_phase,
    report as report_phase,
)
from tests.uat.runner import CellResult


@dataclass(frozen=True)
class SweepResult:
    name: str
    log_dir: Path
    aborted_phase: str | None
    abort_reason: str | None
    phase_exit_codes: dict[str, int]
    # Additive: the raw per-phase results, threaded through so a single-phase
    # caller (e.g. `make uat-execute`, which routes through this same phase
    # loop -- see uat-execute-path-unification w2) can report the same detail
    # `_handle_execute` used to build by hand, without re-deriving it. None
    # when the corresponding phase did not run this sweep.
    preflight: Any = None
    execute_outcome: Any = None

    def exit_code(self) -> int:
        if self.aborted_phase is not None:
            return 2
        return max((c for c in self.phase_exit_codes.values()), default=0)


@dataclass(frozen=True)
class RunSourceInfo:
    commit_sha: str
    commit_short_sha: str
    dirty: bool


CellRunner = Callable[..., CellResult]


class DiskFloorAbort(RuntimeError):
    """Raised when the mid-sweep free-space floor is crossed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def capture_run_source_info(repo_root: Path | None = None) -> RunSourceInfo:
    """Capture source provenance once per sweep."""
    root = repo_root or Path(__file__).resolve().parents[2]
    commit_sha = _git_output(root, "rev-parse", "HEAD") or "unknown"
    commit_short_sha = _git_output(root, "rev-parse", "--short", "HEAD") or commit_sha[:12]
    dirty_output = _git_output(root, "status", "--porcelain", "--untracked-files=normal")
    return RunSourceInfo(
        commit_sha=commit_sha,
        commit_short_sha=commit_short_sha,
        dirty=bool(dirty_output),
    )


def _git_output(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", *args),
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _build_disk_floor_runner(
    base_runner: CellRunner,
    *,
    attempted_cells: list[CellResult],
    watch_disk_floor: bool,
    free_space_path: str | Path,
    free_space_min_gib: float,
) -> CellRunner:
    """Wrap a cell runner with attempted-cell capture and mid-sweep disk checks."""

    def runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        result = base_runner(platform, benchmark, scale, **kwargs)
        attempted_cells.append(result)
        if watch_disk_floor:
            free_gib = preflight_budget.free_space_gib(free_space_path)
            if free_gib < free_space_min_gib:
                raise DiskFloorAbort(
                    f"free space {free_gib:.1f} GiB < cutoff {free_space_min_gib:.1f} GiB at {free_space_path}"
                )
        return result

    return runner


def _record_container_engine_identity(log_dir: Path) -> str | None:
    """Resolve + record the container engine identity at sweep start (uat-container-engine-routing w2).

    Best-effort: a resolution failure (no compose-capable binary on PATH at
    all) does not abort the sweep here -- a config with no Docker-managed
    platforms never needs one, and one that does will fail loudly at its own
    compose-up step with a clear DockerAssetError. Returns the resolved
    binary name (for the accounting sidecar), or None when resolution
    failed.
    """
    try:
        binary, version = docker_assets.container_engine_identity()
    except docker_assets.DockerAssetError as exc:
        exec_phase.append_lifecycle_log(log_dir, f"[engine] resolution failed: {exc}")
        return None
    exec_phase.append_lifecycle_log(log_dir, f"[engine] resolved_container_cli={binary} version={version}")
    return binary


def run_sweep(  # noqa: C901
    config: UATConfig,
    *,
    log_dir_override: Path | None = None,
    databases_root: Path | None = None,
) -> SweepResult:
    """Orchestrate the YAML's `phases:` list. Returns SweepResult."""
    now = _dt.datetime.now()
    log_dir = log_dir_override or exec_phase.default_log_dir(config, now=now)
    benchmark_runs_dir = exec_phase.default_benchmark_runs_dir(config, now=now)
    log_dir.mkdir(parents=True, exist_ok=True)
    container_engine = _record_container_engine_identity(log_dir)

    if databases_root is None:
        databases_root = benchmark_runs_dir / "databases"

    phase_exit_codes: dict[str, int] = {}
    aborted_phase: str | None = None
    abort_reason: str | None = None
    source_info = capture_run_source_info()

    cells_jsonl = log_dir / "cells.jsonl"
    compatibility_pruned_jsonl = log_dir / "compatibility_pruned.jsonl"
    execute_outcome = None
    preflight_result = None
    validator_rollup_tsv: Path | None = None
    submissions_dir: Path | None = None
    validate_result: Any = None
    report_summary: Any = None
    explorer_smoke_status = gate_summary.EXPLORER_SMOKE_NOT_RUN

    if not config.dry_run and "execute" in config.phases:
        gate_warning = disk_gate_disabled_warning(config)
        if gate_warning is not None:
            print(gate_warning, file=sys.stderr)

    for phase in config.phases:
        if config.dry_run:
            phase_exit_codes[phase] = 0
            continue
        if phase == "preflight":
            result = preflight_phase.run_preflight(
                **preflight_phase.preflight_kwargs_from_config(config, benchmark_runs_dir=benchmark_runs_dir)
            )
            preflight_result = result
            disk_budget_summary = getattr(result, "disk_budget_summary", None)
            if disk_budget_summary:
                print(disk_budget_summary, file=sys.stderr)
            for line in getattr(result, "free_space_report", ()):
                print(line, file=sys.stderr)
            for warning in getattr(result, "warnings", ()):
                print(f"[preflight warn] {warning}", file=sys.stderr)
            phase_exit_codes[phase] = result.exit_code()
            if result.aborted:
                aborted_phase = phase
                abort_reason = result.abort_reason
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
        elif phase == "execute":
            attempted_cells: list[CellResult] = []
            execute_kwargs: dict[str, Any] = {
                "log_dir": log_dir,
                "benchmark_runs_dir": benchmark_runs_dir,
                "databases_root": databases_root,
                "cleanup_enabled": config.cleanup.prune_databases,
                "free_space_checks_enabled": config.disk_gate_enabled,
                "runner": _build_disk_floor_runner(
                    exec_phase.run_cell,
                    attempted_cells=attempted_cells,
                    watch_disk_floor=config.disk_gate_enabled,
                    free_space_path=config.preflight.free_space_path or str(benchmark_runs_dir),
                    free_space_min_gib=config.preflight.free_space_min_gib,
                ),
            }
            try:
                execute_outcome = exec_phase.run_execute(config, **execute_kwargs)
            except DiskFloorAbort as exc:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = exc.reason
                # Synthesize an ExecuteOutcome from what run_execute had
                # already accumulated before the abort propagated, instead
                # of passing execute_outcome=None. The None path forced
                # _emit_abort_artifacts to fall back to
                # _compatibility_pruned_for_config, a second independent
                # re-enumeration that can diverge from the one execute
                # actually used. execute.py threads its real enumeration
                # onto the exception (`exc.compatibility_pruned`)
                # specifically so this constructor can use it directly.
                execute_outcome = exec_phase.ExecuteOutcome(
                    phase="execute",
                    results=tuple(attempted_cells),
                    pruned=(),
                    skipped_unreachable=(),
                    startup_failed=(),
                    compatibility_pruned=getattr(exc, "compatibility_pruned", ()) or (),
                    aborted=True,
                    abort_reason=abort_reason,
                    abort_kind="disk_floor",
                )
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=attempted_cells,
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    # The skipped-unreachable / startup-failed Cell objects
                    # (not just their counts) are lost crossing the exception
                    # boundary, so the synthesized outcome above always
                    # carries empty collections -- override with the real
                    # counts run_execute annotated the exception with, or the
                    # abort report would under-count total_defined.
                    skipped_unreachable_count=getattr(exc, "skipped_unreachable_count", 0),
                    startup_failed_count=getattr(exc, "startup_failed_count", 0),
                    container_engine=container_engine,
                )
                break
            cells_io.write_cells_jsonl(
                cells_jsonl,
                execute_outcome.results,
                source_info=source_info,
                skipped_unreachable_count=len(getattr(execute_outcome, "skipped_unreachable", ())),
                startup_failed_count=len(getattr(execute_outcome, "startup_failed", ())),
                disk_gate_disabled=not config.disk_gate_enabled,
                container_engine=container_engine,
            )
            _write_compatibility_pruned_jsonl(
                compatibility_pruned_jsonl,
                getattr(execute_outcome, "compatibility_pruned", ()),
            )
            if execute_outcome.aborted:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = execute_outcome.abort_reason
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
            phase_exit_codes[phase] = execute_outcome.exit_code()
        elif phase == "validate":
            from tests.uat.phases.validate import run_validate

            if execute_outcome is None:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "validate phase requires execute phase to have run"
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
            result_paths = [r.result_path for r in execute_outcome.results if r.result_path]
            output_tsv = log_dir / "validator_rollup.tsv"
            vr = run_validate(
                result_paths,
                output_tsv=output_tsv,
                floor=config.validate.validator_clean_rate_floor,
            )
            phase_exit_codes[phase] = vr.exit_code()
            validate_result = vr
            validator_rollup_tsv = vr.rollup_tsv_path
            if vr.aborted:
                aborted_phase = phase
                abort_reason = vr.abort_reason
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
        elif phase == "package":
            from tests.uat.phases.package import run_package

            if execute_outcome is None:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "package phase requires execute phase to have run"
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
            # Only passed cells are submission-ready. A failed official cell
            # still exports a result JSON (runner.py resolves the path
            # regardless of exit code), but packaging/submitting it would
            # present a known-bad run as a candidate submission.
            result_paths = [r.result_path for r in execute_outcome.results if r.result_path and r.status == "passed"]
            submissions_dir = Path(
                config.output.submissions_dir_template.replace("{date}", now.strftime("%Y%m%d")).replace(
                    "{name}", config.name
                )
            ).expanduser()
            pr = run_package(
                config,
                result_paths=result_paths,
                submissions_dir=submissions_dir,
            )
            phase_exit_codes[phase] = pr.exit_code()
            if pr.aborted:
                aborted_phase = phase
                abort_reason = pr.abort_reason
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
        elif phase == "explorer_smoke":
            from tests.uat.phases.explorer_smoke import run_explorer_smoke

            bundles_dir = submissions_dir if submissions_dir is not None else log_dir / "bundles"
            result = run_explorer_smoke(
                bundles_dir=bundles_dir,
                output_dir=log_dir / "explorer_data",
                log_dir=log_dir,
                playwright_browsers=config.explorer_smoke.playwright_browsers,
            )
            phase_exit_codes[phase] = result.exit_code()
            # Thread the ran/skipped distinction into the gate summary: an
            # explorer_smoke skip is exit 0 by design (node/explorer absent),
            # so the exit code alone cannot tell "browser coverage happened"
            # from "browser coverage silently didn't" -- the release-gate
            # aggregation (`make uat-gate-check`) enforces `ran` for stages
            # whose `phases:` list includes explorer_smoke.
            if getattr(result, "skipped", False):
                explorer_smoke_status = (
                    "skipped_no_node" if getattr(result, "skip_reason", None) == "node not on PATH" else "skipped"
                )
            else:
                explorer_smoke_status = gate_summary.EXPLORER_SMOKE_RAN
            if getattr(result, "skip_reason", None) == "node not on PATH":
                # macOS operator machines legitimately lack `node` for
                # non-explorer sweeps -- exit 0 stays, but the drop in
                # browser coverage must be visible instead of a silent skip.
                # Thread the status into the existing accounting sidecar
                # (written by the execute phase, which always precedes
                # explorer_smoke) rather than a second sidecar write; if no
                # sidecar exists yet (e.g. a `phases:` list that runs
                # explorer_smoke without execute), there is nothing durable
                # to patch and the stderr warning is the only record -- see
                # uat-fail-advance-consistency w2.
                recorded = cells_io.update_accounting_sidecar(cells_jsonl, explorer_smoke_status="skipped_no_node")
                if recorded:
                    print(
                        "[explorer_smoke] WARNING: node not on PATH -- browser coverage skipped for this sweep "
                        "(explorer_smoke_status=skipped_no_node recorded in the accounting sidecar)",
                        file=sys.stderr,
                    )
                else:
                    print(
                        "[explorer_smoke] WARNING: node not on PATH -- browser coverage skipped for this sweep. "
                        "explorer_smoke_status=skipped_no_node was NOT durably recorded: no accounting sidecar "
                        "exists for this run (no execute phase wrote one), so this warning is the only record.",
                        file=sys.stderr,
                    )
            if getattr(result, "aborted", False):
                aborted_phase = phase
                abort_reason = getattr(result, "abort_reason", None)
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
        elif phase == "report":
            if execute_outcome is None:
                # Match validate/package: a report built with no execute
                # phase in this sweep silently wrote an empty TSV and exited
                # 0, which reads as a clean sweep -- see
                # uat-fail-advance-consistency w1. Standalone `make
                # uat-report` (tests/uat/_cli.py `_handle_report`) is a
                # different entry point that reads an existing cells.jsonl
                # directly and never reaches run_sweep, so it is unaffected.
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "report phase requires execute phase to have run"
                report_summary = _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    container_engine=container_engine,
                )
                break
            tsv_path = log_dir / config.report.matrix_summary_tsv
            cells = execute_outcome.results
            # Wire validator status into the cross-scale check when a
            # validate phase ran earlier in this sweep. Without this,
            # cross_scale_clean_pair_count silently degrades to a
            # passed-only check.
            validator_status_by_path = _validator_status_by_path(validator_rollup_tsv)
            summary = report_phase.write_report(
                cells,
                output_path=tsv_path,
                rungs=list(config.scales.rungs),
                cross_scale_floor=config.report.cross_scale_coverage_min_pairs,
                validator_status_by_path=validator_status_by_path,
                compatibility_pruned_count=len(getattr(execute_outcome, "compatibility_pruned", ())),
                early_stop_pruned_count=len(getattr(execute_outcome, "pruned", ())),
                skipped_unreachable_count=len(getattr(execute_outcome, "skipped_unreachable", ())),
                startup_failed_count=len(getattr(execute_outcome, "startup_failed", ())),
                source_info=source_info,
            )
            report_summary = summary
            phase_exit_codes[phase] = summary.exit_code()

    # Gate summary artifact: written for EVERY sweep, including dry-run
    # (verdict "dry_run") and aborted sweeps (verdict "red"), so the
    # release-gate aggregation (`make uat-gate-check`) always has a
    # machine-readable per-stage record beside cells.jsonl. Written last:
    # its completed_at is the sweep-completion timestamp the cross-stage
    # Docker ordering check keys on.
    completed_at = _dt.datetime.now()
    _write_gate_summary_artifact(
        config=config,
        log_dir=log_dir,
        source_info=source_info,
        container_engine=container_engine,
        completed_at=completed_at,
        aborted_phase=aborted_phase,
        abort_reason=abort_reason,
        phase_exit_codes=phase_exit_codes,
        execute_outcome=execute_outcome,
        report_summary=report_summary,
        validate_result=validate_result,
        explorer_smoke_status=explorer_smoke_status,
    )

    return SweepResult(
        name=config.name,
        log_dir=log_dir,
        aborted_phase=aborted_phase,
        abort_reason=abort_reason,
        phase_exit_codes=phase_exit_codes,
        preflight=preflight_result,
        execute_outcome=execute_outcome,
    )


def _validator_status_by_path(validator_rollup_tsv: Path | None) -> dict[Path, str] | None:
    if validator_rollup_tsv is None or not validator_rollup_tsv.exists():
        return None
    from tests.uat.phases.validate import parse_validator_status_by_path

    return parse_validator_status_by_path(validator_rollup_tsv)


def _emit_abort_artifacts(
    *,
    config: UATConfig,
    log_dir: Path,
    attempted: Iterable[CellResult],
    execute_outcome: Any,
    source_info: RunSourceInfo,
    aborted_phase: str,
    abort_reason: str | None,
    skipped_unreachable_count: int | None = None,
    startup_failed_count: int | None = None,
    container_engine: str | None = None,
) -> report_phase.ReportSummary:
    cells = tuple(getattr(execute_outcome, "results", ())) if execute_outcome is not None else tuple(attempted)
    compatibility_pruned = (
        tuple(getattr(execute_outcome, "compatibility_pruned", ()))
        if execute_outcome is not None
        else _compatibility_pruned_for_config(config)
    )
    early_stop_pruned_count = len(getattr(execute_outcome, "pruned", ())) if execute_outcome is not None else 0
    # When the execute outcome is available, derive the unreachable /
    # startup-failed counts from it; otherwise (e.g. a mid-sweep
    # DiskFloorAbort that bypassed the normal return) fall back to the counts
    # threaded in via the `*_count` parameters so the abort report still
    # reflects platforms skipped before the abort.
    if skipped_unreachable_count is None:
        skipped_unreachable_count = (
            len(getattr(execute_outcome, "skipped_unreachable", ())) if execute_outcome is not None else 0
        )
    if startup_failed_count is None:
        startup_failed_count = len(getattr(execute_outcome, "startup_failed", ())) if execute_outcome is not None else 0
    cells_io.write_cells_jsonl(
        log_dir / "cells.jsonl",
        cells,
        source_info=source_info,
        skipped_unreachable_count=skipped_unreachable_count,
        startup_failed_count=startup_failed_count,
        disk_gate_disabled=not config.disk_gate_enabled,
        container_engine=container_engine,
    )
    _write_compatibility_pruned_jsonl(log_dir / "compatibility_pruned.jsonl", compatibility_pruned)
    # Returned so run_sweep can fold the partial report's accounting into the
    # gate summary artifact (uat-release-gate-enforcement w1).
    return report_phase.write_report(
        cells,
        output_path=_partial_report_path(log_dir / config.report.matrix_summary_tsv),
        rungs=list(config.scales.rungs),
        cross_scale_floor=config.report.cross_scale_coverage_min_pairs,
        compatibility_pruned_count=len(compatibility_pruned),
        early_stop_pruned_count=early_stop_pruned_count,
        skipped_unreachable_count=skipped_unreachable_count,
        startup_failed_count=startup_failed_count,
        source_info=source_info,
        run_status="ABORTED",
        abort_phase=aborted_phase,
        abort_reason=abort_reason,
    )


def _accounting_for_gate_summary(report_summary: Any, execute_outcome: Any) -> gate_summary.PhaseAccounting:
    """Fold sweep results into the gate summary's accounting block.

    Prefers the report phase's `ReportSummary` (complete or partial-abort --
    both flow through `report_phase.write_report`, the single owner of the
    accounting math). A sweep that ran execute without a report phase (e.g.
    `make uat-execute`'s scoped `[preflight, execute]` loop) mirrors
    write_report's counting on the outcome directly rather than writing a
    throwaway TSV.
    """
    if report_summary is not None:
        return gate_summary.PhaseAccounting(
            attempted=report_summary.attempted_count,
            passed=report_summary.pass_count,
            failed=report_summary.fail_count,
            timed_out=report_summary.timeout_count,
            unreachable=report_summary.unreachable_count,
            startup_failed=report_summary.startup_failed_count,
            skipped=report_summary.skipped_count,
            compatibility_pruned=report_summary.compatibility_pruned_count,
            early_stop_pruned=report_summary.early_stop_pruned_count,
            registry_pruned=report_summary.registry_pruned_count,
            total_defined=report_summary.total_defined_count,
        )
    if execute_outcome is None:
        return gate_summary.PhaseAccounting()
    results = tuple(getattr(execute_outcome, "results", ()))
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    timed_out = sum(1 for r in results if r.status == "timed-out")
    row_skipped = sum(1 for r in results if report_phase.is_skipped_status(r.status))
    row_unreachable = sum(1 for r in results if report_phase.is_unreachable_status(r.status))
    compatibility_pruned = len(getattr(execute_outcome, "compatibility_pruned", ()))
    early_stop_pruned = len(getattr(execute_outcome, "pruned", ()))
    unreachable = row_unreachable + len(getattr(execute_outcome, "skipped_unreachable", ()))
    startup_failed = len(getattr(execute_outcome, "startup_failed", ()))
    attempted = len(results) - row_skipped - row_unreachable
    skipped = row_skipped + compatibility_pruned + early_stop_pruned
    return gate_summary.PhaseAccounting(
        attempted=attempted,
        passed=passed,
        failed=failed,
        timed_out=timed_out,
        unreachable=unreachable,
        startup_failed=startup_failed,
        skipped=skipped,
        compatibility_pruned=compatibility_pruned,
        early_stop_pruned=early_stop_pruned,
        registry_pruned=0,
        total_defined=attempted + skipped + unreachable + startup_failed,
    )


def _write_gate_summary_artifact(
    *,
    config: UATConfig,
    log_dir: Path,
    source_info: RunSourceInfo,
    container_engine: str | None,
    completed_at: _dt.datetime,
    aborted_phase: str | None,
    abort_reason: str | None,
    phase_exit_codes: dict[str, int],
    execute_outcome: Any,
    report_summary: Any,
    validate_result: Any,
    explorer_smoke_status: str,
) -> None:
    """Serialize the per-sweep gate summary (uat-release-gate-enforcement w1)."""
    summary = gate_summary.GateSummary(
        config_name=config.name,
        source_commit_sha=source_info.commit_sha,
        source_dirty=source_info.dirty,
        container_engine=container_engine,
        completed_at=completed_at.isoformat(),
        dry_run=config.dry_run,
        aborted=aborted_phase is not None,
        abort_phase=aborted_phase,
        abort_reason=abort_reason,
        phase_exit_codes=dict(phase_exit_codes),
        accounting=_accounting_for_gate_summary(report_summary, execute_outcome),
        unreachable_is_estimated=bool(getattr(report_summary, "unreachable_count_is_estimated", False)),
        validator_clean_rate=(validate_result.clean_rate if validate_result is not None else None),
        validator_clean_rate_floor=(validate_result.floor if validate_result is not None else None),
        validator_floor_breached=(validate_result.floor_breached if validate_result is not None else None),
        cross_scale_clean_pairs=(report_summary.cross_scale_clean_pairs if report_summary is not None else None),
        cross_scale_floor=(report_summary.cross_scale_floor if report_summary is not None else None),
        cross_scale_floor_breached=(report_summary.cross_scale_floor_breached if report_summary is not None else None),
        explorer_smoke_status=explorer_smoke_status,
        verdict=gate_summary.derive_verdict(
            dry_run=config.dry_run,
            aborted=aborted_phase is not None,
            phase_exit_codes=phase_exit_codes,
        ),
    )
    gate_summary.write_gate_summary(log_dir, summary)


def _partial_report_path(path: Path) -> Path:
    if path.suffix:
        return path.with_name(f"{path.stem}.partial{path.suffix}")
    return path.with_name(f"{path.name}.partial")


def _compatibility_pruned_for_config(config: UATConfig) -> tuple[Any, ...]:
    return tuple(exec_phase.enumerate_cells_with_pruning(config).compatibility_pruned)


def _write_compatibility_pruned_jsonl(path: Path, cells: Iterable[Any]) -> None:
    lines: list[str] = []
    for cell in cells:
        lines.append(
            json.dumps(
                {
                    "platform": cell.platform,
                    "benchmark": cell.benchmark,
                    "scale": cell.scale,
                    "status": "compatibility-pruned",
                    "rule_id": cell.rule_id,
                    "rule_status": cell.status,
                    "reason": cell.reason,
                    "evidence": cell.evidence,
                }
            )
            + "\n"
        )
    report_phase.atomic_write_text(path, "".join(lines))


def run_sweep_from_path(
    config_path: Path,
    *,
    stress_overrides: dict[str, str | float | None] | None = None,
    dry_run_override: bool | None = None,
) -> SweepResult:
    """Convenience wrapper for `make uat-sweep` and `make uat-stress`."""
    config = load_config(config_path)
    if stress_overrides:
        platform = stress_overrides.get("platform")
        benchmark = stress_overrides.get("benchmark")
        scale = stress_overrides.get("scale")
        if platform is not None:
            config = replace(config, platforms=replace(config.platforms, groups=(), include=(str(platform),)))
        if benchmark is not None:
            config = replace(config, benchmarks=replace(config.benchmarks, groups=(), include=(str(benchmark),)))
        if scale is not None:
            config = replace(config, scales=replace(config.scales, override=float(scale)))
    if dry_run_override is not None:
        config = replace(config, dry_run=dry_run_override)
    return run_sweep(config)
