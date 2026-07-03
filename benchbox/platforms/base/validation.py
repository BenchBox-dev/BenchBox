"""Database validation module for BenchBox platform adapters.

This module provides a modular validation framework for checking database compatibility,
including schema validation, row count verification, and tuning configuration checks.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from benchbox.platforms.base.models import DatabaseValidationResult


@dataclass
class ValidationResult:
    """Generic validation result with errors and warnings."""

    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.is_valid = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)


class BaseValidator(ABC):
    """Abstract base class for validators."""

    def __init__(self, adapter: Any, connection_config: dict[str, Any]):
        """Initialize validator with adapter and connection config.

        Args:
            adapter: The platform adapter instance
            connection_config: Connection configuration dictionary
        """
        self.adapter = adapter
        self.connection_config = connection_config

    @abstractmethod
    def validate(self) -> ValidationResult:
        """Perform validation and return results.

        Returns:
            ValidationResult with validity status, errors, and warnings
        """


class ConnectionValidator(BaseValidator):
    """Validator for creating and managing temporary database connections."""

    @contextmanager
    def create_temporary_connection(self):
        """Create a temporary connection for validation without triggering handle_existing_database.

        Yields:
            Database connection object

        Raises:
            Exception: If connection creation fails
        """
        # Get database path to ensure it exists
        self.adapter.get_database_path(**self.connection_config)

        # Create connection using appropriate method
        if hasattr(self.adapter, "_create_direct_connection"):
            connection = self.adapter._create_direct_connection(**self.connection_config)
        else:
            # Use flag to prevent recursion
            self.adapter._validating_database = True
            try:
                connection = self.adapter.create_connection(**self.connection_config)
            finally:
                self.adapter._validating_database = False

        try:
            yield connection
        finally:
            self.adapter.close_connection(connection)

    def validate(self) -> ValidationResult:
        """Validate that a connection can be established.

        Returns:
            ValidationResult indicating if connection was successful
        """
        result = ValidationResult(is_valid=True)
        try:
            with self.create_temporary_connection():
                pass  # Connection successful
        except Exception as e:
            result.add_error(f"Failed to establish connection: {str(e)}")
        return result


class TuningValidator(BaseValidator):
    """Validator for database tuning configuration."""

    def validate(self) -> ValidationResult:
        """Validate tuning configuration and metadata.

        Returns:
            ValidationResult with tuning validation status
        """
        result = ValidationResult(is_valid=True)

        # Get effective tuning configuration
        effective_config = self.adapter.get_effective_tuning_configuration()

        if self.adapter.tuning_enabled and effective_config:
            # Validate tunings using existing method
            tuning_result = self.adapter._validate_database_tunings(**self.connection_config)
            if not tuning_result.is_valid:
                # Include first 3 errors
                for error in tuning_result.errors[:3]:
                    result.add_error(f"Tuning: {error}")
                # Include summary if more errors exist
                if len(tuning_result.errors) > 3:
                    result.add_error(f"Tuning: ... and {len(tuning_result.errors) - 3} more tuning errors")

        elif self.adapter.tuning_enabled and not effective_config:
            # Check for unexpected tuning metadata
            try:
                from benchbox.core.tuning.metadata import TuningMetadataManager

                metadata_manager = TuningMetadataManager(self.adapter, self.connection_config.get("database"))
                existing_tunings = metadata_manager.load_tunings()
                if existing_tunings and len(existing_tunings) > 0:
                    result.add_warning("Database contains tuning metadata but no tunings expected for this run")
            except Exception:
                pass  # Ignore metadata check failures

        return result


class SchemaValidator(BaseValidator):
    """Validator for database schema and table existence."""

    def validate(self, connection: Any) -> ValidationResult:
        """Validate table existence and schema compatibility.

        Args:
            connection: Database connection to use for validation

        Returns:
            ValidationResult with schema validation status
        """
        result = ValidationResult(is_valid=True)

        try:
            # This will raise ValueError if benchmark_instance is not set
            expected_tables = self._get_expected_tables()
            if not expected_tables:
                result.add_warning("Benchmark schema has no tables defined")
                return result

            # Get existing tables from database
            existing_tables = self._get_existing_tables(connection)

            # Find missing and extra tables
            missing_tables = expected_tables - existing_tables
            extra_tables = existing_tables - expected_tables

            # Handle missing tables
            if missing_tables:
                result.add_error(f"Missing tables: {', '.join(sorted(missing_tables))}")

            # Handle extra tables (after filtering system tables)
            if extra_tables:
                extra_tables = self._filter_system_tables(extra_tables)
                if extra_tables:
                    result.add_warning(f"Extra tables found: {', '.join(sorted(extra_tables))}")

        except ValueError as e:
            # Missing benchmark_instance - cannot validate, treat as skipped (not invalid)
            result.add_warning(f"Schema validation skipped: {str(e)}")
        except Exception as e:
            # Other errors - warnings
            result.add_warning(f"Table validation failed: {str(e)}")

        return result

    def _get_expected_tables(self) -> set[str]:
        """Get expected tables from benchmark schema.

        Returns:
            Set of expected table names (lowercase)

        Raises:
            ValueError: If benchmark_instance is not available or has no schema
        """
        benchmark_instance = getattr(self.adapter, "benchmark_instance", None)
        if not benchmark_instance:
            raise ValueError("benchmark_instance not set on adapter - cannot validate schema")

        if not hasattr(benchmark_instance, "get_schema"):
            raise ValueError(f"benchmark_instance {type(benchmark_instance).__name__} has no get_schema method")

        schema = benchmark_instance.get_schema()
        if not isinstance(schema, dict):
            raise ValueError(f"benchmark schema is not a dict: {type(schema)}")

        tables = {t.lower() for t in schema}
        return tables

    def _get_existing_tables(self, connection: Any) -> set[str]:
        """Get existing tables from database.

        Args:
            connection: Database connection

        Returns:
            Set of existing table names (lowercase)
        """
        existing_table_list = self.adapter._get_existing_tables(connection)
        return {t.lower() for t in existing_table_list}

    def _filter_system_tables(self, tables: set[str]) -> set[str]:
        """Filter out common system tables.

        Args:
            tables: Set of table names to filter

        Returns:
            Set of tables with system tables removed
        """
        system_tables = {
            "benchbox_tuning_metadata",
            "sqlite_sequence",
        }
        return tables - system_tables


class RowCountStrategy(ABC):
    """Abstract base class for benchmark-specific row count validation strategies."""

    def __init__(self, scale_factor: float):
        """Initialize strategy with scale factor.

        Args:
            scale_factor: Scale factor for the benchmark
        """
        self.scale_factor = scale_factor

    @abstractmethod
    def get_sample_tables(self, available_tables: set[str]) -> list[str]:
        """Get tables to sample for this benchmark.

        Args:
            available_tables: Set of available table names (lowercase)

        Returns:
            List of table names to validate (limited to 2 for performance)
        """

    @abstractmethod
    def get_expected_range(self, table: str) -> tuple[float, float] | None:
        """Get expected row count range for a table.

        Args:
            table: Table name (lowercase)

        Returns:
            Tuple of (min_rows, max_rows) or None if no expectation
        """


class TPCHRowCountStrategy(RowCountStrategy):
    """Row count validation strategy for TPC-H benchmark."""

    def get_sample_tables(self, available_tables: set[str]) -> list[str]:
        """Get TPC-H tables to sample for row count validation.

        Returns all available tables to ensure none are empty, which is critical
        for database reuse validation. Previously limited to 2 tables, but this
        could miss empty tables that weren't sampled.
        """
        # Check all tables to ensure none are empty
        return list(available_tables)

    def get_expected_range(self, table: str) -> tuple[float, float] | None:
        """Get expected row count range for TPC-H tables."""
        ranges = {
            "lineitem": (6000000 * self.scale_factor * 0.8, 6000000 * self.scale_factor * 1.2),
            "orders": (1500000 * self.scale_factor * 0.8, 1500000 * self.scale_factor * 1.2),
            "customer": (150000 * self.scale_factor * 0.8, 150000 * self.scale_factor * 1.2),
        }
        return ranges.get(table)


class TPCDSRowCountStrategy(RowCountStrategy):
    """Row count validation strategy for TPC-DS benchmark."""

    def get_sample_tables(self, available_tables: set[str]) -> list[str]:
        """Get TPC-DS tables to sample for row count validation.

        Returns all available tables to ensure none are empty, which is critical
        for database reuse validation. Previously limited to 2 tables, but this
        could miss empty tables that weren't sampled.
        """
        # Check all tables to ensure none are empty
        return list(available_tables)

    def get_expected_range(self, table: str) -> tuple[float, float] | None:
        """Get expected row count range for TPC-DS tables."""
        ranges = {
            "store_sales": (2880000 * self.scale_factor * 0.8, 2880000 * self.scale_factor * 1.2),
            "catalog_sales": (1440000 * self.scale_factor * 0.8, 1440000 * self.scale_factor * 1.2),
            "customer": (100000 * self.scale_factor * 0.8, 100000 * self.scale_factor * 1.2),
        }
        return ranges.get(table)


class SSBRowCountStrategy(RowCountStrategy):
    """Row count validation strategy for Star Schema Benchmark (SSB)."""

    def get_sample_tables(self, available_tables: set[str]) -> list[str]:
        """Get SSB tables to sample for row count validation.

        Returns all available tables to ensure none are empty, which is critical
        for database reuse validation. Previously limited to 2 tables, but this
        could miss empty tables that weren't sampled.
        """
        # Check all tables to ensure none are empty
        return list(available_tables)

    def get_expected_range(self, table: str) -> tuple[float, float] | None:
        """Get expected row count range for SSB tables."""
        ranges = {
            "lineorder": (6000000 * self.scale_factor * 0.8, 6000000 * self.scale_factor * 1.2),
            "customer": (30000 * self.scale_factor * 0.8, 30000 * self.scale_factor * 1.2),
        }
        return ranges.get(table)


class JoinOrderRowCountStrategy(RowCountStrategy):
    """Exact row count validation strategy for canonical JoinOrder data."""

    def __init__(self, scale_factor: float, benchmark_instance: Any):
        """Initialize with the benchmark instance that owns the data manifest."""
        super().__init__(scale_factor)
        self.benchmark_instance = benchmark_instance

    def get_sample_tables(self, available_tables: set[str]) -> list[str]:
        """Validate all loaded JoinOrder tables against manifest counts."""
        return list(available_tables)

    def get_expected_range(self, table: str) -> tuple[float, float] | None:
        """Get exact expected row count from the JoinOrder manifest."""
        row_count_getter = getattr(self.benchmark_instance, "get_table_row_count", None)
        if row_count_getter is None:
            return None

        expected_rows = int(row_count_getter(table))
        if expected_rows <= 0:
            return None
        return (float(expected_rows), float(expected_rows))


class GenericRowCountStrategy(RowCountStrategy):
    """Generic row count validation strategy for unknown benchmarks."""

    def get_sample_tables(self, available_tables: set[str]) -> list[str]:
        """Get all available tables to check for emptiness."""
        return list(available_tables)

    def get_expected_range(self, table: str) -> tuple[float, float] | None:
        """No specific expectations for unknown benchmarks.

        Only validates that tables are not empty.
        """
        return None


class RowCountValidator(BaseValidator):
    """Validator for row counts based on scale factor."""

    def validate(self, connection: Any, expected_tables: set[str]) -> ValidationResult:
        """Validate row counts for expected scale factor.

        Args:
            connection: Database connection to use for queries
            expected_tables: Set of expected table names (lowercase)

        Returns:
            ValidationResult with row count validation status
        """
        result = ValidationResult(is_valid=True)

        # Check if we have required information
        getattr(self.adapter, "scale_factor", None)
        if not (hasattr(self.adapter, "scale_factor") and self.adapter.scale_factor):
            return result  # No scale factor, skip validation

        if not expected_tables:
            return result  # No tables to validate

        try:
            # Get strategy for this benchmark
            strategy = self._get_strategy()

            # Get tables to sample
            sample_tables = strategy.get_sample_tables(expected_tables)

            # Validate each sample table
            for table in sample_tables:
                self._validate_table_row_count(connection, table, strategy, result)

        except ValueError as e:
            # Missing benchmark_instance - cannot validate, treat as skipped (not invalid)
            result.add_warning(f"Row count validation skipped: {str(e)}")
        except Exception as e:
            # Other errors - warnings
            result.add_warning(f"Row count validation failed: {str(e)}")

        return result

    def _get_strategy(self) -> RowCountStrategy:
        """Get appropriate row count strategy based on benchmark.

        Returns:
            RowCountStrategy instance for the current benchmark

        Raises:
            ValueError: If benchmark_instance is not available
        """
        benchmark_instance = getattr(self.adapter, "benchmark_instance", None)
        if not benchmark_instance:
            raise ValueError("benchmark_instance not set on adapter - cannot determine row count strategy")

        scale = getattr(self.adapter, "scale_factor", 1.0)
        benchmark_name = getattr(
            benchmark_instance,
            "__class__",
            type(benchmark_instance),
        ).__name__.lower()

        if "tpch" in benchmark_name:
            return TPCHRowCountStrategy(scale)
        elif "tpcds" in benchmark_name:
            return TPCDSRowCountStrategy(scale)
        elif "ssb" in benchmark_name:
            return SSBRowCountStrategy(scale)
        elif "joinorder" in benchmark_name:
            return JoinOrderRowCountStrategy(scale, benchmark_instance)
        else:
            return GenericRowCountStrategy(scale)

    def _validate_table_row_count(
        self, connection: Any, table: str, strategy: RowCountStrategy, result: ValidationResult
    ) -> None:
        """Validate row count for a single table.

        Args:
            connection: Database connection
            table: Table name to validate
            strategy: Row count strategy to use
            result: ValidationResult to update with findings
        """
        try:
            # Use adapter method instead of hardcoded cursor()
            # This allows platforms like BigQuery to override with their specific APIs
            actual_rows = self.adapter.get_table_row_count(connection, table)

            # Get expected range from strategy
            expected_range = strategy.get_expected_range(table)

            if expected_range:
                min_rows, max_rows = expected_range
                if not (min_rows <= actual_rows <= max_rows):
                    result.add_error(
                        f"Table {table}: expected ~{int(min_rows):,}-{int(max_rows):,} rows, found {actual_rows:,}"
                    )
            elif actual_rows == 0:
                # For generic strategy, only check if table is empty
                result.add_error(f"Table {table} is empty")

        except Exception as e:
            result.add_warning(f"Could not validate row count for table {table}: {str(e)}")


class DatabaseValidator:
    """Main orchestrator for database compatibility validation."""

    def __init__(self, adapter: Any, connection_config: dict[str, Any]):
        """Initialize database validator.

        Args:
            adapter: Platform adapter instance
            connection_config: Connection configuration dictionary
        """
        self.adapter = adapter
        self.connection_config = connection_config

        # Initialize sub-validators
        self.connection_validator = ConnectionValidator(adapter, connection_config)
        self.tuning_validator = TuningValidator(adapter, connection_config)
        self.schema_validator = SchemaValidator(adapter, connection_config)
        self.row_count_validator = RowCountValidator(adapter, connection_config)

    def validate(self) -> DatabaseValidationResult:
        """Perform complete database compatibility validation.

        Returns:
            DatabaseValidationResult with comprehensive validation information
        """
        self.adapter.log_operation_start(
            "Database compatibility validation", "Checking schema, data, and tuning compatibility"
        )

        # Log benchmark_instance status for debugging
        benchmark_instance = getattr(self.adapter, "benchmark_instance", None)
        if benchmark_instance:
            self.adapter.log_very_verbose(f"benchmark_instance available: {type(benchmark_instance).__name__}")
        else:
            self.adapter.log_very_verbose("benchmark_instance NOT SET - validation may fail")

        issues = []
        warnings = []
        tuning_valid = None
        tables_valid = None
        row_counts_valid = None

        try:
            # Create temporary connection for validation
            with self.connection_validator.create_temporary_connection() as connection:
                # 1. Validate tuning configuration
                tuning_result = self.tuning_validator.validate()
                tuning_valid = tuning_result.is_valid
                issues.extend(tuning_result.errors)
                warnings.extend(tuning_result.warnings)

                # 2. Validate schema and tables
                schema_result = self.schema_validator.validate(connection)
                tables_valid = schema_result.is_valid
                issues.extend(schema_result.errors)
                warnings.extend(schema_result.warnings)

                # 3. Validate row counts (only if tables are valid)
                if tables_valid:
                    try:
                        expected_tables = self.schema_validator._get_expected_tables()
                    except ValueError:
                        expected_tables = set()  # No benchmark_instance - skip row count validation
                    row_count_result = self.row_count_validator.validate(connection, expected_tables)
                    row_counts_valid = row_count_result.is_valid
                    issues.extend(row_count_result.errors)
                    warnings.extend(row_count_result.warnings)

        except Exception as e:
            issues.append(f"Database validation failed: {str(e)}")
            return DatabaseValidationResult(is_valid=False, can_reuse=False, issues=issues, warnings=warnings)

        # Determine overall validity and reusability
        is_valid, can_reuse = self._determine_validity(tuning_valid, tables_valid, row_counts_valid)

        # Log results
        status = "valid" if is_valid else ("reusable" if can_reuse else "invalid")
        self.adapter.log_operation_complete(
            "Database compatibility validation",
            details=f"Status: {status}, issues: {len(issues)}, warnings: {len(warnings)}",
        )

        return DatabaseValidationResult(
            is_valid=is_valid,
            can_reuse=can_reuse,
            issues=issues,
            warnings=warnings,
            tuning_valid=tuning_valid,
            tables_valid=tables_valid,
            row_counts_valid=row_counts_valid,
        )

    def _determine_validity(
        self, tuning_valid: bool | None, tables_valid: bool | None, row_counts_valid: bool | None
    ) -> tuple[bool, bool]:
        """Determine overall validity and reusability.

        Args:
            tuning_valid: Tuning validation result (None if not validated)
            tables_valid: Table validation result (None if not validated)
            row_counts_valid: Row count validation result (None if not validated)

        Returns:
            Tuple of (is_valid, can_reuse)
        """
        # If no benchmark instance, be conservative
        has_benchmark = hasattr(self.adapter, "benchmark_instance") and self.adapter.benchmark_instance
        if tables_valid is None and not has_benchmark:
            return False, False

        # All validated aspects must pass
        is_valid = (
            (tuning_valid is None or tuning_valid)
            and (tables_valid is None or tables_valid)
            and (row_counts_valid is None or row_counts_valid)
        )

        # Can reuse if tables are valid and tuning is valid or not validated
        can_reuse = bool(is_valid or (tables_valid and (tuning_valid is None or tuning_valid)))

        return is_valid, can_reuse


__all__ = [
    "ValidationResult",
    "BaseValidator",
    "ConnectionValidator",
    "TuningValidator",
    "SchemaValidator",
    "RowCountValidator",
    "RowCountStrategy",
    "TPCHRowCountStrategy",
    "TPCDSRowCountStrategy",
    "SSBRowCountStrategy",
    "GenericRowCountStrategy",
    "DatabaseValidator",
]
