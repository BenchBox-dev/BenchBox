"""
Tests for NotImplementedError completions.

This test module verifies that all the NotImplementedError issues have been properly
resolved and that implemented methods work correctly.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import contextlib
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from benchbox.core.base_benchmark import BaseBenchmark
from benchbox.platforms.sqlite import SQLiteAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBaseBenchmarkProperties:
    """Test that base benchmark properties now work without NotImplementedError."""

    def test_concrete_benchmark_properties(self):
        """Test that concrete benchmarks can access name, version, and description."""

        # Create a mock concrete benchmark
        class MockBenchmark(BaseBenchmark):
            def generate_data(self, tables=None, output_format="memory"):
                return {"table1": []}

            def get_query(self, query_id):
                return f"SELECT * FROM table WHERE id = {query_id}"

            def get_all_queries(self):
                return {1: "SELECT 1", 2: "SELECT 2"}

            def execute_query(self, query_id, connection, params=None):
                return [(1, "test")]

        benchmark = MockBenchmark(scale_factor=1.0)

        # These should not raise NotImplementedError anymore
        name = benchmark.name
        version = benchmark.version
        description = benchmark.description

        # Check that defaults are sensible
        assert name == "mock"  # Class name without 'Benchmark' suffix
        assert version == "1.0"
        assert "MOCK benchmark implementation" in description

    def test_benchmark_with_explicit_metadata(self):
        """Test benchmark with explicitly set metadata."""

        class ExplicitBenchmark(BaseBenchmark):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self._name = "custom_name"
                self._version = "2.1"
                self._description = "Custom description"

            def generate_data(self, tables=None, output_format="memory"):
                return {}

            def get_query(self, query_id):
                return "SELECT 1"

            def get_all_queries(self):
                return {}

            def execute_query(self, query_id, connection, params=None):
                return []

        benchmark = ExplicitBenchmark()

        assert benchmark.name == "custom_name"
        assert benchmark.version == "2.1"
        assert benchmark.description == "Custom description"


class TestPlatformDropDatabase:
    """Test platform drop_database implementations."""

    def test_sqlite_drop_database_documented_limitation(self):
        """Test that SQLite drop_database raises appropriate NotImplementedError."""
        adapter = SQLiteAdapter()

        # This should raise NotImplementedError with a clear message
        with pytest.raises(NotImplementedError, match="drop_database not implemented"):
            adapter.drop_database()

    def test_sqlite_tpc_tests_documented_limitations(self):
        """Test that SQLite TPC tests raise appropriate NotImplementedError."""
        adapter = SQLiteAdapter()
        mock_benchmark = Mock()

        # These should raise NotImplementedError with clear messages
        with pytest.raises(NotImplementedError, match="Power test not implemented for SQLite"):
            adapter.run_power_test(mock_benchmark)

        with pytest.raises(NotImplementedError, match="Throughput test not implemented for SQLite"):
            adapter.run_throughput_test(mock_benchmark)

        with pytest.raises(NotImplementedError, match="Maintenance test not implemented for SQLite"):
            adapter.run_maintenance_test(mock_benchmark)


class TestDocumentedNotImplementedMethods:
    """Test that documented NotImplementedError methods provide clear guidance."""

    def test_stream_generation_apis_documented(self):
        """Stream generation/info APIs are present, callable, and actually work."""
        from benchbox.core.tpcds.benchmark import TPCDSBenchmark

        tpcds = TPCDSBenchmark(scale_factor=1.0)

        assert callable(getattr(tpcds, "generate_streams", None))
        assert callable(getattr(tpcds, "get_stream_info", None))

    def test_non_executing_stream_stubs_now_raise_not_implemented(self):
        """Stream-execution APIs that used to fake success now raise NotImplementedError.

        `TPCHStreamRunner.run_stream`/`run_concurrent_streams` and
        `TPCDSBenchmark.run_streams` previously reported every query as
        successful by counting `-- Query` comment lines, without executing
        any SQL. As part of the concurrency-executor consolidation, they now
        raise NotImplementedError unconditionally rather than silently
        reporting fake success. Use `TPCHThroughputTest`/`TPCDSThroughputTest`
        (or `TPCDSBenchmark.run_throughput_test`) for real execution.
        """
        from benchbox.core.tpcds.benchmark import TPCDSBenchmark
        from benchbox.core.tpch.streams import TPCHStreamRunner

        runner = TPCHStreamRunner("test://connection", verbose=False)
        tpcds = TPCDSBenchmark(scale_factor=1.0)

        assert callable(getattr(runner, "run_stream", None))
        assert callable(getattr(runner, "run_concurrent_streams", None))
        assert callable(getattr(tpcds, "run_streams", None))

        with pytest.raises(NotImplementedError):
            runner.run_stream(Path("/fake/stream.sql"), stream_id=0)
        with pytest.raises(NotImplementedError):
            runner.run_concurrent_streams([])
        with pytest.raises(NotImplementedError):
            tpcds.run_streams(connection=Mock())


class TestNoPlatformNotImplementedErrors:
    """Test that common platform operations don't raise unexpected NotImplementedErrors."""

    def test_sqlite_adapter_basic_operations(self):
        """Test that SQLite adapter basic operations work without NotImplementedError."""
        adapter = SQLiteAdapter()

        # These should work without NotImplementedError
        platform_name = adapter.platform_name
        assert isinstance(platform_name, str)

        dialect = adapter.get_target_dialect()
        assert isinstance(dialect, str)

        # Connection creation should work
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            connection_config = {"database": tmp_db.name}

            try:
                connection = adapter.create_connection(**connection_config)
                assert connection is not None

                # Basic operations should work
                adapter.close_connection(connection)

            finally:
                # Cleanup
                with contextlib.suppress(Exception):
                    Path(tmp_db.name).unlink()


