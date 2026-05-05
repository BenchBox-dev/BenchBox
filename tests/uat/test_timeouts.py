"""Fast-test coverage for tests/uat/timeouts.py.

Verifies the same exit-code semantics as the bash perl wrapper:
0 on success, child exit code on failure, 124 on timeout.
"""

from __future__ import annotations

import sys

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


def test_iter_argv_for_log_quotes_spaces():
    out = timeouts.iter_argv_for_log(["echo", "hello world"])
    assert out == "echo 'hello world'"


def test_env_with_path_only_drops_pythonpath(monkeypatch):
    monkeypatch.setenv("PYTHONPATH", "/some/path")
    monkeypatch.setenv("OTHER", "x")
    env = timeouts.env_with_path_only_pythonpath()
    assert "PYTHONPATH" not in env
    assert env["OTHER"] == "x"
