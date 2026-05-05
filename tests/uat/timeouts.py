"""Signal-based subprocess timeout wrapper.

Replaces the perl process-group fallback path in
scripts/local_stress_test.sh:359-429 with native Python. Same exit-code
semantics: 0 on success, child exit code on failure, 124 on timeout.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Iterable, Mapping

EXIT_TIMEOUT = 124  # POSIX coreutils convention: SIGTERM after timeout.


@dataclass(frozen=True)
class TimeoutResult:
    """Outcome of `run_with_timeout`. Mirrors the bash wrapper's contract."""

    exit_code: int
    timed_out: bool
    elapsed_s: float


def run_with_timeout(
    argv: list[str],
    timeout_s: int,
    *,
    stdout=None,
    stderr=None,
    env: Mapping[str, str] | None = None,
    cwd: str | None = None,
) -> TimeoutResult:
    """Run `argv` with a hard wall-clock cap.

    `timeout_s == 0` means no timeout (matches the bash flag default).
    Otherwise, after `timeout_s` seconds the process group receives
    SIGTERM, and 200 ms later SIGKILL — same kill ladder as the perl
    wrapper.

    `stdout` and `stderr` accept anything `subprocess.Popen` would, but
    callers that pass `subprocess.PIPE` are responsible for draining the
    pipes; the wrapper does not buffer.
    """
    import time

    start = time.monotonic()
    if timeout_s == 0:
        proc = subprocess.run(argv, stdout=stdout, stderr=stderr, env=env, cwd=cwd, check=False)
        return TimeoutResult(
            exit_code=proc.returncode,
            timed_out=False,
            elapsed_s=time.monotonic() - start,
        )

    # New session so we can kill the whole process group; matches the
    # `setsid()` call in the perl wrapper.
    preexec = os.setsid if sys.platform != "win32" else None
    proc = subprocess.Popen(
        argv,
        stdout=stdout,
        stderr=stderr,
        env=env,
        cwd=cwd,
        preexec_fn=preexec,
    )
    try:
        returncode = proc.wait(timeout=timeout_s)
        return TimeoutResult(
            exit_code=returncode,
            timed_out=False,
            elapsed_s=time.monotonic() - start,
        )
    except subprocess.TimeoutExpired:
        _kill_process_group(proc.pid)
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            # SIGKILL did not reap; let the caller see what they get.
            pass
        return TimeoutResult(
            exit_code=EXIT_TIMEOUT,
            timed_out=True,
            elapsed_s=time.monotonic() - start,
        )


def _kill_process_group(pid: int) -> None:
    """Send SIGTERM, sleep 200 ms, send SIGKILL — same ladder as the perl wrapper."""
    import time

    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


def env_without_pythonpath(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """Build a child env that inherits the parent's env but drops PYTHONPATH.

    Convenience for tests that subprocess `uv run` without inheriting the
    parent's PYTHONPATH. Used by `tests/uat/runner.py` callers.
    """
    base = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    if extra:
        base.update(extra)
    return base


def iter_argv_for_log(argv: Iterable[str]) -> str:
    """Render argv as a single-line shell-escaped string for log files."""
    import shlex

    return " ".join(shlex.quote(a) for a in argv)
