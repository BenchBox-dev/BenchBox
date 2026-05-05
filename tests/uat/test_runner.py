"""Fast-test coverage for tests/uat/runner.py."""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import runner

pytestmark = pytest.mark.fast


def test_extract_result_path_picks_last_match():
    log = """\
[info] running...
benchmark_runs/results/duckdb_tpch_20260502.json
[trace] retry...
/Users/joe/Developer/benchmark_runs/results/duckdb_tpch_20260502_FINAL.json
[done]
"""
    out = runner.extract_result_path(log)
    assert out is not None
    assert out.endswith("FINAL.json")


def test_extract_result_path_returns_none_when_missing():
    log = "[info] running\n[error] failed before result capture\n"
    assert runner.extract_result_path(log) is None


def test_run_cell_writes_log_and_returns_result(tmp_path: Path):
    """Drive run_cell against a stub `benchbox run` (here: python -c)."""
    fake_argv = [
        sys.executable,
        "-c",
        "print('benchmark_runs/results/duckdb_tpch_smoke.json')",
    ]
    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            now=_dt.datetime(2026, 5, 5, 12, 0, 0),
        )

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.result_path is not None
    assert str(result.result_path).endswith("duckdb_tpch_smoke.json")
    assert result.log_path.exists()
    log_text = result.log_path.read_text()
    assert "benchmark_runs/results/" in log_text


def test_run_cell_marks_failure(tmp_path: Path):
    fake_argv = [sys.executable, "-c", "import sys; sys.exit(2)"]
    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)
    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.result_path is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX timeout semantics")
def test_run_cell_marks_timeout(tmp_path: Path):
    fake_argv = [sys.executable, "-c", "import time; time.sleep(3)"]
    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=1, log_dir=tmp_path)
    assert result.status == "timed-out"
    assert result.exit_code == 124  # EXIT_TIMEOUT


def test_default_log_dir_honours_benchbox_output_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path))
    out = runner._default_log_dir(_dt.datetime(2026, 5, 5))
    assert out == tmp_path / "logs" / "uat_20260505"
