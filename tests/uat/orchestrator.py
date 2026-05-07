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
from dataclasses import dataclass, replace
from pathlib import Path

from tests.uat.config import UATConfig, apply_stress_overrides, load_config
from tests.uat.phases import execute as exec_phase, preflight as preflight_phase, report as report_phase


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


def run_sweep(
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
            )
            phase_exit_codes[phase] = 2 if result.aborted else 0
            if result.aborted:
                aborted_phase = phase
                abort_reason = result.abort_reason
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
            execute_outcome = exec_phase.run_execute(
                config,
                log_dir=log_dir,
                benchmark_runs_dir=benchmark_runs_dir,
                databases_root=databases_root,
                cleanup_enabled=config.cleanup.prune_databases,
                free_space_checks_enabled="preflight" in config.phases,
            )
            with cells_jsonl.open("w", encoding="utf-8") as fh:
                for cell in execute_outcome.results:
                    fh.write(
                        json.dumps(
                            {
                                "platform": cell.platform,
                                "benchmark": cell.benchmark,
                                "scale": cell.scale,
                                "status": cell.status,
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
    return run_sweep(config)
