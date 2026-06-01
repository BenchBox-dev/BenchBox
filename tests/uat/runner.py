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
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from benchbox.core.results.submit_classification import (
    SubmitTerminalState,
    classify_result_path,
)
from tests.uat.matrix import benchbox_run_argv
from tests.uat.timeouts import TimeoutResult, run_with_timeout

# SubmitTerminalState is re-exported so existing UAT consumers
# (tests/uat/_cli.py, phases/execute.py, phases/package.py) keep importing it
# from tests.uat.runner. The classification *policy* now lives in
# benchbox.core.results.submit_classification, shared with `benchbox submit`.
__all__ = [
    "CellResult",
    "SubmitTerminalState",
    "classify_for_submit",
    "submit_state_is_cell_failure",
]


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
    """Classify a result JSON for submittability (thin adapter over shared policy).

    Delegates to ``benchbox.core.results.submit_classification`` so UAT and
    ``benchbox submit`` apply identical refusal policy; this wrapper only
    preserves the UAT-facing call site and vocabulary.
    """
    return classify_result_path(result_json)


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


# Upper bound for the verbose diagnostic re-run triggered when a `--quiet`
# cell exits non-zero without emitting stdout. Failures surface fast, so a tight
# cap keeps the re-run cheap while still capturing the real error.
DIAGNOSTIC_RERUN_TIMEOUT_S = 180


def _append_diagnostic_rerun(log_fh, argv: list[str], *, timeout_s: int, env: dict[str, str]) -> None:
    """Re-run a failed cell verbosely and append its output to the log.

    Invoked only when the original ``--quiet`` invocation exited non-zero
    without emitting stdout (``--quiet`` suppresses benchbox's own error
    reporting). Output is written as plain lines so ``_cell_log_tail`` captures
    it into ``failure_tail``. Best-effort: never raises into the caller.
    """
    log_fh.write("[uat] verbose diagnostic re-run (--quiet suppressed the original error):\n")
    log_fh.flush()
    try:
        rerun = run_with_timeout(
            argv,
            timeout_s=timeout_s,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        text = _decode_process_output(rerun.stdout)
        if text:
            log_fh.write(text if text.endswith("\n") else text + "\n")
        log_fh.write(f"[uat] diagnostic re-run exit_code={rerun.exit_code} timed_out={rerun.timed_out}\n")
    except Exception as exc:  # noqa: BLE001 - diagnostics must never mask the original failure
        log_fh.write(f"[uat] diagnostic re-run error {type(exc).__name__}: {exc}\n")


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
            stderr=subprocess.PIPE,
            env=env,
        )
        stdout_text = _decode_process_output(timeout_result.stdout)
        stderr_text = _decode_process_output(timeout_result.stderr)
        if stderr_text:
            log_fh.write(stderr_text)
        if stdout_text:
            log_fh.write(stdout_text)
        if timeout_result.timed_out:
            log_fh.write(f"# UAT_TIMEOUT timeout_s={timeout_s} exit_code={timeout_result.exit_code}\n")
        elif timeout_result.exit_code != 0 and not stdout_text.strip():
            _append_diagnostic_rerun(
                log_fh,
                benchbox_run_argv(
                    platform,
                    benchmark,
                    scale,
                    phases=phases,
                    compression=compression,
                    extra_args=("--output", str(runs_dir / "datagen"), *extra_args),
                    local_managed_platform=local_managed_platform,
                    quiet=False,
                ),
                timeout_s=min(timeout_s, DIAGNOSTIC_RERUN_TIMEOUT_S),
                env=env,
            )

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
