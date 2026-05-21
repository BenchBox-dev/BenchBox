"""Fast-test coverage for tests/uat/timeouts.py."""

from __future__ import annotations

import os
import subprocess
import sys
import time

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
