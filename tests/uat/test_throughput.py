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
    validate_stream_success,
    validate_throughput_metric,
    validate_throughput_result,
)

pytestmark = pytest.mark.fast


# ``resolve_official_result_path`` filters candidates by ``st_mtime >=
# started_after``. Capturing ``started_after = datetime.now()`` immediately
# before writing the fixture file is racy: filesystem mtime granularity (or a
# small backward NTP step between the two calls) can floor the written file's
# mtime just *below* ``started_after``, dropping the file and returning None
# (observed as a one-off CI flake). Backdating ``started_after`` by a slack
# margin makes the boundary robust without weakening any test's intent -- the
# "ignores older files" case backdates its stale file by a full hour, well
# outside this margin.
_MTIME_SLACK = _dt.timedelta(seconds=2)


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
    started = _dt.datetime.now() - _MTIME_SLACK
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
    started = _dt.datetime.now() - _MTIME_SLACK
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
    started = _dt.datetime.now() - _MTIME_SLACK
    match = results_dir / "tpch_sf1_pg_duckdb_sql_20260709.json"
    match.write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="pg-duckdb", benchmark="tpch", started_after=started)
    assert out == match


def test_resolve_official_result_path_duckdb_does_not_match_pg_duckdb_file(tmp_path: Path):
    """Regression: the old substring glob (`*{platform_token}*`) let platform="duckdb" match a
    `pg_duckdb` result file because "duckdb" is a substring of "pg_duckdb". Token-exact matching
    must reject it -- this is the collision direction the pre-existing test above didn't cover
    (it only asserted the *positive* pg-duckdb match, not that plain duckdb excludes it).
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    (results_dir / "tpch_sf1_pg_duckdb_sql_20260709_223304_deadbeef.json").write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=started)
    assert out is None


def test_resolve_official_result_path_pg_duckdb_does_not_match_plain_duckdb_file(tmp_path: Path):
    """Reverse collision direction: platform="pg-duckdb" must not resolve a plain `duckdb` file."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    (results_dir / "tpch_sf1_duckdb_sql_20260709_223304_0865bb91.json").write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="pg-duckdb", benchmark="tpch", started_after=started)
    assert out is None


def test_resolve_official_result_path_matches_multi_token_benchmark(tmp_path: Path):
    """Regression (C1): registry ids like `tpcds_obt`/`tsbs_devops` split into MULTIPLE
    `_`-tokens, so a matcher that hardcoded benchmark=token[0]/scale=token[1] shifted every
    index and returned None for a real `tpcds_obt_sf1_duckdb_sql_*.json` file -- a NEW
    false-negative worse than the substring false-positive it replaced (a None result
    downgrades a passing official cell to FAILED). The benchmark must match as a token
    *prefix sequence*, with scale/platform offsets derived from its length.
    """
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    match = results_dir / "tpcds_obt_sf1_duckdb_sql_20260709_223304_abcdabcd.json"
    match.write_text("{}", encoding="utf-8")
    # A pg_duckdb file for the same multi-token benchmark must NOT collide with plain duckdb.
    (results_dir / "tpcds_obt_sf1_pg_duckdb_sql_20260709_223304_deadbeef.json").write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(
        results_dir, platform="duckdb", benchmark="tpcds_obt", started_after=started, scale=1
    )
    assert out == match


def test_resolve_official_result_path_multi_token_benchmark_without_scale(tmp_path: Path):
    """The multi-token benchmark prefix + platform-token match holds even when `scale` is omitted."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    match = results_dir / "tsbs_devops_sf1_duckdb_sql_20260709_223304_abcdabcd.json"
    match.write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="duckdb", benchmark="tsbs_devops", started_after=started)
    assert out == match


def test_resolve_official_result_path_filters_by_scale_when_given(tmp_path: Path):
    """`scale` (optional, keyword) narrows candidates to the matching sf<N> token."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    sf1 = results_dir / "tpch_sf1_duckdb_sql_20260709_223304_aaaaaaaa.json"
    sf10 = results_dir / "tpch_sf10_duckdb_sql_20260709_223304_bbbbbbbb.json"
    sf1.write_text("{}", encoding="utf-8")
    sf10.write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=started, scale=1)
    assert out == sf1
    out10 = resolve_official_result_path(
        results_dir, platform="duckdb", benchmark="tpch", started_after=started, scale=10
    )
    assert out10 == sf10


def test_resolve_official_result_path_ignores_scale_when_omitted(tmp_path: Path):
    """Backward compatibility: existing callers that don't pass `scale` are unaffected by SF."""
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    sf1 = results_dir / "tpch_sf1_duckdb_sql_20260709_223304_aaaaaaaa.json"
    sf1.write_text("{}", encoding="utf-8")
    out = resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=started)
    assert out == sf1


def test_resolve_official_result_path_breaks_equal_mtime_ties_deterministically(tmp_path: Path):
    """Equal-mtime candidates (within filesystem mtime granularity) must resolve to the same file
    on every call, not whatever order the filesystem/glob happens to yield -- the arbitrary
    max-mtime tie-break this test guards used to depend on iteration order when mtimes tied.
    """
    import os

    results_dir = tmp_path / "results"
    results_dir.mkdir()
    started = _dt.datetime.now() - _MTIME_SLACK
    file_a = results_dir / "tpch_sf1_duckdb_sql_20260709_223304_aaaaaaaa.json"
    file_z = results_dir / "tpch_sf1_duckdb_sql_20260709_223304_zzzzzzzz.json"
    file_a.write_text("{}", encoding="utf-8")
    file_z.write_text("{}", encoding="utf-8")
    same_time = _dt.datetime.now().timestamp()
    os.utime(file_a, (same_time, same_time))
    os.utime(file_z, (same_time, same_time))

    results = {
        resolve_official_result_path(results_dir, platform="duckdb", benchmark="tpch", started_after=started)
        for _ in range(5)
    }
    assert len(results) == 1, "tie-break must be deterministic across repeated calls"
    assert results == {file_z}, "tie-break must prefer the lexicographically-greater filename"


