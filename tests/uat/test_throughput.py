from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from tests.uat.throughput import (
    TPC_ALLOWED_SCALE_FACTORS,
    resolve_official_result_path,
    validate_stream_count,
    validate_stream_success,
    validate_throughput_metric,
    validate_throughput_result,
)

pytestmark = pytest.mark.fast


def test_resolve_official_result_path_returns_none_without_emitted_path(tmp_path: Path):
    results_dir = tmp_path / "shared-runs" / "results"
    assert (
        resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=_dt.datetime.now())
        is None
    )


def test_resolve_official_result_path_accepts_absolute_emitted_path(tmp_path: Path):
    results_dir = tmp_path / "shared-runs" / "results"
    result_path = results_dir / "tpch_sf1_duckdb_sql_20260822_130141_a3f0c570.json"
    result_path.parent.mkdir(parents=True)
    result_path.write_text("{}", encoding="utf-8")

    out = resolve_official_result_path(
        results_dir,
        platform="duckdb",
        benchmark="tpch",
        started_after=_dt.datetime.now(),
        emitted_path=str(result_path),
    )
    assert out == result_path


def test_resolve_official_result_path_resolves_runs_relative_path(tmp_path: Path):
    results_dir = tmp_path / "shared-runs" / "results"
    results_dir.mkdir(parents=True)
    out = resolve_official_result_path(
        results_dir,
        platform="duckdb",
        benchmark="tpch",
        started_after=_dt.datetime.now(),
        emitted_path="results/tpch_sf1_duckdb_sql_20260822_130141_a3f0c570.json",
    )
    assert out == results_dir / "tpch_sf1_duckdb_sql_20260822_130141_a3f0c570.json"


def test_resolve_official_result_path_resolves_benchmark_runs_prefixed_path(tmp_path: Path):
    results_dir = tmp_path / "shared-runs" / "results"
    results_dir.mkdir(parents=True)
    out = resolve_official_result_path(
        results_dir,
        platform="duckdb",
        benchmark="tpch",
        started_after=_dt.datetime.now(),
        emitted_path="benchmark_runs/results/tpch_sf1_duckdb_sql_20260822_130141_a3f0c570.json",
    )
    assert out == tmp_path / "benchmark_runs" / "results" / "tpch_sf1_duckdb_sql_20260822_130141_a3f0c570.json"


def _result_json(
    *,
    streams: dict[int, int],
    throughput_at_size: float | None,
    failed_stream_ids: frozenset[int] = frozenset(),
    duration_ms: int = 1_000_000,
    scale_factor: float = 1.0,
) -> dict:
    queries = []
    for stream_id, count in streams.items():
        status = "FAILED" if stream_id in failed_stream_ids else "SUCCESS"
        for i in range(count):
            queries.append({"id": str(i + 1), "stream": stream_id, "status": status})
    payload: dict = {
        "benchmark": {"scale_factor": scale_factor},
        "phases": {"throughput_test": {"duration_ms": duration_ms}},
        "queries": queries,
        "summary": {},
    }
    if throughput_at_size is not None:
        payload["summary"]["tpc_metrics"] = {"throughput_at_size": throughput_at_size}
    return payload


def test_validate_throughput_result_accepts_correct_metric_and_rejects_old_formula():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=123.4)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is True
    assert reason == "ok"

    result["summary"]["tpc_metrics"]["throughput_at_size"] = 10.8
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "plausibility band" in reason


def test_validate_throughput_result_fails_on_stream_count_mismatch():
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=123.4)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "requested 3, executed 2" in reason


def test_validate_throughput_result_fails_on_missing_throughput_metric():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=None)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "Throughput@Size" in reason


def test_validate_throughput_result_fails_on_zero_throughput_metric():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=0)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "Throughput@Size" in reason


def test_validate_throughput_result_ignores_queries_without_stream_id():
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=100.0)
    result["queries"].append({"id": "99", "status": "SUCCESS"})
    ok, reason = validate_throughput_result(result, requested_streams=2)
    assert ok is True, reason


