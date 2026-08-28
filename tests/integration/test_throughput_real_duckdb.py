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

from collections import Counter, defaultdict
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpcds.streams import MULTI_PART_QUERY_IDS
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
# The exact multiset of query_id strings every stream must produce, derived
# independently from the same seed-invariant properties as
# _TPCDS_QUERIES_PER_STREAM above (query range 1-99, MULTI_PART_QUERY_IDS
# expand into "<id>a"/"<id>b" instead of the plain "<id>" - see
# benchbox/core/tpcds/throughput_test.py's query_display_id construction).
# A stream that duplicates one query while omitting another, or collapses a
# variant pair like "14a"/"14b" into the same id, keeps the same length but
# changes this multiset - which len(...) == _TPCDS_QUERIES_PER_STREAM alone
# cannot detect.
_TPCDS_EXPECTED_QUERY_IDS = Counter(
    f"{query_id}{variant}" if variant else str(query_id)
    for query_id in range(1, 100)
    for variant in (["a", "b"] if query_id in MULTI_PART_QUERY_IDS else [None])
)
# Shared base seed for both throughput runs below.
_BASE_SEED = 7

# HISTORICAL NOTE (fixed by throughput-result-handling-and-metrics): this
# suite originally had no "rows_returned must be truthful" check because two
# independent production bugs made the field meaningless for both
# benchmarks. Both are now fixed (see
# ``benchbox/platforms/base/connection_wrappers.py::PlatformAdapterCursor._extract_rows``
# / ``count_query_rows``, ``benchbox/core/tpch/throughput_test.py``,
# ``benchbox/core/tpcds/throughput_test.py``); the regression coverage lives
# in ``test_tpch_reports_truthful_row_counts`` /
# ``test_tpcds_reports_truthful_row_counts`` below. Kept for context:
#
# - TPC-H: ``rows_returned`` was corrupted by
#   ``PlatformAdapterCursor._extract_rows()``. It preferred a ``first_row``
#   field over reconstructing the full row list from ``rows_returned``:
#   ``first_row = rows[0] if rows else None`` is non-None for any non-empty
#   result, so ``_extract_rows()`` returned ``[first_row]`` - a length-1
#   list - for every query that returns >= 1 row, regardless of the true
#   count. The TPC-H throughput driver
#   (benchbox/core/tpch/throughput_test.py::_execute_stream) did
#   ``rows = cursor.fetchall(); result_count = len(rows)`` against that
#   cursor, so ``result_count``/``rows_returned`` collapsed to 1 (or 0 when
#   the true result was empty) for essentially every TPC-H query. Verified
#   empirically: every one of stream 0's 22 queries in a real run reported
#   result_count 1 except query 18 (0); re-executing the *exact* SQL text
#   production captured (via ``captured_items``) against the same
#   connection immediately afterward returned 3 rows for query 2 - not 1.
#
# - TPC-DS: benchbox/core/tpcds/throughput_test.py::_execute_single_query
#   unconditionally hardcoded ``"result_count": 0`` for every successful
#   query - ``_run_single_stream_query`` called ``cursor.fetchall()`` but
#   discarded the return value, then ``_execute_single_query`` set
#   ``"result_count": 0`` regardless. So ``rows_returned`` was always ``0``
#   for every successful TPC-DS throughput row regardless of the real
#   result set.
#
# Both only ever affected the throughput-test row-count *metric* (a separate
# count made by the throughput drivers after execution), not the row-count
# *validation* that ``DuckDBAdapter.execute_query`` performs inline against
# the expected TPC-H/TPC-DS answer set (computed from the real
# ``actual_row_count`` before the ``PlatformAdapterCursor`` wrapping
# occurred).


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

        This does not attempt to verify per-query *row content* - see
        ``test_tpch_reports_truthful_row_counts`` below for the
        rows_returned-truthfulness regression coverage.
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

    def test_tpch_reports_truthful_row_counts(self, tpch_throughput_run: tuple[list[dict[str, Any]], Any]) -> None:
        """Regression test for the fixed TPC-H result_count truthfulness bug.

        Previously ``PlatformAdapterCursor._extract_rows()`` preferred
        ``first_row`` over ``rows_returned``, so EVERY non-empty result
        collapsed to ``rows_returned == 1`` regardless of the true row count
        (see the module-level HISTORICAL NOTE). Assert that is no longer the
        case against a real, loaded DuckDB database: at least one query must
        report a genuinely multi-row result, and results must not be
        uniformly stuck at the old sentinel values (0 or 1).
        """
        rows, _result = tpch_throughput_run

        result_counts = [row["rows_returned"] for row in rows if row["status"] == "SUCCESS"]
        assert result_counts, "expected at least one successful TPC-H throughput row"
        assert all(isinstance(count, int) for count in result_counts)

        assert any(count > 1 for count in result_counts), (
            "expected at least one TPC-H query to report >1 row - if every "
            "result_count is <= 1, the first_row-collapse bug has regressed"
        )
        assert not all(count in (0, 1) for count in result_counts), (
            "TPC-H row counts must not be uniformly collapsed to the old 0/1 sentinel values"
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

        See ``test_tpcds_reports_truthful_row_counts`` below for the
        rows_returned-truthfulness regression coverage (formerly always 0 -
        see the module-level HISTORICAL NOTE).
        """
        rows, result = tpcds_throughput_run

        by_stream: dict[int, list[Any]] = defaultdict(list)
        for row in rows:
            assert row["test_type"] == "throughput"
            assert row["status"] == "SUCCESS"
            by_stream[row["stream_id"]].append(row["query_id"])

        assert set(by_stream.keys()) == set(range(_TPCDS_NUM_STREAMS))

        # Each stream must have run the exact expected, seed-invariant TPC-DS
        # query multiset - not just the right count. A stream that duplicates
        # one query while omitting another, or collapses a variant pair like
        # "14a"/"14b" into the same id, keeps len(query_ids) == 103 but
        # changes which ids are present; Counter equality catches that.
        for stream_id, query_ids in by_stream.items():
            assert len(query_ids) == _TPCDS_QUERIES_PER_STREAM, (
                f"stream {stream_id} ran {len(query_ids)} queries, expected {_TPCDS_QUERIES_PER_STREAM}"
            )
            assert Counter(query_ids) == _TPCDS_EXPECTED_QUERY_IDS, (
                f"stream {stream_id} ran the wrong query/variant multiset: "
                f"missing={_TPCDS_EXPECTED_QUERY_IDS - Counter(query_ids)}, "
                f"unexpected={Counter(query_ids) - _TPCDS_EXPECTED_QUERY_IDS}"
            )

        # Structured stream_results must agree with the flattened adapter
        # rows on the expected per-stream count too.
        for stream_result in result.stream_results:
            assert stream_result.queries_executed == _TPCDS_QUERIES_PER_STREAM

    def test_tpcds_reports_truthful_row_counts(self, tpcds_throughput_run: tuple[list[dict[str, Any]], Any]) -> None:
        """Regression test for the fixed TPC-DS result_count-always-0 bug.

        Previously ``_execute_single_query`` unconditionally hardcoded
        ``"result_count": 0`` (see the module-level HISTORICAL NOTE). Assert
        that is no longer the case against a real, loaded DuckDB database: at
        least one query must report a nonzero, and at least one a
        genuinely multi-row, result.
        """
        rows, _result = tpcds_throughput_run

        result_counts = [row["rows_returned"] for row in rows if row["status"] == "SUCCESS"]
        assert result_counts, "expected at least one successful TPC-DS throughput row"
        assert all(isinstance(count, int) for count in result_counts)

        assert any(count > 0 for count in result_counts), (
            "expected at least one TPC-DS query to report a nonzero row count - "
            "if every result_count is 0, the hardcoded-zero bug has regressed"
        )
        assert any(count > 1 for count in result_counts), (
            "expected at least one TPC-DS query to report a genuinely multi-row result"
        )
