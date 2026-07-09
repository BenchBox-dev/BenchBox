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
   forwarded it anywhere (fixed here via ``_forward_requested_streams`` in
   ``benchbox/cli/commands/run_official.py``).

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


@pytest.mark.parametrize("requested", [1, 4])
def test_throughput_stream_count_tpch_matches_requested(tmp_path, requested):
    """Requesting N streams via concurrent_streams (RunConfig's real field) runs exactly N streams."""
    result, results = _run_tpch_throughput(tmp_path, concurrent_streams=requested)

    assert result.streams_executed == requested
    assert result.streams_successful == requested
    assert sorted({r.get("stream_id") for r in results}) == list(range(requested))


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
        }
        results = adapter._execute_queries_by_type(bench, conn, run_config)
        result = adapter._last_throughput_test_result

        assert result.streams_executed == 2
        assert sorted({r.get("stream_id") for r in results}) == [0, 1]
    finally:
        conn.close()


def test_throughput_stream_count_default_preserved_when_no_key_present(tmp_path):
    """Back-compat: a run_config with no stream-count key at all still gets the legacy default of 2."""
    result, _results = _run_tpch_throughput(tmp_path)

    assert result.streams_executed == 2


def test_throughput_stream_count_legacy_num_streams_key_still_wins(tmp_path):
    """Back-compat: callers already passing num_streams= directly keep taking precedence."""
    result, _results = _run_tpch_throughput(tmp_path, concurrent_streams=4, num_streams=1)

    assert result.streams_executed == 1


def test_run_official_forward_requested_streams_sets_concurrency():
    """CLI regression: run-official's --streams forwarding sets BenchmarkConfig.concurrency.

    ``run()`` has no ``--streams``/``--concurrency`` option of its own, so
    ``run_official.py`` cannot forward the value as a keyword argument to
    ``ctx.invoke(run, ...)``. Instead it patches
    ``BenchmarkOrchestrator.execute_benchmark`` for the duration of that one
    call so the requested count lands on the same ``BenchmarkConfig.concurrency``
    field the throughput drivers now read. This drives that mechanism
    directly (no CLI harness, no data generation) so it stays fast and
    deterministic while still exercising the real production code path.
    """
    from types import SimpleNamespace

    from benchbox.cli.commands.run_official import _forward_requested_streams
    from benchbox.cli.orchestrator import BenchmarkOrchestrator

    original = BenchmarkOrchestrator.execute_benchmark
    captured: dict = {}

    def _stub_execute_benchmark(
        self, config, system_profile, database_config, phases_to_run=None, progress=None, execution_context=None
    ):
        captured["concurrency"] = config.concurrency
        return "stub-result"

    BenchmarkOrchestrator.execute_benchmark = _stub_execute_benchmark
    try:
        with _forward_requested_streams(4):
            patched = BenchmarkOrchestrator.execute_benchmark
            assert patched is not _stub_execute_benchmark, "context manager should have wrapped execute_benchmark"

            fake_config = SimpleNamespace(concurrency=1)
            outcome = patched(object(), fake_config, None, None)

            assert outcome == "stub-result"
            assert fake_config.concurrency == 4, "requested streams must be set on the BenchmarkConfig"

        # Restored after the context manager exits.
        assert BenchmarkOrchestrator.execute_benchmark is _stub_execute_benchmark
        assert captured["concurrency"] == 4
    finally:
        BenchmarkOrchestrator.execute_benchmark = original


def test_run_official_forward_requested_streams_noop_when_not_requested():
    """When --streams is absent (None), execute_benchmark must be left untouched."""
    from benchbox.cli.commands.run_official import _forward_requested_streams
    from benchbox.cli.orchestrator import BenchmarkOrchestrator

    original = BenchmarkOrchestrator.execute_benchmark
    with _forward_requested_streams(None):
        assert BenchmarkOrchestrator.execute_benchmark is original
    assert BenchmarkOrchestrator.execute_benchmark is original
