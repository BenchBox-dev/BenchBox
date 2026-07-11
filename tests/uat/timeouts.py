"""Signal-based subprocess timeout wrapper.

Exit-code semantics: 0 on success, child exit code on failure, 124 on
timeout.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

EXIT_TIMEOUT = 124  # POSIX coreutils convention: SIGTERM after timeout.


@dataclass(frozen=True)
class TimeoutResult:
    """Outcome of `run_with_timeout`."""

    exit_code: int
    timed_out: bool
    elapsed_s: float
    stdout: Any = None
    stderr: Any = None


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

    `timeout_s == 0` means no timeout. Otherwise, after `timeout_s`
    seconds the process group receives SIGTERM, and 200 ms later
    SIGKILL.

    `stdout` and `stderr` accept anything `subprocess.Popen` would. When
    callers pass `subprocess.PIPE`, this wrapper drains the pipes with
    `communicate()` so a noisy child cannot block timeout enforcement.
    """
    import time

    start = time.monotonic()
    if timeout_s == 0:
        proc = subprocess.run(argv, stdout=stdout, stderr=stderr, env=env, cwd=cwd, check=False)
        return TimeoutResult(
            exit_code=proc.returncode,
            timed_out=False,
            elapsed_s=time.monotonic() - start,
            stdout=proc.stdout,
            stderr=proc.stderr,
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
        out, err = proc.communicate(timeout=timeout_s)
        return TimeoutResult(
            exit_code=proc.returncode,
            timed_out=False,
            elapsed_s=time.monotonic() - start,
            stdout=out,
            stderr=err,
        )
    except subprocess.TimeoutExpired:
        _kill_process_group(proc)
        try:
            out, err = proc.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            # SIGKILL did not reap or output could not drain; keep timeout
            # classification stable and return without blocking the caller.
            out, err = None, None
        return TimeoutResult(
            exit_code=EXIT_TIMEOUT,
            timed_out=True,
            elapsed_s=time.monotonic() - start,
            stdout=out,
            stderr=err,
        )


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Send SIGTERM, sleep 200 ms, send SIGKILL — same ladder as the perl wrapper.

    `os.killpg` does not exist on win32 (the process is also never placed in
    its own session there -- `preexec_fn=os.setsid` is POSIX-only, see the
    `preexec` selection above). Guard with `hasattr` and fall back to
    `proc.kill()`, which `subprocess` implements portably (`TerminateProcess`
    on win32, `SIGKILL` on POSIX), so a per-cell timeout still reaps the
    child instead of crashing the whole execute phase with an uncaught
    AttributeError.
    """
    import time

    if not hasattr(os, "killpg"):
        proc.kill()
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    time.sleep(0.2)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
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
