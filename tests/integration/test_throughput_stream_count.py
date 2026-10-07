# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Regression tests: a user-requested concurrent stream count reaches the throughput driver.

Before this fix, the throughput drivers in
``benchbox/platforms/base/execution.py`` (``_execute_tpch_throughput_test`` /
``_execute_tpcds_throughput_test``) only read the legacy ``num_streams`` /
``streams`` ``run_config`` keys, never ``concurrent_streams`` -- the field
``RunConfig`` actually populates from ``BenchmarkConfig.concurrency`` (see
``benchbox/core/schemas.py`` and ``benchbox/core/runner/runner.py:726``). So a
user-requested stream count silently never reached execution: every
throughput run silently executed the driver's own hardcoded default of 2
streams instead, regardless of what was requested.

Two independent breaks fed this defect:

1. ``benchbox/platforms/base/execution.py`` never mapped ``concurrent_streams``
   at the driver boundary (fixed here via the shared
   ``_resolve_requested_stream_count`` helper).
2. ``run-official --streams N`` validated and printed the value but never
   forwarded it anywhere (fixed by passing it to ``run`` as ``concurrency``
   in ``benchbox/cli/commands/run_official.py``).

Follow-up (review): mapping ``concurrent_streams`` straight through initially
introduced a second regression -- ``BenchmarkConfig.concurrency`` defaults to
1, and the real pipeline (``benchbox/core/runner/runner.py``) *always*
spreads it into ``run_config`` as ``concurrent_streams=1``, so the canonical
"no stream count requested" default silently dropped from 2 streams to 1.
Because a resolved count of 1 is indistinguishable from "unset" at this
boundary, ``_resolve_requested_stream_count`` now floors its result to the
TPC throughput minimum of 2 (see its docstring in ``execution.py``). The
tests below assert that floor directly, using a run_config dict shaped the
way the real pipeline actually produces one (not a hand-built dict missing
keys the real pipeline always sets).

The tests below drive the real (file-based) DuckDB adapter with a genuine,
tiny TPC-H/TPC-DS dataset and assert the number of streams *actually
executed* matches what was requested, plus a focused test of the
run-official CLI forwarding fix.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.platforms.duckdb import DuckDBAdapter

# Real (file-based) DuckDB I/O + a tiny real data-generation pass -- "medium"
# (not "slow"), matching sibling real-DuckDB files (see
# tests/integration/test_plan_capture_phase.py) so this is selected by the
# canonical verification command (`pytest tests/integration -k
# throughput_stream_count`) without needing an explicit -m override: the
# default addopts marker filter excludes "slow" but not "medium".
pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


def _run_tpch_throughput(
    tmp_path: Path,
    *,
    concurrent_streams: int | None = None,
    num_streams: int | None = None,
):
    from benchbox.core.tpch.benchmark import TPCHBenchmark

    db_path = str(tmp_path / "tpch.duckdb")
    adapter = DuckDBAdapter(database_path=db_path)
    conn = adapter.create_connection()
    try:
        bench = TPCHBenchmark(scale_factor=0.01, output_dir=str(tmp_path / "data"))
        bench.generate_data()
        adapter.create_schema(bench, conn)
        adapter.load_data(bench, conn, str(tmp_path / "data"))

        run_config: dict = {
            "benchmark_name": "tpch",
            "test_execution_type": "throughput",
            "scale_factor": 0.01,
        }
        if concurrent_streams is not None:
            run_config["concurrent_streams"] = concurrent_streams
        if num_streams is not None:
            run_config["num_streams"] = num_streams

        results = adapter._execute_queries_by_type(bench, conn, run_config)
        return adapter._last_throughput_test_result, results
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (4, 4),
        (8, 8),
    ],
)
def test_throughput_stream_count_tpch_matches_requested(tmp_path, requested, expected):
    """Requesting N streams via concurrent_streams (RunConfig's real field) runs `expected` streams."""
    result, results = _run_tpch_throughput(tmp_path, concurrent_streams=requested)

    assert result.streams_executed == expected
    assert result.streams_successful == expected
    assert sorted({r.get("stream_id") for r in results}) == list(range(1, expected + 1))


def test_throughput_stream_count_tpcds_matches_requested(tmp_path):
    """The TPC-DS driver honors concurrent_streams via the same shared helper as TPC-H."""
    from benchbox.core.tpcds.benchmark import TPCDSBenchmark

    db_path = str(tmp_path / "tpcds.duckdb")
    adapter = DuckDBAdapter(database_path=db_path)
    conn = adapter.create_connection()
    try:
        bench = TPCDSBenchmark(scale_factor=0.01, output_dir=str(tmp_path / "data"), verbose=False)
        bench.generate_data()
        adapter.create_schema(bench, conn)
        adapter.load_data(bench, conn, str(tmp_path / "data"))

        run_config = {
            "benchmark_name": "tpcds",
            "test_execution_type": "throughput",
            "scale_factor": 0.01,
            "concurrent_streams": 2,
            "validation_mode": "skip",
            "query_subset": ["1", "3"],
        }
        results = adapter._execute_queries_by_type(bench, conn, run_config)
        result = adapter._last_throughput_test_result

        assert result.streams_executed == 2
        assert sorted({r.get("stream_id") for r in results}) == [1, 2]
        assert {str(r.get("query_id")) for r in results} == {"1", "3"}
        assert len(results) == 4
    finally:
        conn.close()


