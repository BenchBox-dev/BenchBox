"""Fast-test coverage for tests/uat/timeouts.py."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
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
    child_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2.0
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _pid_exists(child_pid)


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
def test_run_with_timeout_zero_timeout_kills_real_child_on_cancellation(tmp_path):
    """Real-process proof for the timeout_s == 0 branch: a genuine spawned
    grandchild-capable child must not survive a BaseException landing while
    run_with_timeout blocks in communicate() -- a mocked communicate() could
    look correct while a real process kept running."""
    pid_file = tmp_path / "child.pid"
    script = f"""
import pathlib
import os
import time

pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()), encoding="utf-8")
time.sleep(30)
"""

    class _Cancelled(KeyboardInterrupt):
        pass

    def _raise_cancel(signum, frame):
        raise _Cancelled("simulated sweep cancellation")

    previous = signal.signal(signal.SIGALRM, _raise_cancel)
    signal.alarm(1)
    try:
        with pytest.raises(_Cancelled):
            timeouts.run_with_timeout([sys.executable, "-c", script], timeout_s=0)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    child_pid = int(pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2.0
    while _pid_exists(child_pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _pid_exists(child_pid)


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
