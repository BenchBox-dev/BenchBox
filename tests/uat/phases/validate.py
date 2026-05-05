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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
ROLLUP_SCRIPT = REPO_ROOT / "scripts" / "uat_validator_rollup.py"


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

    def exit_code(self) -> int:
        if self.floor_breached:
            return 1
        return 0


def run_validate(
    results_dir: Path,
    *,
    output_tsv: Path,
    floor: float = 0.80,
    extra_args: tuple[str, ...] = (),
    rollup_script: Path | None = None,
) -> ValidateResult:
    """Execute the validate phase against results_dir, writing the rollup to output_tsv."""
    script = rollup_script or ROLLUP_SCRIPT
    if not script.exists():
        raise FileNotFoundError(f"validator rollup helper not found at {script}")
    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        str(script),
        str(results_dir),
        "--output",
        str(output_tsv),
        *extra_args,
    ]
    subprocess.run(argv, check=True)
    return parse_rollup(output_tsv, floor=floor)


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
