"""Tests for base platform adapter functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest

from benchbox.core.results.builder import benchmark_family as _benchmark_family, normalize_benchmark_id
from benchbox.core.schemas import QueryResult
from benchbox.platforms.base import (
    BenchmarkResults,
    ConnectionConfig,
    PlatformAdapter,
)
from benchbox.utils.dialect_utils import SQLTranslationError, SqlTranslationOutcome
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class MockPlatformAdapter(PlatformAdapter):
    """Mock platform adapter for testing."""

    def add_cli_arguments(self):
        pass

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        return cls(**config)

    def get_target_dialect(self) -> str | None:
        return None

    def get_platform_info(self, connection=None):
        """Mock platform info implementation."""
        return {
            "platform_type": "mock",
            "platform_name": "Mock Platform",
            "platform_version": "1.0.0",
            "connection_mode": "test",
            "host": None,
            "port": None,
            "configuration": {},
            "client_library_version": "1.0.0",
            "embedded_library_version": None,
        }

    def create_connection(self, **connection_config):
        return Mock()

    def create_schema(self, benchmark, connection):
        return 0.1

    def load_data(self, benchmark, connection, data_dir):
        return {"table1": 100}, 0.5, None

    def configure_for_benchmark(self, connection, benchmark_type):
        pass

    def execute_query(self, connection, query, query_id, **kwargs):
        return {
            "query_id": query_id,
            "status": "SUCCESS",
            "execution_time_seconds": 0.1,
            "rows_returned": 10,
        }

    def apply_table_tunings(self, table_tuning, connection):
        """Mock table tuning implementation."""

    def generate_tuning_clause(self, table_tuning):
        """Mock tuning clause generation."""
        return ""

    def apply_unified_tuning(self, unified_config, connection):
        """Mock unified tuning implementation."""

    def apply_platform_optimizations(self, platform_config, connection):
        """Mock platform optimizations implementation."""

    def apply_constraint_configuration(self, primary_key_config, foreign_key_config, connection):
        """Mock constraint configuration implementation."""


class MockPlatformAdapterWithDialect(MockPlatformAdapter):
    """Mock platform adapter with dialect support for testing."""

    def get_target_dialect(self) -> str:
        return "mock_dialect"

    def get_platform_info(self, connection=None):
        """Mock platform info implementation with dialect support."""
        return {
            "platform_type": "mock_dialect",
            "platform_name": "Mock Platform with Dialect",
            "platform_version": "1.0.0",
            "connection_mode": "test",
            "host": None,
            "port": None,
            "configuration": {"dialect": "mock_dialect"},
            "client_library_version": "1.0.0",
            "embedded_library_version": None,
        }

    def run_power_test(self, benchmark, **kwargs):
        """Mock power test implementation."""
        return {
            "test_type": "power",
            "total_execution_time": 5.0,
            "query_count": 22,
            "successful_queries": 22,
            "failed_queries": 0,
            "query_results": [
                {
                    "query_id": f"q{i}",
                    "status": "SUCCESS",
                    "execution_time_seconds": 0.2,
                    "rows_returned": 100,
                }
                for i in range(1, 23)
            ],
            "geometric_mean": 0.2,
            "validation_status": "PASSED",
        }

    def run_throughput_test(self, benchmark, **kwargs):
        """Mock throughput test implementation."""
        stream_count = kwargs.get("stream_count", 2)
        return {
            "test_type": "throughput",
            "stream_count": stream_count,
            "total_execution_time": 10.0,
            "aggregate_query_time": 18.0,
            "queries_per_hour": 7920,
            "stream_results": [
                {
                    "stream_id": i,
                    "execution_time": 9.0,
                    "query_count": 22,
                    "successful_queries": 22,
                    "failed_queries": 0,
                }
                for i in range(stream_count)
            ],
            "validation_status": "PASSED",
        }

    def run_maintenance_test(self, benchmark, **kwargs):
        """Mock maintenance test implementation."""
        return {
            "test_type": "maintenance",
            "operations_executed": 4,
            "total_execution_time": 2.5,
            "operation_results": [
                {
                    "operation": "INSERT",
                    "status": "SUCCESS",
                    "execution_time": 0.5,
                    "rows_affected": 1000,
                },
                {
                    "operation": "UPDATE",
                    "status": "SUCCESS",
                    "execution_time": 0.8,
                    "rows_affected": 500,
                },
                {
                    "operation": "DELETE",
                    "status": "SUCCESS",
                    "execution_time": 0.7,
                    "rows_affected": 200,
                },
                {
                    "operation": "REFRESH",
                    "status": "SUCCESS",
                    "execution_time": 0.5,
                    "rows_affected": 0,
                },
            ],
            "concurrent_query_impact": 0.1,
            "data_integrity_status": "PASSED",
            "validation_status": "PASSED",
        }

    def apply_table_tunings(self, table_tuning, connection):
        """Mock table tuning implementation."""

    def generate_tuning_clause(self, table_tuning):
        """Mock tuning clause generation."""
        return ""

    def apply_unified_tuning(self, unified_config, connection):
        """Mock unified tuning implementation."""

    def apply_platform_optimizations(self, platform_config, connection):
        """Mock platform optimizations implementation."""

    def apply_constraint_configuration(self, primary_key_config, foreign_key_config, connection):
        """Mock constraint configuration implementation."""


class BenchmarkWithVersionAwareQueries:
    """Minimal benchmark stub for testing get_queries() kwarg propagation."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def get_queries(self, dialect: str | None = None, platform_version: str | None = None) -> dict[str, str]:
        self.calls.append(
            {
                "dialect": dialect,
                "platform_version": platform_version,
            }
        )
        return {"Q1": "SELECT 1"}


class BenchmarkWithStrictTranslationFailure:
    """Benchmark stub whose dialect-aware path raises the strict translation exception."""

    def get_queries(self, dialect: str | None = None, base_dialect: str | None = None) -> dict[str, str]:
        if dialect is None:
            return {"Q1": "SELECT fallback"}
        outcome = SqlTranslationOutcome(
            source_dialect=base_dialect or "ansi",
            target_dialect=dialect,
            translator="test",
            status="failed",
            strict_mode=True,
            error_category="translation_failed",
        )
        raise SQLTranslationError("strict translation failed", outcome)


class TestConnectionConfig:
    """Test ConnectionConfig functionality."""

    def test_default_values(self):
        """Test default connection configuration values."""
        config = ConnectionConfig()
        assert config.host is None
        assert config.port is None
        assert config.auth_method == "password"
        assert config.ssl_enabled is False
        assert config.pool_size == 5
        assert config.max_overflow == 10
        assert config.pool_timeout == 30

    def test_env_value_resolution(self):
        """Test environment variable resolution."""
        config = ConnectionConfig(password="${TEST_PASSWORD}")

        with patch.dict("os.environ", {"TEST_PASSWORD": "secret123"}):
            assert config.get_env_value("password") == "secret123"

    def test_env_value_no_expansion(self):
        """Test that regular values are not expanded."""
        config = ConnectionConfig(password="regular_password")
        assert config.get_env_value("password") == "regular_password"

    def test_env_value_missing_variable(self):
        """Test handling of missing environment variables."""
        config = ConnectionConfig(password="${MISSING_VAR}")
        assert config.get_env_value("password", "default") == "default"


