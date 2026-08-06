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

# SIGTERM -> SIGKILL grace, and the bounded `wait()` that follows the ladder so
# a cancelled sweep does not leave `<defunct>` children behind.
_KILL_GRACE_S = 0.2
_REAP_TIMEOUT_S = 1.0


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

    Cancellation teardown
    ---------------------
    Both branches (`timeout_s == 0` and the timed branch) use `Popen` and
    guard `communicate()` with `except BaseException: kill; reap; raise`.
    This matters because `SweepCancelled` (tests/uat/orchestrator.py)
    subclasses `KeyboardInterrupt`, which is NOT an `Exception` -- an
    `except subprocess.TimeoutExpired` (or `except Exception`) clause never
    fires for it, so without a `BaseException` handler a sweep cancellation
    propagates straight out of `communicate()`
    (uat-cell-teardown-orphans-child-processes-20260805).

    State the prior bug precisely, because the case for this change rests on
    it: what leaked was *descendants*, not the direct child. The timed
    branch already spawned into its own session but only handled
    `TimeoutExpired`, so a cancellation left the entire cell process group
    -- database server, datagen, benchbox itself -- running. The
    zero-timeout branch used a bare `subprocess.run`, which has its own
    `except BaseException: process.kill()` plus a context manager that
    `wait()`s, so the direct child did die; but it never called `setsid()`
    and never signalled a group, so every grandchild survived. Measured on
    a child that spawns a grandchild:

        pre-fix  (bare subprocess.run)   child=gone  grandchild=ALIVE
        shipped  (Popen+setsid+killpg)   child=gone  grandchild=gone

    Residual spawn-window exposure (measured, accepted)
    ---------------------------------------------------
    `Popen()` itself runs *inside* the guarded `try` (with `proc` seeded to
    `None` beforehand) rather than being called and assigned before the
    `try` starts. That catches any cancellation landing after `Popen()`
    returns, without a registry of live children outside this function:
    `except BaseException` only kills when `proc is not None`.

    It does NOT close the window *inside* `Popen.__init__`. The child is
    forked, `setsid()`-ed and exec'd while the parent is still blocked
    reading the exec-status pipe, so a signal delivered in there finds
    `proc is None`, the guard no-ops, and a live process in its own session
    is orphaned (state `Ss`, not `Z`). Sweeping 150 SIGALRM deliveries
    across that window produced 12 survivors.

    Accepted rather than closed. `Popen()` returns in ~1 ms idle and ~3 ms
    under 2x load, against an `execute.per_cell_timeout_s` that defaults to
    600 s and is rejected at `<= 0` (tests/uat/config.py), so an operator
    `kill` has to land inside roughly 3 ms out of every 600 s of cell, and
    the result is one recoverable session-leader root rather than a silent
    leak. Not "one visible process": measured, 18/18 of those survivors
    already owned a live grandchild of their own. What makes the residual
    acceptable is that the survivor is a session LEADER -- so the operator
    (or `make uat-docker-cleanup`) can reap the whole tree from that one pid
    with a single `kill -- -PGID` -- not that the tree is a single process.

    What would close it, and why it is not done here: block SIGINT/SIGTERM
    with `signal.pthread_sigmask` around the `Popen()` call and unblock
    inside the guarded `try`, deferring delivery until `proc` is bound.
    That is not free -- a child inherits the parent's blocked mask across
    `fork` + `exec` (measured: a child spawned under a `{SIGINT, SIGTERM}`
    block reports both blocked), so it also needs the mask cleared in
    `preexec_fn`, and getting that wrong leaves every cell child deaf to
    the SIGTERM rung of the ladder below -- a 100%-of-cells regression
    traded against a ~0.0005% window. The other option, a module-level
    registry of live process groups, was deliberately deleted on this
    branch because 589 tests passed with it neutered; restoring it needs
    tests that pin it first.

    Tradeoff: both branches now detach into a new session
    ----------------------------------------------------
    `preexec_fn=os.setsid` now applies to the zero-timeout branch too, so
    its child leaves the caller's foreground process group. Better under an
    operator `kill` of the sweep: teardown reaches the whole descendant
    tree instead of only the direct child. Worse under terminal-generated
    signals: Ctrl-C (SIGINT) and Ctrl-\\ (SIGQUIT) are delivered to the
    foreground process group, which the detached child has left, so it now
    dies only via the ladder this wrapper runs -- and if the sweep process
    is itself `kill -9`'d, nothing runs the ladder and the group is
    orphaned. The timed branch already had that property; this extends it
    to `timeout_s == 0`.
    """
    import time

    start = time.monotonic()
    # New session so we can kill the whole process group; matches the
    # `setsid()` call in the perl wrapper. Applies to both branches below --
    # the zero-timeout branch used to skip this entirely via a bare
    # `subprocess.run`, so it reaped only the direct child and left every
    # descendant running (see the docstring).
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
                _kill_and_reap_process_group(proc)
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
        if proc is None:  # pragma: no cover - unreachable
            # Only `proc.communicate(timeout=...)` above can raise
            # TimeoutExpired, so `proc` is always bound here. This is a real
            # branch rather than an `assert` because `assert` is stripped
            # under `python -O`: it would read as a runtime invariant while
            # only ever narrowing the type for the checker.
            raise
        _kill_process_group(proc)
        try:
            out, err = proc.communicate(timeout=_REAP_TIMEOUT_S)
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
            _kill_and_reap_process_group(proc)
        raise


def _kill_and_reap_process_group(proc: subprocess.Popen) -> None:
    """Run the kill ladder, then reap, so an unwinding caller leaves no zombie.

    `_kill_process_group` only *signals*; nothing on the cancellation path
    ever calls `wait()`, so without this the killed child lingers as
    `<defunct>` until CPython's `Popen` finalizer happens to collect it.
    Harmless in production (the sweep process is on its way out and the
    zombie dies with it) but it makes "the pid disappeared" an untrustworthy
    teardown assertion, because the disappearance is then attributable to
    garbage collection rather than to this module.

    Bounded and non-fatal: SIGKILL has already been delivered, so a child
    still unreaped after `_REAP_TIMEOUT_S` is a kernel-level anomaly, not
    something an unwinding sweep should block on.

    Not reached when a *second* signal lands inside the ladder's grace
    window -- that unwinds out of `_kill_process_group` after its `finally`
    has delivered SIGKILL, skipping this reap. Accepted residue: the group
    is dead either way, only the `<defunct>` entry survives.
    """
    _kill_process_group(proc)
    try:
        proc.wait(timeout=_REAP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        pass


def _kill_process_group(proc: subprocess.Popen) -> None:
    """Send SIGTERM, sleep 200 ms, send SIGKILL — same ladder as the perl wrapper.

    `os.killpg` does not exist on win32 (the process is also never placed in
    its own session there -- `preexec_fn=os.setsid` is POSIX-only, see the
    `preexec` selection above). Guard with `hasattr` and fall back to
    `proc.kill()`, which `subprocess` implements portably (`TerminateProcess`
    on win32, `SIGKILL` on POSIX), so a per-cell timeout still reaps the
    child instead of crashing the whole execute phase with an uncaught
    AttributeError.

    The SIGKILL rung lives in a `finally`, not on the straight line after
    the sleep. An exception raised inside one `except` clause is not caught
    by a sibling `except` of the same `try`, so a second signal arriving
    during the 200 ms grace -- precisely what an operator does when the
    first `kill` appears to do nothing to a SIGTERM-trapping database server
    -- used to unwind out of the sleep and out of `run_with_timeout`'s
    handler with only SIGTERM ever delivered, leaving the group orphaned
    (observed: signals reaching the cell group `[15]`, child state `Ss`).
    The `try` opens *before* the SIGTERM call so there is no unguarded gap
    between the two rungs; the cost is one wasted `killpg` when the group
    was already gone, which `_killpg` swallows.
    """
    import time

    if not hasattr(os, "killpg"):
        proc.kill()
        return
    try:
        if not _killpg(proc.pid, signal.SIGTERM):
            return
        time.sleep(_KILL_GRACE_S)
    finally:
        _killpg(proc.pid, signal.SIGKILL)


def _killpg(pgid: int, sig: int) -> bool:
    """`os.killpg`, reporting whether the signal reached a group."""
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        return False
    return True
