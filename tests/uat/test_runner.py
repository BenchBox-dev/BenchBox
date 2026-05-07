"""Fast-test coverage for tests/uat/runner.py."""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import runner
from tests.uat.timeouts import TimeoutResult

pytestmark = pytest.mark.fast


def _write_result_json(path: Path, *, failed: int = 0, compliance_class: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = 1 if failed == 0 else 0
    payload = {
        "version": "2.1",
        "run": {
            "id": "uat-test",
            "timestamp": "2026-01-01T00:00:00",
            "total_duration_ms": 1,
            "query_time_ms": 1,
            "iterations": 1,
            "streams": 1,
        },
        "benchmark": {
            "id": "tpch",
            "name": "TPC-H",
            "scale_factor": 0.01,
            "test_type": "power",
        },
        "platform": {"name": "DuckDB"},
        "summary": {
            "queries": {"total": 1, "passed": passed, "failed": failed},
            "validation": {"status": "passed" if failed == 0 else "failed"},
        },
        "queries": [{"id": "Q1", "status": "SUCCESS" if failed == 0 else "ERROR", "execution_time_ms": 1}],
        "phases": {},
    }
    if compliance_class is not None:
        payload["benchmark"]["compliance_class"] = compliance_class
    path.write_text(json.dumps(payload), encoding="utf-8")


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


def test_extract_result_path_accepts_custom_runs_root():
    log = "/tmp/shared-runs/results/duckdb_tpch_custom_root.json\n"
    assert runner.extract_result_path(log) == "/tmp/shared-runs/results/duckdb_tpch_custom_root.json"


def test_extract_result_path_returns_none_when_missing():
    log = "[info] running\n[error] failed before result capture\n"
    assert runner.extract_result_path(log) is None


def test_run_cell_writes_log_and_returns_result(tmp_path: Path):
    """Drive run_cell against a stub `benchbox run` (here: python -c)."""
    result_path = tmp_path / "benchmark_runs" / "results" / "duckdb_tpch_smoke.json"
    _write_result_json(result_path)
    fake_argv = [
        sys.executable,
        "-c",
        f"print({str(result_path)!r})",
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


def test_run_cell_sets_benchbox_output_dir_for_subprocess(tmp_path: Path):
    result_path = tmp_path / "shared-runs" / "results" / "duckdb_tpch_env.json"
    _write_result_json(result_path)
    fake_argv = [sys.executable, "-c", "print('unused')"]
    captured = {}

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        captured["env"] = env
        captured["argv"] = argv
        if stdout is not None:
            stdout.write(f"{result_path}\n")
        return TimeoutResult(exit_code=0, timed_out=False, elapsed_s=0.1)

    def fake_benchbox_run_argv(*args, extra_args=(), **kwargs):
        return [*fake_argv, *extra_args]

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            benchmark_runs_dir=tmp_path / "shared-runs",
            now=_dt.datetime(2026, 5, 5, 12, 0, 0),
        )

    assert result.status == "passed"
    assert result.result_path == result_path
    assert captured["env"]["BENCHBOX_OUTPUT_DIR"] == str(tmp_path / "shared-runs")
    assert captured["argv"][-2:] == ["--output", str(tmp_path / "shared-runs" / "datagen")]
    assert "BENCHBOX_OUTPUT_DIR=" in result.log_path.read_text()


def test_run_cell_defaults_benchbox_output_dir_to_shared(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
    fake_argv = [sys.executable, "-c", "print('unused')"]
    captured = {}

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        captured["env"] = env
        return TimeoutResult(exit_code=0, timed_out=False, elapsed_s=0.1)

    with (
        patch.object(runner, "benchbox_run_argv", return_value=fake_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            now=_dt.datetime(2026, 5, 5, 12, 0, 0),
        )

    assert captured["env"]["BENCHBOX_OUTPUT_DIR"] == str(Path.home() / "Developer" / "benchmark_runs")


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


def test_classify_for_submit_vocabulary_and_clean_result(tmp_path: Path):
    result_path = tmp_path / "benchmark_runs" / "results" / "clean.json"
    _write_result_json(result_path)

    assert runner.classify_for_submit(result_path) is runner.SubmitTerminalState.submittable
    assert set(runner.SubmitTerminalState.__members__) == {
        "submittable",
        "unofficial",
        "query_failure",
        "schema_violation",
        "missing_manifest",
    }


def test_classify_for_submit_marks_query_failure_and_run_cell_failed(tmp_path: Path):
    result_path = tmp_path / "benchmark_runs" / "results" / "failed-query.json"
    _write_result_json(result_path, failed=1)
    fake_argv = [sys.executable, "-c", f"print({str(result_path)!r})"]

    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert runner.classify_for_submit(result_path) is runner.SubmitTerminalState.query_failure
    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.submit_terminal_state == "query_failure"


def test_classify_for_submit_keeps_unofficial_as_passed_cell(tmp_path: Path):
    result_path = tmp_path / "benchmark_runs" / "results" / "unofficial.json"
    _write_result_json(result_path, compliance_class="unofficial_subscale")
    fake_argv = [sys.executable, "-c", f"print({str(result_path)!r})"]

    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpcds", 0.01, timeout_s=10, log_dir=tmp_path)

    assert runner.classify_for_submit(result_path) is runner.SubmitTerminalState.unofficial
    assert result.status == "passed"
    assert result.submit_terminal_state == "unofficial"
