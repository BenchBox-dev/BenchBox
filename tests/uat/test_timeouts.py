"""Fast-test coverage for tests/uat/timeouts.py."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.uat import timeouts

pytestmark = pytest.mark.fast


def test_run_with_timeout_zero_disables():
    result = timeouts.run_with_timeout([sys.executable, "-c", "pass"], timeout_s=0)
    assert result.exit_code == 0
    assert result.timed_out is False


def test_run_with_timeout_success_under_cap():
    result = timeouts.run_with_timeout([sys.executable, "-c", "pass"], timeout_s=5)
    assert result.exit_code == 0
    assert result.timed_out is False


def test_run_with_timeout_nonzero_exit():
    result = timeouts.run_with_timeout(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        timeout_s=5,
    )
    assert result.exit_code == 7
    assert result.timed_out is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only kill ladder")
def test_run_with_timeout_kills_runaway_child():
    # 3-second sleep against a 1-second cap → exit 124 (timeout).
    result = timeouts.run_with_timeout(
        [sys.executable, "-c", "import time; time.sleep(3)"],
        timeout_s=1,
    )
    assert result.timed_out is True
    assert result.exit_code == timeouts.EXIT_TIMEOUT
    assert 0.5 <= result.elapsed_s <= 2.5


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only process-group assertion")
def test_run_with_timeout_kills_grandchild_process(tmp_path):
    pid_file = tmp_path / "grandchild.pid"
    script = f"""
import pathlib
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
pathlib.Path({str(pid_file)!r}).write_text(str(child.pid), encoding="utf-8")
time.sleep(30)
"""

    result = timeouts.run_with_timeout([sys.executable, "-c", script], timeout_s=1)

    assert result.timed_out is True
    assert result.exit_code == timeouts.EXIT_TIMEOUT
    grandchild_pid = int(pid_file.read_text(encoding="utf-8"))
    assert _await_process_state(grandchild_pid, {_PROC_GONE}) == _PROC_GONE


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX timeout semantics")
def test_run_with_timeout_drains_noisy_pipe_on_timeout():
    script = """
import sys
import time

for _ in range(20000):
    print("x" * 100)