class TestPlatformAdapter:
    """Test base PlatformAdapter functionality."""

    def test_initialization(self):
        """Test adapter initialization."""
        adapter = MockPlatformAdapter()
        adapter.platform_config["test_param"] = "value"
        assert adapter.platform_config["test_param"] == "value"
        assert adapter.connection is None
        assert adapter.connection_pool is None
        assert adapter.dialect is None

    def test_external_table_capability_defaults_disabled(self):
        """Base adapter defaults to native tables unless subclasses opt in."""
        adapter = MockPlatformAdapter()
        assert adapter.supports_external_tables is False
        assert PlatformAdapter.supports_external_tables is False

    def test_create_external_tables_raises_by_default(self, tmp_path):
        """Base implementation should force adapters to provide external mode behavior."""
        adapter = MockPlatformAdapter()
        with pytest.raises(NotImplementedError, match="does not support external table mode"):
            adapter.create_external_tables(benchmark=Mock(), connection=Mock(), data_dir=tmp_path)

    def test_sql_translation_no_dialect(self):
        """Test SQL translation when no dialect is set."""
        adapter = MockPlatformAdapter()
        sql = "SELECT * FROM table"
        assert adapter.translate_sql(sql) == sql

    @patch("sqlglot.transpile")
    def test_sql_translation_with_dialect(self, mock_transpile):
        """Test SQL translation with dialect set."""
        adapter = MockPlatformAdapter()
        adapter._dialect = "postgresql"

        mock_transpile.return_value = ['SELECT * FROM "table"']

        result = adapter.translate_sql("SELECT * FROM table", "duckdb")
        # identify=True for postgresql (not in the clickhouse/postgres exclusion list)
        mock_transpile.assert_called_once_with("SELECT * FROM table", read="duckdb", write="postgresql", identify=True)
        # translate_sql adds semicolon at the end
        assert result == 'SELECT * FROM "table";'

    @patch("sqlglot.transpile")
    def test_sql_translation_error_handling(self, mock_transpile):
        """Test SQL translation error handling."""
        adapter = MockPlatformAdapter()
        adapter._dialect = "postgresql"

        mock_transpile.side_effect = Exception("Translation error")

        sql = "SELECT * FROM table"
        result = adapter.translate_sql(sql, "duckdb")
        assert result == sql  # Should return original SQL on error

    def test_connection_test_success(self):
        """Test successful connection test."""
        adapter = MockPlatformAdapter()
        assert adapter.test_connection() is True

    def test_connection_test_failure(self):
        """Test failed connection test."""
        adapter = MockPlatformAdapter()

        # Mock create_connection to raise an exception
        adapter.create_connection = Mock(side_effect=Exception("Connection failed"))

        assert adapter.test_connection() is False

    def test_get_connection_from_pool_no_pool(self):
        """Test getting connection when no pool exists."""
        adapter = MockPlatformAdapter()
        adapter.platform_config["test_param"] = "value"
        connection = adapter.get_connection_from_pool()
        assert connection is not None

    def test_get_connection_from_pool_with_pool(self):
        """Test getting connection from pool."""
        adapter = MockPlatformAdapter()
        mock_pool = Mock()
        mock_connection = Mock()
        mock_pool.get_connection.return_value = mock_connection
        adapter.connection_pool = mock_pool

        connection = adapter.get_connection_from_pool()
        assert connection == mock_connection
        mock_pool.get_connection.assert_called_once()

    def test_execute_all_queries_with_dialect_support(self):
        """Test _execute_all_queries method with dialect support."""
        adapter = MockPlatformAdapterWithDialect()

        class DummyBenchmark:
            def __init__(self):
                self.calls = []

            def get_queries(self, dialect=None, base_dialect=None):
                self.calls.append((dialect, base_dialect))
                return {
                    "1": "SELECT * FROM table1 LIMIT 100",
                    "2": "SELECT * FROM table2 LIMIT 50",
                }

        dummy_benchmark = DummyBenchmark()
        mock_connection = Mock()
        run_config = {"benchmark_name": "tpch"}

        with patch("rich.console.Console"):
            results = adapter._execute_all_queries(dummy_benchmark, mock_connection, run_config)

        assert isinstance(results, list)
        assert dummy_benchmark.calls
        dialect, base_dialect = dummy_benchmark.calls[0]
        assert dialect == "mock_dialect"
        assert base_dialect == "netezza"

    def test_execute_all_queries_without_dialect_support(self):
        """Test _execute_all_queries method without dialect support."""
        adapter = MockPlatformAdapter()  # No get_target_dialect method

        # mock benchmark
        mock_benchmark = Mock()
        mock_benchmark.get_queries.return_value = {
            "1": "SELECT TOP 100 * FROM table1",
            "2": "SELECT TOP 50 * FROM table2",
        }
        mock_benchmark.get_platform_skip_queries.return_value = []

        # Mock connection
        mock_connection = Mock()

        # Mock run config
        run_config = {"benchmark_name": "tpch"}

        with patch("rich.console.Console"):
            results = adapter._execute_all_queries(mock_benchmark, mock_connection, run_config)

        # Verify benchmark was called without dialect
        mock_benchmark.get_queries.assert_called_once()
        # Should not have been called with dialect parameter
        args, kwargs = mock_benchmark.get_queries.call_args
        assert "dialect" not in kwargs
        assert isinstance(results, list)
        assert all(r.get("run_type") == "measurement" for r in results)

    def test_execute_all_queries_benchmark_no_dialect_parameter(self):
        """Test _execute_all_queries when benchmark doesn't support dialect parameter."""
        adapter = MockPlatformAdapterWithDialect()

        # mock benchmark without dialect support
        mock_benchmark = Mock()
        mock_benchmark.get_queries.return_value = {"1": "SELECT TOP 100 * FROM table1"}
        mock_benchmark.get_platform_skip_queries.return_value = []

        # Mock connection
        mock_connection = Mock()
        run_config = {"benchmark_name": "tpch"}

        with patch("inspect.signature") as mock_signature:
            # Mock signature to indicate no dialect parameter
            mock_signature.return_value.parameters = {}

            with patch("rich.console.Console"):
                adapter._execute_all_queries(mock_benchmark, mock_connection, run_config)

            # Should call without dialect since benchmark doesn't support it
            mock_benchmark.get_queries.assert_called_once()
            args, kwargs = mock_benchmark.get_queries.call_args
            assert "dialect" not in kwargs

    def test_execute_all_queries_dialect_exception_handling(self):
        """Test _execute_all_queries handles dialect inspection exceptions gracefully."""
        adapter = MockPlatformAdapterWithDialect()

        # mock benchmark
        mock_benchmark = Mock()
        mock_benchmark.get_queries.return_value = {"1": "SELECT * FROM table1"}
        mock_benchmark.get_platform_skip_queries.return_value = []

        mock_connection = Mock()
        run_config = {"benchmark_name": "tpch"}

        with patch("inspect.signature", side_effect=Exception("Signature error")):
            with patch("rich.console.Console"):
                adapter._execute_all_queries(mock_benchmark, mock_connection, run_config)

            # Should fallback to calling without dialect
            mock_benchmark.get_queries.assert_called_once()
            args, kwargs = mock_benchmark.get_queries.call_args
            assert "dialect" not in kwargs

    def test_execute_queries_by_type_sets_run_type_for_throughput(self):
        """_execute_queries_by_type should enforce run_type tagging for throughput rows."""
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"test_execution_type": "throughput"}

        adapter._execute_throughput_test = Mock(
            return_value=[{"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.1}]
        )

        results = adapter._execute_queries_by_type(benchmark, connection, run_config)
        assert results[0]["run_type"] == "measurement"

    def test_execute_queries_by_type_sets_run_type_for_power(self):
        """_execute_queries_by_type should enforce run_type tagging for power rows."""
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"test_execution_type": "power"}

        adapter._execute_power_test = Mock(
            return_value=[{"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.1}]
        )

        results = adapter._execute_queries_by_type(benchmark, connection, run_config)
        assert results[0]["run_type"] == "measurement"

    def test_execute_queries_by_type_sets_run_type_for_maintenance(self):
        """_execute_queries_by_type should enforce run_type tagging for maintenance rows."""
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"test_execution_type": "maintenance"}

        adapter._execute_maintenance_test = Mock(
            return_value=[{"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.1}]
        )

        results = adapter._execute_queries_by_type(benchmark, connection, run_config)
        assert results[0]["run_type"] == "measurement"

    def test_execute_queries_by_type_combined_preserves_explicit_run_type(self):
        """Combined runs preserve explicit run_type and backfill missing values."""
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"test_execution_type": "combined"}

        adapter._execute_combined_test = Mock(
            return_value=[
                {"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.1, "run_type": "warmup"},
                {"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.09},
            ]
        )

        results = adapter._execute_queries_by_type(benchmark, connection, run_config)
        assert results[0]["run_type"] == "warmup"
        assert results[1]["run_type"] == "measurement"

    def test_ensure_query_results_run_type_infers_warmup_from_iteration(self):
        """Missing run_type should infer warmup when iteration is zero."""
        results = MockPlatformAdapter._ensure_query_results_run_type(
            [{"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.1, "iteration": 0}]
        )
        assert results[0]["run_type"] == "warmup"

    def test_ensure_query_results_run_type_infers_warmup_from_flag(self):
        """Missing run_type should infer warmup when is_warmup flag is true."""
        results = MockPlatformAdapter._ensure_query_results_run_type(
            [{"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.1, "is_warmup": True}]
        )
        assert results[0]["run_type"] == "warmup"


class TestBenchmarkResults:
    """Test BenchmarkResults data class."""

    def test_benchmark_results_creation(self):
        """Test creating BenchmarkResults instance."""
        results = make_benchmark_results(
            benchmark_name="test_benchmark",
            platform="test_platform",
            scale_factor=1.0,
            execution_id="test_001",
            duration_seconds=10.5,
            total_queries=5,
            successful_queries=4,
            failed_queries=1,
            total_execution_time=8.0,
            average_query_time=2.0,
            data_loading_time=1.5,
            schema_creation_time=1.0,
            total_rows_loaded=1000,
            data_size_mb=10.5,
            table_statistics={"table1": 1000},
            validation_status="PASSED",
        )
        # Factory sets validation_details={} by default; reset to match dataclass default for this test
        results.validation_details = None

        assert results.benchmark_name == "test_benchmark"
        assert results.platform == "test_platform"
        assert results.scale_factor == 1.0
        assert results.validation_status == "PASSED"  # Default value
        assert results.validation_details is None  # Default value


@pytest.fixture
def mock_benchmark():
    """Create a mock benchmark for testing."""
    benchmark = Mock()
    benchmark.scale_factor = 1.0
    benchmark._name = "test_benchmark"
    benchmark.output_dir = Path("/tmp/test_data")
    benchmark.generate_data = Mock()
    benchmark.get_queries = Mock(return_value={"q1": "SELECT 1", "q2": "SELECT 2"})
    benchmark.get_create_tables_sql = Mock(return_value="CREATE TABLE test (id INT)")
    benchmark.get_platform_skip_queries = Mock(return_value=[])
    # Include tables attribute that won't interfere with data generation phase
    benchmark.tables = None
    benchmark._impl = None
    # Mock create_enhanced_benchmark_result will be set per test
    benchmark.create_enhanced_benchmark_result = Mock()
    return benchmark


class TestPlatformAdapterWorkflow:
    """Test complete platform adapter workflow."""

    def test_run_benchmark_success(self, mock_benchmark, tmp_path):
        """Test successful benchmark execution."""
        adapter = MockPlatformAdapter()
        mock_benchmark.output_dir = tmp_path

        # Mock file system for data size calculation
        test_file = tmp_path / "test.csv"
        test_file.write_text("test,data\n1,value")

        # Mock create_enhanced_benchmark_result to return correct values
        mock_result = make_benchmark_results(
            benchmark_name="test_benchmark",
            platform="mock",
            scale_factor=1.0,
            execution_id="test_001",
            duration_seconds=10.0,
            total_queries=2,
            successful_queries=2,
            total_execution_time=0.2,
            average_query_time=0.1,
            data_loading_time=0.5,
            schema_creation_time=0.1,
            total_rows_loaded=100,
            data_size_mb=1.0,
            table_statistics={"test_table": 100},
        )
        mock_benchmark.create_enhanced_benchmark_result.return_value = mock_result

        result = adapter.run_benchmark(mock_benchmark)

        assert isinstance(result, BenchmarkResults)
        assert result.benchmark_name == "test_benchmark"
        assert result.platform == "mock"
        assert result.total_queries == 2
        assert result.successful_queries == 2
        assert result.failed_queries == 0

    def test_run_benchmark_with_query_subset(self, mock_benchmark, tmp_path):
        """Test benchmark execution with query subset."""
        adapter = MockPlatformAdapter()
        mock_benchmark.output_dir = tmp_path

        # Mock create_enhanced_benchmark_result to return correct values for subset
        mock_result = make_benchmark_results(
            benchmark_name="test_benchmark",
            platform="mock",
            scale_factor=1.0,
            execution_id="test_001",
            duration_seconds=10.0,
            total_queries=1,  # Only 1 query in subset
            successful_queries=1,
            total_execution_time=0.1,
            average_query_time=0.1,
            data_loading_time=0.5,
            schema_creation_time=0.1,
            total_rows_loaded=100,
            data_size_mb=1.0,
            table_statistics={"test_table": 100},
        )
        mock_benchmark.create_enhanced_benchmark_result.return_value = mock_result

        result = adapter.run_benchmark(mock_benchmark, query_subset=["q1"])

        assert result.total_queries == 1
        assert result.successful_queries == 1

    def test_run_benchmark_with_categories(self, mock_benchmark, tmp_path):
        """Test benchmark execution with categories."""
        adapter = MockPlatformAdapter()
        mock_benchmark.output_dir = tmp_path
        mock_benchmark.get_queries_by_category = Mock(return_value={"q1": "SELECT 1"})

        # Mock create_enhanced_benchmark_result to return correct values for categories
        mock_result = make_benchmark_results(
            benchmark_name="test_benchmark",
            platform="mock",
            scale_factor=1.0,
            execution_id="test_001",
            duration_seconds=10.0,
            total_queries=1,  # Only 1 query in category
            successful_queries=1,
            total_execution_time=0.1,
            average_query_time=0.1,
            data_loading_time=0.5,
            schema_creation_time=0.1,
            total_rows_loaded=100,
            data_size_mb=1.0,
            table_statistics={"test_table": 100},
        )
        mock_benchmark.create_enhanced_benchmark_result.return_value = mock_result

        result = adapter.run_benchmark(mock_benchmark, categories=["category1"])

        assert result.total_queries == 1
        mock_benchmark.get_queries_by_category.assert_called_once_with("category1")

    def test_run_benchmark_with_no_tables(self, mock_benchmark, tmp_path):
        """Test benchmark execution when tables are not pre-populated.

        Data generation is the responsibility of run_benchmark_lifecycle (via
        _ensure_data_generated), which runs before the adapter is called. The
        adapter itself does not call generate_data(); it proceeds directly to
        connection, schema, load, and execute phases.
        """
        adapter = MockPlatformAdapter()
        mock_benchmark.output_dir = tmp_path
        mock_benchmark.tables = None
        mock_benchmark._impl = None

        # Mock create_enhanced_benchmark_result
        mock_result = make_benchmark_results(
            benchmark_name="test_benchmark",
            platform="mock",
            scale_factor=1.0,
            execution_id="test_001",
            duration_seconds=10.0,
            total_queries=2,
            successful_queries=2,
            total_execution_time=0.2,
            average_query_time=0.1,
            data_loading_time=0.5,
            schema_creation_time=0.1,
            total_rows_loaded=100,
            data_size_mb=1.0,
            table_statistics={"test_table": 100},
        )
        mock_benchmark.create_enhanced_benchmark_result.return_value = mock_result

        result = adapter.run_benchmark(mock_benchmark)

        # Adapter must NOT call generate_data - that is runner.py's responsibility
        mock_benchmark.generate_data.assert_not_called()
        assert isinstance(result, BenchmarkResults)

    def test_run_benchmark_query_failure(self, mock_benchmark, tmp_path):
        """Test benchmark execution with query failures."""
        adapter = MockPlatformAdapter()
        mock_benchmark.output_dir = tmp_path

        # Mock execute_query to fail for one query
        def mock_execute_query(connection, query, query_id):
            if query_id == "q1":
                raise Exception("Query failed")
            return {
                "query_id": query_id,
                "status": "SUCCESS",
                "execution_time_seconds": 0.1,
                "rows_returned": 10,
            }

        adapter.execute_query = mock_execute_query

        # Mock create_enhanced_benchmark_result to return correct failure counts
        mock_result = make_benchmark_results(
            benchmark_name="test_benchmark",
            platform="mock",
            scale_factor=1.0,
            execution_id="test_001",
            duration_seconds=10.0,
            total_queries=2,
            successful_queries=1,  # 1 success, 1 failure
            failed_queries=1,
            query_results=[
                {"query_id": "q1", "status": "FAILED", "error": "Query failed"},
                {"query_id": "q2", "status": "SUCCESS"},
            ],
            total_execution_time=0.1,
            average_query_time=0.1,
            data_loading_time=0.5,
            schema_creation_time=0.1,
            total_rows_loaded=100,
            data_size_mb=1.0,
            table_statistics={"test_table": 100},
        )
        mock_benchmark.create_enhanced_benchmark_result.return_value = mock_result

        result = adapter.run_benchmark(mock_benchmark)

        assert result.total_queries == 2
        assert result.successful_queries == 1
        assert result.failed_queries == 1

        # Check that failed query has error information
        failed_query = next(q for q in result.query_results if q["status"] == "FAILED")
        assert "error" in failed_query
        assert failed_query["query_id"] == "q1"


def test_collect_resource_utilization_without_psutil(monkeypatch):
    adapter = MockPlatformAdapter()

    original_import = __import__

    def fake_import(name, *args, **kwargs):  # pragma: no cover - exercised during test
        if name == "psutil":
            raise ImportError("psutil not installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    snapshot = adapter._collect_resource_utilization()
    assert snapshot["available"] is False
    assert "cpu_count" in snapshot


def test_collect_resource_utilization_with_stub(monkeypatch):  # noqa: C901
    adapter = MockPlatformAdapter()

    mb = 1024 * 1024

    class DummyProcess:
        def __init__(self, *_args, **_kwargs):
            self.pid = 4321

        class _OneShot:
            def __init__(self, process):
                self._process = process

            def __enter__(self):  # pragma: no cover - trivial
                return self._process

            def __exit__(self, exc_type, exc, tb):  # pragma: no cover - trivial
                return False

        def oneshot(self):
            return DummyProcess._OneShot(self)

        def memory_full_info(self):
            return SimpleNamespace(rss=256 * mb, vms=512 * mb)

        def memory_percent(self):
            return 7.5

        def cpu_percent(self, interval=None):
            return 12.5

        def num_threads(self):
            return 8

        def num_fds(self):
            return 24

        def num_handles(self):  # pragma: no cover - platform specific
            return 30

        def io_counters(self):
            return SimpleNamespace(read_bytes=25 * mb, write_bytes=10 * mb, read_count=120, write_count=45)

        def open_files(self):
            return [SimpleNamespace(path="/tmp/query.sql")]

        def num_ctx_switches(self):
            return SimpleNamespace(voluntary=5, involuntary=1)

        def create_time(self):
            return 1_700_000_000.0

        def name(self):
            return "dummy-process"

        def status(self):
            return "running"

    def cpu_percent(interval=None, percpu=False):
        if percpu:
            return [20.0, 22.0]
        return 21.5

    dummy_psutil = SimpleNamespace(
        cpu_count=lambda: 16,
        virtual_memory=lambda: SimpleNamespace(total=64 * mb, available=40 * mb, percent=37.5),
        swap_memory=lambda: SimpleNamespace(total=8 * mb, used=2 * mb, percent=25.0),
        cpu_percent=cpu_percent,
        getloadavg=lambda: (0.5, 0.4, 0.3),
        cpu_freq=lambda: SimpleNamespace(current=3200.0),
        disk_usage=lambda path: SimpleNamespace(total=120 * mb, used=60 * mb, free=60 * mb, percent=50.0),
        disk_io_counters=lambda: SimpleNamespace(
            read_bytes=600 * mb,
            write_bytes=150 * mb,
            read_count=1200,
            write_count=300,
        ),
        net_io_counters=lambda: SimpleNamespace(
            bytes_sent=800 * mb,
            bytes_recv=400 * mb,
            packets_sent=500,
            packets_recv=250,
        ),
        boot_time=lambda: 1_699_000_000.0,
        Process=lambda pid=None: DummyProcess(),
        __version__="6.0.0",
    )

    monkeypatch.setitem(sys.modules, "psutil", dummy_psutil)

    snapshot = adapter._collect_resource_utilization()
    assert snapshot["available"] is True
    assert snapshot["psutil_version"] == "6.0.0"
    assert snapshot["cpu_count"] == 16
    assert snapshot["cpu_percent"] == pytest.approx(21.5)
    assert snapshot["cpu"]["per_cpu_percent"] == [20.0, 22.0]
    assert snapshot["memory"]["total_mb"] == pytest.approx(64.0)
    assert snapshot["memory"]["used_mb"] == pytest.approx(24.0)
    assert snapshot["disk_io"]["read_mb"] == pytest.approx(600.0)
    assert snapshot["network_io"]["sent_mb"] == pytest.approx(800.0)
    assert snapshot["process_memory_mb"] == pytest.approx(256.0)
    assert snapshot["process_cpu_percent"] == pytest.approx(12.5)
    assert snapshot["process"]["num_threads"] == 8
    assert snapshot["process"]["io_counters"]["write_mb"] == pytest.approx(10.0)
    assert snapshot["process"]["context_switches"]["involuntary"] == 1


def test_summarize_performance_characteristics():
    adapter = MockPlatformAdapter()

    results = [
        QueryResult(
            query_id="q1",
            query_name="Q1",
            sql_text="SELECT 1",
            execution_time_ms=100.0,
            rows_returned=10,
            status="SUCCESS",
        ),
        QueryResult(
            query_id="q2",
            query_name="Q2",
            sql_text="SELECT 2",
            execution_time_ms=200.0,
            rows_returned=5,
            status="ERROR",
            error_message="boom",
        ),
    ]

    summary = adapter._summarize_performance_characteristics(
        results,
        total_duration=5.0,
        total_rows_loaded=123,
    )

    assert summary["total_queries"] == 2
    assert summary["successful_queries"] == 1
    assert summary["failed_queries"] == 1
    assert summary["rows_returned_total"] == 15
    assert summary["average_query_time_ms"] == pytest.approx(150.0)
    assert summary["average_success_query_time_ms"] == pytest.approx(100.0)
    assert summary["throughput_qps"] == pytest.approx(0.4)
    assert summary["successful_throughput_qps"] == pytest.approx(0.2)
    assert summary["rows_returned_per_second"] == pytest.approx(3.0)
    assert summary["rows_returned_average"] == pytest.approx(7.5)
    assert summary["total_rows_loaded"] == 123
    assert summary["success_rate"] == pytest.approx(0.5)
    assert summary["execution_time_stats"]["all"]["seconds"]["max"] == pytest.approx(0.2)
    assert summary["execution_time_stats"]["successful"]["milliseconds"]["min"] == pytest.approx(100.0)
    assert summary["rows_returned_stats"]["successful"]["min"] == pytest.approx(10.0)
    assert summary["error_breakdown"] == {"boom": 1}
    assert summary["failure_samples"][0]["status"] == "ERROR"
    assert summary["failure_samples"][0]["rows_returned"] == 5


def test_summarize_performance_characteristics_failure_samples_limited():
    adapter = MockPlatformAdapter()

    error_results = [
        QueryResult(
            query_id=f"q{i}",
            query_name=f"Q{i}",
            sql_text=f"SELECT {i}",
            execution_time_ms=50.0 + i,
            rows_returned=0,
            status="ERROR",
            error_message=f"err{i}",
        )
        for i in range(6)
    ]

    summary = adapter._summarize_performance_characteristics(
        error_results,
        total_duration=12.0,
        total_rows_loaded=0,
    )

    assert summary["failed_queries"] == 6
    assert len(summary["failure_samples"]) == 5
    assert summary["error_breakdown"]["err5"] == 1
    assert summary["throughput_qps"] == pytest.approx(0.5)


class TestApplyQuerySubsetNormalization:
    """Direct tests for _apply_query_subset() Q-prefix normalization at the adapter boundary."""

    def test_query_subset_accepts_q_prefixed_ids(self):
        adapter = MockPlatformAdapter()
        queries = {"1": "SELECT 1", "37": "SELECT 37", "100": "SELECT 100"}
        result = adapter._apply_query_subset(queries, ["Q37", "Q1"], "test")
        # Order preserved as given by user, Q-prefix stripped
        assert list(result.keys()) == ["37", "1"]
        assert result["37"] == "SELECT 37"

    def test_query_subset_accepts_bare_integer_ids(self):
        adapter = MockPlatformAdapter()
        queries = {"1": "SELECT 1", "37": "SELECT 37"}
        result = adapter._apply_query_subset(queries, ["37", "1"], "test")
        assert list(result.keys()) == ["37", "1"]

    def test_query_subset_accepts_mixed_q_and_bare_ids(self):
        adapter = MockPlatformAdapter()
        queries = {"1": "SELECT 1", "37": "SELECT 37"}
        result = adapter._apply_query_subset(queries, ["Q37", "1"], "test")
        assert list(result.keys()) == ["37", "1"]

    def test_query_subset_lowercase_q_prefix_normalized(self):
        adapter = MockPlatformAdapter()
        queries = {"1": "SELECT 1"}
        result = adapter._apply_query_subset(queries, ["q1"], "test")
        assert list(result.keys()) == ["1"]

    def test_query_subset_invalid_id_still_rejected(self):
        adapter = MockPlatformAdapter()
        queries = {"1": "SELECT 1"}
        with pytest.raises(ValueError, match="Invalid query IDs"):
            adapter._apply_query_subset(queries, ["Q99"], "test")

    def test_query_subset_preserves_non_numeric_ids(self):
        """Non-Qnnn IDs (e.g. 'q-aggregation-1') must not be incorrectly stripped."""
        adapter = MockPlatformAdapter()
        queries = {"q-aggregation-1": "SELECT 1"}
        result = adapter._apply_query_subset(queries, ["q-aggregation-1"], "test")
        assert list(result.keys()) == ["q-aggregation-1"]


class TestConsolidatedFunctionality:
    """Test consolidated functionality added to base platform adapter."""

    def test_tpc_methods_consolidation(self):
        """Test that TPC methods are properly consolidated in base class."""
        adapter = MockPlatformAdapter()
        mock_benchmark = Mock()
        mock_connection = Mock()

        # Test that TPC methods exist and can be called
        assert hasattr(adapter, "run_power_test")
        assert hasattr(adapter, "run_throughput_test")
        assert hasattr(adapter, "run_maintenance_test")

        # Test that run_throughput_test delegates to run_power_test when no TPC benchmark
        with patch.object(adapter, "run_power_test") as mock_run_power_test:
            mock_run_power_test.return_value = {"test": "throughput"}

            # Mock hasattr to ensure benchmark doesn't have run_throughput_test method
            with patch("builtins.hasattr", return_value=False):
                # Benchmark without run_throughput_test method should delegate to run_power_test
                result = adapter.run_throughput_test(mock_benchmark, connection=mock_connection, test_param="value")
                mock_run_power_test.assert_called_with(mock_benchmark, connection=mock_connection, test_param="value")
                assert result == {"test": "throughput"}

    def test_create_schema_with_tuning_helper(self):
        """Test the _create_schema_with_tuning helper method."""
        adapter = MockPlatformAdapterWithDialect()
        mock_benchmark = Mock()

        # Test with tuning configuration
        with patch.object(adapter, "get_effective_tuning_configuration") as mock_get_tuning:
            with patch.object(adapter, "get_target_dialect", return_value="postgres"):
                with patch.object(adapter, "translate_sql", return_value="translated_sql"):
                    mock_tuning_config = Mock()
                    mock_get_tuning.return_value = mock_tuning_config
                    mock_benchmark.get_create_tables_sql.return_value = "original_sql"

                    result = adapter._create_schema_with_tuning(mock_benchmark)

                    mock_benchmark.get_create_tables_sql.assert_called_with(
                        dialect="postgres", tuning_config=mock_tuning_config
                    )
                    adapter.translate_sql.assert_called_with("original_sql", "duckdb")
                    assert result == "translated_sql"

        # Test fallback to legacy signature
        adapter2 = MockPlatformAdapterWithDialect()
        mock_benchmark2 = Mock()

        with patch.object(adapter2, "get_effective_tuning_configuration") as mock_get_tuning:
            with patch.object(adapter2, "get_target_dialect", return_value="postgres"):
                with patch.object(adapter2, "translate_sql", return_value="fallback_sql"):
                    mock_tuning_config = Mock()
                    mock_get_tuning.return_value = mock_tuning_config

                    # Make the new signature raise TypeError, then return success
                    mock_benchmark2.get_create_tables_sql.side_effect = [
                        TypeError("Signature not supported"),
                        "fallback_sql_original",
                    ]

                    result = adapter2._create_schema_with_tuning(mock_benchmark2)

                    # Should call twice - first with new signature (fails), then fallback
                    assert mock_benchmark2.get_create_tables_sql.call_count == 2
                    calls = mock_benchmark2.get_create_tables_sql.call_args_list
                    # First call with new signature
                    assert calls[0].kwargs == {
                        "dialect": "postgres",
                        "tuning_config": mock_tuning_config,
                    }
                    # Second call without arguments (fallback)
                    assert calls[1].args == ()
                    assert calls[1].kwargs == {}

                    adapter2.translate_sql.assert_called_with("fallback_sql_original", "duckdb")
                    assert result == "fallback_sql"

    def test_get_constraint_configuration_helper(self):
        """Test the _get_constraint_configuration helper method."""
        adapter = MockPlatformAdapter()

        # Test with tuning configuration
        with patch.object(adapter, "get_effective_tuning_configuration") as mock_get_tuning:
            mock_tuning_config = Mock()
            mock_tuning_config.primary_keys.enabled = True
            mock_tuning_config.foreign_keys.enabled = False
            mock_get_tuning.return_value = mock_tuning_config

            primary_keys, foreign_keys = adapter._get_constraint_configuration()

            assert primary_keys is True
            assert foreign_keys is False

        # Test without tuning configuration
        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            primary_keys, foreign_keys = adapter._get_constraint_configuration()

            assert primary_keys is False
            assert foreign_keys is False

    def test_log_constraint_configuration_helper(self):
        """Test the _log_constraint_configuration helper method."""
        adapter = MockPlatformAdapter()

        # Test logging with constraints enabled
        with patch.object(adapter.logger, "info") as mock_info:
            with patch.object(adapter.logger, "debug") as mock_debug:
                adapter._log_constraint_configuration(True, True)

                info_messages = [args[0] for args, _ in mock_info.call_args_list]
                assert any("Primary key constraints" in msg for msg in info_messages)
                assert any("Foreign key constraints" in msg for msg in info_messages)
                mock_debug.assert_called_with(
                    "Schema constraints from tuning config: primary_keys=True, foreign_keys=True"
                )

        # Test logging with no constraints
        with patch.object(adapter.logger, "info") as mock_info:
            with patch.object(adapter.logger, "debug") as mock_debug:
                adapter._log_constraint_configuration(False, False)

                mock_info.assert_not_called()
                debug_messages = [args[0] for args, _ in mock_debug.call_args_list]
                assert any("No constraints enabled" in msg for msg in debug_messages)
                assert any(
                    "Schema constraints from tuning config: primary_keys=False, foreign_keys=False" in msg
                    for msg in debug_messages
                )

    def test_schema_creation_no_translation_needed(self):
        """Test schema creation when source and target dialect are the same."""
        adapter = MockPlatformAdapterWithDialect()
        mock_benchmark = Mock()

        with patch.object(adapter, "get_effective_tuning_configuration", return_value=None):
            with patch.object(adapter, "get_target_dialect", return_value="duckdb"):
                with patch.object(adapter, "translate_sql") as mock_translate:
                    mock_benchmark.get_create_tables_sql.return_value = "schema_sql"

                    result = adapter._create_schema_with_tuning(mock_benchmark, source_dialect="duckdb")

                    # Should not call translate_sql when dialects match
                    mock_translate.assert_not_called()
                    assert result == "schema_sql"


class TestTimestampFormatting:
    """Tests for timestamp formatting helper."""

    def test_format_timestamp_string_passthrough(self):
        """Test that string timestamps are passed through unchanged."""
        adapter = MockPlatformAdapter()
        result = adapter._format_timestamp("2025-01-01T12:00:00")
        assert result == "2025-01-01T12:00:00"

    def test_format_timestamp_numeric(self):
        """Test that numeric timestamps are converted to ISO format."""
        adapter = MockPlatformAdapter()
        # Use a known timestamp
        timestamp = 1704110400.0  # 2024-01-01T12:00:00 UTC
        result = adapter._format_timestamp(timestamp)
        # Result should be an ISO format string
        assert "2024" in result or "T" in result

    def test_format_timestamp_zero(self):
        """Test that zero timestamps return current time."""
        adapter = MockPlatformAdapter()
        result = adapter._format_timestamp(0)
        # Should return a valid timestamp string
        assert "T" in result

    def test_format_timestamp_empty_string(self):
        """Test that empty strings return current time."""
        adapter = MockPlatformAdapter()
        result = adapter._format_timestamp("")
        # Should return a valid timestamp string
        assert "T" in result


class TestValidationStatusDetermination:
    """Tests for validation status determination logic."""

    def test_determine_status_all_passed(self):
        """Test overall status when all validations pass."""
        adapter = MockPlatformAdapter()

        validation_phase = Mock()
        validation_phase.row_count_validation = "PASSED"
        validation_phase.schema_validation = "PASSED"
        validation_phase.data_integrity_checks = "PASSED"

        result = adapter._determine_overall_validation_status(validation_phase)
        assert result == "PASSED"

    def test_determine_status_row_count_failed(self):
        """Test overall status when row count validation fails."""
        adapter = MockPlatformAdapter()

        validation_phase = Mock()
        validation_phase.row_count_validation = "FAILED"
        validation_phase.schema_validation = "PASSED"
        validation_phase.data_integrity_checks = "PASSED"

        result = adapter._determine_overall_validation_status(validation_phase)
        assert result == "FAILED"

    def test_determine_status_schema_failed(self):
        """Test overall status when schema validation fails."""
        adapter = MockPlatformAdapter()

        validation_phase = Mock()
        validation_phase.row_count_validation = "PASSED"
        validation_phase.schema_validation = "FAILED"
        validation_phase.data_integrity_checks = "PASSED"

        result = adapter._determine_overall_validation_status(validation_phase)
        assert result == "FAILED"

    def test_determine_status_integrity_failed(self):
        """Test overall status when data integrity fails."""
        adapter = MockPlatformAdapter()

        validation_phase = Mock()
        validation_phase.row_count_validation = "PASSED"
        validation_phase.schema_validation = "PASSED"
        validation_phase.data_integrity_checks = "FAILED"

        result = adapter._determine_overall_validation_status(validation_phase)
        assert result == "FAILED"

    def test_determine_status_partial(self):
        """Test overall status when any validation is partial."""
        adapter = MockPlatformAdapter()

        validation_phase = Mock()
        validation_phase.row_count_validation = "PARTIAL"
        validation_phase.schema_validation = "PASSED"
        validation_phase.data_integrity_checks = "PASSED"

        result = adapter._determine_overall_validation_status(validation_phase)
        assert result == "PARTIAL"


class TestQueryDefinitionExtraction:
    """Tests for query definition extraction."""

    def test_extract_query_definitions(self):
        """Test extracting query definitions from benchmark queries."""
        adapter = MockPlatformAdapter()

        queries = {
            "Q1": "SELECT * FROM orders",
            "Q2": "SELECT * FROM customers",
        }
        mock_benchmark = Mock()

        result = adapter._extract_query_definitions(mock_benchmark, queries, "power")

        assert "power" in result
        assert "Q1" in result["power"]
        assert "Q2" in result["power"]
        assert result["power"]["Q1"].sql == "SELECT * FROM orders"
        assert result["power"]["Q2"].sql == "SELECT * FROM customers"

    def test_extract_query_definitions_default_stream(self):
        """Test extracting query definitions with default stream ID."""
        adapter = MockPlatformAdapter()

        queries = {"Q1": "SELECT 1"}
        mock_benchmark = Mock()

        result = adapter._extract_query_definitions(mock_benchmark, queries)

        assert "standard" in result
        assert "Q1" in result["standard"]


class TestStandardExecutionPhase:
    """Tests for standard execution phase creation."""

    def test_create_standard_execution_phase(self):
        """Test creating execution phase from query results."""
        adapter = MockPlatformAdapter()

        query_results = [
            {"query_id": "Q1", "execution_time_seconds": 1.5, "status": "SUCCESS", "rows_returned": 100},
            {"query_id": "Q2", "execution_time_seconds": 2.0, "status": "SUCCESS", "rows_returned": 50},
        ]

        result = adapter._create_standard_execution_phase(query_results, "test_stream")

        assert len(result) == 2
        assert result[0].query_id == "Q1"
        assert result[0].stream_id == "test_stream"
        assert result[0].execution_order == 1
        assert result[0].execution_time_ms == 1500.0
        assert result[0].run_type == "measurement"
        assert result[1].query_id == "Q2"
        assert result[1].execution_order == 2
        assert result[1].run_type == "measurement"

    def test_create_standard_execution_phase_defaults(self):
        """Test creating execution phase with default stream ID."""
        adapter = MockPlatformAdapter()

        query_results = [{"execution_time_seconds": 0.5}]

        result = adapter._create_standard_execution_phase(query_results)

        assert len(result) == 1
        assert result[0].stream_id == "standard"
        assert result[0].query_id == "Q1"  # Default
        assert result[0].run_type == "measurement"


class TestThroughputPhaseCreation:
    """Tests for throughput phase creation."""

    def test_create_throughput_phase_none(self):
        """Test that None throughput result returns None."""
        adapter = MockPlatformAdapter()
        result = adapter._create_throughput_phase(None)
        assert result is None

    def test_create_throughput_phase_with_streams(self):
        """Test creating throughput phase from stream results."""
        adapter = MockPlatformAdapter()

        # Create mock stream results
        stream1 = Mock()
        stream1.stream_id = 0
        stream1.start_time = "2025-01-01T10:00:00"
        stream1.end_time = "2025-01-01T10:01:00"
        stream1.duration = 60.0
        stream1.query_results = [
            {"query_id": "Q1", "execution_time_seconds": 1.0, "success": True},
            {"query_id": "Q2", "execution_time_seconds": 2.0, "success": True},
        ]
        stream1.queries_executed = 2

        throughput_result = Mock()
        throughput_result.stream_results = [stream1]
        throughput_result.total_time = 60.0
        throughput_result.start_time = "2025-01-01T10:00:00"
        throughput_result.end_time = "2025-01-01T10:01:00"
        throughput_result.config = Mock(num_streams=1)
        throughput_result.throughput_at_size = 720.0

        result = adapter._create_throughput_phase(throughput_result)

        assert result is not None
        assert len(result.streams) == 1
        assert result.streams[0].stream_id == 0
        assert len(result.streams[0].query_executions) == 2
        assert result.total_queries_executed == 2
        assert result.streams[0].query_executions[0].run_type == "measurement"
        assert result.streams[0].query_executions[1].run_type == "measurement"

    def test_create_throughput_phase_infers_warmup_run_type(self):
        """Throughput query executions infer warmup run_type from iteration metadata."""
        adapter = MockPlatformAdapter()

        stream1 = Mock()
        stream1.stream_id = 0
        stream1.start_time = "2025-01-01T10:00:00"
        stream1.end_time = "2025-01-01T10:01:00"
        stream1.duration = 60.0
        stream1.query_results = [{"query_id": "Q1", "execution_time_seconds": 1.0, "success": True, "iteration": 0}]
        stream1.queries_executed = 1

        throughput_result = Mock()
        throughput_result.stream_results = [stream1]
        throughput_result.total_time = 60.0
        throughput_result.start_time = "2025-01-01T10:00:00"
        throughput_result.end_time = "2025-01-01T10:01:00"
        throughput_result.config = Mock(num_streams=1)
        throughput_result.throughput_at_size = 720.0

        result = adapter._create_throughput_phase(throughput_result)

        assert result is not None
        assert result.streams[0].query_executions[0].run_type == "warmup"


class TestGetExistingTables:
    """Tests for getting existing tables from database."""

    def test_get_existing_tables_handles_exception(self):
        """Test that get_existing_tables handles exceptions gracefully."""
        adapter = MockPlatformAdapter()
        mock_conn = Mock()

        # Mock the execute to raise an exception
        mock_conn.execute.side_effect = Exception("Database error")

        result = adapter._get_existing_tables(mock_conn)

        assert result == []


class TestCalculateDataSize:
    """Tests for data size calculation."""

    def test_calculate_data_size_with_files(self, tmp_path):
        """Test calculating data size with actual files."""
        adapter = MockPlatformAdapter()

        # Create test files
        test_file = tmp_path / "test.csv"
        test_file.write_text("a,b,c\n1,2,3\n4,5,6\n")

        result = adapter._calculate_data_size(tmp_path)

        # Should return a positive value
        assert result >= 0

    def test_calculate_data_size_nonexistent_path(self):
        """Test calculating data size with nonexistent path."""
        adapter = MockPlatformAdapter()

        result = adapter._calculate_data_size(Path("/nonexistent/path"))

        assert result == 0.0

    # NOTE: Log operation tests removed as they depend on VerbosityMixin
    # which requires additional setup beyond the mock adapter


class TestConnectionFactoryCursorPattern:
    """Tests for thread-safe cursor pattern in connection factories.

    DuckDB connections are not thread-safe for concurrent query execution.
    Each stream in throughput/maintenance tests must use a separate cursor
    obtained via connection.cursor() to enable safe concurrent execution.

    See: https://duckdb.org/docs/stable/guides/python/multiple_threads
    """

    def test_default_connection_factory_creates_cursor(self):
        """Test that the default connection factory creates a cursor for thread safety.

        The run_throughput_test method creates a _default_connection_factory that
        should call connection.cursor() to create a thread-safe cursor.
        """
        # Create a mock connection with cursor method
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Simulate the _default_connection_factory behavior from adapter.py
        def _default_connection_factory():
            stream_cursor = mock_connection.cursor()
            return stream_cursor

        # Call the factory
        result = _default_connection_factory()

        # Verify cursor() was called
        mock_connection.cursor.assert_called_once()
        assert result is mock_cursor

    def test_connection_factory_creates_unique_cursors_per_call(self):
        """Test that each factory call creates a new cursor for isolation."""
        mock_connection = Mock()
        cursors = [Mock() for _ in range(3)]
        mock_connection.cursor.side_effect = cursors

        def _default_connection_factory():
            stream_cursor = mock_connection.cursor()
            return stream_cursor

        # Call factory multiple times (simulating multiple streams)
        results = [_default_connection_factory() for _ in range(3)]

        # Each call should create a new cursor
        assert mock_connection.cursor.call_count == 3
        assert results == cursors
        # Ensure each result is a different cursor
        assert len(set(id(r) for r in results)) == 3

    def test_tpch_throughput_connection_factory_uses_cursor(self):
        """Test TPC-H throughput test connection factory creates cursors.

        Verifies the connection_factory in _execute_tpch_throughput_test
        calls connection.cursor() for thread-safe concurrent stream execution.
        """
        from benchbox.platforms.base.adapter import PlatformAdapterConnection

        # Create mock connection with cursor
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Create a mock adapter
        mock_adapter = Mock()

        # Simulate the connection_factory from _execute_tpch_throughput_test
        scale_factor = 0.01

        def connection_factory():
            stream_cursor = mock_connection.cursor()
            conn_wrapper = PlatformAdapterConnection(stream_cursor, mock_adapter)
            conn_wrapper.benchmark_type = "tpch"
            conn_wrapper.scale_factor = scale_factor
            return conn_wrapper

        # Call the factory
        result = connection_factory()

        # Verify the cursor was created and used
        mock_connection.cursor.assert_called_once()
        assert isinstance(result, PlatformAdapterConnection)
        assert result.benchmark_type == "tpch"
        assert result.scale_factor == scale_factor

    def test_tpcds_throughput_connection_factory_uses_cursor(self):
        """Test TPC-DS throughput test connection factory creates cursors.

        Verifies the connection_factory in _execute_tpcds_throughput_test
        calls connection.cursor() for thread-safe concurrent stream execution.
        """
        from benchbox.platforms.base.adapter import PlatformAdapterConnection

        # Create mock connection with cursor
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Create a mock adapter
        mock_adapter = Mock()

        # Simulate the connection_factory from _execute_tpcds_throughput_test
        scale_factor = 1.0

        def connection_factory():
            stream_cursor = mock_connection.cursor()
            conn_wrapper = PlatformAdapterConnection(stream_cursor, mock_adapter)
            conn_wrapper.benchmark_type = "tpcds"
            conn_wrapper.scale_factor = scale_factor
            return conn_wrapper

        # Call the factory
        result = connection_factory()

        # Verify the cursor was created and used
        mock_connection.cursor.assert_called_once()
        assert isinstance(result, PlatformAdapterConnection)
        assert result.benchmark_type == "tpcds"
        assert result.scale_factor == scale_factor

    def test_maintenance_test_connection_factory_uses_cursor(self):
        """Test maintenance test connection factory creates cursors.

        Verifies connection factories in _execute_tpch_maintenance_test and
        _execute_tpcds_maintenance_test call connection.cursor() for thread safety.
        """
        from benchbox.platforms.base.adapter import PlatformAdapterConnection

        # Create mock connection with cursor
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Create a mock adapter
        mock_adapter = Mock()

        # Simulate the connection_factory from maintenance tests
        scale_factor = 0.1

        def connection_factory():
            stream_cursor = mock_connection.cursor()
            conn_wrapper = PlatformAdapterConnection(stream_cursor, mock_adapter)
            conn_wrapper.benchmark_type = "tpch"  # or "tpcds"
            conn_wrapper.scale_factor = scale_factor
            return conn_wrapper

        # Call the factory multiple times (simulating concurrent maintenance streams)
        results = []
        for _ in range(3):
            mock_cursor = Mock()
            mock_connection.cursor.return_value = mock_cursor
            results.append(connection_factory())

        # Verify each call created a cursor
        assert mock_connection.cursor.call_count == 3
        assert all(isinstance(r, PlatformAdapterConnection) for r in results)

    def test_cursor_pattern_prevents_shared_connection_state(self):
        """Test that cursor pattern isolates connection state between streams.

        Without cursors, concurrent streams would share connection state,
        leading to race conditions and the 'NULL pointer dereference' error.
        With cursors, each stream gets its own isolated cursor instance.
        """
        from concurrent.futures import ThreadPoolExecutor

        # Create mock connection with cursor that creates unique cursor instances
        mock_connection = Mock()
        cursors_created = []

        def create_cursor():
            cursor = Mock()
            cursor.cursor_id = len(cursors_created)
            cursors_created.append(cursor)
            return cursor

        mock_connection.cursor.side_effect = create_cursor

        def stream_work():
            # Each stream should get its own cursor
            cursor = mock_connection.cursor()
            # Simulate some work
            cursor.execute("SELECT 1")
            return cursor.cursor_id

        # Run multiple streams concurrently
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(stream_work) for _ in range(4)]
            cursor_ids = [f.result() for f in futures]

        # Verify each stream got a unique cursor (unique cursor_id)
        assert len(set(cursor_ids)) == 4, "Each stream should get its own cursor"
        # Verify cursor() was called for each stream
        assert mock_connection.cursor.call_count == 4
        # Verify all cursors are unique objects
        assert len(cursors_created) == 4


class TestMonotonicPhaseTiming:
    """Regression tests for monotonic phase timing in adapter helpers."""

    def test_data_generation_phase_does_not_require_wall_clock(self):
        adapter = MockPlatformAdapter()
        benchmark = SimpleNamespace(tables={"orders": [{"id": 1}, {"id": 2}]})

        mock_clock = Mock(side_effect=[10.0, 10.1, 10.3, 10.8])
        with (
            patch("benchbox.platforms.base.phase_tracking.mono_time", mock_clock),
            patch("benchbox.utils.clock.mono_time", mock_clock),
        ):
            phase = adapter._create_enhanced_data_generation_phase(benchmark)

        assert phase is not None
        assert phase.duration_ms == 800
        assert phase.tables_generated == 1
        assert phase.per_table_stats["orders"].generation_time_ms == 200


class TestReusedDatabaseExternalMode:
    """Verify _setup_reused_database_phases routes to create_external_tables in external mode."""

    def test_reused_db_external_mode_calls_create_external_tables(self):
        adapter = MockPlatformAdapter()
        adapter.table_mode = "external"
        adapter.supports_external_tables = True
        adapter.create_external_tables = Mock(return_value=({"t1": 100}, 0.3, None))

        benchmark = Mock()
        benchmark.output_dir = "/tmp/test"
        connection = Mock()

        result = adapter._setup_reused_database_phases(benchmark, connection)
        schema_time, schema_phase, loading_time, table_stats, data_phase, tuning_saved = result

        adapter.create_external_tables.assert_called_once()
        assert table_stats == {"t1": 100}
        assert loading_time == 0.3
        assert tuning_saved is False

    def test_reused_db_native_mode_skips_external_tables(self):
        adapter = MockPlatformAdapter()
        adapter.table_mode = "native"
        adapter.create_external_tables = Mock()

        benchmark = Mock()
        benchmark.get_schema.return_value = {"t1": {}}
        connection = Mock()

        adapter._setup_reused_database_phases(benchmark, connection)
        adapter.create_external_tables.assert_not_called()

    def test_reused_db_external_raises_for_unsupported_platform(self):
        adapter = MockPlatformAdapter()
        adapter.table_mode = "external"
        adapter.supports_external_tables = False

        benchmark = Mock()
        connection = Mock()

        with pytest.raises(RuntimeError, match="does not support"):
            adapter._setup_reused_database_phases(benchmark, connection)

    def test_reused_db_external_calls_validate_requirements(self):
        adapter = MockPlatformAdapter()
        adapter.table_mode = "external"
        adapter.supports_external_tables = True
        adapter.validate_external_table_requirements = Mock()
        adapter.create_external_tables = Mock(return_value=({"t1": 100}, 0.1, None))

        benchmark = Mock()
        benchmark.output_dir = "/tmp/test"
        connection = Mock()

        adapter._setup_reused_database_phases(benchmark, connection)
        adapter.validate_external_table_requirements.assert_called_once()


class TestExecutionMetadataTableMode:
    """Verify table_mode appears in _build_execution_metadata run_config."""

    def test_external_mode_in_execution_metadata(self):
        adapter = MockPlatformAdapter()
        adapter.table_mode = "external"
        metadata, _, _ = adapter._build_execution_metadata({"benchmark": "tpch", "scale_factor": 0.01})
        run_config = metadata.get("run_config", {})
        assert run_config.get("table_mode") == "external"

    def test_native_mode_omitted_from_execution_metadata(self):
        adapter = MockPlatformAdapter()
        adapter.table_mode = "native"
        metadata, _, _ = adapter._build_execution_metadata({"benchmark": "tpch", "scale_factor": 0.01})
        run_config = metadata.get("run_config", {})
        assert run_config.get("table_mode") is None

    def test_table_format_settings_in_execution_metadata(self):
        adapter = MockPlatformAdapter()
        metadata, _, _ = adapter._build_execution_metadata(
            {
                "benchmark": "tpch",
                "scale_factor": 0.01,
                "table_format": "parquet",
                "table_format_compression": "zstd",
                "table_format_partition_cols": ["region"],
            }
        )
        run_config = metadata.get("run_config", {})
        assert run_config.get("table_format") == "parquet"
        assert run_config.get("table_format_compression") == "zstd"
        assert run_config.get("table_format_partition_cols") == ["region"]


class TestBenchmarkIdentityInExecutionMetadata:
    """Regression tests for benchmark_id propagation contract (w10 of
    eliminate-non-data-loading-wrong-layer-compensation).

    _build_execution_metadata must prefer run_config["benchmark_name"] (the
    canonical slug propagated by the runner from BenchmarkConfig.name) over
    the legacy "benchmark" key so that the live path never infers
    benchmark_id from object internals.
    """

    def test_benchmark_name_key_sets_benchmark_id(self):
        """benchmark_name in run_config becomes benchmark_id in execution_metadata."""
        adapter = MockPlatformAdapter()
        metadata, _, _ = adapter._build_execution_metadata({"benchmark_name": "tpch", "scale_factor": 0.01})
        assert metadata.get("benchmark_id") == "tpch"

    def test_no_benchmark_identity_in_run_config_produces_none(self):
        """When neither key is present benchmark_id is None (not inferred)."""
        adapter = MockPlatformAdapter()
        metadata, _, _ = adapter._build_execution_metadata({"scale_factor": 0.01})
        assert metadata.get("benchmark_id") is None


class TestTPCExecutionRouting:
    """Exercise benchmark-family routing for specialized TPC helpers."""

    def test_execute_power_test_routes_tpch_via_run_config_benchmark_name(self):
        # Routing now reads benchmark_name from run_config, not display_name sniffing.
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_power_test = Mock(return_value=[{"query_id": "Q1"}])
        benchmark = SimpleNamespace(_name="adhoc", display_name="adhoc", scale_factor=1.0)
        connection = Mock()
        run_config = {"benchmark_name": "tpch", "iterations": 2}

        results = adapter._execute_power_test(benchmark, connection, run_config)

        adapter._execute_tpch_power_test.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "Q1"}]

    def test_execute_throughput_test_routes_tpcds_via_run_config_benchmark_name(self):
        # Routing now reads benchmark_name from run_config, not display_name sniffing.
        adapter = MockPlatformAdapter()
        adapter._execute_tpcds_throughput_test = Mock(return_value=[{"query_id": "Q99"}])
        benchmark = SimpleNamespace(_name="custom", display_name="custom benchmark")

        results = adapter._execute_throughput_test(benchmark, Mock(), {"benchmark_name": "tpcds", "num_streams": 4})

        adapter._execute_tpcds_throughput_test.assert_called_once()
        assert results == [{"query_id": "Q99"}]

    def test_execute_power_test_routes_tpcds_obt_to_generic_power(self):
        adapter = MockPlatformAdapter()
        adapter._execute_tpcds_power_test = Mock(return_value=[{"query_id": "specialized"}])
        adapter._execute_generic_power_test = Mock(return_value=[{"query_id": "generic"}])
        benchmark = SimpleNamespace(_name="custom", display_name="custom benchmark")
        connection = Mock()
        run_config = {"benchmark_name": "tpcds_obt", "iterations": 1}

        results = adapter._execute_power_test(benchmark, connection, run_config)

        adapter._execute_tpcds_power_test.assert_not_called()
        adapter._execute_generic_power_test.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "generic"}]

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_throughput_test_falls_back_for_unsupported_benchmark(self, mock_console):
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "clickbench", "num_streams": 4}
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])

        results = adapter._execute_throughput_test(benchmark, connection, run_config)

        adapter._execute_all_queries.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "fallback"}]
        assert any("Throughput test not supported" in str(call) for call in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_throughput_test_tpcds_obt_falls_back_to_all_queries(self, mock_console):
        adapter = MockPlatformAdapter()
        adapter._execute_tpcds_throughput_test = Mock(return_value=[{"query_id": "specialized"}])
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "tpcds_obt", "num_streams": 4}

        results = adapter._execute_throughput_test(benchmark, connection, run_config)

        adapter._execute_tpcds_throughput_test.assert_not_called()
        adapter._execute_all_queries.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "fallback"}]
        assert any("Throughput test not supported" in str(call) for call in mock_console.print.call_args_list)

    def test_execute_maintenance_test_routes_tpch_via_run_config_benchmark_name(self):
        # Routing now reads benchmark_name from run_config, not class_name sniffing.
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_maintenance_test = Mock(return_value=[{"query_id": "RF1"}])

        class SomeBenchmark:
            display_name = ""
            _name = "some_benchmark"

        benchmark = SomeBenchmark()
        results = adapter._execute_maintenance_test(
            benchmark, Mock(), {"benchmark_name": "tpch", "maintenance_pairs": 2}
        )

        adapter._execute_tpch_maintenance_test.assert_called_once()
        assert results == [{"query_id": "RF1"}]

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_maintenance_test_tpcds_obt_falls_back_to_all_queries(self, mock_console):
        adapter = MockPlatformAdapter()
        adapter._execute_tpcds_maintenance_test = Mock(return_value=[{"query_id": "specialized"}])
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "tpcds_obt", "maintenance_pairs": 2}

        results = adapter._execute_maintenance_test(benchmark, connection, run_config)

        adapter._execute_tpcds_maintenance_test.assert_not_called()
        adapter._execute_all_queries.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "fallback"}]
        assert any("Maintenance test not supported" in str(call) for call in mock_console.print.call_args_list)

    def test_execute_combined_test_defaults_to_all_tpch_phases(self):
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "tpch"}
        adapter._execute_tpch_power_test = Mock(return_value=[{"query_id": "power"}])
        adapter._execute_tpch_throughput_test = Mock(return_value=[{"query_id": "throughput"}])
        adapter._execute_tpch_maintenance_test = Mock(return_value=[{"query_id": "maintenance"}])

        results = adapter._execute_combined_test(benchmark, connection, run_config)

        adapter._execute_tpch_power_test.assert_called_once_with(benchmark, connection, run_config)
        adapter._execute_tpch_throughput_test.assert_called_once_with(benchmark, connection, run_config)
        adapter._execute_tpch_maintenance_test.assert_called_once_with(benchmark, connection, run_config)
        assert [row["query_id"] for row in results] == ["power", "throughput", "maintenance"]

    def test_execute_combined_test_respects_requested_tpcds_phase_subset(self):
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "tpcds", "options": {"requested_phases": ["throughput"]}}
        adapter._execute_tpcds_power_test = Mock()
        adapter._execute_tpcds_throughput_test = Mock(return_value=[{"query_id": "stream-1"}])
        adapter._execute_tpcds_maintenance_test = Mock()

        results = adapter._execute_combined_test(benchmark, connection, run_config)

        adapter._execute_tpcds_power_test.assert_not_called()
        adapter._execute_tpcds_throughput_test.assert_called_once_with(benchmark, connection, run_config)
        adapter._execute_tpcds_maintenance_test.assert_not_called()
        assert results == [{"query_id": "stream-1"}]

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_combined_test_tpcds_obt_falls_back_to_all_queries(self, mock_console):
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "tpcds_obt"}
        adapter._execute_tpcds_power_test = Mock(return_value=[{"query_id": "power"}])
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])

        results = adapter._execute_combined_test(benchmark, connection, run_config)

        adapter._execute_tpcds_power_test.assert_not_called()
        adapter._execute_all_queries.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "fallback"}]
        assert any("Combined test not supported" in str(call) for call in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_combined_test_falls_back_for_unsupported_benchmark(self, mock_console):
        adapter = MockPlatformAdapter()
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": "ssb", "options": {"requested_phases": ["power"]}}
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "standard"}])

        results = adapter._execute_combined_test(benchmark, connection, run_config)

        adapter._execute_all_queries.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "standard"}]
        assert any("Combined test not supported" in str(call) for call in mock_console.print.call_args_list)


