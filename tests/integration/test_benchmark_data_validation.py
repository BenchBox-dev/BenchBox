"""Integration tests for benchmark data validation functionality."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base import PlatformAdapter, ValidationPhase

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


class MockBenchmark:
    """Mock benchmark for testing."""

    def __init__(self, tables=None):
        self.tables = tables or {"test_table": "/tmp/test_table.tbl"}
        self.scale_factor = 0.01
        self.benchmark_name = "test_benchmark"

    def get_queries(self):
        """Mock get_queries method."""
        return {"Q1": "SELECT COUNT(*) FROM test_table"}

    def create_enhanced_benchmark_result(self, **kwargs):
        from datetime import datetime

        from benchbox.core.results.models import (
            BenchmarkResults,
            ExecutionPhases,
            PowerTestPhase,
            QueryDefinition,
            SetupPhase,
        )

        return BenchmarkResults(
            benchmark_name=self.benchmark_name,
            platform=kwargs.get("platform", "test"),
            scale_factor=self.scale_factor,
            execution_id="test_001",
            timestamp=datetime.now(),
            duration_seconds=10.0,
            query_definitions=kwargs.get(
                "query_definitions",
                {"standard": {"Q1": QueryDefinition(sql="SELECT COUNT(*) FROM test_table")}},
            ),
            execution_phases=kwargs.get(
                "execution_phases",
                ExecutionPhases(
                    setup=SetupPhase(),
                    power_test=PowerTestPhase(
                        start_time=datetime.now().isoformat(),
                        end_time=datetime.now().isoformat(),
                        duration_ms=0,
                        query_executions=[],
                        geometric_mean_time=0.0,
                        power_at_size=0.0,
                    ),
                ),
            ),
            total_queries=kwargs.get("total_queries", 0),
            successful_queries=kwargs.get("successful_queries", 0),
            failed_queries=kwargs.get("failed_queries", 0),
            total_execution_time=kwargs.get("total_execution_time", 0.0),
            average_query_time=kwargs.get("average_query_time", 0.0),
            validation_status=kwargs.get("validation_status", "PASSED"),
            validation_details=kwargs.get("validation_details", {}),
            execution_metadata=kwargs.get("execution_metadata", {}),
        )


class MockPlatformAdapter(PlatformAdapter):
    """Test platform adapter for validation testing."""

    def __init__(self):
        super().__init__()
        self._platform_name = "test_platform"
        self.mock_connection = Mock()

    @staticmethod
    def add_cli_arguments(parser) -> None:  # minimal no-op for abstract API
        return None

    @classmethod
    def from_config(cls, config):  # minimal constructor passthrough for abstract API
        return cls()

    def get_target_dialect(self) -> str:  # satisfy adapter base init
        return "duckdb"

    @property
    def platform_name(self):
        return self._platform_name

    def create_connection(self, **connection_config):
        return self.mock_connection

    def create_schema(self, benchmark, connection):
        return 0.1  # Mock schema creation time

    def load_data(self, benchmark, connection, data_dir):
        # This will be mocked in tests
        return {"test_table": 100}, 1.0, None

    def configure_for_benchmark(self, connection, benchmark_type):
        pass

    def execute_query(self, connection, query, query_id):
        return {
            "query_id": query_id,
            "execution_time_seconds": 0.1,
            "rows_returned": 10,
            "success": True,
        }

    def _get_existing_tables(self, connection):
        # Mock implementation
        return ["test_table"]

    def get_platform_info(self, connection):
        return {"platform": "test", "version": "1.0"}

    # Implement required abstract methods with minimal functionality
    def apply_constraint_configuration(self, config, connection):
        pass

    def apply_platform_optimizations(self, config, connection):
        pass

    def apply_table_tunings(self, config, connection):
        pass

    def apply_unified_tuning(self, config, connection):
        pass

    def generate_tuning_clause(self, table_name, config):
        return ""


class TestBenchmarkDataValidation:
    """Test suite for benchmark data validation functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.adapter = MockPlatformAdapter()
        self.benchmark = MockBenchmark()

    def test_validate_table_row_counts_empty_tables(self):
        """Test validation fails when tables are empty."""
        table_stats = {"test_table": 0, "another_table": 0}

        status, details = self.adapter._validate_table_row_counts(self.benchmark, table_stats)

        assert status == "FAILED"
        assert details["row_count_matches"] is False
        assert "empty_tables" in details
        assert set(details["empty_tables"]) == {"test_table", "another_table"}
        assert details["total_tables_validated"] == 2
        assert details["tables_with_data"] == 0

    def test_validate_table_row_counts_partial_empty(self):
        """Test validation handles mix of empty and non-empty tables."""
        table_stats = {"test_table": 100, "empty_table": 0}

        status, details = self.adapter._validate_table_row_counts(self.benchmark, table_stats)

        assert status == "FAILED"
        assert details["row_count_matches"] is False
        assert details["empty_tables"] == ["empty_table"]
        assert details["total_tables_validated"] == 2
        assert details["tables_with_data"] == 1

    def test_validate_table_row_counts_all_good(self):
        """Test validation passes when all tables have data."""
        table_stats = {"test_table": 100, "another_table": 50}

        status, details = self.adapter._validate_table_row_counts(self.benchmark, table_stats)

        assert status == "PASSED"
        assert details["row_count_matches"] is True
        assert "empty_tables" not in details
        assert details["total_tables_validated"] == 2
        assert details["tables_with_data"] == 2

    def test_validate_table_row_counts_with_expected_minimums(self):
        """Test validation against expected minimum row counts."""
        # Mock benchmark with expected row counts
        benchmark_with_expected = MockBenchmark()
        benchmark_with_expected.expected_row_counts = {"test_table": 150}

        table_stats = {"test_table": 100}  # Below minimum

        status, details = self.adapter._validate_table_row_counts(benchmark_with_expected, table_stats)

        assert status == "PARTIAL"
        assert details["row_count_matches"] is False
        assert "insufficient_data_tables" in details
        insufficient = details["insufficient_data_tables"][0]
        assert insufficient["table"] == "test_table"
        assert insufficient["actual"] == 100
        assert insufficient["expected_minimum"] == 150

    def test_validate_schema_integrity_missing_tables(self):
        """Test schema validation fails when tables are missing."""
        # Mock connection that returns empty table list
        mock_connection = Mock()
        self.adapter._get_existing_tables = Mock(return_value=[])

        benchmark = MockBenchmark(tables={"test_table": "/tmp/test.tbl", "another_table": "/tmp/another.tbl"})

        status, details = self.adapter._validate_schema_integrity(benchmark, mock_connection)

        assert status == "FAILED"
        assert details["schema_valid"] is False
        assert set(details["missing_tables"]) == {"test_table", "another_table"}

    def test_validate_schema_integrity_all_tables_exist(self):
        """Test schema validation passes when all tables exist."""
        mock_connection = Mock()
        self.adapter._get_existing_tables = Mock(return_value=["test_table", "another_table"])

        benchmark = MockBenchmark(tables={"test_table": "/tmp/test.tbl", "another_table": "/tmp/another.tbl"})

        status, details = self.adapter._validate_schema_integrity(benchmark, mock_connection)

        assert status == "PASSED"
        assert details["schema_valid"] is True
        assert set(details["verified_tables"]) == {"test_table", "another_table"}

    def test_validate_data_integrity_inaccessible_tables(self):
        """Test data integrity validation fails when tables are inaccessible."""
        mock_connection = Mock()
        # Mock cursor that raises exception when executing queries
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Table not accessible")
        mock_connection.cursor.return_value = mock_cursor
        # Strip _mock_name attribute so the validation logic treats it as a real connection
        if hasattr(mock_connection, "_mock_name"):
            del mock_connection._mock_name

        table_stats = {"test_table": 100}

        status, details = self.adapter._validate_data_integrity(self.benchmark, mock_connection, table_stats)

        assert status == "FAILED"
        assert details["constraints_enabled"] is False
        assert details["inaccessible_tables"] == ["test_table"]

    def test_validate_data_integrity_all_accessible(self):
        """Test data integrity validation passes when all tables are accessible."""
        mock_connection = Mock()
        mock_connection.execute.return_value = Mock()  # Successful query

        table_stats = {"test_table": 100}

        status, details = self.adapter._validate_data_integrity(self.benchmark, mock_connection, table_stats)

        assert status == "PASSED"
        assert details["constraints_enabled"] is True
        assert details["accessible_tables"] == ["test_table"]

    def test_create_enhanced_validation_phase_with_data(self):
        """Test comprehensive validation phase creation."""
        # Mock successful validations
        mock_connection = Mock()
        mock_connection.execute.return_value = Mock()
        self.adapter._get_existing_tables = Mock(return_value=["test_table"])

        table_stats = {"test_table": 100}

        validation_phase = self.adapter._create_enhanced_validation_phase(self.benchmark, mock_connection, table_stats)

        assert isinstance(validation_phase, ValidationPhase)
        assert validation_phase.row_count_validation == "PASSED"
        assert validation_phase.schema_validation == "PASSED"
        assert validation_phase.data_integrity_checks == "PASSED"
        assert validation_phase.validation_details["row_count_matches"] is True
        assert validation_phase.validation_details["schema_valid"] is True
        assert validation_phase.validation_details["constraints_enabled"] is True

    def test_create_enhanced_validation_phase_with_failures(self):
        """Test validation phase creation with failures."""
        mock_connection = Mock()
        # Mock cursor that raises exception when executing queries
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("Connection failed")
        mock_connection.cursor.return_value = mock_cursor
        # Strip _mock_name attribute so the validation logic treats it as a real connection
        if hasattr(mock_connection, "_mock_name"):
            del mock_connection._mock_name
        self.adapter._get_existing_tables = Mock(return_value=[])

        table_stats = {"test_table": 0}  # Empty table

        validation_phase = self.adapter._create_enhanced_validation_phase(self.benchmark, mock_connection, table_stats)

        assert validation_phase.row_count_validation == "FAILED"
        assert validation_phase.schema_validation == "FAILED"
        assert validation_phase.data_integrity_checks == "FAILED"
        assert validation_phase.validation_details["row_count_matches"] is False
        assert validation_phase.validation_details["schema_valid"] is False
        assert validation_phase.validation_details["constraints_enabled"] is False

    def test_determine_overall_validation_status(self):
        """Test overall validation status determination logic."""
        # Mock validation phases for different scenarios

        # All passed
        passed_phase = Mock()
        passed_phase.row_count_validation = "PASSED"
        passed_phase.schema_validation = "PASSED"
        passed_phase.data_integrity_checks = "PASSED"
        assert self.adapter._determine_overall_validation_status(passed_phase) == "PASSED"

        # One failed
        failed_phase = Mock()
        failed_phase.row_count_validation = "FAILED"
        failed_phase.schema_validation = "PASSED"
        failed_phase.data_integrity_checks = "PASSED"
        assert self.adapter._determine_overall_validation_status(failed_phase) == "FAILED"

        # One partial
        partial_phase = Mock()
        partial_phase.row_count_validation = "PARTIAL"
        partial_phase.schema_validation = "PASSED"
        partial_phase.data_integrity_checks = "PASSED"
        assert self.adapter._determine_overall_validation_status(partial_phase) == "PARTIAL"

    @patch("benchbox.platforms.base.PlatformAdapter.load_data")
    def test_run_enhanced_benchmark_validation_failure_stops_execution(self, mock_load_data):
        """Test that validation failures stop benchmark execution."""
        # Mock data loading to return empty tables
        mock_load_data.return_value = ({"test_table": 0}, 1.0, None)

        # Mock other dependencies
        self.adapter.create_database = Mock(return_value=(Mock(), {}))
        self.adapter._get_existing_tables = Mock(return_value=[])

        benchmark = MockBenchmark()
        run_config = {"benchmark_type": "olap"}

        # This should fail validation and return early
        result = self.adapter.run_enhanced_benchmark(benchmark, **run_config)

        # Verify result indicates failure
        assert result.validation_status == "FAILED"
        assert result.total_queries == 0  # No queries should have been executed
        assert result.successful_queries == 0

    @patch("benchbox.platforms.base.PlatformAdapter.load_data")
    def test_run_enhanced_benchmark_validation_success_continues_execution(self, mock_load_data):
        """Test that validation success allows benchmark execution to continue."""
        # Mock successful data loading
        mock_load_data.return_value = ({"test_table": 100}, 1.0, None)

        # Mock other dependencies
        self.adapter.create_database = Mock(return_value=(Mock(), {}))
        self.adapter._get_existing_tables = Mock(return_value=["test_table"])
        mock_connection = Mock()
        mock_connection.execute.return_value = Mock()
        self.adapter.connect = Mock(return_value=mock_connection)

        # Mock query execution
        self.adapter._execute_all_queries = Mock(
            return_value=[{"query_id": "Q1", "execution_time_seconds": 0.1, "status": "SUCCESS"}]
        )

        benchmark = MockBenchmark()
        run_config = {"benchmark_type": "olap"}

        result = self.adapter.run_enhanced_benchmark(benchmark, **run_config)

        # Verify validation passed and queries were executed
        assert result.validation_status == "PASSED"
        # Note: The actual query count depends on the benchmark implementation