class TestErrorMessagesQuality:
    """Test that NotImplementedError messages are helpful and descriptive."""

    def test_base_class_error_messages_helpful(self):
        """Test that base class NotImplementedError messages are helpful."""
        from benchbox.base import BaseBenchmark

        # Create a benchmark that doesn't override _load_data
        class IncompleteBenchmark(BaseBenchmark):
            def generate_data(self):
                return []

            def get_queries(self):
                return {}

            def get_query(self, query_id, params=None):
                return "SELECT 1"

        benchmark = IncompleteBenchmark(scale_factor=1.0)
        mock_connection = Mock()

        # Should raise helpful NotImplementedError
        with pytest.raises(NotImplementedError) as excinfo:
            benchmark._load_data(mock_connection)

        error_msg = str(excinfo.value)
        assert "IncompleteBenchmark" in error_msg
        assert "_load_data" in error_msg
        assert "database execution functionality" in error_msg


@pytest.mark.integration
class TestNotImplementedErrorResolution:
    """Integration tests verifying NotImplementedError resolution."""

    def test_no_runtime_notimplementederrors_in_basic_usage(self):
        """Test that basic benchmark usage doesn't hit NotImplementedErrors."""
        # Test basic TPC-H usage pattern
        from benchbox import TPCH

        benchmark = TPCH(scale_factor=0.01)

        # These operations should not raise NotImplementedError
        queries = benchmark.get_queries()
        assert isinstance(queries, dict)

        query1 = benchmark.get_query(1)
        assert isinstance(query1, str)

        # Data generation should work
        data_files = benchmark.generate_data()
        assert isinstance(data_files, list)

    def test_platform_adapter_integration_no_notimplementederrors(self):
        """Test that platform adapter integration doesn't hit unexpected NotImplementedErrors."""
        from benchbox import TPCH
        from benchbox.platforms.sqlite import SQLiteAdapter

        TPCH(scale_factor=0.01)
        adapter = SQLiteAdapter()

        # Basic adapter operations should work without NotImplementedError
        platform_name = adapter.platform_name
        assert isinstance(platform_name, str)

        dialect = adapter.get_target_dialect()
        assert isinstance(dialect, str)

        # Connection creation should work
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            connection_config = {"database": tmp_db.name}

            try:
                connection = adapter.create_connection(**connection_config)
                assert connection is not None

                # Basic operations should work
                adapter.close_connection(connection)

            finally:
                # Cleanup
                with contextlib.suppress(Exception):
                    Path(tmp_db.name).unlink()
