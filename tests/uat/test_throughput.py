"""Fast-test coverage for tests/uat/throughput.py.

Covers the two pieces a `run-official --streams N`-backed UAT cell needs
that a `--quiet` `benchbox run` cell gets for free (see the module
docstring in tests/uat/throughput.py): locating the result JSON on disk,
and validating a throughput result against the requested stream count.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from tests.uat.throughput import (
    TPC_ALLOWED_SCALE_FACTORS,
    resolve_official_result_path,
    validate_stream_count,
    validate_throughput_metric,
    validate_throughput_result,
)

pytestmark = pytest.mark.fast


# ---------------------------------------------------------------------------
# resolve_official_result_path
# ---------------------------------------------------------------------------


def test_resolve_official_result_path_returns_none_for_missing_dir(tmp_path: Path):
    missing = tmp_path / "results"
    assert (
        resolve_official_result_path(missing, platform="duckdb", benchmark="tpch", started_after=_dt.datetime.now())
        is None
    )


def test_resolve_official_result_path_returns_none_when_no_candidates(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    (results_dir / "tpcds_sf1_duckdb_sql_unrelated.json").write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(
        results_dir, platform="duckdb", benchmark="tpch", started_after=_dt.datetime.now()
    )
    assert out is None


def test_resolve_official_result_path_matches_platform_and_benchmark(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now()
    match = results_dir / "tpch_sf1_duckdb_sql_20260709_223304_0865bb91.json"
    match.write_text("{}", encoding="utf-8")
    # A same-timestamp but different-platform file must not match.
    (results_dir / "tpch_sf1_postgresql_sql_20260709_223304_deadbeef.json").write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=started)
    assert out == match


def test_resolve_official_result_path_ignores_files_older_than_started_after(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    stale = results_dir / "tpch_sf1_duckdb_sql_stale.json"
    stale.write_text("{}", encoding="utf-8")
    # Backdate the stale file's mtime well before "started_after".
    import os

    old_time = (_dt.datetime.now() - _dt.timedelta(hours=1)).timestamp()
    os.utime(stale, (old_time, old_time))
    out = resolve_official_result_path(
        results_dir, platform="duckdb", benchmark="tpch", started_after=_dt.datetime.now()
    )
    assert out is None


def test_resolve_official_result_path_picks_newest_of_multiple_candidates(tmp_path: Path):
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now()
    older = results_dir / "tpch_sf1_duckdb_sql_older.json"
    newer = results_dir / "tpch_sf1_duckdb_sql_newer.json"
    older.write_text("{}", encoding="utf-8")
    newer.write_text("{}", encoding="utf-8")
    import os
    import time

    time.sleep(0.01)
    now = _dt.datetime.now().timestamp()
    os.utime(newer, (now, now))
    out = resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=started)
    assert out == newer


def test_resolve_official_result_path_is_case_and_dash_insensitive(tmp_path: Path):
    """Platform tokens with dashes (e.g. `pg-duckdb`) normalize like the CLI's own output filenames."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now()
    match = results_dir / "tpch_sf1_pg_duckdb_sql_20260709.json"
    match.write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="pg-duckdb", benchmark="tpch", started_after=started)
    assert out == match


# ---------------------------------------------------------------------------
# validate_throughput_result
# ---------------------------------------------------------------------------


def _result_json(*, streams: dict[int, int], throughput_at_size: float | None) -> dict:
    """Build a minimal result JSON with `queries[]` covering the given streams.

    ``streams`` maps stream id -> number of queries executed on that stream.
    """
    queries = []
    for stream_id, count in streams.items():
        for i in range(count):
            queries.append({"id": str(i + 1), "stream": stream_id, "status": "SUCCESS"})
    payload: dict = {"queries": queries, "summary": {}}
    if throughput_at_size is not None:
        payload["summary"]["tpc_metrics"] = {"throughput_at_size": throughput_at_size}
    return payload


def test_validate_throughput_result_ok_on_clean_pass():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=123.4)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is True
    assert reason == "ok"


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
    """A malformed/legacy query row with no `stream` key must not count as a phantom stream."""
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=100.0)
    result["queries"].append({"id": "99", "status": "SUCCESS"})  # no "stream" key
    ok, reason = validate_throughput_result(result, requested_streams=2)
    assert ok is True, reason


def test_validate_throughput_result_handles_empty_queries_list():
    ok, reason = validate_throughput_result({"queries": [], "summary": {}}, requested_streams=2)
    assert ok is False
    assert "requested 2, executed 0" in reason


# ---------------------------------------------------------------------------
# validate_stream_count / validate_throughput_metric (split checks)
#
# Split so a caller (e.g. nightly CI) can hard-gate on stream-count wiring
# independent of the Throughput@Size metric -- see the tracked, pre-existing
# TPC-H non-deterministic-query validation gap documented on
# validate_throughput_metric.
# ---------------------------------------------------------------------------


def test_validate_stream_count_ignores_throughput_metric():
    """Stream-count check passes even when Throughput@Size is absent."""
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
    """Throughput-metric check passes even with a stream-count mismatch (it's not its job)."""
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
    """validate_throughput_result short-circuits on the stream-count check first."""
    result = _result_json(streams={0: 22}, throughput_at_size=None)
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    # Stream-count failure reported, not the (also-failing) throughput metric.
    assert "stream count mismatch" in reason


# ---------------------------------------------------------------------------
# TPC_ALLOWED_SCALE_FACTORS
# ---------------------------------------------------------------------------


def test_tpc_allowed_scale_factors_matches_run_official_constant():
    """Mirrors run_official.py's own constant; catch drift if the CLI's changes."""
    from benchbox.cli.commands.run_official import TPC_ALLOWED_SCALE_FACTORS as cli_constant

    assert cli_constant == TPC_ALLOWED_SCALE_FACTORS
