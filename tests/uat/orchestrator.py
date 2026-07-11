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

from tests.uat import cells_io
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
            free_gib = preflight_phase.free_space_gib(free_space_path)
            if free_gib < free_space_min_gib:
                raise DiskFloorAbort(
                    f"free space {free_gib:.1f} GiB < cutoff {free_space_min_gib:.1f} GiB at {free_space_path}"
                )
        return result

    return runner


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
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
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
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=attempted_cells,
                    execute_outcome=None,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    # run_execute annotates the abort with the unreachable
                    # cells skipped before the disk-floor trip; without this
                    # the abort report would drop them from total_defined.
                    skipped_unreachable_count=getattr(exc, "skipped_unreachable_count", 0),
                )
                break
            cells_io.write_cells_jsonl(
                cells_jsonl,
                execute_outcome.results,
                source_info=source_info,
                skipped_unreachable_count=len(getattr(execute_outcome, "skipped_unreachable", ())),
                disk_gate_disabled=not config.disk_gate_enabled,
            )
            _write_compatibility_pruned_jsonl(
                compatibility_pruned_jsonl,
                getattr(execute_outcome, "compatibility_pruned", ()),
            )
            if execute_outcome.aborted:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = execute_outcome.abort_reason
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                )
                break
            phase_exit_codes[phase] = execute_outcome.exit_code()
        elif phase == "validate":
            from tests.uat.phases.validate import run_validate

            if execute_outcome is None:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "validate phase requires execute phase to have run"
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
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
            validator_rollup_tsv = vr.rollup_tsv_path
            if vr.aborted:
                aborted_phase = phase
                abort_reason = vr.abort_reason
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                )
                break
        elif phase == "package":
            from tests.uat.phases.package import run_package

            if execute_outcome is None:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "package phase requires execute phase to have run"
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
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
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=(),
                    execute_outcome=execute_outcome,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
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
        elif phase == "report":
            tsv_path = log_dir / config.report.matrix_summary_tsv
            cells = execute_outcome.results if execute_outcome else []
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
                compatibility_pruned_count=(
                    len(getattr(execute_outcome, "compatibility_pruned", ())) if execute_outcome else 0
                ),
                early_stop_pruned_count=(len(getattr(execute_outcome, "pruned", ())) if execute_outcome else 0),
                skipped_unreachable_count=(
                    len(getattr(execute_outcome, "skipped_unreachable", ())) if execute_outcome else 0
                ),
                source_info=source_info,
            )
            phase_exit_codes[phase] = summary.exit_code()

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
) -> None:
    cells = tuple(getattr(execute_outcome, "results", ())) if execute_outcome is not None else tuple(attempted)
    compatibility_pruned = (
        tuple(getattr(execute_outcome, "compatibility_pruned", ()))
        if execute_outcome is not None
        else _compatibility_pruned_for_config(config)
    )
    early_stop_pruned_count = len(getattr(execute_outcome, "pruned", ())) if execute_outcome is not None else 0
    # When the execute outcome is available, derive the unreachable count from
    # it; otherwise (e.g. a mid-sweep DiskFloorAbort that bypassed the normal
    # return) fall back to the count threaded in via `skipped_unreachable_count`
    # so the abort report still reflects platforms skipped before the abort.
    if skipped_unreachable_count is None:
        skipped_unreachable_count = (
            len(getattr(execute_outcome, "skipped_unreachable", ())) if execute_outcome is not None else 0
        )
    cells_io.write_cells_jsonl(
        log_dir / "cells.jsonl",
        cells,
        source_info=source_info,
        skipped_unreachable_count=skipped_unreachable_count,
        disk_gate_disabled=not config.disk_gate_enabled,
    )
    _write_compatibility_pruned_jsonl(log_dir / "compatibility_pruned.jsonl", compatibility_pruned)
    report_phase.write_report(
        cells,
        output_path=_partial_report_path(log_dir / config.report.matrix_summary_tsv),
        rungs=list(config.scales.rungs),
        cross_scale_floor=config.report.cross_scale_coverage_min_pairs,
        compatibility_pruned_count=len(compatibility_pruned),
        early_stop_pruned_count=early_stop_pruned_count,
        skipped_unreachable_count=skipped_unreachable_count,
        source_info=source_info,
        run_status="ABORTED",
        abort_phase=aborted_phase,
        abort_reason=abort_reason,
    )


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
