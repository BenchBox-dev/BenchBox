# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Real-DuckDB multi-stream throughput integration tests.

Closes a coverage gap identified in ``throughput-real-db-integration-tests``:
the production throughput path (``benchbox/platforms/base/execution.py``
``_execute_tpch_throughput_test`` / ``_execute_tpcds_throughput_test``, and the
underlying ``benchbox/core/{tpch,tpcds}/throughput_test.py`` drivers) was only
ever exercised end-to-end against Mock/Dummy connections:

- ``tests/integration/test_tpch_throughput_test.py`` / ``test_tpcds_throughput_test.py``
  use a real ``ThreadPoolExecutor`` but a ``Mock`` connection.
- ``tests/integration/test_throughput_corrections.py`` is the strongest prior
  harness (real threads + real timing) but still mocks the connection.

None of the above proves that N concurrent streams actually run real SQL
against real loaded data without cross-stream result bleed, connection
mix-ups, or dialect-translation gaps that only surface against a live engine.
This module closes that gap using DuckDB (embedded, fast, already a test
dependency) as the real-database oracle: tables are generated once via the
real dbgen/dsdgen-backed generators and loaded once via the real
``DuckDBAdapter.create_schema`` / ``load_data`` path, then reused read-only
across every stream in a run (mirrors the production ``connection_factory``,
which hands each stream a cursor over the same underlying connection - see
``benchbox/platforms/base/connection_wrappers.py::_make_stream_cursor``).

Tests drive the *real* production entry point
(``DuckDBAdapter._execute_queries_by_type`` with
``test_execution_type="throughput"``) exactly as the benchmark runner does,
rather than constructing ``TPCHThroughputTest`` / ``TPCDSThroughputTest``
directly - so a regression anywhere in the routing, connection-wrapping, or
driver layers would be caught here.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.platforms.duckdb import DuckDBAdapter

# Mark all tests in this file as integration tests. Real dbgen/dsdgen data
# generation plus real DuckDB schema/load makes this the slow lane - the
# existing mock-based throughput tests remain the fast lane (see module
# docstring); this suite is additive, not a replacement.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]

_SCALE_FACTOR = 0.01
_TPCH_NUM_STREAMS = 3
# TPC-DS executes the full ~99-query (+variants) permutation per stream with
# no query-count override available through the adapter's public run_config
# (see benchbox/platforms/base/execution.py::_execute_tpcds_throughput_test),
# so 2 streams keeps runtime bounded at SF 0.01 (~20-30s total).
_TPCDS_NUM_STREAMS = 2