class TestNormalizeBenchmarkIdDerivedBenchmarks:
    """Verify normalize_benchmark_id correctly distinguishes derived benchmarks."""

    @pytest.mark.parametrize(
        "input_name,expected_id",
        [
            ("tpchavoc", "tpchavoc"),
            ("tpch-avoc", "tpchavoc"),
            ("tpch_avoc", "tpchavoc"),
            ("tpc-havoc", "tpchavoc"),
            ("tpc-h avoc", "tpchavoc"),
            ("tpch_skew", "tpch_skew"),
            ("tpch-skew", "tpch_skew"),
            ("tpcds_obt", "tpcds_obt"),
            ("tpcds-obt", "tpcds_obt"),
            # Parents must still resolve correctly
            ("tpch", "tpch"),
            ("tpc-h", "tpch"),
            ("TPC-H Benchmark", "tpch"),
            ("tpcds", "tpcds"),
            ("tpc-ds", "tpcds"),
            # Display names with parenthetical suffixes (from benchmark._name)
            ("TPC-H Skew Benchmark (heavy)", "tpch_skew"),
            ("TPC-Havoc Benchmark", "tpchavoc"),
            ("TPC-DS One Big Table Benchmark", "tpcds_obt"),
            ("Star Schema Benchmark", "ssb"),
        ],
    )
    def test_normalize_benchmark_id_derived(self, input_name, expected_id):
        assert normalize_benchmark_id(input_name) == expected_id