sys.stdout.flush()
time.sleep(30)
"""

    result = timeouts.run_with_timeout(
        [sys.executable, "-c", script],
        timeout_s=1,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert result.timed_out is True
    assert result.exit_code == timeouts.EXIT_TIMEOUT
    assert result.stdout


# ---------------------------------------------------------------------------
# w6: _kill_process_group must not crash on platforms without os.killpg.
#
# `preexec_fn=os.setsid` is POSIX-only, so the process is never placed in
# its own session on win32 either -- `os.killpg` doesn't exist there at all,
# and AttributeError was not in the (ProcessLookupError, PermissionError)
# catch. A per-cell timeout would crash the whole execute phase instead of
# classifying the cell timed-out. The fix is an up-front
# `hasattr(os, "killpg")` guard that falls back to proc.kill(). Exercised
# via monkeypatch.delattr (no skipif) -- deleting the attribute makes the
# hasattr guard take the fallback path on every CI platform, not just win32.
# ---------------------------------------------------------------------------


def test_kill_process_group_falls_back_to_proc_kill_without_os_killpg(monkeypatch):
    monkeypatch.delattr(timeouts.os, "killpg", raising=False)
    mock_proc = Mock(pid=12345)

    timeouts._kill_process_group(mock_proc)

    mock_proc.kill.assert_called_once()


def test_kill_process_group_uses_killpg_when_available(monkeypatch):
    """Sanity check the guard did not disturb the ordinary POSIX ladder."""
    sigterm = object()
    sigkill = object()
    calls: list[tuple[int, object]] = []

    def fake_killpg(pid, sig):
        calls.append((pid, sig))

    # raising=False so this also runs on win32, where os.killpg does not exist:
    # injecting it makes the hasattr guard take the POSIX branch, which is exactly
    # the ladder under test. A skipif here would drop that coverage instead.
    monkeypatch.setattr(timeouts.os, "killpg", fake_killpg, raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGTERM", sigterm, raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGKILL", sigkill, raising=False)
    mock_proc = Mock(pid=999)

    timeouts._kill_process_group(mock_proc)

    assert calls == [(999, sigterm), (999, sigkill)]
    mock_proc.kill.assert_not_called()


# ---------------------------------------------------------------------------
# uat-cell-teardown-orphans-child-processes-20260805 (w0/w1): a sweep
# cancellation is `SweepCancelled`, a `KeyboardInterrupt` subclass -- NOT an
# `Exception` -- so it used to propagate straight out of `communicate()`
# with the child untouched. Both branches of `run_with_timeout` now guard
# `communicate()` with `except BaseException: kill; raise`.
# ---------------------------------------------------------------------------


def test_run_with_timeout_kills_group_on_base_exception_before_reraising(monkeypatch):
    """A BaseException (e.g. SweepCancelled) raised while blocked in
    communicate() must trigger the group-kill ladder BEFORE it escapes
    run_with_timeout -- not just subprocess.TimeoutExpired."""

    class _Cancelled(KeyboardInterrupt):
        pass

    class FakeProc:
        pid = 4242
        returncode = None

        def communicate(self, timeout=None):
            raise _Cancelled("simulated sweep cancellation")

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    sigterm = object()
    sigkill = object()
    killpg_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(timeouts.subprocess, "Popen", lambda *a, **k: FakeProc())
    # raising=False so this also runs on win32, where os.killpg/SIGKILL do not
    # exist: injecting them makes the hasattr guard take the POSIX branch,
    # which is exactly the ladder under test -- same technique as
    # test_kill_process_group_uses_killpg_when_available above.
    monkeypatch.setattr(timeouts.os, "killpg", lambda pid, sig: killpg_calls.append((pid, sig)), raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGTERM", sigterm, raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGKILL", sigkill, raising=False)

    with pytest.raises(_Cancelled):
        timeouts.run_with_timeout([sys.executable, "-c", "pass"], timeout_s=5)

    # killpg fired (SIGTERM, then SIGKILL after the 200ms ladder sleep) before
    # the cancellation escaped -- proving the kill happens, not just that the
    # exception eventually propagates.
    assert killpg_calls[0] == (4242, sigterm)
    assert killpg_calls[-1] == (4242, sigkill)


def test_run_with_timeout_kills_group_on_a_non_keyboardinterrupt_base_exception(monkeypatch):
    """must_preserve: the guard is `except BaseException`, not `except KeyboardInterrupt`.

    Every other cancellation rung in this module raises a
    `KeyboardInterrupt` subclass, because that is what `SweepCancelled`
    actually is. That makes them all survive a narrowing of the guard from
    `BaseException` to `KeyboardInterrupt` -- the contract is asserted in the
    module comment above and in `run_with_timeout`'s docstring, but nothing
    tested it. This rung raises a `BaseException` that is deliberately NOT a
    `KeyboardInterrupt`, so a narrowed guard lets it escape with the child
    untouched and `killpg_calls` empty.

    Concretely reachable, not hypothetical: `GeneratorExit` and `SystemExit`
    are both plain `BaseException`s, and a `SystemExit` unwinding through a
    cell (an `atexit`-triggered teardown, a nested `sys.exit()`) must reap
    the group for the same reason a sweep cancellation must.
    """

    class _Unwound(BaseException):
        """Not a KeyboardInterrupt, not an Exception -- a bare BaseException."""

    class FakeProc:
        pid = 5150
        returncode = None

        def communicate(self, timeout=None):
            raise _Unwound("simulated non-KeyboardInterrupt unwind")

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    sigterm = object()
    sigkill = object()
    killpg_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(timeouts.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(timeouts.os, "killpg", lambda pid, sig: killpg_calls.append((pid, sig)), raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGTERM", sigterm, raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGKILL", sigkill, raising=False)

    with pytest.raises(_Unwound):
        timeouts.run_with_timeout([sys.executable, "-c", "pass"], timeout_s=5)

    assert killpg_calls, (
        "a BaseException that is not a KeyboardInterrupt escaped run_with_timeout without reaping the "
        "process group -- the guard has been narrowed from `except BaseException` and the child tree is "
        "orphaned on this path."
    )
    assert killpg_calls[0] == (5150, sigterm)
    assert killpg_calls[-1] == (5150, sigkill)


def test_timeout_path_drains_using_the_reap_timeout_constant(monkeypatch):
    """must_preserve: the post-SIGKILL drain must honour `_REAP_TIMEOUT_S`.

    `_REAP_TIMEOUT_S` was introduced for the reap in
    `_kill_and_reap_process_group` but the timeout path's own drain kept a
    hardcoded `1.0`. They were equal, so nothing observably differed -- which
    is exactly why it needed a rung: the next person to tune the constant
    would have moved one site and silently left the other behind. This pins
    that both follow the constant, by setting it to a value no literal in
    the module matches and asserting the drain used it.
    """
    monkeypatch.setattr(timeouts, "_REAP_TIMEOUT_S", 7.5)
    drain_timeouts: list[float | None] = []

    class FakeProc:
        pid = 6060
        returncode = -9

        def __init__(self) -> None:
            self._calls = 0

        def communicate(self, timeout=None):
            self._calls += 1
            if self._calls == 1:
                raise subprocess.TimeoutExpired(cmd="probe", timeout=timeout)
            drain_timeouts.append(timeout)
            return (b"", b"")

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(timeouts.subprocess, "Popen", lambda *a, **k: FakeProc())
    monkeypatch.setattr(timeouts.os, "killpg", lambda pid, sig: None, raising=False)
    # Inject the signals too, same technique and same reason as the two tests
    # above: on win32 `signal.SIGKILL` does not exist, and the ladder evaluates
    # it as an ARGUMENT to os.killpg, so patching killpg alone still raised
    # AttributeError before the call. Patching both keeps the POSIX branch --
    # the thing under test -- reachable on Windows rather than skipping it.
    monkeypatch.setattr(timeouts.signal, "SIGTERM", object(), raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGKILL", object(), raising=False)
    # The ladder's real 200 ms grace sleep is left in place: `timeouts` imports
    # `time` inside the function rather than at module scope, so there is no
    # module attribute to patch, and 200 ms is not worth reshaping the module for.

    result = timeouts.run_with_timeout([sys.executable, "-c", "pass"], timeout_s=1)

    assert result.timed_out
    assert drain_timeouts == [7.5], (
        f"the post-SIGKILL drain used {drain_timeouts!r} instead of the patched _REAP_TIMEOUT_S (7.5) -- "
        "it is back to a hardcoded literal, so tuning the constant no longer moves this site."
    )


def test_run_with_timeout_zero_timeout_kills_group_on_base_exception(monkeypatch):
    """The timeout_s == 0 branch must use the same guarded-kill Popen path as
    the timed branch, not the old bare subprocess.run with no teardown."""

    class _Cancelled(KeyboardInterrupt):
        pass

    class FakeProc:
        pid = 4343
        returncode = None

        def communicate(self, timeout=None):
            raise _Cancelled("simulated sweep cancellation")

        def kill(self):
            pass

        def wait(self, timeout=None):
            return 0

    sigterm = object()
    sigkill = object()
    killpg_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(timeouts.subprocess, "Popen", lambda *a, **k: FakeProc())
    # raising=False -- see the sibling timed-branch test above for why.
    monkeypatch.setattr(timeouts.os, "killpg", lambda pid, sig: killpg_calls.append((pid, sig)), raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGTERM", sigterm, raising=False)
    monkeypatch.setattr(timeouts.signal, "SIGKILL", sigkill, raising=False)

    with pytest.raises(_Cancelled):
        timeouts.run_with_timeout([sys.executable, "-c", "pass"], timeout_s=0)

    assert killpg_calls[0] == (4343, sigterm)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only kill ladder / SIGALRM")
def test_cancellation_kills_trapping_child_and_grandchild(tmp_path):
    """Production-path real-process proof: cancel a cell on the *timed*
    branch and neither the child nor its grandchild may survive.

    This is the capability the branch exists for, so every axis is the
    production one:

    * a positive `timeout_s`, not 0 -- a sweep can never reach the
      zero-timeout branch (`runner.run_cell` defaults `timeout_s=600`,
      `phases/execute.py` passes `config.execute.per_cell_timeout_s`, and
      `config.py` rejects `<= 0`), so a cancellation test pinned at 0 tests
      code no operator can run;
    * a real GRANDCHILD -- the direct child died on the pre-fix code too
      (`subprocess.run` kills it, `Popen` + `TimeoutExpired` at least left a
      handle); descendants are what leaked, so descendants are what the
      assertion has to be about;
    * a child that TRAPS SIGTERM, like the database servers a real cell
      spawns, so the group survives the grace window and the SIGKILL rung is
      actually exercised rather than skipped;
    * a "gone" check that cannot be satisfied by a zombie or by CPython's
      `Popen` finalizer -- see `_process_state`.
    """
    probe = _run_cancelled_probe(tmp_path, timeout_s=_PRODUCTION_LIKE_TIMEOUT_S)

    assert probe.sigterm_path.exists(), "SIGTERM rung never reached the child"
    assert _await_process_state(probe.grandchild_pid, {_PROC_GONE}) == _PROC_GONE
    assert _await_process_state(probe.child_pid, {_PROC_GONE}) == _PROC_GONE


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only kill ladder / SIGALRM")
def test_zero_timeout_cancellation_kills_trapping_child_and_grandchild(tmp_path):
    """Same proof for `timeout_s == 0`.

    Kept alongside the production-path test because it is the only thing
    that can see the zero-timeout branch regress: reverting it to the
    original bare `subprocess.run` leaves the direct child dead (that call
    has its own `except BaseException: process.kill()` and a context manager
    that `wait()`s) but never calls `setsid()` and never signals a group, so
    the grandchild survives.
    """
    probe = _run_cancelled_probe(tmp_path, timeout_s=0)

    assert probe.sigterm_path.exists(), "SIGTERM rung never reached the child"
    assert _await_process_state(probe.grandchild_pid, {_PROC_GONE}) == _PROC_GONE
    assert _await_process_state(probe.child_pid, {_PROC_GONE}) == _PROC_GONE


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only kill ladder / SIGALRM")
def test_kill_ladder_completes_sigkill_when_interrupted_during_grace(tmp_path):
    """A second signal inside the grace window must not drop the SIGKILL.

    An exception raised inside one `except` clause is not caught by a
    sibling `except` of the same `try`. So a cancellation landing in
    `_kill_process_group`'s 200 ms sleep used to unwind straight out of
    `run_with_timeout` with SIGTERM as the only signal ever delivered --
    and against a SIGTERM-trapping child (a database server running its own
    shutdown) that means nothing dies. Exactly the operator sequence that
    produces it: `kill` the sweep, see nothing exit, `kill` it again.

    The child is reaped here rather than polled for disappearance: this
    path deliberately skips `_kill_and_reap_process_group`'s `wait()` (the
    second signal unwinds through it), so the child is a zombie and
    `waitpid` can report *how* it died. `WTERMSIG == SIGKILL` is the direct
    assertion that the second rung ran.
    """
    probe = _run_cancelled_probe(tmp_path, timeout_s=_PRODUCTION_LIKE_TIMEOUT_S, deliveries=2)

    assert _await_process_state(probe.grandchild_pid, {_PROC_GONE}) == _PROC_GONE
    status = _reap(probe.child_pid)
    assert status is not None, "child was never reaped -- it outlived the interrupted ladder"
    assert os.WIFSIGNALED(status), f"child exited normally (status={status}) instead of being killed"
    assert os.WTERMSIG(status) == signal.SIGKILL


# ---------------------------------------------------------------------------
# Real-process probe + process-state helpers.
#
# `os.kill(pid, 0)` is the wrong predicate for teardown assertions and was
# duplicated verbatim in test_sweep_durability.py; both problems are fixed
# here and that module imports these.
# ---------------------------------------------------------------------------

_PROC_GONE = "gone"
_PROC_ZOMBIE = "zombie"
_PROC_LIVE = "live"

# Any positive value takes the same timed branch as the 600 s
# `execute.per_cell_timeout_s` default; small enough that a wedged probe
# fails the suite in seconds instead of stalling it for ten minutes.
_PRODUCTION_LIKE_TIMEOUT_S = 30

# Gate polling for the probe, bounded so nothing here can wait forever. The
# tick has to be short relative to `timeouts._KILL_GRACE_S`, because one of the
# gates is "the kill ladder has entered its grace window".
_PROBE_TICK_S = 0.02
_PROBE_MAX_TICKS = 500
_STATE_TIMEOUT_S = 5.0

# Minimum ratio of the product's grace window to the probe's tick period.
# The gate-2 delivery must land INSIDE the ladder's 200 ms grace window, and
# the only thing that guarantees it is the tick being much shorter than the
# window. That relationship was assumed, never asserted: shrink
# `timeouts._KILL_GRACE_S` (or lengthen the tick) far enough and the follow-up
# signal starts landing after the ladder has already finished. The probe would
# still deliver both signals and still pass -- while silently no longer
# exercising the interrupted-ladder path it exists to cover. Assert the margin
# statically so losing it fails loudly and immediately, with no timing flake.
_MIN_GRACE_TO_TICK_RATIO = 5.0


def test_cancel_probe_tick_leaves_margin_inside_the_kill_ladder_grace_window():
    """must_preserve: gate 2 is only meaningful while tick << grace window."""
    ratio = timeouts._KILL_GRACE_S / _PROBE_TICK_S
    assert ratio >= _MIN_GRACE_TO_TICK_RATIO, (
        f"the cancellation probe ticks every {_PROBE_TICK_S * 1000:.0f} ms against a "
        f"{timeouts._KILL_GRACE_S * 1000:.0f} ms kill-ladder grace window (ratio {ratio:.1f}, minimum "
        f"{_MIN_GRACE_TO_TICK_RATIO:.1f}). Gate 2's follow-up signal can no longer be relied on to land "
        "inside the grace window, so the interrupted-ladder tests would keep passing without exercising "
        "the path they exist to cover. Shorten _PROBE_TICK_S or restore the grace window."
    )


# Ignores SIGTERM, so its disappearance can only be the group SIGKILL rung.
_GRANDCHILD_SRC = "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(600)"

_CANCEL_PROBE_SRC = """
import os
import pathlib
import signal
import subprocess
import sys
import time

