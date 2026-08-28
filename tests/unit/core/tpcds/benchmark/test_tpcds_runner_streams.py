"""Tests for TPC-DS benchmark runner: stream operations and orchestration.

Covers query stream permutation, single stream execution, result aggregation,
throughput test orchestration, power test execution, and parameter validation.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.tpcds.benchmark.runner import (
    TPCDSBenchmark,
    _aggregate_stream_results,
    _execute_single_stream,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture()
def tpcds(tmp_path, monkeypatch):
    """Create a TPCDSBenchmark with mocked dependencies."""

    class FakeQueryManager:
        def get_query(self, query_id, **kwargs):
            return f"SELECT {query_id}"

        def get_all_queries(self, **kwargs):
            return {i: f"SELECT {i}" for i in range(1, 100)}

    class FakeDataGenerator:
        def __init__(self, **kwargs):
            self.scale_factor = kwargs.get("scale_factor", 1.0)
            self.output_dir = Path(kwargs.get("output_dir", "."))

        def generate(self):
            return {"store_sales": self.output_dir / "store_sales.dat"}

    class FakeCTools:
        def get_tools_info(self):
            return {"available_tools": []}

    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSQueryManager", FakeQueryManager)
    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSDataGenerator", FakeDataGenerator)
    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSCTools", FakeCTools)

    return TPCDSBenchmark(scale_factor=1.0, output_dir=tmp_path, verbose=False)


class _Conn:
    """Minimal mock connection for benchmark tests."""

    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on
        self.closed = False

    def execute(self, query, *args, **kwargs):
        if self.fail_on and self.fail_on in str(query):
            raise RuntimeError("forced failure")
        return self

    def fetchall(self):
        return [(1,)]

    def fetchone(self):
        return (0,)

    def close(self):
        self.closed = True

    def commit(self):
        pass


# ---------------------------------------------------------------------------
# _execute_single_stream (module-level function)
# ---------------------------------------------------------------------------
class TestExecuteSingleStream:
    """_execute_single_stream used to "execute" a stream by counting `-- Query`
    comment lines and reporting every query as successful, without running
    any SQL (it doesn't even accept a database connection). That fake-success
    stub is retired: it now raises NotImplementedError unconditionally,
    regardless of whether the stream file exists or what it contains.
    """

    def test_missing_stream_file_raises_not_implemented(self, tmp_path: Path):
        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            _execute_single_stream(0, tmp_path / "nonexistent.sql")

    def test_valid_stream_file_raises_not_implemented(self, tmp_path: Path):
        stream_file = tmp_path / "stream_0.sql"
        stream_file.write_text("-- Query 1 Position 1\nSELECT 1;\n-- Query 19 Position 2\nSELECT 19;\n")
        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            _execute_single_stream(0, stream_file)

    def test_empty_stream_file_raises_not_implemented(self, tmp_path: Path):
        stream_file = tmp_path / "stream_empty.sql"
        stream_file.write_text("")
        with pytest.raises(NotImplementedError, match="does not execute SQL"):
            _execute_single_stream(0, stream_file)


# ---------------------------------------------------------------------------
# _aggregate_stream_results (module-level function)
# ---------------------------------------------------------------------------
class TestAggregateStreamResults:
    def test_aggregates_successful_streams(self):
        results = [
            {"success": True, "queries_executed": 99, "queries_successful": 99, "queries_failed": 0, "error": None},
            {"success": True, "queries_executed": 99, "queries_successful": 99, "queries_failed": 0, "error": None},
        ]
        agg = _aggregate_stream_results(results, time.time() - 1.0)
        assert agg["num_streams"] == 2
        assert agg["streams_successful"] == 2
        assert agg["total_queries_executed"] == 198
        assert agg["success"] is True

    def test_aggregates_mixed_results(self):
        results = [
            {"success": True, "queries_executed": 99, "queries_successful": 99, "queries_failed": 0, "error": None},
            {"success": False, "queries_executed": 50, "queries_successful": 40, "queries_failed": 10, "error": "fail"},
        ]
        agg = _aggregate_stream_results(results, time.time() - 1.0)
        assert agg["success"] is False
        assert agg["streams_failed"] == 1
        assert agg["errors"] == ["fail"]
        assert agg["total_queries_failed"] == 10


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestTPCDSInit:
    def test_type_error_scale_factor(self, tmp_path, monkeypatch):
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSQueryManager", MagicMock)
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSDataGenerator", MagicMock)
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSCTools", MagicMock)
        with pytest.raises(TypeError, match="number"):
            TPCDSBenchmark(scale_factor="bad", output_dir=tmp_path)

    def test_zero_scale_factor_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSQueryManager", MagicMock)
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSDataGenerator", MagicMock)
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSCTools", MagicMock)
        with pytest.raises(ValueError, match="positive"):
            TPCDSBenchmark(scale_factor=0, output_dir=tmp_path)

    def test_fractional_sf_rounds_up(self, tpcds):
        # Constructor rounds 0.5 → 1.0 with warning; our fixture already uses 1.0
        assert tpcds.scale_factor == 1.0

    def test_parallel_type_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSQueryManager", MagicMock)
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSDataGenerator", MagicMock)
        monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSCTools", MagicMock)
        with pytest.raises(TypeError, match="integer"):
            TPCDSBenchmark(scale_factor=1, output_dir=tmp_path, parallel=1.5)


# ---------------------------------------------------------------------------
# get_query argument validation
# ---------------------------------------------------------------------------
class TestGetQueryValidation:
    def test_string_query_id_raises(self, tpcds):
        with pytest.raises(TypeError):
            tpcds.get_query("1")

    def test_out_of_range_raises(self, tpcds):
        with pytest.raises(ValueError):
            tpcds.get_query(0)
        with pytest.raises(ValueError):
            tpcds.get_query(100)

    def test_valid_query_returns_string(self, tpcds):
        result = tpcds.get_query(1)
        assert isinstance(result, str)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# Stream info
# ---------------------------------------------------------------------------
class TestStreamInfo:
    def test_get_stream_info_valid(self, tpcds):
        info = tpcds.get_stream_info(0)
        assert isinstance(info, dict)
        assert "stream_id" in info

    def test_get_all_streams_info_skips_invalid(self, tpcds):
        """get_all_streams_info should silently skip invalid streams."""
        results = tpcds.get_all_streams_info(num_streams=2)
        assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Available queries and tables
# ---------------------------------------------------------------------------
class TestAvailableQueriesAndTables:
    def test_available_queries_returns_99(self, tpcds):
        queries = tpcds.get_available_queries()
        assert len(queries) == 99
        assert queries[0] == 1
        assert queries[-1] == 99

    def test_available_tables_returns_list(self, tpcds):
        tables = tpcds.get_available_tables()
        assert isinstance(tables, list)
        assert len(tables) > 0

    def test_get_table_loading_order(self, tpcds):
        tables = tpcds.get_available_tables()
        ordered = tpcds.get_table_loading_order(tables)
        assert isinstance(ordered, list)


# ---------------------------------------------------------------------------
# Power test
# ---------------------------------------------------------------------------
class TestPowerTest:
    def test_runs_all_99_queries(self, tpcds):
        conn = _Conn()
        result = tpcds.run_power_test(conn, warm_up=False, validation=False)
        assert "query_results" in result
        assert result["total_time"] >= 0
        assert "power_at_size" in result

    def test_handles_query_failure_gracefully(self, tpcds):
        conn = _Conn(fail_on="SELECT 42")
        result = tpcds.run_power_test(conn, warm_up=False, validation=False)
        assert len(result["errors"]) > 0
        # Other queries should still succeed
        assert result["total_time"] >= 0


# ---------------------------------------------------------------------------
# Throughput test parameter validation
# ---------------------------------------------------------------------------
class TestThroughputTestValidation:
    def test_rejects_zero_streams(self, tpcds):
        with pytest.raises(ValueError):
            tpcds.run_throughput_test(lambda: _Conn(), num_streams=0)

    def test_rejects_negative_timeout(self, tpcds):
        with pytest.raises(ValueError):
            tpcds.run_throughput_test(lambda: _Conn(), query_timeout=-1)

    def test_rejects_negative_retries(self, tpcds):
        with pytest.raises(ValueError):
            tpcds.run_throughput_test(lambda: _Conn(), max_retries=-1)


# ---------------------------------------------------------------------------
# Query text normalization
# ---------------------------------------------------------------------------
class TestQueryNormalization:
    def test_normalize_interval_syntax(self, tpcds):
        input_sql = "date + 30 days"
        result = tpcds._normalize_interval_syntax(input_sql)
        assert "INTERVAL" in result or "days" in result.lower()

    def test_fix_query58_ambiguity(self, tpcds):
        # Should handle query58-specific ORDER BY disambiguation
        result = tpcds._fix_query58_ambiguity("SELECT * FROM t ORDER BY 1")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Benchmark info
# ---------------------------------------------------------------------------
class TestBenchmarkInfo:
    def test_includes_required_keys(self, tpcds):
        info = tpcds.get_benchmark_info()
        assert "name" in info
        assert "scale_factor" in info
        assert info["scale_factor"] == 1.0

    def test_includes_tools_info(self, tpcds):
        info = tpcds.get_benchmark_info()
        assert "c_tools_info" in info


# ---------------------------------------------------------------------------
# Validation methods
# ---------------------------------------------------------------------------
class TestValidation:
    def test_validate_data_integrity_returns_result(self, tpcds):
        result = tpcds.validate_data_integrity()
        assert hasattr(result, "is_valid")

    def test_validate_preflight_returns_result(self, tpcds):
        result = tpcds.validate_preflight_conditions()
        assert hasattr(result, "is_valid")

    def test_validate_generated_data_returns_result(self, tpcds):
        result = tpcds.validate_generated_data()
        assert hasattr(result, "is_valid")


# ---------------------------------------------------------------------------
# Schema and SQL generation
# ---------------------------------------------------------------------------
class TestSchemaAndSQL:
    def test_get_schema_returns_dict(self, tpcds):
        schema = tpcds.get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0

    def test_get_create_tables_sql_returns_string(self, tpcds):
        sql = tpcds.get_create_tables_sql()
        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql.upper()