@pytest.fixture(scope="module")
def tpch_real_duckdb(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[tuple[DuckDBAdapter, TPCHBenchmark, Any], None, None]:
    """Real DuckDB database with TPC-H data generated and loaded exactly once.

    Module-scoped so every test in this file reuses the same loaded tables
    instead of regenerating/reloading data per test.
    """
    base = tmp_path_factory.mktemp("tpch_throughput_real")
    db_path = str(base / "tpch.duckdb")
    adapter = DuckDBAdapter(database_path=db_path)
    conn = adapter.create_connection()
    bench = TPCHBenchmark(scale_factor=_SCALE_FACTOR, output_dir=str(base / "data"))
    bench.generate_data()
    adapter.create_schema(bench, conn)
    adapter.load_data(bench, conn, Path(base / "data"))
    yield adapter, bench, conn
    conn.close()


@pytest.fixture(scope="module")
def tpcds_real_duckdb(
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[tuple[DuckDBAdapter, TPCDSBenchmark, Any], None, None]:
    """Real DuckDB database with TPC-DS data generated and loaded exactly once."""
    base = tmp_path_factory.mktemp("tpcds_throughput_real")
    db_path = str(base / "tpcds.duckdb")
    adapter = DuckDBAdapter(database_path=db_path)
    conn = adapter.create_connection()
    bench = TPCDSBenchmark(scale_factor=_SCALE_FACTOR, output_dir=str(base / "data"))
    bench.generate_data()
    adapter.create_schema(bench, conn)
    adapter.load_data(bench, conn, Path(base / "data"))
    yield adapter, bench, conn
    conn.close()


@pytest.fixture(scope="module")
def tpch_throughput_run(
    tpch_real_duckdb: tuple[DuckDBAdapter, TPCHBenchmark, Any],
) -> tuple[list[dict[str, Any]], Any]:
    """Run the real production TPC-H throughput path exactly once, real streams."""
    adapter, bench, conn = tpch_real_duckdb
    run_config = {
        "benchmark_name": "tpch",
        "test_execution_type": "throughput",
        "scale_factor": _SCALE_FACTOR,
        "num_streams": _TPCH_NUM_STREAMS,
        "seed": 7,
        "verbose": False,
    }
    rows = adapter._execute_queries_by_type(bench, conn, run_config)
    return rows, adapter._last_throughput_test_result


@pytest.fixture(scope="module")
def tpcds_throughput_run(
    tpcds_real_duckdb: tuple[DuckDBAdapter, TPCDSBenchmark, Any],
) -> tuple[list[dict[str, Any]], Any]:
    """Run the real production TPC-DS throughput path exactly once, real streams."""
    adapter, bench, conn = tpcds_real_duckdb
    run_config = {
        "benchmark_name": "tpcds",
        "test_execution_type": "throughput",
        "scale_factor": _SCALE_FACTOR,
        "num_streams": _TPCDS_NUM_STREAMS,
        "seed": 7,
        "verbose": False,
    }
    rows = adapter._execute_queries_by_type(bench, conn, run_config)
    return rows, adapter._last_throughput_test_result


@pytest.mark.duckdb
class TestTPCHThroughputRealDuckDB:
    """TPC-H throughput happy path against real, loaded DuckDB data."""

    def test_all_streams_run_all_22_queries_successfully(
        self, tpch_throughput_run: tuple[list[dict[str, Any]], Any]
    ) -> None:
        _rows, result = tpch_throughput_run

        assert result is not None
        assert result.success is True
        assert result.streams_executed == _TPCH_NUM_STREAMS
        assert result.streams_successful == _TPCH_NUM_STREAMS
        assert result.throughput_at_size > 0

        assert len(result.stream_results) == _TPCH_NUM_STREAMS
        for stream_result in result.stream_results:
            assert stream_result.success is True
            assert stream_result.queries_executed == 22
            assert stream_result.queries_successful == 22
            assert stream_result.queries_failed == 0

    def test_no_cross_stream_result_bleed(self, tpch_throughput_run: tuple[list[dict[str, Any]], Any]) -> None:
        """Each stream must independently execute all 22 distinct query ids,
        with no query id missing, duplicated cross-stream, or misattributed."""
        rows, result = tpch_throughput_run

        assert len(rows) == _TPCH_NUM_STREAMS * 22
        by_stream: dict[int, list[Any]] = defaultdict(list)
        for row in rows:
            assert row["test_type"] == "throughput"
            assert row["status"] == "SUCCESS"
            by_stream[row["stream_id"]].append(row["query_id"])

        assert set(by_stream.keys()) == set(range(_TPCH_NUM_STREAMS))
        for stream_id, query_ids in by_stream.items():
            assert sorted(query_ids) == list(range(1, 23)), (
                f"stream {stream_id} must run each of the 22 TPC-H queries exactly once"
            )

        # Cross-check the flattened adapter rows against the structured stream
        # results the driver itself produced - the two must agree on shape.
        for stream_result in result.stream_results:
            assert len(stream_result.query_results) == 22


@pytest.mark.duckdb
class TestTPCDSThroughputRealDuckDB:
    """TPC-DS throughput happy path against real, loaded DuckDB data."""

    def test_all_streams_run_permuted_set_successfully(
        self, tpcds_throughput_run: tuple[list[dict[str, Any]], Any]
    ) -> None:
        _rows, result = tpcds_throughput_run

        assert result is not None
        assert result.success is True
        assert result.streams_executed == _TPCDS_NUM_STREAMS
        assert result.streams_successful == _TPCDS_NUM_STREAMS
        assert result.throughput_at_size > 0

        assert len(result.stream_results) == _TPCDS_NUM_STREAMS
        for stream_result in result.stream_results:
            assert stream_result.success is True
            assert stream_result.queries_executed > 0
            assert stream_result.queries_successful == stream_result.queries_executed
            assert stream_result.queries_failed == 0

    def test_no_cross_stream_result_bleed(self, tpcds_throughput_run: tuple[list[dict[str, Any]], Any]) -> None:
        """Each stream's flattened rows must match its own structured stream
        result 1:1 - no query result attributed to the wrong stream."""
        rows, result = tpcds_throughput_run

        by_stream: dict[int, list[Any]] = defaultdict(list)
        for row in rows:
            assert row["test_type"] == "throughput"
            assert row["status"] == "SUCCESS"
            by_stream[row["stream_id"]].append(row["query_id"])

        assert set(by_stream.keys()) == set(range(_TPCDS_NUM_STREAMS))

        # Per-stream row count must exactly match that stream's own executed
        # query count - proves the flat adapter-level rows were not
        # cross-attributed between concurrently running streams.
        stream_counts_by_id = {sr.stream_id: sr.queries_executed for sr in result.stream_results}
        for stream_id, query_ids in by_stream.items():
            assert len(query_ids) == stream_counts_by_id[stream_id]

        assert sum(len(v) for v in by_stream.values()) == sum(sr.queries_executed for sr in result.stream_results)