child_pid_path, grandchild_pid_path, sigterm_path, ready_path, grandchild_src = sys.argv[1:6]


def _trap_sigterm(signum, frame):
    # Acknowledge and survive, the way a database server runs its own
    # shutdown: the ladder must escalate to SIGKILL to end this process.
    pathlib.Path(sigterm_path).write_text("1", encoding="utf-8")


signal.signal(signal.SIGTERM, _trap_sigterm)

grandchild = subprocess.Popen([sys.executable, "-c", grandchild_src])
pathlib.Path(grandchild_pid_path).write_text(str(grandchild.pid), encoding="utf-8")
pathlib.Path(child_pid_path).write_text(str(os.getpid()), encoding="utf-8")
pathlib.Path(ready_path).write_text("1", encoding="utf-8")

while True:
    time.sleep(0.05)
"""


class _Cancelled(KeyboardInterrupt):
    """Stand-in for orchestrator.SweepCancelled: a BaseException, not an Exception."""


@dataclass(frozen=True)
class _ProbeOutcome:
    child_pid: int
    grandchild_pid: int
    sigterm_path: Path
    cancelled: pytest.ExceptionInfo[_Cancelled]


def _run_cancelled_probe(tmp_path: Path, *, timeout_s: int, deliveries: int = 1) -> _ProbeOutcome:
    """Cancel `run_with_timeout` around a real child that owns a grandchild.

    Cancellations are driven by a repeating interval timer whose handler
    no-ops until a *gate file* proves the target moment has arrived, rather
    than by a fixed `alarm(1)` that has to guess. Both gates are causal, so
    the test is not timing-tuned:

    * gate 1, `child.ready` -- the probe has spawned its grandchild and
      recorded both pids, so the cancellation is guaranteed to land while
      `run_with_timeout` is blocked in `communicate()` with a full
      descendant tree alive, on a loaded machine as well as an idle one;
    * gate 2, `child.sigterm` -- the child's SIGTERM trap has fired, i.e.
      the kill ladder has just entered its 200 ms grace window, which is
      exactly where a follow-up signal has to land.

    Gate 2 cannot be replaced by "N ms after gate 1": CPython's
    `Popen.wait()`/`communicate()` deliberately swallow the first
    `KeyboardInterrupt` and re-`_wait` for `_sigint_wait_secs` (0.25 s by
    default) before re-raising it (bpo-25942), so the first cancellation
    reaches `run_with_timeout`'s handler a quarter of a second late and a
    fixed follow-up interval lands back inside `communicate()` instead of
    inside the ladder.

    `_PROBE_MAX_TICKS` bounds the whole thing, so a probe that never
    reaches a gate fails the test instead of hanging it.
    """
    child_pid_path = tmp_path / "child.pid"
    grandchild_pid_path = tmp_path / "grandchild.pid"
    sigterm_path = tmp_path / "child.sigterm"
    ready_path = tmp_path / "child.ready"
    argv = [
        sys.executable,
        "-c",
        _CANCEL_PROBE_SRC,
        str(child_pid_path),
        str(grandchild_pid_path),
        str(sigterm_path),
        str(ready_path),
        _GRANDCHILD_SRC,
    ]
    gates = [ready_path, sigterm_path][:deliveries]
    counters = {"ticks": 0, "delivered": 0}

    def _on_alarm(signum: int, frame: object) -> None:
        counters["ticks"] += 1
        if counters["ticks"] >= _PROBE_MAX_TICKS:
            signal.setitimer(signal.ITIMER_REAL, 0)
            raise AssertionError(f"probe never reached gate {gates[counters['delivered']].name}")
        if not gates[counters["delivered"]].exists():
            return
        counters["delivered"] += 1
        if counters["delivered"] >= deliveries:
            signal.setitimer(signal.ITIMER_REAL, 0)
        raise _Cancelled("simulated sweep cancellation")

    assert len(gates) == deliveries, "no gate defined for that many deliveries"
    previous = signal.signal(signal.SIGALRM, _on_alarm)
    signal.setitimer(signal.ITIMER_REAL, _PROBE_TICK_S, _PROBE_TICK_S)
    try:
        with pytest.raises(_Cancelled) as cancelled:
            timeouts.run_with_timeout(argv, timeout_s=timeout_s)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)

    assert counters["delivered"] == deliveries
    return _ProbeOutcome(
        child_pid=int(child_pid_path.read_text(encoding="utf-8")),
        grandchild_pid=int(grandchild_pid_path.read_text(encoding="utf-8")),
        sigterm_path=sigterm_path,
        # Held deliberately. `cancelled` keeps the traceback alive, and with
        # it `run_with_timeout`'s `proc` local; drop it and CPython's
        # `Popen.__del__` reaps the child, so "pid gone" would pass for a
        # garbage-collection reason with nothing to do with the code under
        # test.
        cancelled=cancelled,
    )


def _process_state(pid: int) -> str:
    """Classify `pid` as gone / zombie / live.

    `os.kill(pid, 0)` on its own is not a teardown predicate: it succeeds
    for a `<defunct>` zombie, so it measures *reaping* rather than killing,
    and the reaper is often CPython's `Popen` finalizer rather than
    `timeouts.py`. Reading the state makes "terminated" and "still
    scheduled" distinguishable and makes a zombie an explicit third answer.
    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return _PROC_GONE
    except PermissionError:
        return _PROC_LIVE
    linux_stat = Path(f"/proc/{pid}/stat")
    try:
        raw = linux_stat.read_text(encoding="utf-8")
    except FileNotFoundError:
        return _bsd_process_state(pid)
    except OSError:
        return _PROC_LIVE
    # Field 3 is the state code; comm (field 2) is parenthesised and may
    # itself contain spaces, so split after the final ')'.
    fields = raw.rpartition(")")[2].split()
    return _PROC_ZOMBIE if fields and fields[0] == "Z" else _PROC_LIVE


def _bsd_process_state(pid: int) -> str:
    """macOS/BSD fallback: `ps` state code ('Z', 'Ss', 'S+', ...)."""
    try:
        completed = subprocess.run(
            ["ps", "-o", "state=", "-p", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return _PROC_LIVE
    state = completed.stdout.strip()
    if not state:
        return _PROC_GONE
    return _PROC_ZOMBIE if state.startswith("Z") else _PROC_LIVE


def _await_process_state(pid: int, accepted: set[str], *, timeout_s: float = _STATE_TIMEOUT_S) -> str:
    """Poll until `pid` reaches one of `accepted`, or `timeout_s` elapses."""
    deadline = time.monotonic() + timeout_s
    state = _process_state(pid)
    while state not in accepted and time.monotonic() < deadline:
        time.sleep(0.02)
        state = _process_state(pid)
    return state


def _reap(pid: int, *, timeout_s: float = _STATE_TIMEOUT_S) -> int | None:
    """`waitpid(WNOHANG)` until `pid` is collected; None if it never is."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            reaped, status = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            return None
        if reaped == pid:
            return status
        time.sleep(0.02)
    return None