# ---------------------------------------------------------------------------
# validate_throughput_result
# ---------------------------------------------------------------------------


def _result_json(
    *,
    streams: dict[int, int],
    throughput_at_size: float | None,
    failed_stream_ids: frozenset[int] = frozenset(),
    duration_ms: int = 1_000_000,
    scale_factor: float = 1.0,
) -> dict:
    """Build a minimal result JSON with `queries[]` covering the given streams.

    ``streams`` maps stream id -> number of queries executed on that stream.
    ``failed_stream_ids`` marks streams whose queries should all carry status
    "FAILED" instead of "SUCCESS" -- used to exercise
    ``validate_stream_success``'s all-queries-failed rejection without
    affecting every other test's SUCCESS-only fixtures.
    """
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
    """A malformed/legacy query row with no `stream` key must not count as a phantom stream."""
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=100.0)
    result["queries"].append({"id": "99", "status": "SUCCESS"})  # no "stream" key
    ok, reason = validate_throughput_result(result, requested_streams=2)
    assert ok is True, reason


def test_validate_throughput_result_handles_empty_queries_list():
    ok, reason = validate_throughput_result({"queries": [], "summary": {}}, requested_streams=2)
    assert ok is False
    assert "requested 2, executed 0" in reason


def test_validate_throughput_result_rejects_all_queries_failed_stream():
    """A stream with rows but zero SUCCESSFUL queries must be REJECTED even
    though the stream-count check alone would pass (all 3 streams present)."""
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=123.4, failed_stream_ids=frozenset({2}))
    ok, reason = validate_throughput_result(result, requested_streams=3)
    assert ok is False
    assert "stream" in reason
    assert "[2]" in reason


# ---------------------------------------------------------------------------
# validate_stream_count / validate_stream_success / validate_throughput_metric
# (split checks)
#
# Split so a caller (e.g. nightly CI) can hard-gate on stream-count wiring
# independent of per-stream success and of the Throughput@Size metric -- see
# the HISTORICAL NOTE on validate_throughput_metric for the now-fixed (#1142)
# TPC-H non-deterministic-query validation gap this split was originally
# designed to isolate.
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


def test_validate_throughput_result_composes_all_three_checks_stream_success_between_count_and_metric():
    """A stream-success failure is reported ahead of a same-run throughput-metric failure,
    but only once the stream-count check itself has passed."""
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=None, failed_stream_ids=frozenset({1}))
    ok, reason = validate_throughput_result(result, requested_streams=2)
    assert ok is False
    assert "SUCCESSFUL" in reason
    assert "Throughput@Size" not in reason


# ---------------------------------------------------------------------------
# validate_stream_success
# ---------------------------------------------------------------------------


def test_validate_stream_success_ok_when_every_stream_has_a_success():
    result = _result_json(streams={0: 22, 1: 22, 2: 22}, throughput_at_size=None)
    ok, reason = validate_stream_success(result)
    assert ok is True
    assert reason == "ok"


def test_validate_stream_success_rejects_stream_with_zero_successful_queries():
    """Core regression case: a stream with rows but every query FAILED must be REJECTED,
    even though validate_stream_count alone would count it as "executed"."""
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
    """A stream with a mix of failed and successful queries -- not ALL failed -- must pass:
    this check only rejects a stream that is 100% failed, matching the "zero SUCCESSFUL
    queries" contract, not a general per-query success-rate gate."""
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
    """A malformed/legacy query row with no `stream` key must not be treated as its own
    (trivially failing) stream."""
    result = _result_json(streams={0: 22, 1: 22}, throughput_at_size=None)
    result["queries"].append({"id": "99", "status": "FAILED"})  # no "stream" key
    ok, reason = validate_stream_success(result)
    assert ok is True, reason


def test_validate_stream_success_handles_empty_queries_list():
    """No streams observed at all -- vacuously true; validate_stream_count is the check
    responsible for catching a missing/empty run."""
    ok, reason = validate_stream_success({"queries": [], "summary": {}})
    assert ok is True
    assert reason == "ok"


def test_validate_stream_success_ignores_throughput_metric():
    """Stream-success check passes even when Throughput@Size is absent (it's not its job)."""
    result = _result_json(streams={0: 22}, throughput_at_size=None)
    ok, reason = validate_stream_success(result)
    assert ok is True
    assert reason == "ok"


# ---------------------------------------------------------------------------
# TPC_ALLOWED_SCALE_FACTORS
# ---------------------------------------------------------------------------


def test_tpc_allowed_scale_factors_matches_run_official_constant():
    """Mirrors run_official.py's own constant; catch drift if the CLI's changes."""
    from benchbox.cli.commands.run_official import TPC_ALLOWED_SCALE_FACTORS as cli_constant

    assert cli_constant == TPC_ALLOWED_SCALE_FACTORS
