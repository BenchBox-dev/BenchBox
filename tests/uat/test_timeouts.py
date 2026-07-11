"""Fast-test coverage for tests/uat/timeouts.py."""

from __future__ import annotations

import os
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
    calls: list[tuple[int, int]] = []

    def fake_killpg(pid, sig):
        calls.append((pid, sig))

    monkeypatch.setattr(timeouts.os, "killpg", fake_killpg)
    mock_proc = Mock(pid=999)

    timeouts._kill_process_group(mock_proc)

    assert calls == [(999, timeouts.signal.SIGTERM), (999, timeouts.signal.SIGKILL)]
    mock_proc.kill.assert_not_called()


def test_iter_argv_for_log_quotes_spaces():
    out = timeouts.iter_argv_for_log(["echo", "hello world"])
    assert out == "echo 'hello world'"


def test_env_without_pythonpath_drops_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/some/path")
    monkeypatch.setenv("OTHER", "x")
    env = timeouts.env_without_pythonpath()
    assert "PYTHONPATH" not in env
    assert env["OTHER"] == "x"


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
