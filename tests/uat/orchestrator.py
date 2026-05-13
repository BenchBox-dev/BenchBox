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
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tests.uat.config import UATConfig, apply_stress_overrides, load_config
from tests.uat.phases import execute as exec_phase, preflight as preflight_phase, report as report_phase
from tests.uat.preflight_budget import cell_key
from tests.uat.runner import CellResult


@dataclass(frozen=True)
class SweepResult:
    name: str
    log_dir: Path
    aborted_phase: str | None
    abort_reason: str | None
    phase_exit_codes: dict[str, int]

    def exit_code(self) -> int:
        if self.aborted_phase is not None:
            return 2
        return max((c for c in self.phase_exit_codes.values()), default=0)


RESUME_MANIFEST_VERSION = 1
ResumeAttempts = Mapping[str, Mapping[str, Any]]
CellRunner = Callable[..., CellResult]


class DiskFloorAbort(RuntimeError):
    """Raised when the mid-sweep free-space floor is crossed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def load_resume_attempts(path: Path | str | None) -> dict[str, Mapping[str, Any]]:
    """Load attempted-cell records from a resume manifest."""
    if path is None:
        return {}
    manifest_path = Path(path).expanduser()
    with manifest_path.open(encoding="utf-8") as fh:
        payload = json.load(fh)
    attempts: dict[str, Mapping[str, Any]] = {}
    for record in payload.get("attempted", []):
        key = record.get("cell_key") or cell_key(record["platform"], record["benchmark"], float(record["scale"]))
        attempts[str(key)] = record
    return attempts


def build_resume_runner(
    attempts: ResumeAttempts,
    base_runner: CellRunner,
    *,
    log_dir: Path,
) -> CellRunner:
    """Return a runner that reuses manifest records instead of rerunning attempted cells."""

    def runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        key = cell_key(platform, benchmark, scale)
        record = attempts.get(key)
        if record is None:
            return base_runner(platform, benchmark, scale, **kwargs)
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status=str(record.get("terminal_state", record.get("status", "failed"))),
            exit_code=int(record.get("exit_code", 0)),
            elapsed_s=float(record.get("elapsed_s", 0.0)),
            log_path=_optional_path(record.get("log_path")) or log_dir / "resume-skipped.log",
            result_path=_optional_path(record.get("result_path")),
        )

    return runner


def _build_disk_floor_runner(
    base_runner: CellRunner,
    *,
    attempted_for_resume: list[CellResult],
    watch_disk_floor: bool,
    free_space_path: str | Path,
    free_space_min_gib: float,
) -> CellRunner:
    """Wrap a cell runner with attempted-cell capture and mid-sweep disk checks."""

    def runner(platform: str, benchmark: str, scale: float, **kwargs) -> CellResult:
        result = base_runner(platform, benchmark, scale, **kwargs)
        attempted_for_resume.append(result)
        if watch_disk_floor:
            free_gib = preflight_phase.free_space_gib(free_space_path)
            if free_gib < free_space_min_gib:
                raise DiskFloorAbort(
                    f"free space {free_gib:.1f} GiB < cutoff {free_space_min_gib:.1f} GiB at {free_space_path}"
                )
        return result

    return runner


def _optional_path(value: Any) -> Path | None:
    if not value:
        return None
    return Path(str(value)).expanduser()


def _write_resume_manifest(
    *,
    log_dir: Path,
    config: UATConfig,
    aborted_phase: str,
    abort_reason: str | None,
    attempted: Iterable[CellResult],
) -> Path:
    """Persist a resume manifest for a disk-floor abort."""
    manifest_path = log_dir / "resume.json"
    payload = {
        "version": RESUME_MANIFEST_VERSION,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "config_name": config.name,
        "log_dir": str(log_dir),
        "aborted_phase": aborted_phase,
        "abort_reason": abort_reason,
        "attempted": [
            {
                "cell_key": cell_key(result.platform, result.benchmark, result.scale),
                "platform": result.platform,
                "benchmark": result.benchmark,
                "scale": result.scale,
                "terminal_state": result.status,
                "exit_code": result.exit_code,
                "elapsed_s": result.elapsed_s,
                "log_path": str(result.log_path),
                "result_path": str(result.result_path) if result.result_path else None,
            }
            for result in attempted
        ],
    }
    with manifest_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return manifest_path


def run_sweep(  # noqa: C901
    config: UATConfig,
    *,
    log_dir_override: Path | None = None,
    databases_root: Path | None = None,
    resume_manifest: Path | None = None,
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
    resume_attempts = load_resume_attempts(resume_manifest)

    cells_jsonl = log_dir / "cells.jsonl"
    execute_outcome = None
    validator_rollup_tsv: Path | None = None
    submissions_dir: Path | None = None

    for phase in config.phases:
        if config.dry_run and phase != "enumerate":
            # Enumerate is cheap and pure (no subprocesses, no FS writes
            # for the cells themselves). Run it even in dry_run so a
            # malformed config — unknown platform group, retired
            # benchmark in a frozen YAML — surfaces as a non-zero
            # phase exit instead of silently passing through.
            phase_exit_codes[phase] = 0
            continue
        if phase == "preflight":
            result = preflight_phase.run_preflight(
                free_space_path=config.preflight.free_space_path or str(benchmark_runs_dir),
                free_space_min_gib=config.preflight.free_space_min_gib,
                docker_required=config.preflight.docker_required or config.cleanup.docker_manage_platforms,
                noisy_neighbor_warn_load=config.preflight.noisy_neighbor_warn_load,
                local_platforms_check=config.preflight.local_platforms_check,
                requested_platforms=preflight_phase.requested_platforms_from_raw(config.raw),
                benchmark_runs_dir=benchmark_runs_dir,
                disk_budget_config=config,
            )
            disk_budget_summary = getattr(result, "disk_budget_summary", None)
            if disk_budget_summary:
                print(disk_budget_summary, file=sys.stderr)
            phase_exit_codes[phase] = 2 if result.aborted else 0
            if result.aborted:
                aborted_phase = phase
                abort_reason = result.abort_reason
                if "free space" in (result.abort_reason or ""):
                    attempted = execute_outcome.results if execute_outcome is not None else ()
                    _write_resume_manifest(
                        log_dir=log_dir,
                        config=config,
                        aborted_phase=phase,
                        abort_reason=abort_reason,
                        attempted=attempted,
                    )
                break
        elif phase == "enumerate":
            # Materialise the cell list eagerly so a malformed config
            # (unknown platform group, missing benchmark) fails here
            # rather than at execute or — under dry_run — never at all.
            try:
                exec_phase.enumerate_cells(config.raw)
                phase_exit_codes[phase] = 0
            except (ValueError, KeyError, TypeError) as exc:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = str(exc)
                break
        elif phase == "execute":
            base_runner = (
                build_resume_runner(resume_attempts, exec_phase.run_cell, log_dir=log_dir)
                if resume_attempts
                else exec_phase.run_cell
            )
            attempted_for_resume: list[CellResult] = []
            execute_kwargs: dict[str, Any] = {
                "log_dir": log_dir,
                "benchmark_runs_dir": benchmark_runs_dir,
                "databases_root": databases_root,
                "cleanup_enabled": config.cleanup.prune_databases,
                "free_space_checks_enabled": "preflight" in config.phases,
                "runner": _build_disk_floor_runner(
                    base_runner,
                    attempted_for_resume=attempted_for_resume,
                    watch_disk_floor="preflight" in config.phases,
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
                _write_resume_manifest(
                    log_dir=log_dir,
                    config=config,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                    attempted=attempted_for_resume,
                )
                break
            with cells_jsonl.open("w", encoding="utf-8") as fh:
                for cell in execute_outcome.results:
                    fh.write(
                        json.dumps(
                            {
                                "platform": cell.platform,
                                "benchmark": cell.benchmark,
                                "scale": cell.scale,
                                "status": cell.status,
                                "timed_out": cell.status == "timed-out",
                                "exit_code": cell.exit_code,
                                "elapsed_s": cell.elapsed_s,
                                "log_path": str(cell.log_path),
                                "result_path": (str(cell.result_path) if cell.result_path else None),
                            }
                        )
                        + "\n"
                    )
            if execute_outcome.aborted:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = execute_outcome.abort_reason
                if "free space" in (abort_reason or ""):
                    _write_resume_manifest(
                        log_dir=log_dir,
                        config=config,
                        aborted_phase=phase,
                        abort_reason=abort_reason,
                        attempted=execute_outcome.results,
                    )
                break
            phase_exit_codes[phase] = 0 if all(r.status == "passed" for r in execute_outcome.results) else 1
        elif phase == "validate":
            from tests.uat.phases.validate import ValidatePhaseError, run_validate

            validate_cfg = config.raw.get("validate") or {}
            if execute_outcome is None:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "validate phase requires execute phase to have run"
                break
            result_paths = [r.result_path for r in execute_outcome.results if r.result_path]
            output_tsv = log_dir / "validator_rollup.tsv"
            try:
                vr = run_validate(
                    result_paths,
                    output_tsv=output_tsv,
                    floor=float(validate_cfg.get("validator_clean_rate_floor", 0.80)),
                )
                phase_exit_codes[phase] = vr.exit_code()
                validator_rollup_tsv = vr.rollup_tsv_path
            except (FileNotFoundError, ValidatePhaseError) as exc:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = str(exc)
                break
        elif phase == "package":
            from tests.uat.phases.package import run_package

            if execute_outcome is None:
                phase_exit_codes[phase] = 2
                aborted_phase = phase
                abort_reason = "package phase requires execute phase to have run"
                break
            result_paths = [r.result_path for r in execute_outcome.results if r.result_path]
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
        elif phase == "explorer_smoke":
            from tests.uat.phases.explorer_smoke import run_explorer_smoke

            es_cfg = config.raw.get("explorer_smoke") or {}
            bundles_dir = submissions_dir if submissions_dir is not None else log_dir / "bundles"
            result = run_explorer_smoke(
                bundles_dir=bundles_dir,
                output_dir=log_dir / "explorer_data",
                log_dir=log_dir,
                playwright_browsers=tuple(es_cfg.get("playwright_browsers", ["chromium"])),
            )
            phase_exit_codes[phase] = result.exit_code()
        elif phase == "report":
            report_cfg = config.raw.get("report") or {}
            tsv_path = log_dir / report_cfg.get("matrix_summary_tsv", "matrix_summary.tsv")
            cells = execute_outcome.results if execute_outcome else []
            scales_cfg = config.raw.get("scales") or {}
            rungs = scales_cfg.get("rungs")
            # Wire validator status into the cross-scale check when a
            # validate phase ran earlier in this sweep. Without this,
            # cross_scale_clean_pair_count silently degrades to a
            # passed-only check.
            validator_status_by_path = _validator_status_by_path(validator_rollup_tsv)
            summary = report_phase.write_report(
                cells,
                output_path=tsv_path,
                rungs=[float(r) for r in rungs] if rungs else None,
                cross_scale_floor=report_cfg.get("cross_scale_coverage_min_pairs"),
                validator_status_by_path=validator_status_by_path,
            )
            phase_exit_codes[phase] = summary.exit_code()

    return SweepResult(
        name=config.name,
        log_dir=log_dir,
        aborted_phase=aborted_phase,
        abort_reason=abort_reason,
        phase_exit_codes=phase_exit_codes,
    )


def _validator_status_by_path(validator_rollup_tsv: Path | None) -> dict[Path, str] | None:
    if validator_rollup_tsv is None or not validator_rollup_tsv.exists():
        return None
    from tests.uat.phases.validate import parse_validator_status_by_path

    return parse_validator_status_by_path(validator_rollup_tsv)


def run_sweep_from_path(
    config_path: Path,
    *,
    stress_overrides: dict[str, str | float | None] | None = None,
    dry_run_override: bool | None = None,
    resume_manifest: Path | None = None,
) -> SweepResult:
    """Convenience wrapper for `make uat-sweep` and `make uat-stress`."""
    config = load_config(config_path)
    if stress_overrides:
        config = apply_stress_overrides(
            config,
            platform=stress_overrides.get("platform"),
            benchmark=stress_overrides.get("benchmark"),
            scale=stress_overrides.get("scale"),
        )
    if dry_run_override is not None:
        raw = dict(config.raw)
        raw["dry_run"] = dry_run_override
        config = replace(config, dry_run=dry_run_override, raw=raw)
    return run_sweep(config, resume_manifest=resume_manifest)