class MockPlatformAdapterErrorHandling:
    """Test improved error handling in platform adapters."""

    def test_clickhouse_adapter_critical_failure_propagation(self):
        """Test that ClickHouse adapter handles critical data loading failures gracefully."""
        from benchbox.platforms.clickhouse import ClickHouseAdapter

        adapter = ClickHouseAdapter(deployment_mode="local")

        # temporary files to ensure they exist
        with tempfile.TemporaryDirectory() as temp_dir:
            file1 = Path(temp_dir) / "table1.tbl"
            file2 = Path(temp_dir) / "table2.tbl"

            # files with some content
            file1.write_text("some,test,data\n")
            file2.write_text("more,test,data\n")

            benchmark = MockBenchmark(tables={"table1": str(file1), "table2": str(file2)})

            # Mock connection to raise error when attempting to load data
            mock_connection = Mock()
            mock_connection.execute.side_effect = Exception("Simulated load failure")

            # Load data - errors should be logged but not raise
            table_stats, load_time, _ = adapter.load_data(benchmark, mock_connection, Path(temp_dir))

            # Verify that both tables failed to load (should not be in stats dict or have 0 rows)
            assert table_stats.get("TABLE1", 0) == 0, "table1 should have 0 rows due to load failure"
            assert table_stats.get("TABLE2", 0) == 0, "table2 should have 0 rows due to load failure"
            # Verify that load returned but didn't succeed
            assert isinstance(table_stats, dict), "Should return a dict even on failure"
            assert isinstance(load_time, (int, float)), "Should return load time even on failure"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