def test_validate_throughput_result_handles_empty_queries_list():
    ok, reason = validate_throughput_result({"queries": [], "summary": {}}, requested_streams=2)
    assert ok is False
    assert "requested 2, executed 0" in reason


def test_validate_throughput_result_rejects_all_queries_failed_stream():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=123.4, failed_stream_ids=frozenset({2}))
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "stream" in reason
    assert "[2]" in reason


def test_validate_stream_count_ignores_throughput_metric():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=None)
    ok, reason = validate_stream_count(result, requested_streams=3)
    assert ok is True
    assert reason == "ok"


def test_validate_stream_count_fails_on_mismatch():
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=None)
    ok, reason = validate_stream_count(result, requested_streams=3)
    assert ok is False
    assert "requested 3, executed 2" in reason


def test_validate_throughput_metric_ignores_stream_count():
    result = _result_json(streams={0: 22}, throughput_at_size=55.5)
    ok, reason = validate_throughput_metric(result)
    assert ok is True
    assert reason == "ok"


def test_validate_throughput_metric_fails_on_missing_metric():
    result = _result_json(streams={0: 22}, throughput_at_size=None)
    ok, reason = validate_throughput_metric(result)
    assert ok is False
    assert "Throughput@Size" in reason


def test_validate_throughput_result_composes_both_checks():
    result = _result_json(streams={0: 22}, throughput_at_size=None)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "stream count mismatch" in reason


def test_validate_throughput_result_composes_all_three_checks_stream_success_between_count_and_metric():
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=None, failed_stream_ids=frozenset({1}))
    ok, reason = validate_throughput_result(result, requested_streams=2)
    assert ok is False
    assert "SUCCESSFUL" in reason
    assert "Throughput@Size" not in reason


def test_validate_stream_success_ok_when_every_stream_has_a_success():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=None)
    ok, reason = validate_stream_success(result)
    assert ok is True
    assert reason == "ok"


def test_validate_stream_success_rejects_stream_with_zero_successful_queries():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=None, failed_stream_ids=frozenset({1}))
    ok, reason = validate_stream_success(result)
    assert ok is False
    assert "[1]" in reason
    assert "SUCCESSFUL" in reason


def test_validate_stream_success_rejects_multiple_all_failed_streams():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=None, failed_stream_ids=frozenset({1, 2}))
    ok, reason = validate_stream_success(result)
    assert ok is False
    assert "[1, 2]" in reason


def test_validate_stream_success_ok_when_stream_has_at_least_one_success_among_failures():
    result = _result_json(streams={0: 1}, throughput_at_size=None)
    result["queries"].append({"id": "2", "stream": 0, "status": "FAILED"})
    ok, reason = validate_stream_success(result)
    assert ok is True, reason


def test_validate_stream_success_is_case_insensitive_on_status():
    result = _result_json(streams={0: 1}, throughput_at_size=None)
    result["queries"][0]["status"] = "success"
    ok, reason = validate_stream_success(result)
    assert ok is True, reason


def test_validate_stream_success_ignores_queries_without_stream_id():
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=None)
    result["queries"].append({"id": "99", "status": "FAILED"})
    ok, reason = validate_stream_success(result)
    assert ok is True, reason


def test_validate_stream_success_handles_empty_queries_list():
    ok, reason = validate_stream_success({"queries": [], "summary": {}})
    assert ok is True
    assert reason == "ok"


def test_validate_stream_success_ignores_throughput_metric():
    result = _result_json(streams={0: 22}, throughput_at_size=None)
    ok, reason = validate_stream_success(result)
    assert ok is True
    assert reason == "ok"


def test_tpc_allowed_scale_factors_matches_run_official_constant():
    from benchbox.cli.commands.run_official import TPC_ALLOWED_SCALE_FACTORS as cli_constant

    assert cli_constant == TPC_ALLOWED_SCALE_FACTORS