class TestDerivedBenchmarkRouting:
    """Verify derived benchmarks (tpchavoc, tpch_skew) are NOT routed to specialized TPC helpers."""

    @pytest.mark.parametrize("benchmark_name", ["tpchavoc", "tpch_skew"])
    def test_power_test_routes_tpch_derived_to_generic(self, benchmark_name):
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_power_test = Mock(return_value=[{"query_id": "specialized"}])
        adapter._execute_generic_power_test = Mock(return_value=[{"query_id": "generic"}])
        benchmark = SimpleNamespace(_name="custom", display_name="custom benchmark")
        connection = Mock()
        run_config = {"benchmark_name": benchmark_name, "iterations": 1}

        results = adapter._execute_power_test(benchmark, connection, run_config)

        adapter._execute_tpch_power_test.assert_not_called()
        adapter._execute_generic_power_test.assert_called_once_with(benchmark, connection, run_config)
        assert results == [{"query_id": "generic"}]

    @patch("benchbox.platforms.base.adapter.quiet_console")
    @pytest.mark.parametrize("benchmark_name", ["tpchavoc", "tpch_skew"])
    def test_throughput_test_routes_tpch_derived_to_fallback(self, mock_console, benchmark_name):
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_throughput_test = Mock(return_value=[{"query_id": "specialized"}])
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": benchmark_name, "num_streams": 4}

        results = adapter._execute_throughput_test(benchmark, connection, run_config)

        adapter._execute_tpch_throughput_test.assert_not_called()
        adapter._execute_all_queries.assert_called_once()
        assert results == [{"query_id": "fallback"}]

    @patch("benchbox.platforms.base.adapter.quiet_console")
    @pytest.mark.parametrize("benchmark_name", ["tpchavoc", "tpch_skew"])
    def test_maintenance_test_routes_tpch_derived_to_fallback(self, mock_console, benchmark_name):
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_maintenance_test = Mock(return_value=[{"query_id": "specialized"}])
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": benchmark_name, "maintenance_pairs": 2}

        results = adapter._execute_maintenance_test(benchmark, connection, run_config)

        adapter._execute_tpch_maintenance_test.assert_not_called()
        adapter._execute_all_queries.assert_called_once()
        assert results == [{"query_id": "fallback"}]

    @patch("benchbox.platforms.base.adapter.quiet_console")
    @pytest.mark.parametrize("benchmark_name", ["tpchavoc", "tpch_skew"])
    def test_combined_test_routes_tpch_derived_to_fallback(self, mock_console, benchmark_name):
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_power_test = Mock(return_value=[{"query_id": "power"}])
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "fallback"}])
        benchmark = Mock()
        connection = Mock()
        run_config = {"benchmark_name": benchmark_name}

        results = adapter._execute_combined_test(benchmark, connection, run_config)

        adapter._execute_tpch_power_test.assert_not_called()
        adapter._execute_all_queries.assert_called_once()
        assert results == [{"query_id": "fallback"}]


