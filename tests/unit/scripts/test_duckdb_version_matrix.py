"""Unit tests for the operator-run DuckDB version-matrix helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import analyze_duckdb_version_matrix as analyzer, run_duckdb_version_matrix as matrix

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_prerelease_detection_covers_dev_and_stable_versions() -> None:
    assert matrix._is_prerelease("1.6.0.dev365") is True
    assert matrix._is_prerelease("1.5.5") is False


def test_matrix_uses_sf10_for_all_four_workloads() -> None:
    assert matrix.BENCHMARKS == (("tpch", 10.0), ("tpcds", 10.0), ("clickbench", 10.0), ("ssb", 10.0))


def test_benchbox_command_uses_package_option_for_stable_versions() -> None:
    command = matrix._benchbox_command(phase="power", benchmark="tpch", scale=10.0, version="1.5.5")

    assert command[command.index("--platform") + 1] == "duckdb"
    assert command[-2:] == ["--platform-option", "driver_version=1.5.5"]


def test_benchbox_command_omits_driver_option_for_dev_versions() -> None:
    command = matrix._benchbox_command(phase="power", benchmark="tpch", scale=10.0, version="1.6.0.dev365")

    assert "--platform-option" not in command


def test_dry_run_does_not_require_a_log_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, output, elapsed = matrix._run_command(
        ["command-that-is-not-run"],
        cwd=tmp_path,
        env={},
        log_path=tmp_path / "missing" / "matrix.log",
        dry_run=True,
    )

    assert (status, output, elapsed) == (0, "", 0.0)
    assert "$ command-that-is-not-run" in capsys.readouterr().out


def test_find_result_path_accepts_relative_path(tmp_path: Path) -> None:
    result = tmp_path / "results" / "run.json"
    result.parent.mkdir()
    result.write_text("{}", encoding="utf-8")

    assert matrix._find_result_path("ignored\nresults/run.json\n", cwd=tmp_path) == result.resolve()


def test_run_command_uses_repository_monotonic_clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    elapsed_starts: list[float] = []
    monkeypatch.setattr(matrix, "mono_time", lambda: 10.0)
    monkeypatch.setattr(matrix, "elapsed_seconds", lambda started: elapsed_starts.append(started) or 2.5)
    monkeypatch.setattr(
        matrix.subprocess,
        "run",
        lambda *args, **kwargs: type("Completed", (), {"returncode": 0, "stdout": "", "stderr": ""})(),
    )

    status, output, elapsed = matrix._run_command(
        ["command-that-runs"],
        cwd=tmp_path,
        env={},
        log_path=tmp_path / "matrix.log",
        dry_run=False,
    )

    assert (status, output, elapsed) == (0, "", 2.5)
    assert elapsed_starts == [10.0]


def _matrix_payload(run_id: str, total_ms: float, query_ms: float) -> dict:
    return {
        "export": {"anonymized": True},
        "run": {"id": run_id, "query_time_ms": total_ms, "total_duration_ms": total_ms + 100},
        "summary": {
            "data": {"load_time_ms": total_ms + 10, "rows_loaded": 10},
            "queries": {"failed": 0, "passed": 1, "total": 1},
            "timing": {"avg_ms": query_ms, "total_ms": total_ms},
            "tpc_metrics": {"power_at_size": 1000 / total_ms},
            "validation": "passed",
        },
        "queries": [
            {"id": "1", "iter": 0, "ms": 99.0, "run_type": "warmup", "status": "SUCCESS", "stream": 0},
            {"id": "1", "iter": 1, "ms": query_ms, "run_type": "measurement", "status": "SUCCESS", "stream": 0},
        ],
    }


def test_aggregate_payloads_medians_measurements_and_run_metrics() -> None:
    aggregate = analyzer.aggregate_payloads(
        [_matrix_payload("one", 30.0, 3.0), _matrix_payload("two", 10.0, 1.0), _matrix_payload("three", 20.0, 2.0)],
        version="1.5.5",
        benchmark="tpch",
    )

    assert aggregate["run"]["id"] != "one"
    assert aggregate["run"]["query_time_ms"] == 20.0
    assert aggregate["run"]["total_duration_ms"] == 120.0
    assert aggregate["summary"]["timing"] == {"avg_ms": 2.0, "total_ms": 20.0}
    assert aggregate["summary"]["data"]["load_time_ms"] == 30.0
    assert aggregate["summary"]["tpc_metrics"]["power_at_size"] == 50.0
    assert [query["ms"] for query in aggregate["queries"]] == [99.0, 2.0]
    assert aggregate["export"]["aggregation"] == {
        "method": "median",
        "repetitions": 3,
        "source_run_ids": ["one", "two", "three"],
    }
