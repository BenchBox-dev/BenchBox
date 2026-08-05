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

# Live child process groups spawned by `run_with_timeout`, keyed by pid
# (== pgid under `setsid`). Registered right after `Popen()` and drained on
# every exit path (including the finally below), so a sweep cancellation
# landing in the narrow window between `Popen()` returning and this
# function's own try/except being entered still has a kill path: the
# orchestrator's SIGTERM shim calls `drain_live_process_groups()` before it
# raises `SweepCancelled` (uat-cell-teardown-orphans-child-processes w2).
_LIVE_PROCESS_GROUPS: dict[int, subprocess.Popen] = {}


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
    """
    import time

    start = time.monotonic()
    # New session so we can kill the whole process group; matches the
    # `setsid()` call in the perl wrapper. Applies to both branches below --
    # the zero-timeout branch used to skip this entirely via a bare
    # `subprocess.run`, which left it with no teardown path at all.
    preexec = os.setsid if sys.platform != "win32" else None

    if timeout_s == 0:
        proc = subprocess.Popen(
            argv,
            stdout=stdout,
            stderr=stderr,
            env=env,
            cwd=cwd,
            preexec_fn=preexec,
        )
        _register_live_group(proc)
        try:
            out, err = proc.communicate()
            return TimeoutResult(
                exit_code=proc.returncode,
                timed_out=False,
                elapsed_s=time.monotonic() - start,
                stdout=out,
                stderr=err,
            )
        except BaseException:
            _kill_process_group(proc)
            raise
        finally:
            _unregister_live_group(proc)

    proc = subprocess.Popen(
        argv,
        stdout=stdout,
        stderr=stderr,
        env=env,
        cwd=cwd,
        preexec_fn=preexec,
    )
    _register_live_group(proc)
    try:
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
        except BaseException:
            # Any other unwind (SweepCancelled/KeyboardInterrupt included --
            # see the docstring above) still reaps the group before
            # propagating unchanged: the sweep must keep unwinding so the
            # platform teardown and finalize markers run.
            _kill_process_group(proc)
            raise
    finally:
        _unregister_live_group(proc)


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


def _register_live_group(proc: subprocess.Popen) -> None:
    """Track a just-`Popen`'d child so `drain_live_process_groups` can reap it.

    Covers the window between `Popen()` returning and `run_with_timeout`
    entering its own try/except: a cancellation landing there would
    otherwise unwind past this function with no kill call armed yet.
    """
    _LIVE_PROCESS_GROUPS[proc.pid] = proc


def _unregister_live_group(proc: subprocess.Popen) -> None:
    _LIVE_PROCESS_GROUPS.pop(proc.pid, None)


def drain_live_process_groups() -> None:
    """Kill and clear every currently-registered live child process group.

    Called by the sweep orchestrator's SIGTERM handler
    (`orchestrator._install_sweep_sigterm_shim`) before it raises
    `SweepCancelled`, so a signal landing in the narrow gap between a
    child's `Popen()` and `run_with_timeout`'s own `except BaseException`
    guard still gets reaped instead of orphaned
    (uat-cell-teardown-orphans-child-processes-20260805 w2).
    """
    for proc in list(_LIVE_PROCESS_GROUPS.values()):
        _kill_process_group(proc)
    _LIVE_PROCESS_GROUPS.clear()