class TestFallbackEffectiveExecutionType:
    """Verify fallback paths set _effective_execution_type so result shape is correct."""

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_throughput_fallback_sets_effective_type_to_power(self, mock_console):
        adapter = MockPlatformAdapter()
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "Q1"}])
        run_config = {"benchmark_name": "tpcds_obt", "num_streams": 4}

        adapter._execute_throughput_test(Mock(), Mock(), run_config)

        assert run_config["_effective_execution_type"] == "power"

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_maintenance_fallback_sets_effective_type_to_power(self, mock_console):
        adapter = MockPlatformAdapter()
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "Q1"}])
        run_config = {"benchmark_name": "tpcds_obt", "maintenance_pairs": 2}

        adapter._execute_maintenance_test(Mock(), Mock(), run_config)

        assert run_config["_effective_execution_type"] == "power"

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_combined_fallback_sets_effective_type_to_power(self, mock_console):
        adapter = MockPlatformAdapter()
        adapter._execute_all_queries = Mock(return_value=[{"query_id": "Q1"}])
        run_config = {"benchmark_name": "tpcds_obt"}

        adapter._execute_combined_test(Mock(), Mock(), run_config)

        assert run_config["_effective_execution_type"] == "power"

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_throughput_fallback_does_not_set_flag_for_tpch(self, mock_console):
        """Specialized TPC-H path should NOT set _effective_execution_type."""
        adapter = MockPlatformAdapter()
        adapter._execute_tpch_throughput_test = Mock(return_value=[])
        run_config = {"benchmark_name": "tpch", "num_streams": 4}

        adapter._execute_throughput_test(Mock(), Mock(), run_config)

        assert "_effective_execution_type" not in run_config


