"""Single-cell `benchbox run` execution.

Mirrors the bash `run_benchmark` function in
scripts/local_stress_test.sh:433-493 — build the argv, capture output
to a per-run log, extract the result-JSON path on success.

Sequential platform execution discipline (UAT W3 line 222 in
_project/handoffs/results-explorer-uat-retrospective-20260502.md):
this module exposes one-cell-at-a-time invocation only. Higher layers
must iterate sequentially.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from pathlib import Path

from tests.uat.matrix import benchbox_run_argv
from tests.uat.timeouts import TimeoutResult, run_with_timeout

# Mirrors scripts/local_stress_test.sh:478 — match either an absolute or
# relative `benchmark_runs/results/.../*.json` path.
RESULT_PATH_RE = re.compile(r"(?:/[^\s]+/)?benchmark_runs/results/[^\s]+\.json")


@dataclass(frozen=True)
class CellResult:
    """Outcome of a single (platform, benchmark, scale) cell."""

    platform: str
    benchmark: str
    scale: float
    status: str  # "passed" | "failed" | "timed-out"
    exit_code: int
    elapsed_s: float
    log_path: Path
    result_path: Path | None


def extract_result_path(log_text: str) -> str | None:
    """Return the last `benchmark_runs/results/.../*.json` path mentioned in log_text.

    Bash semantics: `grep -oE ... | tail -1`. The Python port matches the
    last occurrence so log re-prints (e.g. summary tables) take precedence
    over earlier diagnostic prints.
    """
    matches = RESULT_PATH_RE.findall(log_text)
    if not matches:
        return None
    return matches[-1]


def _default_log_path(log_dir: Path, platform: str, benchmark: str, scale: float, now: _dt.datetime) -> Path:
    timestamp = now.strftime("%Y%m%d_%H%M%S")
    return log_dir / f"{platform}_{benchmark}_{scale}_{timestamp}.log"


def run_cell(
    platform: str,
    benchmark: str,
    scale: float,
    *,
    timeout_s: int = 600,
    phases: str = "load,power",
    compression: str | None = None,
    log_dir: Path | str | None = None,
    extra_args=(),
    now: _dt.datetime | None = None,
) -> CellResult:
    """Run a single cell end-to-end and return the cell result.

    Mirrors scripts/local_stress_test.sh:433-493.
    """
    now = now or _dt.datetime.now()
    log_dir = Path(log_dir) if log_dir is not None else _default_log_dir(now)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = _default_log_path(log_dir, platform, benchmark, scale, now)
    argv = benchbox_run_argv(
        platform,
        benchmark,
        scale,
        phases=phases,
        compression=compression,
        extra_args=extra_args,
    )

    with log_path.open("w", encoding="utf-8") as log_fh:
        log_fh.write(f"# {' '.join(argv)}\n")
        log_fh.flush()
        timeout_result = run_with_timeout(
            argv,
            timeout_s=timeout_s,
            stdout=log_fh,
            stderr=log_fh,
        )

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    result_path_str = extract_result_path(log_text) if timeout_result.exit_code == 0 else None
    result_path = Path(result_path_str) if result_path_str else None
    status = _classify(timeout_result)
    return CellResult(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        status=status,
        exit_code=timeout_result.exit_code,
        elapsed_s=timeout_result.elapsed_s,
        log_path=log_path,
        result_path=result_path,
    )


def _classify(timeout_result: TimeoutResult) -> str:
    if timeout_result.timed_out:
        return "timed-out"
    if timeout_result.exit_code == 0:
        return "passed"
    return "failed"


def _default_log_dir(now: _dt.datetime) -> Path:
    runs_root = Path(
        os.environ.get(
            "BENCHBOX_OUTPUT_DIR",
            str(Path.home() / "Developer" / "benchmark_runs"),
        )
    )
    return runs_root / "logs" / f"uat_{now.strftime('%Y%m%d')}"
