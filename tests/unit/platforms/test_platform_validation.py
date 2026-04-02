"""Unit tests for database validation module."""

from unittest.mock import Mock, patch

import pytest

from benchbox.platforms.base.models import DatabaseValidationResult
from benchbox.platforms.base.validation import (
    ConnectionValidator,
    DatabaseValidator,
    GenericRowCountStrategy,
    RowCountValidator,
    SchemaValidator,
    SSBRowCountStrategy,
    TPCDSRowCountStrategy,
    TPCHRowCountStrategy,
    TuningValidator,
    ValidationResult,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_initialization(self):
        """Test ValidationResult initialization."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid is True
        assert result.errors == []
        assert result.warnings == []

    def test_add_error(self):
        """Test adding errors invalidates result."""
        result = ValidationResult(is_valid=True)
        result.add_error("Test error")
        assert result.is_valid is False
        assert "Test error" in result.errors

    def test_add_warning(self):
        """Test adding warnings doesn't invalidate result."""
        result = ValidationResult(is_valid=True)
        result.add_warning("Test warning")
        assert result.is_valid is True
        assert "Test warning" in result.warnings


class TestConnectionValidator:
    """Test ConnectionValidator."""

    def test_create_temporary_connection_with_direct_connection(self):
        """Test connection creation when _create_direct_connection exists."""
        mock_adapter = Mock()
        mock_adapter._create_direct_connection = Mock(return_value="mock_connection")
        mock_adapter.get_database_path = Mock(return_value="/path/to/db")
        mock_adapter.close_connection = Mock()

        validator = ConnectionValidator(mock_adapter, {"database": "test"})

        with validator.create_temporary_connection() as conn:
            assert conn == "mock_connection"

        mock_adapter._create_direct_connection.assert_called_once_with(database="test")
        mock_adapter.close_connection.assert_called_once_with("mock_connection")

    def test_create_temporary_connection_with_flag(self):
        """Test connection creation using validation flag."""
        mock_adapter = Mock(spec=["get_database_path", "create_connection", "close_connection"])
        mock_adapter.create_connection = Mock(return_value="mock_connection")
        mock_adapter.get_database_path = Mock(return_value="/path/to/db")
        mock_adapter.close_connection = Mock()

        validator = ConnectionValidator(mock_adapter, {"database": "test"})

        # Store flag state during execution
        flag_states = []

        def record_flag_state(*args, **kwargs):
            flag_states.append(mock_adapter._validating_database)
            return "mock_connection"

        mock_adapter.create_connection = Mock(side_effect=record_flag_state)

        with validator.create_temporary_connection() as conn:
            assert conn == "mock_connection"

        # Flag should have been True during execution
        assert True in flag_states
        # Flag should be reset after context manager exits
        assert mock_adapter._validating_database is False
        mock_adapter.close_connection.assert_called_once_with("mock_connection")

    def test_validate_success(self):
        """Test successful connection validation."""
        mock_adapter = Mock()
        mock_adapter._create_direct_connection = Mock(return_value="mock_connection")
        mock_adapter.get_database_path = Mock(return_value="/path/to/db")
        mock_adapter.close_connection = Mock()

        validator = ConnectionValidator(mock_adapter, {"database": "test"})
        result = validator.validate()

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_failure(self):
        """Test connection validation failure."""
        mock_adapter = Mock()
        mock_adapter.get_database_path = Mock(side_effect=Exception("Connection failed"))

        validator = ConnectionValidator(mock_adapter, {"database": "test"})
        result = validator.validate()

        assert result.is_valid is False
        assert "Failed to establish connection" in result.errors[0]


class TestTuningValidator:
    """Test TuningValidator."""

    def test_validate_no_tuning_enabled(self):
        """Test validation when tuning is not enabled."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = False
        mock_adapter.get_effective_tuning_configuration = Mock(return_value=None)

        validator = TuningValidator(mock_adapter, {})
        result = validator.validate()

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_validate_with_valid_tuning(self):
        """Test validation with valid tuning configuration."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = True
        mock_adapter.get_effective_tuning_configuration = Mock(return_value={"some": "config"})

        mock_tuning_result = Mock()
        mock_tuning_result.is_valid = True
        mock_tuning_result.errors = []
        mock_adapter._validate_database_tunings = Mock(return_value=mock_tuning_result)

        validator = TuningValidator(mock_adapter, {})
        result = validator.validate()

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_with_invalid_tuning(self):
        """Test validation with invalid tuning configuration."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = True
        mock_adapter.get_effective_tuning_configuration = Mock(return_value={"some": "config"})

        mock_tuning_result = Mock()
        mock_tuning_result.is_valid = False
        mock_tuning_result.errors = ["Error 1", "Error 2"]
        mock_adapter._validate_database_tunings = Mock(return_value=mock_tuning_result)

        validator = TuningValidator(mock_adapter, {})
        result = validator.validate()

        assert result.is_valid is False
        assert len(result.errors) == 2
        assert "Tuning: Error 1" in result.errors

    def test_validate_with_many_tuning_errors(self):
        """Test validation with more than 3 tuning errors."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = True
        mock_adapter.get_effective_tuning_configuration = Mock(return_value={"some": "config"})

        mock_tuning_result = Mock()
        mock_tuning_result.is_valid = False
        mock_tuning_result.errors = [f"Error {i}" for i in range(10)]
        mock_adapter._validate_database_tunings = Mock(return_value=mock_tuning_result)

        validator = TuningValidator(mock_adapter, {})
        result = validator.validate()

        assert result.is_valid is False
        assert len(result.errors) == 4  # First 3 + summary
        assert "... and 7 more tuning errors" in result.errors[-1]

    def test_validate_unexpected_metadata(self):
        """Test validation warns about unexpected tuning metadata."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = True
        mock_adapter.get_effective_tuning_configuration = Mock(return_value=None)

        # Mock TuningMetadataManager - patch at the import location
        with patch("benchbox.core.tuning.metadata.TuningMetadataManager") as mock_manager_class:
            mock_manager = mock_manager_class.return_value
            mock_manager.load_tunings.return_value = ["tuning1", "tuning2"]

            validator = TuningValidator(mock_adapter, {"database": "test"})
            result = validator.validate()

            assert result.is_valid is True
            assert len(result.warnings) == 1
            assert "contains tuning metadata" in result.warnings[0]


class TestSchemaValidator:
    """Test SchemaValidator."""

    def test_validate_no_benchmark_instance(self):
        """Test validation with no benchmark instance skips gracefully."""
        mock_adapter = Mock(spec=["benchmark_instance"])
        mock_adapter.benchmark_instance = None

        validator = SchemaValidator(mock_adapter, {})
        result = validator.validate(Mock())

        # Missing benchmark_instance is treated as skipped (not invalid)
        assert result.is_valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 1
        assert "benchmark_instance not set" in result.warnings[0]

    def test_validate_all_tables_present(self):
        """Test validation when all expected tables are present."""
        mock_adapter = Mock()
        mock_benchmark = Mock()
        mock_benchmark.get_schema = Mock(return_value={"table1": {}, "table2": {}})
        mock_adapter.benchmark_instance = mock_benchmark
        mock_adapter._get_existing_tables = Mock(return_value=["table1", "table2"])

        validator = SchemaValidator(mock_adapter, {})
        result = validator.validate(Mock())

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_missing_tables(self):
        """Test validation detects missing tables."""
        mock_adapter = Mock()
        mock_benchmark = Mock()
        mock_benchmark.get_schema = Mock(return_value={"table1": {}, "table2": {}, "table3": {}})
        mock_adapter.benchmark_instance = mock_benchmark
        mock_adapter._get_existing_tables = Mock(return_value=["table1"])

        validator = SchemaValidator(mock_adapter, {})
        result = validator.validate(Mock())

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "Missing tables" in result.errors[0]
        assert "table2" in result.errors[0]
        assert "table3" in result.errors[0]

    def test_validate_extra_tables(self):
        """Test validation detects extra tables."""
        mock_adapter = Mock()
        mock_benchmark = Mock()
        mock_benchmark.get_schema = Mock(return_value={"table1": {}})
        mock_adapter.benchmark_instance = mock_benchmark
        mock_adapter._get_existing_tables = Mock(return_value=["table1", "table2", "extra_table"])

        validator = SchemaValidator(mock_adapter, {})
        result = validator.validate(Mock())

        assert result.is_valid is True  # Extra tables are just warnings
        assert len(result.warnings) == 1
        assert "Extra tables found" in result.warnings[0]

    def test_validate_filters_system_tables(self):
        """Test validation filters out system tables."""
        mock_adapter = Mock()
        mock_benchmark = Mock()
        mock_benchmark.get_schema = Mock(return_value={"table1": {}})
        mock_adapter.benchmark_instance = mock_benchmark
        mock_adapter._get_existing_tables = Mock(return_value=["table1", "benchbox_tuning_metadata", "sqlite_sequence"])

        validator = SchemaValidator(mock_adapter, {})
        result = validator.validate(Mock())

        assert result.is_valid is True
        assert len(result.warnings) == 0  # System tables filtered out


class TestRowCountStrategies:
    """Test row count validation strategies."""

    def test_tpch_strategy_sample_tables(self):
        """Test TPC-H strategy checks all tables for emptiness."""
        strategy = TPCHRowCountStrategy(scale_factor=1.0)
        available = {"lineitem", "orders", "customer", "nation", "region"}
        samples = strategy.get_sample_tables(available)

        # Should return all tables to ensure none are empty
        assert len(samples) == len(available)
        assert set(samples) == available

    def test_tpch_strategy_expected_ranges(self):
        """Test TPC-H strategy returns correct row count ranges."""
        strategy = TPCHRowCountStrategy(scale_factor=1.0)

        lineitem_range = strategy.get_expected_range("lineitem")
        assert lineitem_range is not None
        assert lineitem_range[0] < lineitem_range[1]
        assert lineitem_range[0] == 6000000 * 0.8

    def test_tpcds_strategy_sample_tables(self):
        """Test TPC-DS strategy checks all tables for emptiness."""
        strategy = TPCDSRowCountStrategy(scale_factor=1.0)
        available = {"store_sales", "catalog_sales", "customer", "item"}
        samples = strategy.get_sample_tables(available)

        # Should return all tables to ensure none are empty
        assert len(samples) == len(available)
        assert set(samples) == available

    def test_ssb_strategy_sample_tables(self):
        """Test SSB strategy checks all tables for emptiness."""
        strategy = SSBRowCountStrategy(scale_factor=1.0)
        available = {"lineorder", "customer", "supplier"}
        samples = strategy.get_sample_tables(available)

        # Should return all tables to ensure none are empty
        assert len(samples) == len(available)
        assert set(samples) == available

    def test_ssb_strategy_expected_ranges(self):
        """Test SSB strategy returns correct row count ranges based on SSB spec (not TPC-H)."""
        strategy = SSBRowCountStrategy(scale_factor=1.0)

        # SSB customer base = 30,000/SF (not 150,000 which is the TPC-H value)
        customer_range = strategy.get_expected_range("customer")
        assert customer_range is not None
        assert customer_range[0] == 30000 * 0.8
        assert customer_range[1] == 30000 * 1.2

        # SSB lineorder base = 6,000,000/SF
        lineorder_range = strategy.get_expected_range("lineorder")
        assert lineorder_range is not None
        assert lineorder_range[0] == 6000000 * 0.8
        assert lineorder_range[1] == 6000000 * 1.2

        # Unknown tables return None
        assert strategy.get_expected_range("supplier") is None

    def test_ssb_strategy_expected_ranges_sf10(self):
        """Test SSB expected ranges at SF=10 match actual generated row counts."""
        strategy = SSBRowCountStrategy(scale_factor=10.0)

        # At SF=10: 300,000 customer rows must be within range
        customer_range = strategy.get_expected_range("customer")
        assert customer_range[0] <= 300_000 <= customer_range[1], (
            f"300,000 customer rows at SF=10 should be in range {customer_range}"
        )

        # At SF=10: 60,000,000 lineorder rows must be within range
        lineorder_range = strategy.get_expected_range("lineorder")
        assert lineorder_range[0] <= 60_000_000 <= lineorder_range[1]

    def test_generic_strategy_sample_tables(self):
        """Test generic strategy checks all tables for emptiness."""
        strategy = GenericRowCountStrategy(scale_factor=1.0)
        available = {"table1", "table2", "table3"}
        samples = strategy.get_sample_tables(available)

        # Should return all tables to ensure none are empty
        assert len(samples) == len(available)
        assert set(samples) == available

    def test_generic_strategy_no_expected_ranges(self):
        """Test generic strategy has no specific expectations."""
        strategy = GenericRowCountStrategy(scale_factor=1.0)
        assert strategy.get_expected_range("any_table") is None

    def test_scale_factor_affects_ranges(self):
        """Test that scale factor affects row count ranges."""
        strategy1 = TPCHRowCountStrategy(scale_factor=1.0)
        strategy2 = TPCHRowCountStrategy(scale_factor=10.0)

        range1 = strategy1.get_expected_range("lineitem")
        range2 = strategy2.get_expected_range("lineitem")

        assert range2[0] == range1[0] * 10
        assert range2[1] == range1[1] * 10


class TestRowCountValidator:
    """Test RowCountValidator."""

    def test_validate_no_scale_factor(self):
        """Test validation skips when no scale factor is set."""
        mock_adapter = Mock(spec=["benchmark_instance"])
        mock_adapter.benchmark_instance = Mock()

        validator = RowCountValidator(mock_adapter, {})
        result = validator.validate(Mock(), {"table1"})

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_no_tables(self):
        """Test validation skips when no tables provided."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_adapter.benchmark_instance = Mock()

        validator = RowCountValidator(mock_adapter, {})
        result = validator.validate(Mock(), set())

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_get_strategy_tpch(self):
        """Test strategy selection for TPC-H benchmark."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCHBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        validator = RowCountValidator(mock_adapter, {})
        strategy = validator._get_strategy()

        assert isinstance(strategy, TPCHRowCountStrategy)

    def test_get_strategy_tpcds(self):
        """Test strategy selection for TPC-DS benchmark."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCDSBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        validator = RowCountValidator(mock_adapter, {})
        strategy = validator._get_strategy()

        assert isinstance(strategy, TPCDSRowCountStrategy)

    def test_get_strategy_ssb(self):
        """Test strategy selection for SSB benchmark."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "SSBBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        validator = RowCountValidator(mock_adapter, {})
        strategy = validator._get_strategy()

        assert isinstance(strategy, SSBRowCountStrategy)

    def test_get_strategy_generic(self):
        """Test strategy selection for unknown benchmark."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "UnknownBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        validator = RowCountValidator(mock_adapter, {})
        strategy = validator._get_strategy()

        assert isinstance(strategy, GenericRowCountStrategy)

    def test_validate_table_row_count_within_range(self):
        """Test validation passes when row count is within expected range."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCHBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        # Mock connection and cursor
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (6000000,)  # Within range
        mock_connection = Mock()
        mock_connection.cursor.return_value = mock_cursor

        validator = RowCountValidator(mock_adapter, {})
        result = validator.validate(mock_connection, {"lineitem"})

        assert result.is_valid is True
        assert len(result.errors) == 0

    def test_validate_table_row_count_outside_range(self):
        """Test validation fails when row count is outside expected range."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "TPCHBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        # Mock get_table_row_count to return a value outside the expected range
        mock_adapter.get_table_row_count = Mock(return_value=100)  # Outside range for lineitem at SF=1

        mock_connection = Mock()

        validator = RowCountValidator(mock_adapter, {})
        result = validator.validate(mock_connection, {"lineitem"})

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "expected" in result.errors[0].lower()

    def test_validate_table_empty(self):
        """Test validation detects empty tables."""
        mock_adapter = Mock()
        mock_adapter.scale_factor = 1.0
        mock_benchmark = Mock()
        mock_benchmark.__class__.__name__ = "UnknownBenchmark"
        mock_adapter.benchmark_instance = mock_benchmark

        # Mock get_table_row_count to return 0 (empty table)
        mock_adapter.get_table_row_count = Mock(return_value=0)

        mock_connection = Mock()

        validator = RowCountValidator(mock_adapter, {})
        result = validator.validate(mock_connection, {"some_table"})

        assert result.is_valid is False
        assert len(result.errors) == 1
        assert "empty" in result.errors[0].lower()


class TestDatabaseValidator:
    """Test DatabaseValidator orchestrator."""

    def test_validate_success(self):
        """Test successful complete validation."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = False
        # Setup benchmark_instance with proper schema
        mock_benchmark = Mock()
        mock_benchmark.get_schema = Mock(return_value={"table1": {}, "table2": {}})
        mock_adapter.benchmark_instance = mock_benchmark
        mock_adapter.get_effective_tuning_configuration = Mock(return_value=None)
        mock_adapter.log_operation_start = Mock()
        mock_adapter.log_operation_complete = Mock()
        mock_adapter.log_very_verbose = Mock()

        # Mock connection creation
        mock_connection = Mock()
        with patch.object(ConnectionValidator, "create_temporary_connection") as mock_conn_mgr:
            mock_conn_mgr.return_value.__enter__ = Mock(return_value=mock_connection)
            mock_conn_mgr.return_value.__exit__ = Mock(return_value=False)

            # Mock successful validation results
            with (
                patch.object(TuningValidator, "validate") as mock_tuning,
                patch.object(SchemaValidator, "validate") as mock_schema,
                patch.object(RowCountValidator, "validate") as mock_rows,
            ):
                mock_tuning.return_value = ValidationResult(is_valid=True)
                mock_schema.return_value = ValidationResult(is_valid=True)
                mock_rows.return_value = ValidationResult(is_valid=True)

                validator = DatabaseValidator(mock_adapter, {})
                result = validator.validate()

                assert isinstance(result, DatabaseValidationResult)
                assert result.is_valid is True
                assert result.can_reuse is True

    def test_validate_with_errors(self):
        """Test validation with errors from sub-validators."""
        mock_adapter = Mock()
        mock_adapter.tuning_enabled = False
        mock_adapter.benchmark_instance = Mock()
        mock_adapter.get_effective_tuning_configuration = Mock(return_value=None)
        mock_adapter.log_operation_start = Mock()
        mock_adapter.log_operation_complete = Mock()

        # Mock connection creation
        mock_connection = Mock()
        with patch.object(ConnectionValidator, "create_temporary_connection") as mock_conn_mgr:
            mock_conn_mgr.return_value.__enter__ = Mock(return_value=mock_connection)
            mock_conn_mgr.return_value.__exit__ = Mock(return_value=False)

            # Mock validation results with errors
            with (
                patch.object(TuningValidator, "validate") as mock_tuning,
                patch.object(SchemaValidator, "validate") as mock_schema,
                patch.object(RowCountValidator, "validate") as mock_rows,
            ):
                mock_tuning.return_value = ValidationResult(is_valid=True)

                schema_result = ValidationResult(is_valid=False)
                schema_result.add_error("Missing tables: table1, table2")
                mock_schema.return_value = schema_result

                mock_rows.return_value = ValidationResult(is_valid=True)

                validator = DatabaseValidator(mock_adapter, {})
                result = validator.validate()

                assert result.is_valid is False
                assert len(result.issues) > 0
                assert "Missing tables" in result.issues[0]

    def test_validate_connection_exception(self):
        """Test validation handles connection exceptions."""
        mock_adapter = Mock()
        mock_adapter.log_operation_start = Mock()

        with patch.object(ConnectionValidator, "create_temporary_connection") as mock_conn_mgr:
            mock_conn_mgr.side_effect = Exception("Connection failed")

            validator = DatabaseValidator(mock_adapter, {})
            result = validator.validate()

            assert result.is_valid is False
            assert result.can_reuse is False
            assert "Database validation failed" in result.issues[0]

    def test_determine_validity_all_valid(self):
        """Test validity determination when all checks pass."""
        mock_adapter = Mock()
        validator = DatabaseValidator(mock_adapter, {})

        is_valid, can_reuse = validator._determine_validity(tuning_valid=True, tables_valid=True, row_counts_valid=True)

        assert is_valid is True
        assert can_reuse is True

    def test_determine_validity_row_count_invalid(self):
        """Test validity determination when row counts are invalid."""
        mock_adapter = Mock()
        validator = DatabaseValidator(mock_adapter, {})

        is_valid, can_reuse = validator._determine_validity(
            tuning_valid=True, tables_valid=True, row_counts_valid=False
        )

        assert is_valid is False
        assert can_reuse is True  # Can still reuse if tables are valid

    def test_determine_validity_tables_invalid(self):
        """Test validity determination when tables are invalid."""
        mock_adapter = Mock()
        validator = DatabaseValidator(mock_adapter, {})

        is_valid, can_reuse = validator._determine_validity(
            tuning_valid=True, tables_valid=False, row_counts_valid=None
        )

        assert is_valid is False
        assert can_reuse is False  # Cannot reuse if tables are invalid

    def test_determine_validity_no_benchmark(self):
        """Test validity determination without benchmark instance."""
        mock_adapter = Mock(spec=[])  # No benchmark_instance attribute
        validator = DatabaseValidator(mock_adapter, {})

        is_valid, can_reuse = validator._determine_validity(tuning_valid=None, tables_valid=None, row_counts_valid=None)

        assert is_valid is False
        assert can_reuse is False


@pytest.mark.unit
@pytest.mark.unit
class TestValidationCoverageGaps:
    """Test validation coverage gaps."""

    def test_schema_validator_exception_handling(self):
        """Test schema validator exception handling."""
        adapter = Mock()
        adapter._get_existing_tables.side_effect = Exception("DB error")
        validator = SchemaValidator(adapter, {})

        result = validator.validate(Mock())

        assert result is not None
        assert isinstance(result.errors, list)

    def test_row_count_validator_exception_handling(self):
        """Test row count validator exception handling."""
        adapter = Mock()
        adapter.get_table_row_count.side_effect = RuntimeError("Query failed")
        validator = RowCountValidator(adapter, {})

        result = validator.validate(Mock(), {"table1"})

        # Should handle gracefully with warning
        assert result is not None
        assert len(result.warnings) > 0

    def test_database_validator_initialization(self):
        """Test database validator initialization and structure."""
        adapter = Mock()
        config = {"type": "duckdb"}
        validator = DatabaseValidator(adapter, config)

        # Should initialize correctly
        assert validator is not None
        assert hasattr(validator, "validate")
        assert hasattr(validator, "connection_validator")
        assert hasattr(validator, "schema_validator")
