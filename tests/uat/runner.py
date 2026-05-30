"""Single-cell `benchbox run` execution.

Build the argv, capture output to a per-run log, and read the quiet
result-JSON path on success.

Sequential platform execution discipline (UAT W3 line 222 in
_project/handoffs/results-explorer-uat-retrospective-20260502.md):
this module exposes one-cell-at-a-time invocation only. Higher layers
must iterate sequentially.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from benchbox.core.results.loader import ResultLoadError, UnsupportedSchemaError, load_result_file
from benchbox.core.results.status import result_failed_query_count, result_non_clean_reason
from tests.uat.matrix import benchbox_run_argv
from tests.uat.timeouts import TimeoutResult, run_with_timeout

UNOFFICIAL_COMPLIANCE_CLASSES = frozenset({"unofficial_nonstandard", "unofficial_subscale"})


class SubmitTerminalState(str, Enum):
    """UAT mirror of the `benchbox submit --output` refusal vocabulary."""

    submittable = "submittable"
    unofficial = "unofficial"
    query_failure = "query_failure"
    schema_violation = "schema_violation"
    missing_manifest = "missing_manifest"


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
    submit_terminal_state: str = SubmitTerminalState.submittable.value


def last_nonempty_output_line(log_text: str) -> str | None:
    """Return the final subprocess output line from a UAT cell log."""
    for line in reversed(log_text.splitlines()):
        stripped = line.strip()
        if stripped and not stripped.startswith("# "):
            return stripped
    return None


def classify_for_submit(result_json: Path | str | None) -> SubmitTerminalState:
    """Classify a result JSON using the same refusal predicates as `benchbox submit`.

    Mirrors `benchbox/cli/commands/submit.py`: load failures are schema
    problems, unofficial TPC-DS compliance classes remain successful but
    non-submittable, and non-clean results are refused before packaging.
    """
    if result_json is None:
        return SubmitTerminalState.missing_manifest
    path = Path(result_json).expanduser()
    if not path.exists():
        return SubmitTerminalState.missing_manifest
    try:
        result, _raw = load_result_file(path)
    except FileNotFoundError:
        return SubmitTerminalState.missing_manifest
    except (json.JSONDecodeError, OSError, ResultLoadError, UnsupportedSchemaError):
        return SubmitTerminalState.schema_violation

    if getattr(result, "compliance_class", None) in UNOFFICIAL_COMPLIANCE_CLASSES:
        return SubmitTerminalState.unofficial

    non_clean_reason = result_non_clean_reason(result)
    if non_clean_reason:
        if result_failed_query_count(result):
            return SubmitTerminalState.query_failure
        return SubmitTerminalState.schema_violation
    return SubmitTerminalState.submittable


def submit_state_is_cell_failure(state: SubmitTerminalState | str) -> bool:
    """Return True for submit states that should downgrade a passed cell to FAILED."""
    normalized = state.value if isinstance(state, SubmitTerminalState) else str(state)
    return normalized in {
        SubmitTerminalState.query_failure.value,
        SubmitTerminalState.schema_violation.value,
        SubmitTerminalState.missing_manifest.value,
    }


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
    benchmark_runs_dir: Path | str | None = None,
    extra_args=(),
    local_managed_platform: bool = False,
    now: _dt.datetime | None = None,
) -> CellResult:
    """Run a single cell end-to-end and return the cell result."""
    now = now or _dt.datetime.now()
    log_dir = Path(log_dir) if log_dir is not None else _default_log_dir(now)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = _default_log_path(log_dir, platform, benchmark, scale, now)
    runs_dir = _default_benchmark_runs_dir() if benchmark_runs_dir is None else Path(benchmark_runs_dir).expanduser()
    argv = benchbox_run_argv(
        platform,
        benchmark,
        scale,
        phases=phases,
        compression=compression,
        extra_args=("--output", str(runs_dir / "datagen"), *extra_args),
        local_managed_platform=local_managed_platform,
    )

    with log_path.open("w", encoding="utf-8") as log_fh:
        log_fh.write(f"# {' '.join(argv)}\n")
        env = os.environ.copy()
        env["BENCHBOX_OUTPUT_DIR"] = str(runs_dir)
        log_fh.write(f"# BENCHBOX_OUTPUT_DIR={runs_dir}\n")
        log_fh.flush()
        timeout_result = run_with_timeout(
            argv,
            timeout_s=timeout_s,
            stdout=subprocess.PIPE,
            stderr=log_fh,
            env=env,
        )
        stdout_text = _decode_process_output(timeout_result.stdout)
        if stdout_text:
            log_fh.write(stdout_text)
        if timeout_result.timed_out:
            log_fh.write(f"# UAT_TIMEOUT timeout_s={timeout_s} exit_code={timeout_result.exit_code}\n")

    result_path_str = last_nonempty_output_line(stdout_text) if timeout_result.exit_code == 0 else None
    result_path = _resolve_result_path(result_path_str, runs_dir) if result_path_str else None
    status = _classify(timeout_result)
    submit_state = (
        classify_for_submit(result_path) if timeout_result.exit_code == 0 else SubmitTerminalState.missing_manifest
    )
    exit_code = timeout_result.exit_code
    if status == "passed" and submit_state_is_cell_failure(submit_state):
        status = "failed"
        exit_code = exit_code or 1
    return CellResult(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        status=status,
        exit_code=exit_code,
        elapsed_s=timeout_result.elapsed_s,
        log_path=log_path,
        result_path=result_path,
        submit_terminal_state=submit_state.value,
    )


def _resolve_result_path(result_path_str: str, runs_dir: Path) -> Path:
    path = Path(result_path_str).expanduser()
    if path.is_absolute() or path.exists():
        return path
    if len(path.parts) >= 2 and path.parts[0] == "benchmark_runs":
        return runs_dir.parent / path
    return runs_dir / path


def _decode_process_output(output: object) -> str:
    if output is None:
        return ""
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return str(output)


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


def _default_benchmark_runs_dir() -> Path:
    return Path(
        os.environ.get(
            "BENCHBOX_OUTPUT_DIR",
            str(Path.home() / "Developer" / "benchmark_runs"),
        )
    ).expanduser()