def _run_tpch_throughput_via_real_pipeline_shape(tmp_path: Path):
    """Build the run_config dict the way the REAL pipeline actually does, then run.

    A hand-built dict with no ``concurrent_streams`` key at all (the previous
    version of this test) is a shape the real pipeline never produces: the
    runner always constructs a ``RunConfig`` from a ``BenchmarkConfig`` and
    spreads its ``__dict__`` into the adapter kwargs
    (``benchbox/core/runner/runner.py`` -- ``_build_run_config_from_options``
    sets ``concurrent_streams=benchmark_config.concurrency`` at line ~726, and
    ``_execute_via_adapter`` spreads ``run_config.__dict__`` at line ~803).
    With the default, unconfigured ``BenchmarkConfig`` (``concurrency=1``,
    see ``benchbox/core/schemas.py``), that always yields
    ``concurrent_streams=1`` on the wire -- never an absent key. This helper
    reproduces that real shape so the default-preservation test can't pass
    for the wrong reason (a run_config shape that can't occur in production).
    """
    from benchbox.core.schemas import BenchmarkConfig, RunConfig
    from benchbox.core.tpch.benchmark import TPCHBenchmark

    db_path = str(tmp_path / "tpch.duckdb")
    adapter = DuckDBAdapter(database_path=db_path)
    conn = adapter.create_connection()
    try:
        bench = TPCHBenchmark(scale_factor=0.01, output_dir=str(tmp_path / "data"))
        bench.generate_data()
        adapter.create_schema(bench, conn)
        adapter.load_data(bench, conn, str(tmp_path / "data"))

        # Default BenchmarkConfig: concurrency is left unset by the caller,
        # so it takes the schema default of 1 -- exactly the "user requested
        # nothing" case must_preserve is about.
        benchmark_config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.01,
            test_execution_type="throughput",
        )
        run_config_model = RunConfig(
            benchmark=benchmark_config.name,
            concurrent_streams=benchmark_config.concurrency,
            test_execution_type="throughput",
            scale_factor=benchmark_config.scale_factor,
        )
        # Mirrors runner.py:_execute_via_adapter exactly: spread __dict__,
        # drop "benchmark", then set "benchmark_name" from it.
        run_config = {k: v for k, v in run_config_model.__dict__.items() if k != "benchmark"}
        run_config.setdefault("benchmark_name", run_config_model.benchmark)

        assert "concurrent_streams" in run_config
        assert run_config["concurrent_streams"] is None

        results = adapter._execute_queries_by_type(bench, conn, run_config)
        return adapter._last_throughput_test_result, results
    finally:
        conn.close()


def test_throughput_stream_count_default_preserved_via_real_pipeline_shape(tmp_path):
    """must_preserve: a real (unconfigured) pipeline run still gets the default of 2 streams.

    Regression coverage for the review-found floor defect: with a run_config
    built the way the real pipeline builds one (carrying
    ``concurrent_streams=1``, the ``BenchmarkConfig.concurrency`` schema
    default -- see ``_run_tpch_throughput_via_real_pipeline_shape``), the
    throughput driver must still execute 2 streams. Before the floor was
    added to ``_resolve_requested_stream_count``, this run_config shape
    resolved to 1 stream, silently breaking the documented default.
    """
    result, _results = _run_tpch_throughput_via_real_pipeline_shape(tmp_path)

    assert result.streams_executed == 2


@pytest.mark.parametrize("key", ["num_streams", "concurrent_streams"])
def test_throughput_stream_count_explicit_single_stream_is_rejected(tmp_path, key):
    result, results = _run_tpch_throughput(tmp_path, **{key: 1})

    assert result is None
    assert results[0]["query_id"] == "throughput_test_error"
    assert "at least 2" in results[0]["error"]


def test_throughput_stream_count_legacy_num_streams_key_still_wins(tmp_path):
    """Back-compat: callers already passing num_streams= directly keep taking precedence.

    Uses values above the floor (both > 2) so this test proves precedence
    ordering independently of the floor behavior (covered separately by
    ``test_throughput_stream_count_low_request_floored_to_two``).
    """
    result, _results = _run_tpch_throughput(tmp_path, concurrent_streams=8, num_streams=3)

    assert result.streams_executed == 3


def test_run_official_rejects_explicit_streams_one():
    """#1077 review: an explicit --streams 1 must error, not be silently
    floored to 2. _resolve_requested_stream_count() floors any resolved
    value to the TPC throughput minimum because it cannot distinguish an
    explicit user request of 1 from the schema's own default of 1 at that
    deep boundary -- so run-official (the one place the request is still
    known to be explicit) must reject it up front instead of accepting it
    and silently running a different stream count than requested."""
    from click.testing import CliRunner

    from benchbox.cli.commands.run_official import run_official

    runner = CliRunner()
    result = runner.invoke(
        run_official,
        ["tpch", "--platform", "duckdb", "--scale", "1", "--phases", "throughput", "--streams", "1", "--seed", "42"],
    )

    assert result.exit_code != 0
    assert "streams must be >= 2" in result.output
