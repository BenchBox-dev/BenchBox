"""Tuning metadata management system for BenchBox.

This module provides database metadata table management for tracking and validating
tuning configurations across benchmark executions. It ensures database compatibility
when reusing databases with different tuning configurations.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from .interface import BenchmarkTunings, TableTuning, TuningColumn, TuningType, UnifiedTuningConfiguration

logger = logging.getLogger(__name__)


@dataclass
class TuningMetadata:
    """Represents a single tuning metadata record."""

    table_name: str
    tuning_type: str
    column_name: str
    column_order: int
    configuration_hash: str
    created_at: datetime
    platform: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "table_name": self.table_name,
            "tuning_type": self.tuning_type,
            "column_name": self.column_name,
            "column_order": self.column_order,
            "configuration_hash": self.configuration_hash,
            "created_at": self.created_at.isoformat(),
            "platform": self.platform,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TuningMetadata":
        """Create from dictionary representation."""
        created_at = data["created_at"]
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return cls(
            table_name=data["table_name"],
            tuning_type=data["tuning_type"],
            column_name=data["column_name"],
            column_order=data["column_order"],
            configuration_hash=data["configuration_hash"],
            created_at=created_at,
            platform=data["platform"],
        )


@dataclass
class MetadataValidationResult:
    """Result of tuning metadata validation."""

    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    missing_tables: set[str] = field(default_factory=set)
    extra_tables: set[str] = field(default_factory=set)
    configuration_mismatches: dict[str, str] = field(default_factory=dict)

    def add_error(self, message: str) -> None:
        """Add an error and mark validation as failed."""
        self.errors.append(message)
        self.is_valid = False

    def add_warning(self, message: str) -> None:
        """Add a warning."""
        self.warnings.append(message)

    def has_issues(self) -> bool:
        """Check if there are any errors or warnings."""
        return len(self.errors) > 0 or len(self.warnings) > 0


class TuningMetadataManager:
    """Manages tuning metadata operations for database validation."""

    def __init__(self, platform_adapter, database_name: Optional[str] = None):
        """Initialize the metadata manager.

        Args:
            platform_adapter: Database platform adapter instance
            database_name: Optional database name for isolation
        """
        self.platform_adapter = platform_adapter
        self.database_name = database_name
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self._metadata_table_name = "benchbox_tuning_metadata"
        self._table_exists = None  # Cache for table existence check

    def create_metadata_table(self) -> bool:
        """Create the tunings metadata table if it doesn't exist.

        Returns:
            True if table was created or already exists, False on error
        """
        if self._table_exists:
            return True

        try:
            # Platform-specific table creation SQL
            create_sql = self._get_create_table_sql()

            self.logger.info(f"Creating tuning metadata table: {self._metadata_table_name}")

            # Create temporary connection for schema operations
            temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
            try:
                self._execute_sql(temp_conn, create_sql)

                # Create index for performance
                index_sql = self._get_create_index_sql()
                if index_sql:
                    self._execute_sql(temp_conn, index_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)

            self._table_exists = True
            return True

        except Exception as e:
            self.logger.error(f"Failed to create metadata table: {e}")
            return False

    def _get_create_table_sql(self) -> str:
        """Get platform-specific CREATE TABLE SQL."""
        platform = self.platform_adapter.platform_name.lower()

        # Base table definition
        base_sql = f"""
        CREATE TABLE IF NOT EXISTS {self._metadata_table_name} (
            table_name VARCHAR(255) NOT NULL,
            tuning_type VARCHAR(50) NOT NULL,
            column_name VARCHAR(255) NOT NULL,
            column_order INTEGER NOT NULL,
            configuration_hash VARCHAR(64) NOT NULL,
            created_at TIMESTAMP NOT NULL,
            platform VARCHAR(50) NOT NULL
        )"""

        # Platform-specific modifications
        if platform == "bigquery":
            # BigQuery doesn't support IF NOT EXISTS, but we'll handle that in the adapter
            return base_sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE")
        elif platform == "snowflake":
            # Snowflake uses TIMESTAMP_NTZ for deterministic timestamps
            return base_sql.replace("TIMESTAMP", "TIMESTAMP_NTZ")
        elif platform == "redshift":
            # Redshift prefers explicit column encoding
            return base_sql + " ENCODE AUTO"
        elif platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
            # ClickHouse uses specific engine and ordering
            return base_sql.replace(")", ") ENGINE = MergeTree() ORDER BY (table_name, tuning_type)")
        else:
            # Default for DuckDB, Databricks, etc.
            return base_sql

    def _get_create_index_sql(self) -> Optional[str]:
        """Get platform-specific index creation SQL."""
        platform = self.platform_adapter.platform_name.lower()

        if platform in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
            # ClickHouse uses ORDER BY in table definition, no separate index needed
            return None
        elif platform == "bigquery":
            # BigQuery doesn't support explicit indexes
            return None
        else:
            # Create index for faster lookups
            return f"""
            CREATE INDEX IF NOT EXISTS idx_{self._metadata_table_name}_lookup
            ON {self._metadata_table_name} (table_name, configuration_hash)
            """

    def save_tunings(self, benchmark_tunings: BenchmarkTunings) -> bool:
        """Save tuning configuration to metadata table.

        Args:
            benchmark_tunings: The tuning configuration to save

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            if not self.create_metadata_table():
                return False

            # Clear existing metadata for this configuration
            self.clear_tunings(benchmark_tunings.benchmark_name)

            # Generate configuration hash
            config_hash = benchmark_tunings.get_configuration_hash()
            platform = self.platform_adapter.platform_name
            current_time = datetime.now()

            # Prepare records to insert
            records = []
            for table_name in benchmark_tunings.get_table_names():
                table_tuning = benchmark_tunings.get_table_tuning(table_name)
                if not table_tuning:
                    continue

                # Create records for each tuning type and column
                for tuning_type in TuningType:
                    columns = table_tuning.get_columns_by_type(tuning_type)
                    if not columns:
                        continue

                    for column in columns:
                        records.append(
                            TuningMetadata(
                                table_name=table_name,
                                tuning_type=tuning_type.value,
                                column_name=column.name,
                                column_order=column.order,
                                configuration_hash=config_hash,
                                created_at=current_time,
                                platform=platform,
                            )
                        )

            # Insert records in batch
            if records:
                self._batch_insert_records(records)
                self.logger.info(f"Saved {len(records)} tuning metadata records")

            return True

        except Exception as e:
            self.logger.error(f"Failed to save tunings: {e}")
            return False

    def _as_benchmark_tunings(
        self, unified_config: UnifiedTuningConfiguration, benchmark_name: str = "unified"
    ) -> BenchmarkTunings:
        """Convert unified tuning config to benchmark tuning representation."""
        return BenchmarkTunings(
            benchmark_name=benchmark_name,
            enable_primary_keys=unified_config.primary_keys.enabled,
            enable_foreign_keys=unified_config.foreign_keys.enabled,
            table_tunings=unified_config.table_tunings.copy(),
        )

    def _as_unified_tunings(self, benchmark_tunings: BenchmarkTunings) -> UnifiedTuningConfiguration:
        """Convert benchmark tuning representation to unified tuning config."""
        unified = UnifiedTuningConfiguration()
        unified.primary_keys.enabled = benchmark_tunings.enable_primary_keys
        unified.foreign_keys.enabled = benchmark_tunings.enable_foreign_keys
        unified.table_tunings.update(benchmark_tunings.table_tunings)
        return unified

    def save_unified_tunings(self, unified_config: UnifiedTuningConfiguration) -> bool:
        """Save a UnifiedTuningConfiguration to the metadata table."""
        try:
            if not isinstance(unified_config, UnifiedTuningConfiguration):
                raise TypeError("Expected UnifiedTuningConfiguration")
            return self.save_tunings(self._as_benchmark_tunings(unified_config))
        except Exception as e:
            self.logger.error(f"Failed to save unified tunings: {e}")
            return False

    def load_unified_tunings(self) -> Optional[UnifiedTuningConfiguration]:
        """Load tuning metadata and return as UnifiedTuningConfiguration."""
        try:
            benchmark_tunings = self.load_tunings()
            if not benchmark_tunings:
                return None
            return self._as_unified_tunings(benchmark_tunings)
        except Exception as e:
            self.logger.error(f"Failed to load unified tunings: {e}")
            return None

    def validate_unified_tunings(self, unified_config: UnifiedTuningConfiguration) -> MetadataValidationResult:
        """Validate database metadata against a UnifiedTuningConfiguration."""
        try:
            if not isinstance(unified_config, UnifiedTuningConfiguration):
                raise TypeError("Expected UnifiedTuningConfiguration")
            return self.validate_tunings(self._as_benchmark_tunings(unified_config))
        except Exception as e:
            result = MetadataValidationResult(is_valid=False)
            result.add_error(f"Validation failed with error: {e}")
            return result

    def _batch_insert_records(self, records: list[TuningMetadata]) -> None:
        """Insert metadata records in batch."""
        if not records:
            return

        # Build INSERT statement
        insert_sql = f"""
        INSERT INTO {self._metadata_table_name}
        (table_name, tuning_type, column_name, column_order,
         configuration_hash, created_at, platform)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """

        # Prepare parameter lists
        param_lists = []
        for record in records:
            param_lists.append(
                [
                    record.table_name,
                    record.tuning_type,
                    record.column_name,
                    record.column_order,
                    record.configuration_hash,
                    record.created_at,
                    record.platform,
                ]
            )

        # Execute batch insert - handle platforms that don't support batch operations
        temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
        try:
            cursor = temp_conn.cursor()
            for params in param_lists:
                cursor.execute(insert_sql, params)
            temp_conn.commit()
        finally:
            self.platform_adapter.close_connection(temp_conn)

    def load_tunings(self, benchmark_name: Optional[str] = None) -> Optional[BenchmarkTunings]:
        """Load tuning configuration from metadata table.

        Args:
            benchmark_name: Optional benchmark name filter

        Returns:
            BenchmarkTunings object if found, None otherwise
        """
        try:
            if not self._table_exists_check():
                return None

            # Query metadata records
            query_sql = f"""
            SELECT table_name, tuning_type, column_name, column_order,
                   configuration_hash, created_at, platform
            FROM {self._metadata_table_name}
            ORDER BY table_name, tuning_type, column_order
            """

            temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
            try:
                results = self._fetch_all(temp_conn, query_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)
            if not results:
                return None

            # Group records by table and rebuild tuning configuration
            return self._rebuild_tunings_from_records(results, benchmark_name or "loaded")

        except Exception as e:
            self.logger.error(f"Failed to load tunings: {e}")
            return None

    def _table_exists_check(self) -> bool:
        """Check if metadata table exists."""
        if self._table_exists is not None:
            return self._table_exists

        try:
            # Try to query the table
            query_sql = f"SELECT COUNT(*) FROM {self._metadata_table_name} LIMIT 1"
            temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
            try:
                self._fetch_one(temp_conn, query_sql)
                self._table_exists = True
                return True
            finally:
                self.platform_adapter.close_connection(temp_conn)
        except Exception:
            self._table_exists = False
            return False

    def _rebuild_tunings_from_records(self, records: list[tuple], benchmark_name: str) -> BenchmarkTunings:
        """Rebuild BenchmarkTunings object from metadata records."""
        benchmark_tunings = BenchmarkTunings(benchmark_name=benchmark_name)

        # Group records by table
        tables = {}
        for record in records:
            (
                table_name,
                tuning_type,
                column_name,
                column_order,
                config_hash,
                created_at,
                platform,
            ) = record

            if table_name not in tables:
                tables[table_name] = {
                    TuningType.PARTITIONING.value: [],
                    TuningType.CLUSTERING.value: [],
                    TuningType.DISTRIBUTION.value: [],
                    TuningType.SORTING.value: [],
                }

            # Include column in appropriate tuning type
            tables[table_name][tuning_type].append(
                TuningColumn(
                    name=column_name,
                    type="UNKNOWN",  # Type not stored in metadata
                    order=column_order,
                )
            )

        # Create TableTuning objects
        for table_name, tuning_columns in tables.items():
            table_tuning = TableTuning(
                table_name=table_name,
                partitioning=tuning_columns[TuningType.PARTITIONING.value] or None,
                clustering=tuning_columns[TuningType.CLUSTERING.value] or None,
                distribution=tuning_columns[TuningType.DISTRIBUTION.value] or None,
                sorting=tuning_columns[TuningType.SORTING.value] or None,
            )

            # Only add if it has actual tuning configurations
            if table_tuning.has_any_tuning():
                benchmark_tunings.add_table_tuning(table_tuning)

        return benchmark_tunings

    def validate_tunings(self, expected_tunings: BenchmarkTunings) -> MetadataValidationResult:
        """Validate that database tunings match expected configuration.

        Args:
            expected_tunings: The expected tuning configuration

        Returns:
            MetadataValidationResult with detailed comparison results
        """
        result = MetadataValidationResult()

        try:
            # Load existing tunings from database
            existing_tunings = self.load_tunings(expected_tunings.benchmark_name)

            if not existing_tunings:
                result.add_error("No tuning metadata found in database")
                return result

            # Compare configurations
            self._compare_tuning_configurations(expected_tunings, existing_tunings, result)

            if result.is_valid:
                self.logger.info("Tuning configuration validation passed")
            else:
                self.logger.warning(f"Tuning validation failed with {len(result.errors)} errors")

            return result

        except Exception as e:
            result.add_error(f"Validation failed with error: {e}")
            return result

    def _compare_tuning_configurations(
        self,
        expected: BenchmarkTunings,
        existing: BenchmarkTunings,
        result: MetadataValidationResult,
    ) -> None:
        """Compare expected vs existing tuning configurations."""
        # Check configuration hashes first (quick comparison)
        expected_hash = expected.get_configuration_hash()
        existing_hash = existing.get_configuration_hash()

        if expected_hash == existing_hash:
            # Configurations are identical
            return

        # Detailed comparison if hashes don't match
        expected_tables = set(expected.get_table_names())
        existing_tables = set(existing.get_table_names())

        # Find missing and extra tables
        result.missing_tables = expected_tables - existing_tables
        result.extra_tables = existing_tables - expected_tables

        for table_name in result.missing_tables:
            result.add_error(f"Expected tuning for table '{table_name}' not found in database")

        for table_name in result.extra_tables:
            result.add_warning(f"Unexpected tuning found for table '{table_name}' in database")

        # Compare common tables
        common_tables = expected_tables & existing_tables
        for table_name in common_tables:
            self._compare_table_tunings(
                expected.get_table_tuning(table_name),
                existing.get_table_tuning(table_name),
                result,
            )

    def _compare_table_tunings(
        self,
        expected: Optional[TableTuning],
        existing: Optional[TableTuning],
        result: MetadataValidationResult,
    ) -> None:
        """Compare tuning configurations for a specific table."""
        if not expected or not existing:
            return

        table_name = expected.table_name

        # Compare each tuning type
        for tuning_type in TuningType:
            expected_columns = expected.get_columns_by_type(tuning_type)
            existing_columns = existing.get_columns_by_type(tuning_type)

            # Convert to comparable format (sorted by order)
            expected_spec = sorted([(col.name, col.order) for col in expected_columns])
            existing_spec = sorted([(col.name, col.order) for col in existing_columns])

            if expected_spec != existing_spec:
                result.configuration_mismatches[f"{table_name}.{tuning_type.value}"] = (
                    f"Expected: {expected_spec}, Found: {existing_spec}"
                )
                result.add_error(
                    f"Table '{table_name}' {tuning_type.value} tuning mismatch: "
                    f"expected {expected_spec}, found {existing_spec}"
                )

    def clear_tunings(self, benchmark_name: Optional[str] = None) -> bool:
        """Clear tuning metadata from the database.

        Args:
            benchmark_name: Optional benchmark name filter (unused in current implementation)

        Returns:
            True if cleared successfully, False otherwise
        """
        try:
            if not self._table_exists_check():
                return True  # Nothing to clear

            # Delete all records (could be filtered by benchmark_name if we stored it)
            delete_sql = f"DELETE FROM {self._metadata_table_name}"
            temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
            try:
                self._execute_sql(temp_conn, delete_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)

            self.logger.info("Cleared tuning metadata")
            return True

        except Exception as e:
            self.logger.error(f"Failed to clear tunings: {e}")
            return False

    def get_metadata_summary(self) -> dict[str, Any]:
        """Get summary of stored tuning metadata.

        Returns:
            Dictionary with metadata statistics
        """
        try:
            if not self._table_exists_check():
                return {"table_exists": False}

            # Query summary statistics
            summary_sql = f"""
            SELECT
                COUNT(*) as total_records,
                COUNT(DISTINCT table_name) as unique_tables,
                COUNT(DISTINCT tuning_type) as unique_tuning_types,
                COUNT(DISTINCT platform) as unique_platforms,
                MIN(created_at) as oldest_record,
                MAX(created_at) as newest_record
            FROM {self._metadata_table_name}
            """

            temp_conn = self.platform_adapter.create_connection(**self.platform_adapter.platform_config)
            try:
                result = self._fetch_one(temp_conn, summary_sql)
            finally:
                self.platform_adapter.close_connection(temp_conn)
            if result:
                return {
                    "table_exists": True,
                    "total_records": result[0],
                    "unique_tables": result[1],
                    "unique_tuning_types": result[2],
                    "unique_platforms": result[3],
                    "oldest_record": result[4],
                    "newest_record": result[5],
                }

            return {"table_exists": True, "no_data": True}

        except Exception as e:
            return {"table_exists": False, "error": str(e)}

    def _execute_sql(self, connection, sql: str, params: Optional[list] = None) -> Any:
        """Execute SQL statement through platform adapter.

        Args:
            connection: Database connection
            sql: SQL statement to execute
            params: Optional query parameters

        Returns:
            Query result if applicable
        """
        # Use platform adapter's query execution method
        if hasattr(self.platform_adapter, "execute_query"):
            result = self.platform_adapter.execute_query(connection, sql, "metadata")
            return result.get("result")
        else:
            # Fall back to direct connection execution
            cursor = connection.cursor()
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)

            try:
                return cursor.fetchall()
            except Exception:
                return None

    def _fetch_all(self, connection, sql: str) -> list[tuple]:
        """Fetch all results from a SELECT query.

        Args:
            connection: Database connection
            sql: SELECT SQL statement

        Returns:
            List of result tuples
        """
        cursor = connection.cursor()
        cursor.execute(sql)
        return cursor.fetchall()

    def _fetch_one(self, connection, sql: str) -> Optional[tuple]:
        """Fetch one result from a SELECT query.

        Args:
            connection: Database connection
            sql: SELECT SQL statement

        Returns:
            Single result tuple or None
        """
        cursor = connection.cursor()
        cursor.execute(sql)
        return cursor.fetchone()
