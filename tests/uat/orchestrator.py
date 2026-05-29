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
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from tests.uat.config import UATConfig, load_config
from tests.uat.phases import (
    execute as exec_phase,
    preflight as preflight_phase,
    report as report_phase,
)
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


@dataclass(frozen=True)
class RunSourceInfo:
    commit_sha: str
    commit_short_sha: str
    dirty: bool


RESUME_MANIFEST_VERSION = 1
ResumeAttempts = Mapping[str, Mapping[str, Any]]
CellRunner = Callable[..., CellResult]
FAILURE_TAIL_LINES = 50
FAILURE_TAIL_CHARS = 12_000


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
            submit_terminal_state=str(record.get("submit_terminal_state", "submittable")),
        )

    return runner


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
    source_info: RunSourceInfo,
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
        "source": {
            "commit_sha": source_info.commit_sha,
            "commit_short_sha": source_info.commit_short_sha,
            "dirty": source_info.dirty,
        },
        "attempted": [
            {
                "cell_key": cell_key(result.platform, result.benchmark, result.scale),
                "platform": result.platform,
                "benchmark": result.benchmark,
                "scale": result.scale,
                "terminal_state": result.status,
                "submit_terminal_state": result.submit_terminal_state,
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
    source_info = capture_run_source_info()

    cells_jsonl = log_dir / "cells.jsonl"
    compatibility_pruned_jsonl = log_dir / "compatibility_pruned.jsonl"
    execute_outcome = None
    validator_rollup_tsv: Path | None = None
    submissions_dir: Path | None = None

    for phase in config.phases:
        if config.dry_run:
            phase_exit_codes[phase] = 0
            continue
        if phase == "preflight":
            result = preflight_phase.run_preflight(
                **preflight_phase.preflight_kwargs_from_config(config, benchmark_runs_dir=benchmark_runs_dir)
            )
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
                if "free space" in (result.abort_reason or ""):
                    attempted = execute_outcome.results if execute_outcome is not None else ()
                    _write_resume_manifest(
                        log_dir=log_dir,
                        config=config,
                        aborted_phase=phase,
                        abort_reason=abort_reason,
                        attempted=attempted,
                        source_info=source_info,
                    )
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
                    source_info=source_info,
                )
                _emit_abort_artifacts(
                    config=config,
                    log_dir=log_dir,
                    attempted=attempted_for_resume,
                    execute_outcome=None,
                    source_info=source_info,
                    aborted_phase=phase,
                    abort_reason=abort_reason,
                )
                break
            _write_cells_jsonl(cells_jsonl, execute_outcome.results, source_info=source_info)
            _write_compatibility_pruned_jsonl(
                compatibility_pruned_jsonl,
                getattr(execute_outcome, "compatibility_pruned", ()),
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
                        source_info=source_info,
                    )
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
                source_info=source_info,
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


def _emit_abort_artifacts(
    *,
    config: UATConfig,
    log_dir: Path,
    attempted: Iterable[CellResult],
    execute_outcome: Any,
    source_info: RunSourceInfo,
    aborted_phase: str,
    abort_reason: str | None,
) -> None:
    cells = tuple(getattr(execute_outcome, "results", ())) if execute_outcome is not None else tuple(attempted)
    compatibility_pruned = (
        tuple(getattr(execute_outcome, "compatibility_pruned", ()))
        if execute_outcome is not None
        else _compatibility_pruned_for_config(config)
    )
    early_stop_pruned_count = len(getattr(execute_outcome, "pruned", ())) if execute_outcome is not None else 0
    _write_cells_jsonl(log_dir / "cells.jsonl", cells, source_info=source_info)
    _write_compatibility_pruned_jsonl(log_dir / "compatibility_pruned.jsonl", compatibility_pruned)
    report_phase.write_report(
        cells,
        output_path=_partial_report_path(log_dir / config.report.matrix_summary_tsv),
        rungs=list(config.scales.rungs),
        cross_scale_floor=config.report.cross_scale_coverage_min_pairs,
        compatibility_pruned_count=len(compatibility_pruned),
        early_stop_pruned_count=early_stop_pruned_count,
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


def _write_cells_jsonl(path: Path, cells: Iterable[CellResult], *, source_info: RunSourceInfo) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for cell in cells:
            terminal_state = report_phase.terminal_state(cell)
            failure_tail = _persist_cell_failure_context(cell, terminal_state=terminal_state)
            fh.write(
                json.dumps(
                    {
                        "platform": cell.platform,
                        "benchmark": cell.benchmark,
                        "scale": cell.scale,
                        "status": cell.status,
                        "terminal_state": terminal_state,
                        "submit_terminal_state": cell.submit_terminal_state,
                        "timed_out": cell.status == "timed-out",
                        "exit_code": cell.exit_code,
                        "elapsed_s": cell.elapsed_s,
                        "log_path": str(cell.log_path),
                        "result_path": (str(cell.result_path) if cell.result_path else None),
                        "failure_tail": failure_tail,
                        "source_commit_sha": source_info.commit_sha,
                        "source_commit_short_sha": source_info.commit_short_sha,
                        "source_dirty": source_info.dirty,
                    }
                )
                + "\n"
            )


def _write_compatibility_pruned_jsonl(path: Path, cells: Iterable[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for cell in cells:
            fh.write(
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


def _persist_cell_failure_context(cell: CellResult, *, terminal_state: str) -> str:
    if cell.status == "passed" and cell.result_path is not None:
        return ""
    log_path = Path(cell.log_path)
    tail = _cell_log_tail(log_path)
    if log_path.exists():
        if not _cell_log_has_marker(log_path):
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(
                    f"# UAT_TERMINAL_STATE terminal_state={terminal_state} "
                    f"status={cell.status} exit_code={cell.exit_code} "
                    f"result_path={cell.result_path or ''}\n"
                )
                fh.write(f"# UAT_FAILURE_TAIL_START max_lines={FAILURE_TAIL_LINES}\n")
                fh.write((tail or "(no subprocess output captured)") + "\n")
                fh.write("# UAT_FAILURE_TAIL_END\n")
    return tail


def _cell_log_tail(log_path: Path) -> str:
    if not log_path.exists():
        return ""
    lines: deque[str] = deque(maxlen=FAILURE_TAIL_LINES)
    with log_path.open(encoding="utf-8", errors="replace") as fh:
        for raw_line in fh:
            line = raw_line.rstrip("\n")
            if line.startswith("# UAT_"):
                break
            if line.startswith("# "):
                continue
            if line.strip():
                lines.append(line)
    tail = "\n".join(lines)
    if len(tail) > FAILURE_TAIL_CHARS:
        return tail[-FAILURE_TAIL_CHARS:]
    return tail


def _cell_log_has_marker(log_path: Path) -> bool:
    with log_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            if line.startswith("# UAT_TERMINAL_STATE "):
                return True
            if line.startswith("# UAT_"):
                break
    return False


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
    return run_sweep(config, resume_manifest=resume_manifest)
