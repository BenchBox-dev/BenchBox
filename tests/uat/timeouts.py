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
from typing import Any, Mapping

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

    Both branches (`timeout_s == 0` and the timed branch) use `Popen` and
    guard `communicate()` with `except BaseException: kill; raise`. This
    matters because `SweepCancelled` (tests/uat/orchestrator.py) subclasses
    `KeyboardInterrupt`, which is NOT an `Exception` -- an
    `except subprocess.TimeoutExpired` (or `except Exception`) clause never
    fires for it, so without a `BaseException` handler a sweep cancellation
    propagates straight out of `communicate()` with the child untouched
    (uat-cell-teardown-orphans-child-processes-20260805).

    `Popen()` itself runs *inside* the guarded `try` (with `proc` seeded to
    `None` beforehand) rather than being called and assigned before the
    `try` starts. That closes the gap a cancellation landing between
    `Popen()` returning and a subsequent statement would otherwise fall
    into, without needing any registry of live children outside this
    function: `except BaseException` only calls `_kill_process_group` when
    `proc is not None`, i.e. once `Popen()` has actually returned a handle.
    A signal arriving before that point has no process to kill yet; one
    arriving after it is caught by this same guard regardless of exactly
    which line was executing.
    """
    import time

    start = time.monotonic()
    # New session so we can kill the whole process group; matches the
    # `setsid()` call in the perl wrapper. Applies to both branches below --
    # the zero-timeout branch used to skip this entirely via a bare
    # `subprocess.run`, which left it with no teardown path at all.
    preexec = os.setsid if sys.platform != "win32" else None

    if timeout_s == 0:
        proc: subprocess.Popen | None = None
        try:
            proc = subprocess.Popen(
                argv,
                stdout=stdout,
                stderr=stderr,
                env=env,
                cwd=cwd,
                preexec_fn=preexec,
            )
            out, err = proc.communicate()
            return TimeoutResult(
                exit_code=proc.returncode,
                timed_out=False,
                elapsed_s=time.monotonic() - start,
                stdout=out,
                stderr=err,
            )
        except BaseException:
            if proc is not None:
                _kill_process_group(proc)
            raise

    proc = None
    try:
        proc = subprocess.Popen(
            argv,
            stdout=stdout,
            stderr=stderr,
            env=env,
            cwd=cwd,
            preexec_fn=preexec,
        )
        out, err = proc.communicate(timeout=timeout_s)
        return TimeoutResult(
            exit_code=proc.returncode,
            timed_out=False,
            elapsed_s=time.monotonic() - start,
            stdout=out,
            stderr=err,
        )
    except subprocess.TimeoutExpired:
        # Only raised by the `proc.communicate(timeout=...)` call above, so
        # `proc` is always assigned here.
        assert proc is not None
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
    except BaseException:
        # Any other unwind (SweepCancelled/KeyboardInterrupt included -- see
        # the docstring above) still reaps the group, when one was actually
        # spawned, before propagating unchanged: the sweep must keep
        # unwinding so the platform teardown and finalize markers run.
        if proc is not None:
            _kill_process_group(proc)
        raise


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
