"""Validate phase: invoke scripts/uat_validator_rollup.py per sweep.

INTEGRATION work, not reimplementation. The
`scripts/uat_validator_rollup.py` helper from
`uat-template-validator-clean-rate-runner` is the source of truth for
validation; this phase invokes it as a subprocess and consumes the
resulting TSV.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ROLLUP_SCRIPT = REPO_ROOT / "scripts" / "uat_validator_rollup.py"
TSV_HEADER = "platform\tbenchmark\tscale\tresult_path\tvalidator_status\terror_count\twarning_count\tfirst_error"


@dataclass(frozen=True)
class ValidateResult:
    rollup_tsv_path: Path
    clean_count: int
    warning_count: int
    error_count: int
    refused_count: int
    total: int
    clean_rate: float
    floor: float
    floor_breached: bool
    script_returncode: int = 0

    def exit_code(self) -> int:
        if self.script_returncode != 0:
            return self.script_returncode
        if self.floor_breached:
            return 1
        return 0


class ValidatePhaseError(RuntimeError):
    """Raised when the validator subprocess fails before producing a TSV."""


def run_validate(
    results_dir: Path | Sequence[Path],
    *,
    output_tsv: Path,
    floor: float = 0.80,
    extra_args: tuple[str, ...] = (),
    rollup_script: Path | None = None,
    runner=None,
) -> ValidateResult:
    """Execute the validate phase against results_dir, writing the rollup to output_tsv.

    Does NOT raise on non-zero validator exit. The returncode is surfaced
    through `ValidateResult.script_returncode` and folded into
    `exit_code()` so the orchestrator can keep the phase contract uniform
    (set phase_exit_codes, never propagate CalledProcessError).
    Raises `ValidatePhaseError` only when the subprocess fails AND no TSV
    was produced — in that case there is nothing to parse.
    """
    if runner is None:
        runner = subprocess.run
    script = rollup_script or ROLLUP_SCRIPT
    if not script.exists():
        raise FileNotFoundError(f"validator rollup helper not found at {script}")
    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    if output_tsv.exists():
        output_tsv.unlink()
    if not isinstance(results_dir, Path):
        return _run_validate_paths(
            tuple(results_dir),
            output_tsv=output_tsv,
            floor=floor,
            extra_args=extra_args,
            rollup_script=script,
            runner=runner,
        )
    argv = [
        sys.executable,
        str(script),
        str(results_dir),
        "--output",
        str(output_tsv),
        *extra_args,
    ]
    completed = runner(argv, check=False)
    rc = getattr(completed, "returncode", 0)
    if rc != 0 and not output_tsv.exists():
        raise ValidatePhaseError(f"validator subprocess exited {rc} without producing {output_tsv}")
    parsed = parse_rollup(output_tsv, floor=floor)
    if rc == 0:
        return parsed
    return ValidateResult(
        rollup_tsv_path=parsed.rollup_tsv_path,
        clean_count=parsed.clean_count,
        warning_count=parsed.warning_count,
        error_count=parsed.error_count,
        refused_count=parsed.refused_count,
        total=parsed.total,
        clean_rate=parsed.clean_rate,
        floor=parsed.floor,
        floor_breached=parsed.floor_breached,
        script_returncode=rc,
    )


def _run_validate_paths(
    result_paths: tuple[Path, ...],
    *,
    output_tsv: Path,
    floor: float,
    extra_args: tuple[str, ...],
    rollup_script: Path,
    runner,
) -> ValidateResult:
    """Run the rollup helper against exact execute result paths and merge its TSV rows."""
    rows: list[str] = []
    script_returncode = 0
    for idx, result_path in enumerate(result_paths):
        tmp_tsv = output_tsv.with_name(f".{output_tsv.name}.{idx}.tmp")
        if tmp_tsv.exists():
            tmp_tsv.unlink()
        argv = [
            sys.executable,
            str(rollup_script),
            str(result_path),
            "--output",
            str(tmp_tsv),
            *extra_args,
        ]
        completed = runner(argv, check=False)
        rc = getattr(completed, "returncode", 0)
        if script_returncode == 0 and rc != 0:
            script_returncode = rc
        if rc != 0 and not tmp_tsv.exists():
            raise ValidatePhaseError(f"validator subprocess exited {rc} without producing {tmp_tsv}")
        rows.extend(_rollup_body_rows(tmp_tsv))
        tmp_tsv.unlink(missing_ok=True)

    output_tsv.write_text(TSV_HEADER + "\n" + "\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")
    parsed = parse_rollup(output_tsv, floor=floor)
    if script_returncode == 0:
        return parsed
    return ValidateResult(
        rollup_tsv_path=parsed.rollup_tsv_path,
        clean_count=parsed.clean_count,
        warning_count=parsed.warning_count,
        error_count=parsed.error_count,
        refused_count=parsed.refused_count,
        total=parsed.total,
        clean_rate=parsed.clean_rate,
        floor=parsed.floor,
        floor_breached=parsed.floor_breached,
        script_returncode=script_returncode,
    )


def _rollup_body_rows(rollup_tsv: Path) -> list[str]:
    with rollup_tsv.open("r", encoding="utf-8") as fh:
        lines = [line.rstrip("\n") for line in fh]
    return [line for line in lines[1:] if line and not line.startswith("#")]


def parse_rollup(rollup_tsv: Path, *, floor: float = 0.80) -> ValidateResult:
    """Parse the TSV emitted by scripts/uat_validator_rollup.py and compute clean-rate."""
    clean = warning = error = refused = 0
    with rollup_tsv.open("r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        try:
            status_idx = header.index("validator_status")
        except ValueError as exc:
            raise ValueError(f"rollup TSV header missing validator_status column: {header}") from exc
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= status_idx:
                continue
            status = fields[status_idx]
            if status == "clean":
                clean += 1
            elif status == "warning_only":
                warning += 1
            elif status == "error":
                error += 1
            elif status == "refused-by-cli":
                refused += 1
    total = clean + warning + error + refused
    if total == 0:
        clean_rate = 0.0
    else:
        # Clean-rate is computed against all bundles the validator
        # actually ran on (i.e. excluding refused). Matches the
        # interpretation used in the 2026-05-02 retrospective.
        denom = total - refused
        clean_rate = clean / denom if denom > 0 else 0.0
    floor_breached = clean_rate < floor
    return ValidateResult(
        rollup_tsv_path=rollup_tsv,
        clean_count=clean,
        warning_count=warning,
        error_count=error,
        refused_count=refused,
        total=total,
        clean_rate=clean_rate,
        floor=floor,
        floor_breached=floor_breached,
    )


def parse_validator_status_by_path(rollup_tsv: Path) -> dict[Path, str]:
    """Extract result_path → validator_status from a rollup TSV.

    Used by the report phase so cross_scale_clean_pair_count can apply
    the validator-clean dimension. Missing or short rows are skipped.
    """
    out: dict[Path, str] = {}
    with rollup_tsv.open("r", encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        try:
            status_idx = header.index("validator_status")
            path_idx = header.index("result_path")
        except ValueError:
            return out
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            fields = line.rstrip("\n").split("\t")
            if len(fields) <= max(status_idx, path_idx):
                continue
            result_path = fields[path_idx].strip()
            if not result_path:
                continue
            out[Path(result_path).resolve()] = fields[status_idx]
    return out


def standalone_argv(results_dir: Path, output_tsv: Path) -> list[str]:
    """Help text helper for `make uat-validate`."""
    return [
        sys.executable,
        str(ROLLUP_SCRIPT),
        str(results_dir),
        "--output",
        str(output_tsv),
    ]


def has_rollup_script() -> bool:
    return ROLLUP_SCRIPT.exists() or shutil.which("uat_validator_rollup.py") is not None
