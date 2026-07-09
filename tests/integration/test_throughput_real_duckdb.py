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
from benchbox.core.tpch.streams import TPCHStreams
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
# The TPC-DS stream permutation (benchbox/core/tpcds/streams.py::create_standard_streams)
# runs all 99 base query templates per stream, with query ids 14/23/24/39 each
# expanded into two variants (a/b) - i.e. 95 single queries + 4 * 2 variant
# queries = 103 executions per stream. This is a stable, seed-independent
# property of the standard TPC-DS query set/streams generator (not derived
# from this test's own run output), so it can safely serve as an independent
# expected-count oracle.
_TPCDS_QUERIES_PER_STREAM = 103
# Shared base seed for both throughput runs below.
_BASE_SEED = 7

# NOTE on why there is no "rows_returned must be equal/match across streams"
# check here (an earlier draft of this suite had one, per review comment):
# it is not achievable today for either benchmark, for two independent
# reasons discovered while implementing it - both are real production bugs
# in the row-count reporting path, out of scope to fix from this tests-only
# worktree, and are flagged separately rather than papered over with a check
# that would either always trivially pass or always fail:
#
# - TPC-H: ``rows_returned`` is corrupted by
#   ``PlatformAdapterCursor._extract_rows()``
#   (benchbox/platforms/base/connection_wrappers.py:247-262). It prefers a
#   ``first_row`` field over reconstructing the full row list from
#   ``rows_returned``: ``first_row = rows[0] if rows else None`` is
#   non-None for any non-empty result, so ``_extract_rows()`` returns
#   ``[first_row]`` - a length-1 list - for every query that returns >= 1
#   row, regardless of the true count. The TPC-H throughput driver
#   (benchbox/core/tpch/throughput_test.py::_execute_stream) does
#   ``rows = cursor.fetchall(); result_count = len(rows)`` against that
#   cursor, so ``result_count``/``rows_returned`` collapses to 1 (or 0 when
#   the true result is empty) for essentially every TPC-H query. Verified
#   empirically: every one of stream 0's 22 queries in a real run reported
#   result_count 1 except query 18 (0); re-executing the *exact* SQL text
#   production captured (via ``captured_items``) against the same
#   connection immediately afterward returned 3 rows for query 2 - not 1.
#   This also means the field cannot legitimately be compared *within* a
#   single stream, let alone across streams.
#
# - TPC-DS: benchbox/core/tpcds/throughput_test.py::_execute_single_query
#   unconditionally hardcodes ``"result_count": 0`` for every successful
#   query - ``_run_single_stream_query`` calls ``cursor.fetchall()`` but
#   discards the return value, then ``_execute_single_query`` sets
#   ``"result_count": 0`` regardless. So ``rows_returned`` is always ``0``
#   for every successful TPC-DS throughput row regardless of the real
#   result set.
#
# Both are believed to affect only the throughput-test row-count *metric*
# (a separate ``cursor.fetchall()`` call made by the throughput drivers
# after execution), not the row-count *validation* that
# ``DuckDBAdapter.execute_query`` performs inline against the expected TPC-H/
# TPC-DS answer set (computed from the real ``actual_row_count`` before the
# ``PlatformAdapterCursor`` wrapping/loss occurs) - but that scope has not
# been fully verified and the row-count metric bug plausibly extends to the
# analogous *power*-test code path, since both share
# ``PlatformAdapterConnection``/``PlatformAdapterCursor``.


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
        "seed": _BASE_SEED,
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
        "seed": _BASE_SEED,
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

    def test_stream_positions_match_canonical_permutation(
        self, tpch_throughput_run: tuple[list[dict[str, Any]], Any]
    ) -> None:
        """Independent, non-tautological attribution check.

        For each stream, verify every recorded (position, query_id) pair
        against ``TPCHStreams.PERMUTATION_MATRIX`` - the fixed, external TPC-H
        spec permutation table (not derived from this run's own output in any
        way). A stream that ran a query at the wrong position, or a
        cross-stream position mix-up, would be caught here even though a
        purely coverage-based check (all 22 ids present, once each) cannot
        tell positions apart.

        This does not attempt to verify per-query *row content* - see the
        module-level NOTE on why a rows_returned-based content check is not
        achievable today for either benchmark (a discovered production
        row-count-reporting defect, out of scope for this tests-only
        worktree).
        """
        _rows, result = tpch_throughput_run

        assert result.stream_results, "no stream results to verify"
        for stream_result in result.stream_results:
            stream_id = stream_result.stream_id
            permutation = TPCHStreams.PERMUTATION_MATRIX[stream_id % len(TPCHStreams.PERMUTATION_MATRIX)]
            assert len(stream_result.query_results) == len(permutation)
            for qr in stream_result.query_results:
                expected_position = permutation.index(qr["query_id"]) + 1
                assert qr["position"] == expected_position, (
                    f"stream {stream_id} query {qr['query_id']}: recorded position "
                    f"{qr['position']} does not match canonical TPC-H permutation "
                    f"position {expected_position}"
                )


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
            # Expected count is an independent, seed-invariant property of the
            # standard TPC-DS query set/streams generator (see
            # _TPCDS_QUERIES_PER_STREAM), not derived from this run's own
            # output - so it actually detects a stream silently running the
            # wrong (e.g. truncated or duplicated) query subset.
            assert stream_result.queries_executed == _TPCDS_QUERIES_PER_STREAM
            assert stream_result.queries_successful == stream_result.queries_executed
            assert stream_result.queries_failed == 0

    def test_no_cross_stream_result_bleed(self, tpcds_throughput_run: tuple[list[dict[str, Any]], Any]) -> None:
        """Each stream must independently execute the expected, seed-invariant
        TPC-DS query count (see _TPCDS_QUERIES_PER_STREAM and the module-level
        NOTE) - independent of what the flattened rows/stream_results
        themselves report, so this actually detects a stream silently running
        a truncated or duplicated query subset.

        Unlike the TPC-H variant of this test, there is no content-level
        (rows_returned) bleed check here: benchbox/core/tpcds/throughput_test.py
        ::_execute_single_query hardcodes ``result_count: 0`` for every
        successful query regardless of the real result set (see the
        module-level NOTE), so rows_returned carries no signal for TPC-DS
        today. Fixing that is a production-source change out of scope for
        this tests-only worktree.
        """
        rows, result = tpcds_throughput_run

        by_stream: dict[int, list[Any]] = defaultdict(list)
        for row in rows:
            assert row["test_type"] == "throughput"
            assert row["status"] == "SUCCESS"
            by_stream[row["stream_id"]].append(row["query_id"])

        assert set(by_stream.keys()) == set(range(_TPCDS_NUM_STREAMS))

        # Each stream must have run the expected, seed-invariant TPC-DS query
        # count - independent of what the flattened rows/stream_results
        # themselves report.
        for stream_id, query_ids in by_stream.items():
            assert len(query_ids) == _TPCDS_QUERIES_PER_STREAM, (
                f"stream {stream_id} ran {len(query_ids)} queries, expected {_TPCDS_QUERIES_PER_STREAM}"
            )

        # Structured stream_results must agree with the flattened adapter
        # rows on the expected per-stream count too.
        for stream_result in result.stream_results:
            assert stream_result.queries_executed == _TPCDS_QUERIES_PER_STREAM