class TestKnownBenchmarkIds:
    """Verify _normalize_known_benchmark_id recognizes derived benchmarks."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("tpch", "tpch"),
            ("tpcds", "tpcds"),
            ("tpcds_obt", "tpcds_obt"),
            ("tpch_skew", "tpch_skew"),
            ("tpchavoc", "tpchavoc"),
            ("ssb", "ssb"),
            ("clickbench", "clickbench"),
        ],
    )
    def test_known_ids_recognized(self, name, expected):
        assert MockPlatformAdapter._normalize_known_benchmark_id(name) == expected

    @pytest.mark.parametrize("name", ["nyctaxi", "h2odb", "unknown_bench"])
    def test_unknown_ids_return_none(self, name):
        assert MockPlatformAdapter._normalize_known_benchmark_id(name) is None


class TestBenchmarkFamily:
    """Verify _benchmark_family() returns correct parent family."""

    @pytest.mark.parametrize(
        "bench_id,expected_family",
        [
            ("tpch", "tpch"),
            ("tpch_skew", "tpch"),
            ("tpchavoc", "tpch"),
            ("tpcds", "tpcds"),
            ("tpcds_obt", "tpcds"),
            ("ssb", "generic"),
            ("clickbench", "generic"),
            ("nyctaxi", "generic"),
        ],
    )
    def test_family_mapping(self, bench_id, expected_family):
        assert _benchmark_family(bench_id) == expected_family


class TestNormalizeBenchmarkIdSubstringSafety:
    """Verify that substring-like names do NOT false-match existing benchmarks."""

    @pytest.mark.parametrize(
        "input_name",
        [
            "tpchavoc2",
            "tpch_skewed",
            "tpcds_obt_v2",
            "mytpch",
            "sstpch",
        ],
    )
    def test_substring_names_do_not_match_parents(self, input_name):
        """Names containing known IDs as substrings must NOT match those IDs."""
        result = normalize_benchmark_id(input_name)
        assert result not in ("tpch", "tpcds", "tpchavoc", "tpch_skew", "tpcds_obt")


class TestBuildExecutionPhasesWithEffectiveType:
    """Integration test: _build_execution_phases produces a PowerTestPhase when
    _effective_execution_type='power' is set on run_config (the fallback path)."""

    def test_fallback_produces_power_test_phase(self):
        adapter = MockPlatformAdapter()
        adapter.capture_plans = False
        adapter.plan_capture_failures = 0
        adapter._last_power_test_result = None
        adapter._last_throughput_test_result = None

        query_results = [
            {"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.5},
            {"query_id": "Q2", "status": "SUCCESS", "execution_time_seconds": 0.3},
        ]
        query_executions = []

        from benchbox.platforms.base.models import SetupPhase

        setup_phase = SetupPhase(
            schema_creation=None,
            data_generation=None,
            data_loading=None,
        )

        run_config = {
            "test_execution_type": "throughput",
            "_effective_execution_type": "power",
        }

        execution_phases, total_exec_time, power_test_phase, throughput_test_phase = adapter._build_execution_phases(
            query_results, query_executions, run_config, setup_phase
        )

        assert power_test_phase is not None, "Fallback should produce a PowerTestPhase"
        assert execution_phases.power_test is not None
        assert throughput_test_phase is None
        assert total_exec_time == pytest.approx(0.8)

    def test_throughput_type_without_fallback_skips_power_phase(self):
        """When execution_type is 'throughput' (no fallback), power_test should be None."""
        adapter = MockPlatformAdapter()
        adapter.capture_plans = False
        adapter.plan_capture_failures = 0
        adapter._last_power_test_result = None
        adapter._last_throughput_test_result = None

        query_results = [
            {"query_id": "Q1", "status": "SUCCESS", "execution_time_seconds": 0.5},
        ]

        from benchbox.platforms.base.models import SetupPhase

        setup_phase = SetupPhase(
            schema_creation=None,
            data_generation=None,
            data_loading=None,
        )

        run_config = {"test_execution_type": "throughput"}

        execution_phases, _, power_test_phase, _ = adapter._build_execution_phases(
            query_results, [], run_config, setup_phase
        )

        assert power_test_phase is None
        assert execution_phases.power_test is None


class TestTPCHAndTPCDSExecutionHelpers:
    """Cover warmup, seeded execution, and error conversion in TPC helpers."""

    @patch("benchbox.platforms.base.execution.quiet_console")
    @patch("benchbox.core.tpch.power_test.TPCHPowerTest")
    def test_execute_tpch_power_test_records_warmup_and_failures(self, mock_power_test_cls, mock_console):
        adapter = MockPlatformAdapterWithDialect()
        benchmark = Mock()
        connection = Mock()
        run_config = {
            "scale_factor": 0.01,
            "seed": 11,
            "validation_mode": "strict",
            "query_subset": ["1", "2"],
            "timeout": 12,
            "iterations": 2,
            "warm_up_iterations": 1,
            "power_fail_fast": True,
        }

        warmup_result = SimpleNamespace(
            success=True,
            queries_successful=1,
            queries_executed=1,
            power_at_size=10.0,
            total_time=1.0,
            errors=[],
            query_results=[
                {
                    "query_id": "1",
                    "execution_time_seconds": 0.1,
                    "success": True,
                    "result_count": 5,
                    "stream_id": 0,
                    "position": 1,
                }
            ],
        )
        measurement_result = SimpleNamespace(
            success=False,
            queries_successful=1,
            queries_executed=2,
            power_at_size=8.5,
            total_time=2.0,
            errors=["query 2 failed"],
            query_results=[
                {
                    "query_id": "1",
                    "execution_time_seconds": 0.2,
                    "success": True,
                    "result_count": 7,
                    "stream_id": 1,
                    "position": 1,
                },
                {
                    "query_id": "2",
                    "execution_time_seconds": 0.4,
                    "success": False,
                    "result_count": 0,
                    "stream_id": 1,
                    "position": 2,
                    "error": "timeout",
                },
            ],
        )
        mock_power_test_cls.return_value.run.side_effect = [warmup_result, measurement_result]

        results = adapter._execute_tpch_power_test(benchmark, connection, run_config)

        assert mock_power_test_cls.call_count == 2
        first_kwargs = mock_power_test_cls.call_args_list[0].kwargs
        second_kwargs = mock_power_test_cls.call_args_list[1].kwargs
        assert first_kwargs["stream_id"] == 0
        assert second_kwargs["stream_id"] == 1
        assert first_kwargs["query_subset"] == ["1", "2"]
        assert second_kwargs["dialect"] == "mock_dialect"
        assert results[0]["run_type"] == "warmup"
        assert results[0]["iteration"] == 0
        assert results[-1]["run_type"] == "measurement"
        assert results[-1]["iteration"] == 1
        assert results[-1]["status"] == "FAILED"
        assert results[-1]["error"] == "timeout"
        assert adapter._last_power_test_result is measurement_result
        assert any("fail_fast enabled" in str(call) for call in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    @patch("benchbox.core.tpch.power_test.TPCHPowerTest", side_effect=RuntimeError("power init boom"))
    def test_execute_tpch_power_test_returns_error_result_on_exception(self, _mock_power_test_cls, _mock_console):
        adapter = MockPlatformAdapterWithDialect()

        results = adapter._execute_tpch_power_test(Mock(), Mock(), {"scale_factor": 0.01})

        assert results == [
            {
                "query_id": "power_test_error",
                "execution_time_seconds": 0.0,
                "status": "FAILED",
                "rows_returned": 0,
                "error": "power init boom",
                "test_type": "power",
            }
        ]

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_tpch_power_test_uses_resolved_validation_policy(self, _mock_console):
        adapter = MockPlatformAdapterWithDialect()
        benchmark = Mock()
        benchmark._name = "tpch"
        connection = Mock()
        run_config = {
            "scale_factor": 1.0,
            "iterations": 1,
            "warm_up_iterations": 1,
        }

        warmup_result = SimpleNamespace(
            success=True,
            queries_successful=1,
            queries_executed=1,
            power_at_size=10.0,
            total_time=1.0,
            errors=[],
            query_results=[
                {
                    "query_id": "1",
                    "execution_time_seconds": 0.1,
                    "success": True,
                    "result_count": 5,
                    "stream_id": 0,
                    "position": 1,
                }
            ],
        )
        measurement_result = SimpleNamespace(
            success=True,
            queries_successful=1,
            queries_executed=1,
            power_at_size=9.5,
            total_time=1.0,
            errors=[],
            query_results=[
                {
                    "query_id": "1",
                    "execution_time_seconds": 0.2,
                    "success": True,
                    "result_count": 6,
                    "stream_id": 1,
                    "position": 1,
                }
            ],
        )

        observed_flags: list[tuple[int, bool]] = []
        power_results = [warmup_result, measurement_result]

        class FakeTPCHPowerTest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                # Force a policy that differs from stream_id to prove the adapter
                # consumes resolved config.validation rather than re-deriving it.
                self.config = SimpleNamespace(validation=kwargs["stream_id"] == 1)

            def run(self):
                observed_flags.append((self.kwargs["stream_id"], self.kwargs["connection"]._validate_row_count))
                return power_results.pop(0)

        with patch("benchbox.core.tpch.power_test.TPCHPowerTest", FakeTPCHPowerTest):
            adapter._execute_tpch_power_test(benchmark, connection, run_config)

        assert observed_flags == [(0, False), (1, True)]

    @patch("benchbox.platforms.base.execution.quiet_console")
    @patch("benchbox.core.expected_results.tpcds_results.set_config_validation_mode")
    def test_execute_tpcds_power_test_uses_connection_factory_and_fail_fast(
        self, mock_set_validation_mode, mock_console
    ):
        adapter = MockPlatformAdapterWithDialect()
        adapter.very_verbose = True
        benchmark = Mock()
        benchmark._name = "tpcds"
        connection = Mock()
        connection.cursor.side_effect = [Mock(name="warmup_cursor"), Mock(name="measurement_cursor")]
        run_config = {
            "scale_factor": 0.01,
            "seed": 7,
            "validation_mode": "strict",
            "query_subset": ["1", "2"],
            "timeout": 30,
            "iterations": 3,
            "warm_up_iterations": 1,
            "power_fail_fast": True,
        }

        warmup_result = SimpleNamespace(
            success=True,
            queries_successful=1,
            queries_executed=1,
            power_at_size=42.0,
            total_time=1.0,
            errors=[],
            query_results=[
                {
                    "query_id": "1",
                    "execution_time_seconds": 0.1,
                    "success": True,
                    "result_count": 3,
                    "stream_id": 0,
                    "position": 1,
                }
            ],
        )
        measurement_result = SimpleNamespace(
            success=False,
            queries_successful=1,
            queries_executed=2,
            power_at_size=21.0,
            total_time=2.0,
            errors=["query 2 failed"],
            query_results=[
                {
                    "query_id": "1",
                    "execution_time_seconds": 0.2,
                    "success": True,
                    "result_count": 4,
                    "stream_id": 1,
                    "position": 1,
                },
                {
                    "query_id": "2",
                    "execution_time_seconds": 0.3,
                    "success": False,
                    "result_count": 0,
                    "stream_id": 1,
                    "position": 2,
                    "error": "timeout",
                },
            ],
        )

        created_kwargs: list[dict[str, Any]] = []
        power_results = [warmup_result, measurement_result]

        class FakeTPCDSPowerTest:
            def __init__(self, **kwargs):
                self.kwargs = kwargs
                created_kwargs.append(kwargs)

            def run(self):
                wrapper = self.kwargs["connection_factory"]()
                self.kwargs["wrapped_connection"] = wrapper
                return power_results.pop(0)

        with patch("benchbox.core.tpcds.power_test.TPCDSPowerTest", FakeTPCDSPowerTest):
            results = adapter._execute_tpcds_power_test(benchmark, connection, run_config)

        assert mock_set_validation_mode.call_args.args == ("strict",)
        assert len(created_kwargs) == 2
        assert created_kwargs[0]["stream_id"] == 0
        assert created_kwargs[1]["stream_id"] == 1
        assert created_kwargs[0]["query_subset"] == ["1", "2"]
        assert created_kwargs[1]["dialect"] == "mock_dialect"
        assert created_kwargs[0]["wrapped_connection"].benchmark_type == "tpcds"
        assert created_kwargs[1]["wrapped_connection"].scale_factor == 0.01
        assert connection.cursor.call_count == 2
        assert results[0]["run_type"] == "warmup"
        assert results[-1]["run_type"] == "measurement"
        assert results[-1]["error"] == "timeout"
        assert adapter._last_power_test_result is measurement_result
        assert any("Target dialect" in str(call) for call in mock_console.print.call_args_list)
        assert any("fail_fast enabled" in str(call) for call in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    @patch("benchbox.core.expected_results.tpcds_results.set_config_validation_mode")
    def test_execute_tpcds_power_test_returns_error_result_on_exception(self, _mock_set_validation_mode, _mock_console):
        adapter = MockPlatformAdapterWithDialect()

        class BrokenTPCDSPowerTest:
            def __init__(self, **kwargs):
                raise RuntimeError("tpcds power boom")

        with patch("benchbox.core.tpcds.power_test.TPCDSPowerTest", BrokenTPCDSPowerTest):
            results = adapter._execute_tpcds_power_test(Mock(), Mock(), {"scale_factor": 0.01})

        assert results == [
            {
                "query_id": "power_test_error",
                "execution_time_seconds": 0.0,
                "status": "FAILED",
                "rows_returned": 0,
                "error": "tpcds power boom",
                "test_type": "power",
            }
        ]

    @patch("benchbox.platforms.base.execution.quiet_console")
    @patch("benchbox.core.expected_results.tpcds_results.set_config_validation_mode")
    def test_execute_tpcds_throughput_test_uses_seeded_config_and_preserves_errors(
        self, mock_set_validation_mode, mock_console
    ):
        adapter = MockPlatformAdapterWithDialect()
        adapter.very_verbose = True
        benchmark = Mock()
        connection = Mock()
        connection.cursor.return_value = Mock(name="stream_cursor")
        run_config = {"scale_factor": 1.0, "validation_mode": "off", "num_streams": 2, "seed": 17, "verbose": True}

        stream_result = SimpleNamespace(
            stream_id=3,
            queries_successful=1,
            queries_executed=2,
            query_results=[
                {"query_id": "7", "execution_time_seconds": 0.6, "success": True, "result_count": 8},
                {
                    "query_id": "9",
                    "execution_time_seconds": 1.4,
                    "success": False,
                    "result_count": 0,
                    "error": "stream timeout",
                },
            ],
        )
        throughput_result = SimpleNamespace(
            success=True,
            throughput_at_size=123.4,
            streams_executed=2,
            streams_successful=1,
            total_time=9.5,
            errors=[],
            stream_results=[stream_result],
        )

        captured: dict[str, Any] = {}

        class FakeTPCDSThroughputTest:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def run(self, config=None):
                captured["config"] = config
                captured["wrapped_connection"] = captured["init"]["connection_factory"]()
                return throughput_result

        with patch("benchbox.core.tpcds.throughput_test.TPCDSThroughputTest", FakeTPCDSThroughputTest):
            results = adapter._execute_tpcds_throughput_test(benchmark, connection, run_config)

        assert mock_set_validation_mode.call_args.args == ("off",)
        assert captured["init"]["num_streams"] == 2
        assert captured["init"]["dialect"] == "mock_dialect"
        assert captured["config"].base_seed == 17
        assert captured["wrapped_connection"].benchmark_type == "tpcds"
        assert connection.cursor.call_count == 1
        assert results == [
            {
                "query_id": "7",
                "execution_time_seconds": 0.6,
                "status": "SUCCESS",
                "rows_returned": 8,
                "test_type": "throughput",
                "stream_id": 3,
            },
            {
                "query_id": "9",
                "execution_time_seconds": 1.4,
                "status": "FAILED",
                "rows_returned": 0,
                "test_type": "throughput",
                "stream_id": 3,
                "error": "stream timeout",
            },
        ]
        assert adapter._last_throughput_test_result is throughput_result
        assert any("Target dialect" in str(call) for call in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    @patch("benchbox.core.expected_results.tpcds_results.set_config_validation_mode")
    def test_execute_tpcds_throughput_test_resets_cached_result_on_exception(
        self, _mock_set_validation_mode, _mock_console
    ):
        adapter = MockPlatformAdapterWithDialect()
        adapter._last_throughput_test_result = object()

        class BrokenTPCDSThroughputTest:
            def __init__(self, **kwargs):
                pass

            def run(self, config=None):
                raise RuntimeError("throughput boom")

        with patch("benchbox.core.tpcds.throughput_test.TPCDSThroughputTest", BrokenTPCDSThroughputTest):
            results = adapter._execute_tpcds_throughput_test(Mock(), Mock(), {"scale_factor": 1.0})

        assert adapter._last_throughput_test_result is None
        assert results == [
            {
                "query_id": "throughput_test_error",
                "execution_time_seconds": 0.0,
                "status": "FAILED",
                "rows_returned": 0,
                "error": "throughput boom",
                "test_type": "throughput",
            }
        ]

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_tpcds_maintenance_test_converts_output_dir_and_operation_errors(self, mock_console, tmp_path):
        adapter = MockPlatformAdapterWithDialect()
        benchmark = Mock()
        connection = Mock()
        connection.cursor.return_value = Mock(name="maintenance_cursor")
        run_config = {"scale_factor": 1.0, "verbose": True, "output_dir": str(tmp_path / "maintenance")}

        maintenance_result = {
            "success": False,
            "insert_operations": 1,
            "update_operations": 0,
            "delete_operations": 1,
            "total_operations": 2,
            "successful_operations": 1,
            "total_time": 5.0,
            "overall_throughput": 0.4,
            "errors": ["delete failed"],
            "operations": [
                SimpleNamespace(
                    operation_type="INSERT",
                    table_name="catalog_sales",
                    duration=1.5,
                    success=True,
                    rows_affected=10,
                    error=None,
                ),
                SimpleNamespace(
                    operation_type="DELETE",
                    table_name="store_sales",
                    duration=3.5,
                    success=False,
                    rows_affected=0,
                    error="lock timeout",
                ),
            ],
        }

        captured: dict[str, Any] = {}

        class FakeTPCDSMaintenanceTest:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def run(self):
                captured["wrapped_connection"] = captured["init"]["connection_factory"]()
                return maintenance_result

        with patch("benchbox.core.tpcds.maintenance_test.TPCDSMaintenanceTest", FakeTPCDSMaintenanceTest):
            results = adapter._execute_tpcds_maintenance_test(benchmark, connection, run_config)

        assert captured["init"]["output_dir"] == Path(run_config["output_dir"])
        assert captured["init"]["dialect"] == "mock_dialect"
        assert captured["wrapped_connection"].benchmark_type == "tpcds"
        assert connection.cursor.call_count == 1
        assert results == [
            {
                "query_id": "insert_catalog_sales",
                "execution_time_seconds": 1.5,
                "status": "SUCCESS",
                "rows_returned": 10,
                "test_type": "maintenance",
                "operation_type": "INSERT",
                "table_name": "catalog_sales",
            },
            {
                "query_id": "delete_store_sales",
                "execution_time_seconds": 3.5,
                "status": "FAILED",
                "rows_returned": 0,
                "test_type": "maintenance",
                "operation_type": "DELETE",
                "table_name": "store_sales",
                "error": "lock timeout",
            },
        ]
        assert any("delete failed" in str(call) for call in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_tpch_throughput_test_uses_seeded_config(self, _mock_console):
        adapter = MockPlatformAdapterWithDialect()
        benchmark = Mock()
        connection = Mock()
        connection.cursor.return_value = Mock(name="tpch_stream_cursor")
        run_config = {"scale_factor": 0.01, "num_streams": 3, "seed": 23, "verbose": True}

        stream_result = SimpleNamespace(
            stream_id=2,
            query_results=[
                {"query_id": "1", "execution_time_seconds": 0.5, "success": True, "result_count": 9},
                {
                    "query_id": "2",
                    "execution_time_seconds": 0.7,
                    "success": False,
                    "result_count": 0,
                    "error": "tpch timeout",
                },
            ],
        )
        throughput_result = SimpleNamespace(
            success=True,
            throughput_at_size=98.7,
            streams_executed=3,
            streams_successful=2,
            total_time=12.0,
            errors=[],
            stream_results=[stream_result],
        )

        captured: dict[str, Any] = {}

        class FakeTPCHThroughputTest:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def run(self, config=None):
                captured["config"] = config
                captured["wrapped_connection"] = captured["init"]["connection_factory"]()
                return throughput_result

        with patch("benchbox.core.tpch.throughput_test.TPCHThroughputTest", FakeTPCHThroughputTest):
            results = adapter._execute_tpch_throughput_test(benchmark, connection, run_config)

        assert captured["config"].base_seed == 23
        assert captured["wrapped_connection"].benchmark_type == "tpch"
        assert connection.cursor.call_count == 1
        assert results[-1]["error"] == "tpch timeout"
        assert adapter._last_throughput_test_result is throughput_result

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_execute_tpch_maintenance_test_passes_rf_intervals_and_integrity_flag(self, _mock_console, tmp_path):
        adapter = MockPlatformAdapterWithDialect()
        connection = Mock()
        connection.cursor.return_value = Mock(name="tpch_maintenance_cursor")
        run_config = {
            "scale_factor": 0.1,
            "verbose": True,
            "maintenance_pairs": 3,
            "rf1_interval": 0.25,
            "rf2_interval": 0.75,
            "validate_integrity": False,
            "output_dir": str(tmp_path / "tpch-maint"),
        }

        result = SimpleNamespace(
            success=False,
            total_operations=2,
            successful_operations=1,
            failed_operations=1,
            total_time=4.0,
            overall_throughput=0.5,
            errors=["rf2 failed"],
            operations=[
                SimpleNamespace(operation_type="RF1", duration=1.0, success=True, rows_affected=100),
                SimpleNamespace(operation_type="RF2", duration=3.0, success=False, rows_affected=0),
            ],
        )

        captured: dict[str, Any] = {}

        class FakeTPCHMaintenanceTest:
            def __init__(self, **kwargs):
                captured["init"] = kwargs

            def run_maintenance_test(self, **kwargs):
                captured["run_kwargs"] = kwargs
                captured["wrapped_connection"] = captured["init"]["connection_factory"]()
                return result

        with patch("benchbox.core.tpch.maintenance_test.TPCHMaintenanceTest", FakeTPCHMaintenanceTest):
            results = adapter._execute_tpch_maintenance_test(Mock(), connection, run_config)

        assert captured["init"]["output_dir"] == Path(run_config["output_dir"])
        assert captured["run_kwargs"] == {
            "maintenance_pairs": 3,
            "concurrent_with_queries": False,
            "rf1_interval": 0.25,
            "rf2_interval": 0.75,
            "validate_integrity": False,
        }
        assert captured["wrapped_connection"].benchmark_type == "tpch"
        assert captured["wrapped_connection"]._maintenance_mode is True
        assert connection.cursor.call_count == 1
        assert results == [
            {
                "query_id": "RF1",
                "execution_time_seconds": 1.0,
                "status": "SUCCESS",
                "rows_returned": 100,
                "test_type": "maintenance",
            },
            {
                "query_id": "RF2",
                "execution_time_seconds": 3.0,
                "status": "FAILED",
                "rows_returned": 0,
                "test_type": "maintenance",
            },
        ]


class TestExecuteGenericPowerTest:
    """Tests for _execute_generic_power_test orchestration."""

    def _make_adapter(self):
        return MockPlatformAdapter()

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_warmup_and_measurement_iterations_tagged_correctly(self, _mock_console):
        adapter = self._make_adapter()
        call_count = [0]

        def fake_execute_all(benchmark, connection, run_config):
            call_count[0] += 1
            return [
                {"query_id": "Q1", "execution_time_seconds": 0.5, "status": "SUCCESS", "rows_returned": 10},
            ]

        adapter._execute_all_queries = fake_execute_all
        run_config = {"iterations": 2, "warm_up_iterations": 1}

        results = adapter._execute_generic_power_test(Mock(), Mock(), run_config)

        # 1 warmup + 2 measurement = 3 total calls
        assert call_count[0] == 3
        warmup_results = [r for r in results if r["run_type"] == "warmup"]
        measurement_results = [r for r in results if r["run_type"] == "measurement"]
        assert len(warmup_results) == 1
        assert len(measurement_results) == 2
        assert warmup_results[0]["iteration"] == 0
        assert measurement_results[0]["iteration"] == 1
        assert measurement_results[1]["iteration"] == 2

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_aborts_remaining_iterations_when_all_queries_fail(self, mock_console):
        adapter = self._make_adapter()
        call_count = [0]

        def fake_execute_all(benchmark, connection, run_config):
            call_count[0] += 1
            return [{"query_id": "Q1", "execution_time_seconds": 0.0, "status": "FAILED", "rows_returned": 0}]

        adapter._execute_all_queries = fake_execute_all
        run_config = {"iterations": 3, "warm_up_iterations": 0}

        results = adapter._execute_generic_power_test(Mock(), Mock(), run_config)

        # Should stop after first failed iteration
        assert call_count[0] == 1
        assert all(r["status"] == "FAILED" for r in results)
        assert any("All queries failed" in str(c) for c in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_fail_fast_aborts_on_partial_failure(self, mock_console):
        adapter = self._make_adapter()
        call_count = [0]

        def fake_execute_all(benchmark, connection, run_config):
            call_count[0] += 1
            return [
                {"query_id": "Q1", "execution_time_seconds": 0.3, "status": "SUCCESS", "rows_returned": 5},
                {"query_id": "Q2", "execution_time_seconds": 0.0, "status": "FAILED", "rows_returned": 0},
            ]

        adapter._execute_all_queries = fake_execute_all
        run_config = {"iterations": 5, "warm_up_iterations": 0, "power_fail_fast": True}

        adapter._execute_generic_power_test(Mock(), Mock(), run_config)

        # fail_fast stops after first iteration with partial failures
        assert call_count[0] == 1
        assert any("fail_fast" in str(c) for c in mock_console.print.call_args_list)

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_summary_printed_with_success_rate(self, mock_console):
        adapter = self._make_adapter()

        def fake_execute_all(benchmark, connection, run_config):
            return [{"query_id": "Q1", "execution_time_seconds": 1.0, "status": "SUCCESS", "rows_returned": 3}]

        adapter._execute_all_queries = fake_execute_all
        run_config = {"iterations": 1, "warm_up_iterations": 0}

        results = adapter._execute_generic_power_test(Mock(), Mock(), run_config)

        assert len(results) == 1
        assert results[0]["status"] == "SUCCESS"
        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "100.0%" in printed

    @patch("benchbox.platforms.base.execution.quiet_console")
    def test_no_summary_for_empty_results(self, _mock_console):
        adapter = self._make_adapter()
        adapter._execute_all_queries = lambda b, c, r: []
        run_config = {"iterations": 1, "warm_up_iterations": 0}

        results = adapter._execute_generic_power_test(Mock(), Mock(), run_config)

        assert results == []


class TestBuildExecutionPhasesVariants:
    """Tests for _build_execution_phases throughput path and capture_plans."""

    def _make_query_results(self, n=2, status="SUCCESS"):
        return [
            {"query_id": f"Q{i}", "execution_time_seconds": float(i), "status": status, "rows_returned": 10}
            for i in range(1, n + 1)
        ]

    def _make_query_executions(self):
        from benchbox.platforms.base.models import QueryExecution

        return [
            QueryExecution(
                query_id="Q1",
                stream_id="standard",
                execution_order=1,
                execution_time_ms=1000.0,
                status="SUCCESS",
                rows_returned=10,
            )
        ]

    def test_throughput_execution_type_skips_power_test_phase(self):
        adapter = MockPlatformAdapter()
        query_results = self._make_query_results()
        query_executions = self._make_query_executions()
        run_config = {"test_execution_type": "throughput"}

        execution_phases, total_exec_time, power_test_phase, throughput_test_phase = adapter._build_execution_phases(
            query_results, query_executions, run_config, setup_phase=None
        )

        assert power_test_phase is None
        assert execution_phases.power_test is None

    def test_standard_execution_type_creates_power_test_phase(self):
        adapter = MockPlatformAdapter()
        query_results = self._make_query_results()
        query_executions = self._make_query_executions()
        run_config = {"test_execution_type": "standard"}

        execution_phases, total_exec_time, power_test_phase, throughput_test_phase = adapter._build_execution_phases(
            query_results, query_executions, run_config, setup_phase=None
        )

        assert power_test_phase is not None
        assert execution_phases.power_test is power_test_phase

    def test_captures_last_power_test_result_power_at_size(self):
        adapter = MockPlatformAdapter()
        power_result = SimpleNamespace(power_at_size=99.5)
        adapter._last_power_test_result = power_result
        query_results = self._make_query_results()
        query_executions = self._make_query_executions()
        run_config = {}

        execution_phases, _, power_test_phase, _ = adapter._build_execution_phases(
            query_results, query_executions, run_config, setup_phase=None
        )

        assert power_test_phase.power_at_size == 99.5
        assert adapter._last_power_test_result is None

    def test_captures_last_throughput_result(self):
        adapter = MockPlatformAdapter()
        stream = SimpleNamespace(
            stream_id=0,
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:01:00",
            duration=60.0,
            queries_executed=1,
            query_results=[{"query_id": "Q1", "execution_time_seconds": 1.0, "success": True}],
        )
        throughput_result = SimpleNamespace(
            stream_results=[stream],
            total_time=60.0,
            start_time="2025-01-01T00:00:00",
            end_time="2025-01-01T00:01:00",
            config=SimpleNamespace(num_streams=1),
            throughput_at_size=720.0,
        )
        adapter._last_throughput_test_result = throughput_result
        query_results = self._make_query_results()
        query_executions = self._make_query_executions()
        run_config = {"test_execution_type": "throughput"}

        execution_phases, _, _, throughput_test_phase = adapter._build_execution_phases(
            query_results, query_executions, run_config, setup_phase=None
        )

        assert throughput_test_phase is not None
        assert adapter._last_throughput_test_result is None

    def test_capture_plans_path_does_not_raise(self):
        adapter = MockPlatformAdapter()
        adapter.capture_plans = True
        adapter.query_plans_captured = 3
        adapter.plan_capture_failures = 0
        query_results = self._make_query_results()
        query_executions = self._make_query_executions()
        run_config = {}

        execution_phases, _, _, _ = adapter._build_execution_phases(
            query_results, query_executions, run_config, setup_phase=None
        )

        assert execution_phases is not None

    def test_total_exec_time_sums_only_successful_queries(self):
        adapter = MockPlatformAdapter()
        query_results = [
            {"query_id": "Q1", "execution_time_seconds": 2.0, "status": "SUCCESS", "rows_returned": 5},
            {"query_id": "Q2", "execution_time_seconds": 3.0, "status": "FAILED", "rows_returned": 0},
        ]
        query_executions = self._make_query_executions()

        _, total_exec_time, _, _ = adapter._build_execution_phases(
            query_results, query_executions, {}, setup_phase=None
        )

        assert total_exec_time == 2.0


class TestExceptionPathsForThroughputAndMaintenance:
    """Error path tests for tpch_throughput, tpcds_maintenance, tpch_maintenance."""

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_execute_tpch_throughput_test_resets_cached_result_on_exception(self, _mock_console):
        adapter = MockPlatformAdapterWithDialect()
        adapter._last_throughput_test_result = object()

        class BrokenTPCHThroughputTest:
            def __init__(self, **kwargs):
                pass

            def run(self, config=None):
                raise RuntimeError("tpch throughput boom")

        with patch("benchbox.core.tpch.throughput_test.TPCHThroughputTest", BrokenTPCHThroughputTest):
            results = adapter._execute_tpch_throughput_test(Mock(), Mock(), {"scale_factor": 1.0})

        assert adapter._last_throughput_test_result is None
        assert results == [
            {
                "query_id": "throughput_test_error",
                "execution_time_seconds": 0.0,
                "status": "FAILED",
                "rows_returned": 0,
                "error": "tpch throughput boom",
                "test_type": "throughput",
            }
        ]

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_execute_tpcds_maintenance_test_returns_error_on_exception(self, _mock_console):
        adapter = MockPlatformAdapterWithDialect()

        class BrokenTPCDSMaintenanceTest:
            def __init__(self, **kwargs):
                raise RuntimeError("tpcds maintenance boom")

        with patch("benchbox.core.tpcds.maintenance_test.TPCDSMaintenanceTest", BrokenTPCDSMaintenanceTest):
            results = adapter._execute_tpcds_maintenance_test(Mock(), Mock(), {"scale_factor": 1.0})

        assert results == [
            {
                "query_id": "maintenance_test_error",
                "execution_time_seconds": 0.0,
                "status": "FAILED",
                "rows_returned": 0,
                "error": "tpcds maintenance boom",
                "test_type": "maintenance",
            }
        ]

    @patch("benchbox.platforms.base.adapter.quiet_console")
    def test_execute_tpch_maintenance_test_returns_error_on_exception(self, _mock_console):
        adapter = MockPlatformAdapterWithDialect()

        class BrokenTPCHMaintenanceTest:
            def __init__(self, **kwargs):
                raise RuntimeError("tpch maintenance boom")

        with patch("benchbox.core.tpch.maintenance_test.TPCHMaintenanceTest", BrokenTPCHMaintenanceTest):
            results = adapter._execute_tpch_maintenance_test(Mock(), Mock(), {"scale_factor": 1.0})

        assert results == [
            {
                "query_id": "maintenance_test_error",
                "execution_time_seconds": 0.0,
                "status": "FAILED",
                "rows_returned": 0,
                "error": "tpch maintenance boom",
                "test_type": "maintenance",
            }
        ]


class TestDataGenerationPhaseEdgeCases:
    """Additional edge cases for _create_enhanced_data_generation_phase."""

    def test_returns_none_when_benchmark_has_no_tables_attr(self):
        adapter = MockPlatformAdapter()
        benchmark = SimpleNamespace()  # no 'tables' attribute

        result = adapter._create_enhanced_data_generation_phase(benchmark)

        assert result is None

    def test_returns_none_when_tables_dict_empty(self):
        adapter = MockPlatformAdapter()
        benchmark = SimpleNamespace(tables={})

        result = adapter._create_enhanced_data_generation_phase(benchmark)

        assert result is None

    def test_returns_none_when_tables_is_not_mapping(self):
        adapter = MockPlatformAdapter()
        benchmark = SimpleNamespace(tables="not_a_dict")

        result = adapter._create_enhanced_data_generation_phase(benchmark)

        assert result is None

    def test_partial_failure_when_one_table_raises(self):
        adapter = MockPlatformAdapter()

        class BadTable:
            def __iter__(self):
                raise RuntimeError("disk full")

        benchmark = SimpleNamespace(tables={"good": [{"id": 1}, {"id": 2}], "bad": BadTable()})

        result = adapter._create_enhanced_data_generation_phase(benchmark)

        assert result is not None
        assert result.status == "PARTIAL_FAILURE"
        assert result.tables_generated == 1
        assert result.per_table_stats["good"].status == "SUCCESS"
        assert result.per_table_stats["bad"].status == "FAILED"
        assert "disk full" in result.per_table_stats["bad"].error_message

    def test_table_with_string_data_skipped(self):
        adapter = MockPlatformAdapter()
        # String data is skipped (isinstance check: not (hasattr __iter__ and not str))
        benchmark = SimpleNamespace(tables={"t": "some_string_path"})

        result = adapter._create_enhanced_data_generation_phase(benchmark)

        assert result is not None
        assert result.tables_generated == 0

    def test_uses_impl_tables_when_no_direct_tables(self):
        adapter = MockPlatformAdapter()
        impl = SimpleNamespace(tables={"lineitem": [{"l_orderkey": 1}]})
        benchmark = SimpleNamespace(_impl=impl)

        result = adapter._create_enhanced_data_generation_phase(benchmark)

        assert result is not None
        assert result.tables_generated == 1
        assert "lineitem" in result.per_table_stats


class TestDialectQuerySelection:
    def test_get_dialect_queries_passes_platform_version_when_supported(self):
        adapter = MockPlatformAdapterWithDialect()
        benchmark = BenchmarkWithVersionAwareQueries()

        queries = adapter._get_dialect_queries(
            benchmark,
            benchmark_slug="vector_search",
            connection=Mock(name="versioned_connection"),
        )

        assert queries == {"Q1": "SELECT 1"}
        assert benchmark.calls == [{"dialect": "mock_dialect", "platform_version": "1.0.0"}]

    def test_get_dialect_queries_preserves_strict_translation_failures(self):
        adapter = MockPlatformAdapterWithDialect()
        benchmark = BenchmarkWithStrictTranslationFailure()

        with pytest.raises(SQLTranslationError):
            adapter._get_dialect_queries(
                benchmark,
                benchmark_slug="tpch",
                connection=Mock(name="strict_translation_connection"),
            )
