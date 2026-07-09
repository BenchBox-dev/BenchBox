"""Transaction Primitives benchmark implementation.

Tests database transaction semantics and overhead using TPC-H schema.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import datetime
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from benchbox.core.connection import DatabaseConnection
from benchbox.core.primitives_benchmark_utils import (
    build_tpch_staging_tables_sql,
    quote_identifier,
    table_exists,
)
from benchbox.core.transaction_primitives.generator import TransactionPrimitivesDataGenerator
from benchbox.core.transaction_primitives.operations import TransactionOperationsManager
from benchbox.core.transaction_primitives.schema import STAGING_TABLES, get_all_staging_tables_sql, get_create_table_sql
from benchbox.core.transactional.benchmark_base import TransactionalBenchmarkBase
from benchbox.sql_compat.rules.execution_filter.duckdb_transaction_primitives import (
    DUCKDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS,
)
from benchbox.sql_compat.rules.execution_filter.pg_duckdb_transaction_primitives import (
    PG_DUCKDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS,
)
from benchbox.sql_compat.rules.execution_filter.timescaledb_transaction_primitives import (
    TIMESCALEDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS,
)
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path


def _pk_lock_bypass_required(dialect: str) -> bool:
    """Return True if PK-based lock DDL should be bypassed for this platform.

    Consults the sql_compat registry (REGISTRY.resolve) for the platform decision.
    Every transaction_primitives-capable platform must have a registered rule in
    benchbox/sql_compat/rules/schema_emit/pk_capability_txn.py.

    Args:
        dialect: Platform dialect string (e.g. "starrocks", "snowflake").
    """
    import benchbox.sql_compat.rules.schema_emit.pk_capability_txn  # noqa: F401
    from benchbox.sql_compat.actions import CompatAction
    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform=dialect.lower(),
        platform_version=None,
        benchmark="transaction_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect=dialect,
    )
    registry_decision = REGISTRY.resolve(ctx)

    if registry_decision is not None:
        return registry_decision.action != CompatAction.NATIVE
    # No rule registered → platform enforces PK natively (e.g., duckdb, sqlite, postgres).
    return False


@dataclass
class OperationResult:
    """Result of executing a transaction operation.

    Attributes:
        operation_id: ID of the operation
        success: Whether operation succeeded
        write_duration_ms: Time to execute transaction SQL
        rows_affected: Number of rows affected by transaction
        validation_duration_ms: Time to execute validation queries
        validation_passed: Whether all validations passed
        validation_results: Details of each validation
        cleanup_duration_ms: Time to execute cleanup
        cleanup_success: Whether cleanup succeeded
        error: Error message if operation failed
        cleanup_warning: Warning message for cleanup failures
        status: Explicit status string ("SUCCESS", "FAILED", "SKIPPED"); derived from success if None
        skip_reason: Human-readable explanation when status is "SKIPPED"; distinct from error
        executed_sql: The final transaction SQL actually executed (after platform
            overrides, dialect rewrites, and placeholder replacement); used for plan capture.
    """

    operation_id: str
    success: bool
    write_duration_ms: float
    rows_affected: int
    validation_duration_ms: float
    validation_passed: bool
    validation_results: list[dict[str, Any]]
    cleanup_duration_ms: float
    cleanup_success: bool
    error: Optional[str] = None
    cleanup_warning: Optional[str] = None
    status: Optional[str] = None
    skip_reason: Optional[str] = None
    executed_sql: Optional[str] = None


class TransactionPrimitivesBenchmark(TransactionalBenchmarkBase["OperationResult"]):
    """Transaction Primitives benchmark implementation.

    Tests database transaction semantics and overhead (COMMIT, ROLLBACK, savepoints,
    isolation levels, multi-statement transactions, advanced features) using TPC-H
    schema as foundation.

    Implements OperationExecutor interface to support operation-based execution
    through the platform adapter.

    Attributes:
        scale_factor: Scale factor (1.0 = standard size)
        output_dir: Data output directory
        operations_manager: Operation manager
        data_generator: Data generator
    """

    _benchmark_label = "Transaction Primitives"
    _staging_tables = STAGING_TABLES

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize Transaction Primitives benchmark.

        Args:
            scale_factor: Scale factor (1.0 = standard size)
            output_dir: Data output directory
            **config: Additional configuration
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, quiet=quiet, **config)

        self._name = "Transaction Primitives Benchmark"
        self._version = "1.0"
        self._description = "Transaction Primitives benchmark - Testing fundamental write operations using TPC-H schema"

        # Setup directories
        if output_dir is None:
            # Reuse the canonical TPC-H datagen directory
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)

        self.output_dir = output_dir

        # Initialize components
        self.operations_manager = TransactionOperationsManager()
        self.data_generator = TransactionPrimitivesDataGenerator(scale_factor, self.output_dir, **config)

        # Data files mapping
        self.tables: dict[str, Path] = {}

    def _acquire_setup_lock(
        self, connection: DatabaseConnection, timeout_seconds: int = 300, dialect: str = "standard"
    ) -> bool:
        """Acquire an exclusive lock for staging table setup to prevent concurrent populations.

        Uses a dedicated lock table to prevent multiple processes from simultaneously
        populating staging tables, which could waste resources and cause conflicts.

        Args:
            connection: Database connection
            timeout_seconds: Maximum seconds to wait for lock (default: 300)

        Returns:
            True if lock acquired, False if timeout

        Note:
            Caller must call _release_setup_lock() when done, preferably in a finally block.
            Lock is automatically released on connection close/crash.
        """
        import time

        if _pk_lock_bypass_required(dialect):
            return True

        # Create lock table if it doesn't exist (atomic operation)
        try:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS transaction_primitives_setup_lock (
                    lock_name VARCHAR(255) PRIMARY KEY,
                    holder_info VARCHAR(1000),
                    acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        except Exception as e:
            self.log_verbose(f"Warning: Could not create lock table: {e}")
            return False

        # Try to acquire lock with timeout
        lock_name = "staging_table_setup"
        start_time = mono_time()

        while elapsed_seconds(start_time) < timeout_seconds:
            try:
                # Attempt to insert lock row (fails if already exists)
                import os

                holder_info = f"pid:{os.getpid()},time:{time.time()}"

                # Escape single quotes in values to prevent SQL injection
                escaped_lock_name = lock_name.replace("'", "''")
                escaped_holder_info = holder_info.replace("'", "''")

                connection.execute(
                    f"INSERT INTO transaction_primitives_setup_lock (lock_name, holder_info) "
                    f"VALUES ('{escaped_lock_name}', '{escaped_holder_info}')"
                )
                self.log_verbose(f"Acquired setup lock (waited {elapsed_seconds(start_time):.1f}s)")
                return True
            except Exception as e:
                error_msg = str(e).lower()
                if "unique" in error_msg or "duplicate" in error_msg or "constraint" in error_msg:
                    # Lock held by another process - wait and retry
                    time.sleep(0.5)
                else:
                    # Unexpected error
                    self.log_verbose(f"Unexpected error acquiring lock: {e}")
                    return False

        # Timeout - check if lock is stale
        try:
            # Escape lock name for SELECT query
            escaped_lock_name = lock_name.replace("'", "''")
            result = connection.execute(
                f"SELECT acquired_at FROM transaction_primitives_setup_lock WHERE lock_name = '{escaped_lock_name}'"
            ).fetchone()
            if result:
                self.log_verbose(f"Setup lock timeout after {timeout_seconds}s (lock held since {result[0]})")
        except Exception:
            pass

        return False

    def _release_setup_lock(self, connection: DatabaseConnection, dialect: str = "standard") -> None:
        """Release the staging table setup lock.

        Args:
            connection: Database connection
            dialect: SQL dialect (e.g. 'datafusion', 'clickhouse', 'standard')
        """
        if _pk_lock_bypass_required(dialect):
            return
        try:
            lock_name = "staging_table_setup"
            # Escape lock name for DELETE query
            escaped_lock_name = lock_name.replace("'", "''")
            connection.execute(f"DELETE FROM transaction_primitives_setup_lock WHERE lock_name = '{escaped_lock_name}'")
            self.log_verbose("Released setup lock")
        except Exception as e:
            self.log_verbose(f"Warning: Could not release setup lock: {e}")

    def _quote_identifier(self, identifier: str) -> str:
        """Quote SQL identifier to prevent SQL injection.

        Uses double quotes (SQL standard) which work in DuckDB, PostgreSQL, SQLite.
        For compatibility, validates identifier first.

        Args:
            identifier: Table, column, or schema name

        Returns:
            Quoted identifier safe for SQL

        Raises:
            ValueError: If identifier contains dangerous characters

        Security:
            - Validates identifier contains only safe characters
            - Quotes with double quotes (SQL standard for identifiers)
            - Escapes any existing double quotes by doubling them
        """
        return quote_identifier(identifier)

    def _table_exists(self, connection: DatabaseConnection, table_name: str) -> bool:
        """Check if a table exists in the database.

        Uses a platform-agnostic approach that attempts to query the table
        with LIMIT 0, which should work across most SQL databases without
        requiring INFORMATION_SCHEMA access.

        Args:
            connection: Database connection
            table_name: Name of table to check (will be quoted for safety)

        Returns:
            True if table exists, False otherwise

        Note:
            This method catches exceptions to distinguish between:
            - Table doesn't exist (expected, returns False)
            - Other errors (logged, returns False for safety)

        Security:
            Table name is quoted using _quote_identifier() to prevent SQL injection.
        """
        return table_exists(connection, table_name, self.log_verbose)

    def _populate_staging_table(self, connection: DatabaseConnection, staging_table: str, source_table: str) -> None:
        """Populate staging table from TPC-H source table.

        Args:
            connection: Database connection
            staging_table: Name of staging table to populate
            source_table: Name of source TPC-H table
        """
        self.log_verbose(f"Populating {staging_table} from {source_table}...")

        # Use INSERT...SELECT to copy data
        populate_sql = f"""
        INSERT INTO {staging_table}
        SELECT * FROM {source_table}
        """

        connection.execute(populate_sql)
        self.log_verbose(f"{staging_table} populated successfully")

    def setup(self, connection: DatabaseConnection, force: bool = False, dialect: str = "standard") -> dict[str, Any]:
        """Setup benchmark for execution.

        Creates and populates staging tables from TPC-H base tables.

        Uses an exclusive database lock to prevent concurrent setup operations
        that could waste resources or cause conflicts.

        Args:
            connection: Database connection
            force: If True, drop existing staging tables first
            dialect: SQL dialect (e.g. 'clickhouse', 'standard')

        Returns:
            Dictionary with setup status and details

        Raises:
            RuntimeError: If required tables don't exist or setup fails
        """
        self.log_verbose("Setting up Transaction Primitives benchmark...")

        # Validate TPC-H base tables exist
        required_tables = ["orders", "lineitem", "customer"]
        for table in required_tables:
            try:
                connection.execute(f"SELECT 1 FROM {table} LIMIT 1")
            except Exception as e:
                raise RuntimeError(
                    f"Required TPC-H table '{table}' not found. "
                    f"Please load TPC-H data first using generate_data() and loading the files. "
                    f"Error: {e}"
                ) from e

        # Acquire exclusive lock to prevent concurrent setup operations
        # This eliminates race conditions during staging table population
        if not self._acquire_setup_lock(connection, timeout_seconds=300, dialect=dialect):
            raise RuntimeError(
                "Could not acquire setup lock after 5 minutes. "
                "Another process may be running setup, or a previous setup crashed. "
                "Check transaction_primitives_setup_lock table for stale locks."
            )

        try:
            # Drop existing staging tables if force=True (done once before loop)
            if force:
                for table_name in STAGING_TABLES:
                    try:
                        connection.execute(f"DROP TABLE IF EXISTS {table_name}")
                        self.log_verbose(f"Dropped existing {table_name} (force mode)")
                    except Exception as e:
                        self.log_verbose(f"Warning: Could not drop {table_name}: {e}")

            # Create staging tables and populate from TPC-H base tables
            # Lock is held - no concurrent setup can interfere
            created_tables = []
            status = {}

            for table_name, table_def in STAGING_TABLES.items():
                # Check if table exists before creating
                table_existed = self._table_exists(connection, table_name)

                # Create table if not exists (atomic operation)
                create_sql = get_create_table_sql(table_name, dialect=dialect, if_not_exists=True)
                try:
                    connection.execute(create_sql)

                    # Track newly created tables (didn't exist before)
                    if not table_existed:
                        created_tables.append(table_name)
                        self.log_verbose(f"✅ Created {table_name}")
                    else:
                        self.log_verbose(f"Table {table_name} already exists")
                except Exception as e:
                    raise RuntimeError(f"Failed to create {table_name}: {e}") from e

                # Populate staging tables that are based on TPC-H tables
                if table_name in ["txn_orders", "txn_lineitem", "txn_customer"]:
                    source_table = (
                        "orders" if "orders" in table_name else ("lineitem" if "lineitem" in table_name else "customer")
                    )

                    # Check if table needs population
                    try:
                        quoted_table = self._quote_identifier(table_name)
                        result = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
                        current_count = result[0] if result else 0
                    except Exception:
                        current_count = 0

                    if current_count == 0:
                        # Validate source table has data before copying
                        try:
                            quoted_source = self._quote_identifier(source_table)
                            source_result = connection.execute(f"SELECT COUNT(*) FROM {quoted_source}").fetchone()
                            source_count = source_result[0] if source_result else 0
                        except Exception as e:
                            raise RuntimeError(
                                f"Cannot validate source table '{source_table}' before populating '{table_name}': {e}"
                            ) from e

                        if source_count == 0:
                            raise RuntimeError(
                                f"Source table '{source_table}' is empty (0 rows). "
                                f"Cannot populate staging table '{table_name}'. "
                                f"Please ensure TPC-H data is loaded before running setup()."
                            )

                        # Table is empty - populate it (lock prevents concurrent population)
                        self.log_verbose(f"Populating {table_name} from {source_table} ({source_count} rows)...")
                        self._populate_staging_table(connection, table_name, source_table)
                        result = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
                        status[table_name] = result[0] if result else 0
                        self.log_verbose(f"✅ Populated {table_name} with {status[table_name]} rows")

                        # Verify row count matches (detect copy failures)
                        if status[table_name] != source_count:
                            self.log_verbose(
                                f"⚠️ Warning: Row count mismatch after population. "
                                f"Source: {source_count}, Destination: {status[table_name]}"
                            )
                    else:
                        # Table already has data
                        status[table_name] = current_count
                        self.log_verbose(f"Table {table_name} already populated ({current_count} rows)")
                else:
                    # Other staging tables start empty - just count rows
                    try:
                        result = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                        status[table_name] = result[0] if result else 0
                    except Exception:
                        status[table_name] = 0

            self.log_verbose(f"Setup complete: {status}")

            return {
                "success": True,
                "tables_created": created_tables,
                "table_row_counts": status,
            }
        finally:
            # Always release lock, even if setup fails
            self._release_setup_lock(connection, dialect=dialect)

    def teardown(self, connection: DatabaseConnection) -> None:
        """Clean up all staging tables.

        Args:
            connection: Database connection
        """
        self.log_verbose("Tearing down Transaction Primitives benchmark...")

        for table_name in STAGING_TABLES:
            try:
                connection.execute(f"DROP TABLE IF EXISTS {table_name}")
                self.log_verbose(f"Dropped {table_name}")
            except Exception as e:
                self.log_verbose(f"Warning: Could not drop {table_name}: {e}")

        self.log_verbose("Teardown complete")

    def cleanup_auxiliary_files(self) -> None:
        """Remove auxiliary data files (bulk load test files).

        This removes the transaction_primitives_auxiliary subdirectory containing
        bulk load test files. Useful for cleanup or before regeneration.

        Note:
            This does not remove TPC-H base data, only auxiliary test files.
        """
        import shutil

        aux_dir = self.data_generator.files_dir
        if aux_dir.exists():
            try:
                shutil.rmtree(aux_dir)
                self.log_verbose(f"Removed auxiliary files directory: {aux_dir}")
            except Exception as e:
                self.log_verbose(f"Warning: Could not remove auxiliary files: {e}")

    def load_data(self, connection: DatabaseConnection, **kwargs: Any) -> dict[str, Any]:
        """Load data into database (standard benchmark interface).

        For Transaction Primitives, data loading is handled by the platform adapter
        loading .tbl files for both base TPC-H tables and staging tables.
        This method just verifies that data was loaded correctly.

        Args:
            connection: Database connection
            **kwargs: ``dialect`` (str, default "standard") propagates to setup() so
                the PK lock-bypass registry lookup matches the adapter's dialect.

        Returns:
            Dictionary with loading results
        """
        # Verify that tables exist and have data. Propagate dialect so cloud platforms
        # (Snowflake, BigQuery, etc.) hit their registered PK lock-bypass rule.
        return self.setup(connection, force=False, dialect=kwargs.get("dialect", "standard"))

    def reset(self, connection: DatabaseConnection) -> None:
        """Reset staging tables to initial state.

        Truncates and repopulates staging tables.

        Args:
            connection: Database connection
        """
        self.log_verbose("Resetting Transaction Primitives staging tables...")

        # Truncate populated staging tables
        for table_name in ["txn_orders", "txn_lineitem", "txn_customer"]:
            try:
                connection.execute(f"TRUNCATE TABLE {table_name}")
                self.log_verbose(f"Truncated {table_name}")
            except Exception as e:
                self.log_verbose(f"Warning: Could not truncate {table_name}: {e}")

        # Repopulate
        self._populate_staging_table(connection, "txn_orders", "orders")
        self._populate_staging_table(connection, "txn_lineitem", "lineitem")
        self._populate_staging_table(connection, "txn_customer", "customer")

        self.log_verbose("Reset complete")

    def is_setup(self, connection: DatabaseConnection) -> bool:
        """Check if staging tables are ready.

        Args:
            connection: Database connection

        Returns:
            True if all staging tables exist and have data
        """
        try:
            # Check that key staging tables exist and have data
            for table_name in ["txn_orders", "txn_lineitem", "txn_customer"]:
                result = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                if not result or result[0] == 0:
                    return False
            return True
        except Exception:
            return False

    def _replace_placeholders(self, sql: str) -> str:
        """Replace placeholders in SQL with actual values.

        Args:
            sql: SQL string potentially containing placeholders

        Returns:
            SQL with placeholders replaced

        Supported placeholders:
            {file_path}: Replaced with auxiliary files directory path for bulk load operations

        Note:
            File paths are sanitized by escaping single quotes to prevent SQL injection.
            Uses transaction_primitives_auxiliary subdirectory to isolate auxiliary files.
        """
        if "{file_path}" in sql:
            # Replace with the auxiliary files directory path
            # This uses a subdirectory to keep bulk load files separate from TPC-H data
            if self.output_dir:
                file_path = str(self.output_dir / "transaction_primitives_auxiliary")
            else:
                file_path = ""

            # Escape single quotes in path to prevent SQL injection
            # SQL standard: '' (two single quotes) escapes a single quote
            file_path = file_path.replace("'", "''")

            # Validate path doesn't contain other dangerous characters
            # Allow common path characters: alphanumeric, /, \, ., -, _, :, space
            import re

            if re.search(r"[^\w\s/\\\.\-:]", file_path.replace("''", "'")):
                # Contains unusual characters - log warning
                self.log_verbose(f"Warning: File path contains unusual characters: {file_path}")

            sql = sql.replace("{file_path}", file_path)
        return sql

    def get_schema(self, dialect: str = "standard") -> dict[str, dict]:
        """Get the Transaction Primitives schema definitions.

        Args:
            dialect: SQL dialect to use for data types

        Returns:
            Dictionary mapping table names to their schema definitions
        """
        return STAGING_TABLES

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get CREATE TABLE SQL for all required tables.

        Includes both TPC-H base tables and Transaction Primitives staging tables.
        TPC-H base tables must exist before staging tables can be populated.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            Complete SQL schema creation script
        """
        return build_tpch_staging_tables_sql(
            dialect=dialect,
            tuning_config=tuning_config,
            staging_heading="Transaction Primitives Staging Tables",
            get_staging_tables_sql=get_all_staging_tables_sql,
        )

    def execute_operation(
        self,
        operation_id: str,
        connection: DatabaseConnection,
        **kwargs: Any,
    ) -> OperationResult:
        """Execute a transaction operation and validate results.

        Note: Transaction operations contain their own BEGIN/COMMIT/ROLLBACK logic,
        so no transaction wrapping is performed by this method.

        Args:
            operation_id: ID of operation to execute
            connection: Database connection
            **kwargs: Optional keyword arguments:
                platform_key: Platform dialect key (e.g. 'datafusion', 'duckdb')
                sql_override: Pre-processed SQL from adapter preprocessing

        Returns:
            OperationResult with execution metrics

        Raises:
            ValueError: If connection is invalid
            RuntimeError: If staging tables not initialized
        """
        operation, platform_key, sql_override = self._prepare_operation(operation_id, connection, **kwargs)
        platform_name = str(kwargs.get("platform_name") or "").lower()

        try:
            platform_operation_skips = {
                "duckdb": DUCKDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS,
                "pg_duckdb": PG_DUCKDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS,
                "timescaledb": TIMESCALEDB_TRANSACTION_PRIMITIVES_OPERATION_SKIPS,
            }
            if operation_id in platform_operation_skips.get(platform_name, {}):
                skip_details = platform_operation_skips[platform_name][operation_id]
                skip_reason = f"Operation '{operation_id}' is skipped on {platform_name}: {skip_details}"
                self.log_verbose(f"Skipping operation {operation_id}: {skip_reason}")
                return OperationResult(
                    operation_id=operation_id,
                    success=True,
                    write_duration_ms=0.0,
                    rows_affected=0,
                    validation_duration_ms=0.0,
                    validation_passed=True,
                    validation_results=[],
                    cleanup_duration_ms=0.0,
                    cleanup_success=True,
                    status="SKIPPED",
                    skip_reason=skip_reason,
                )

            # Resolve effective SQL respecting platform overrides
            if sql_override is not None:
                write_sql_raw = sql_override
            elif (
                platform_key
                and hasattr(operation, "platform_overrides")
                and operation.platform_overrides
                and platform_key in operation.platform_overrides
            ):
                override = operation.platform_overrides[platform_key]
                if override is None:
                    skip_reason = f"Operation '{operation_id}' is unsupported on platform '{platform_key}'."
                    self.log_verbose(f"Skipping operation {operation_id}: {skip_reason}")
                    return OperationResult(
                        operation_id=operation_id,
                        success=True,
                        write_duration_ms=0.0,
                        rows_affected=0,
                        validation_duration_ms=0.0,
                        validation_passed=True,
                        validation_results=[],
                        cleanup_duration_ms=0.0,
                        cleanup_success=True,
                        status="SKIPPED",
                        skip_reason=skip_reason,
                    )
                write_sql_raw = override
            else:
                write_sql_raw = operation.write_sql

            # Execute transaction SQL (operations already contain BEGIN/COMMIT/ROLLBACK)
            self.log_verbose(f"Executing transaction operation: {operation_id}")
            write_sql_raw = self._rewrite_transactional_sql_for_platform(write_sql_raw, platform_key)
            write_sql = self._replace_placeholders(write_sql_raw)
            write_start = time.perf_counter()
            write_result = connection.execute(write_sql)
            write_duration_ms = (time.perf_counter() - write_start) * 1000

            # Get rows affected (platform-specific)
            rows_affected = getattr(write_result, "rowcount", None)
            if rows_affected is None:
                self.log_verbose(f"Warning: Platform doesn't support rowcount for {operation_id}")
                rows_affected = -1  # Sentinel value indicating "unknown"
            elif rows_affected == -1:
                # Some platforms return -1 for "not applicable"
                self.log_verbose(f"Note: rowcount not applicable for {operation_id}")

            # Execute validation queries
            self.log_verbose(f"Validating operation: {operation_id}")
            validation_start = time.perf_counter()
            validation_results = []
            validation_passed = True

            for val_query in operation.validation_queries:
                val_sql = self._replace_placeholders(val_query.sql)
                val_result = connection.execute(val_sql).fetchall()
                actual_rows = len(val_result)
                expected_rows = val_query.expected_rows

                # Validation logic: exact match > range check > no validation
                if expected_rows is not None:
                    # Exact row count expected
                    passed = actual_rows == expected_rows
                    validation_passed = validation_passed and passed
                elif val_query.expected_rows_min is not None or val_query.expected_rows_max is not None:
                    # Range validation
                    min_val = val_query.expected_rows_min if val_query.expected_rows_min is not None else 0
                    max_val = val_query.expected_rows_max if val_query.expected_rows_max is not None else float("inf")
                    passed = min_val <= actual_rows <= max_val
                    validation_passed = validation_passed and passed
                else:
                    # No validation criteria - just verify query runs
                    passed = True

                validation_results.append(
                    {
                        "query_id": val_query.id,
                        "sql": val_query.sql,
                        "expected_rows": expected_rows,
                        "actual_rows": actual_rows,
                        "passed": passed,
                        "sample": val_result[:5] if val_result else [],  # Only store first 5 rows for debugging
                    }
                )

            validation_duration_ms = (time.perf_counter() - validation_start) * 1000

            # Execute cleanup if specified
            self.log_verbose(f"Cleaning up operation: {operation_id}")
            cleanup_start = time.perf_counter()
            cleanup_success = True
            cleanup_warning = None

            if operation.cleanup_sql:
                # Execute cleanup SQL
                try:
                    connection.execute(operation.cleanup_sql)
                except Exception as e:
                    cleanup_error = str(e)
                    self.log_verbose(f"Cleanup SQL failed for {operation_id}: {cleanup_error}")
                    cleanup_success = False
                    cleanup_warning = (
                        f"Transaction operation '{operation_id}' cleanup failed. "
                        f"Database may be in modified state. Run reset() to restore staging tables. "
                        f"Error: {cleanup_error}"
                    )
                    self.log_verbose(f"WARNING: {cleanup_warning}")

            cleanup_duration_ms = (time.perf_counter() - cleanup_start) * 1000

            return OperationResult(
                operation_id=operation_id,
                success=True,
                write_duration_ms=write_duration_ms,
                rows_affected=rows_affected,
                validation_duration_ms=validation_duration_ms,
                validation_passed=validation_passed,
                validation_results=validation_results,
                cleanup_duration_ms=cleanup_duration_ms,
                cleanup_success=cleanup_success,
                cleanup_warning=cleanup_warning,
                executed_sql=write_sql,
            )

        except Exception as e:
            self._rollback_connection_after_error(connection)
            error_msg = f"Operation {operation_id} failed: {str(e)}"
            self.log_verbose(error_msg)

            # Warn for operations that fail - partial changes may exist
            cleanup_warning = (
                "Transaction operation failed during execution. "
                "Partial changes may exist in database. Run reset() to ensure clean state."
            )
            self.log_verbose(f"WARNING: {cleanup_warning}")

            return OperationResult(
                operation_id=operation_id,
                success=False,
                write_duration_ms=0.0,
                rows_affected=0,
                validation_duration_ms=0.0,
                validation_passed=False,
                validation_results=[],
                cleanup_duration_ms=0.0,
                cleanup_success=False,
                error=error_msg,
                cleanup_warning=cleanup_warning,
            )

    # =========================================================================
    # DataFrame Support
    # =========================================================================

    def supports_dataframe_mode(self, platform_name: str) -> bool:
        """Check if a platform supports DataFrame mode for Transaction Primitives.

        Transaction Primitives requires ACID transaction support, which is only
        available on certain DataFrame platforms with Delta Lake or Iceberg.

        Args:
            platform_name: Platform name to check

        Returns:
            True if platform supports DataFrame mode for transactions
        """
        from benchbox.core.transaction_primitives.dataframe_operations import (
            validate_transaction_primitives_platform,
        )

        is_valid, _ = validate_transaction_primitives_platform(platform_name)
        return is_valid

    def get_dataframe_operations(self, platform_name: str, spark_session: Any = None) -> Any:
        """Get DataFrame transaction operations manager for a platform.

        This returns a DataFrameTransactionOperationsManager configured for
        the specified platform, enabling ACID transaction benchmarking.

        Args:
            platform_name: Platform name (e.g., "pyspark-df", "delta-lake")
            spark_session: SparkSession instance (required for pyspark-df)

        Returns:
            DataFrameTransactionOperationsManager instance

        Raises:
            ValueError: If platform does not support transactions
        """
        from benchbox.core.transaction_primitives.dataframe_operations import (
            get_dataframe_transaction_manager,
            validate_transaction_primitives_platform,
        )

        # Validate platform first
        is_valid, error_msg = validate_transaction_primitives_platform(platform_name)
        if not is_valid:
            raise ValueError(error_msg)

        manager = get_dataframe_transaction_manager(platform_name, spark_session=spark_session)

        if manager is None:
            raise ValueError(f"Could not create DataFrame transaction manager for {platform_name}")

        return manager

    def validate_dataframe_configuration(self, platform_name: str, spark_session: Any = None) -> tuple[bool, str]:
        """Validate DataFrame configuration for Transaction Primitives.

        This should be called during benchmark initialization to provide
        early feedback when users attempt to run Transaction Primitives
        on unsupported platforms.

        Args:
            platform_name: Platform name to validate
            spark_session: SparkSession instance (for pyspark-df)

        Returns:
            Tuple of (is_valid, error_message)
        """
        from benchbox.core.transaction_primitives.dataframe_operations import (
            validate_transaction_primitives_platform,
        )

        # First check if platform is potentially valid
        is_valid, error_msg = validate_transaction_primitives_platform(platform_name)
        if not is_valid:
            return False, error_msg

        # For PySpark, check that SparkSession is provided
        if "pyspark" in platform_name.lower() or "spark" in platform_name.lower():
            if spark_session is None:
                return False, (
                    f"Platform '{platform_name}' requires a SparkSession for DataFrame operations.\n"
                    f"Provide spark_session when initializing the platform adapter."
                )

        return True, ""

    def skip_dataframe_data_loading(self) -> bool:
        """Transaction Primitives DataFrame execution manages its own Delta/Iceberg table lifecycle."""
        return True

    def _create_test_orders_df(self, spark_session: Any, start_key: int, count: int) -> Any:
        """Create a small synthetic TPC-H ORDERS DataFrame for test operations.

        Uses PySpark createDataFrame when a SparkSession is available, otherwise
        falls back to a pandas DataFrame for delta-rs paths.

        Args:
            spark_session: SparkSession instance, or None for pandas fallback
            start_key: Starting o_orderkey value (use range 8000001-9000000)
            count: Number of rows to generate

        Returns:
            DataFrame compatible with the platform's write operations
        """
        rows = [
            {
                "o_orderkey": start_key + i,
                "o_custkey": 1000 + (i % 100),
                "o_orderstatus": "O",
                "o_totalprice": round(1000.00 + i * 10.5, 2),
                "o_orderdate": "1998-01-01",
                "o_orderpriority": "3-MEDIUM",
                "o_clerk": f"Clerk#{i:010d}",
                "o_shippriority": 0,
                "o_comment": f"benchbox test row {i}",
            }
            for i in range(count)
        ]
        if spark_session is not None:
            return spark_session.createDataFrame(rows)
        import pandas as pd

        return pd.DataFrame(rows)

    def _setup_transaction_table(self, spark_session: Any, table_path: Path) -> None:
        """Create (or recreate) the initial Delta table with synthetic TPC-H ORDERS data.

        Writes 100 rows with o_orderkey in the 1-100 range as a stable baseline.
        Any prior table at table_path is removed first so each iteration starts clean.

        Args:
            spark_session: SparkSession instance, or None for delta-rs path
            table_path: Directory path for the Delta table
        """
        if table_path.exists():
            shutil.rmtree(str(table_path))

        initial_rows = [
            {
                "o_orderkey": i + 1,
                "o_custkey": 1000 + (i % 100),
                "o_orderstatus": "O",
                "o_totalprice": round(1000.00 + i * 10.5, 2),
                "o_orderdate": "1998-01-01",
                "o_orderpriority": "3-MEDIUM",
                "o_clerk": f"Clerk#{i:010d}",
                "o_shippriority": 0,
                "o_comment": f"benchbox initial row {i}",
            }
            for i in range(100)
        ]
        table_path_str = str(table_path)

        if spark_session is not None:
            df = spark_session.createDataFrame(initial_rows)
            df.write.format("delta").mode("overwrite").save(table_path_str)
        else:
            import pyarrow as pa
            from deltalake.writer import write_deltalake

            keys = [r["o_orderkey"] for r in initial_rows]
            table = pa.table(
                {
                    "o_orderkey": pa.array(keys, type=pa.int64()),
                    "o_custkey": pa.array([r["o_custkey"] for r in initial_rows], type=pa.int64()),
                    "o_orderstatus": pa.array([r["o_orderstatus"] for r in initial_rows], type=pa.string()),
                    "o_totalprice": pa.array([r["o_totalprice"] for r in initial_rows], type=pa.float64()),
                    "o_orderdate": pa.array([r["o_orderdate"] for r in initial_rows], type=pa.string()),
                    "o_orderpriority": pa.array([r["o_orderpriority"] for r in initial_rows], type=pa.string()),
                    "o_clerk": pa.array([r["o_clerk"] for r in initial_rows], type=pa.string()),
                    "o_shippriority": pa.array([r["o_shippriority"] for r in initial_rows], type=pa.int32()),
                    "o_comment": pa.array([r["o_comment"] for r in initial_rows], type=pa.string()),
                }
            )
            write_deltalake(table_path_str, table, mode="overwrite")

    def execute_dataframe_workload(
        self,
        *,
        ctx: Any,
        adapter: Any,
        benchmark_config: Any,
        query_filter: set[str] | None = None,
        monitor: Any | None = None,  # noqa: ARG002
        run_options: Any | None = None,  # noqa: ARG002
    ) -> list[dict[str, Any]]:
        """Execute Transaction Primitives in DataFrame mode.

        This hook is called by the DataFrame adapter to execute ACID transaction
        operations on supported platforms (e.g., PySpark + Delta Lake).

        Implements Pattern B (native DataFrame execution): calls
        get_dataframe_operations() to obtain a DataFrameTransactionOperationsManager,
        creates a temporary Delta table, then executes 12 operation types in three
        dependency-ordered phases:
          Phase A - Write operations (atomic_insert/update/delete/merge)
          Phase B - Version operations (rollback_to_version/timestamp, time_travel, version_compare)
          Phase C - Concurrency/isolation (concurrent_write, conflict_resolution,
                     snapshot_isolation, read_your_writes)

        CRITICAL: Every SUCCESS result row has execution_time_seconds > 0 because each
        row comes from a real manager.execute_*() call with measured timing.
        A zero-time SUCCESS would indicate the phantom-data anti-pattern from the
        prior defect - guarded against in w3 behavioral tests.
        """
        from benchbox.core.transaction_primitives.dataframe_operations import (
            TransactionOperationType,
        )

        platform_name = adapter.platform_name
        spark_session = getattr(ctx, "spark_session", None)

        config_options = getattr(benchmark_config, "options", {}) or {}
        iterations = int(config_options.get("power_iterations", 1) or 1)

        manager = self.get_dataframe_operations(platform_name, spark_session)

        output: list[dict[str, Any]] = []
        op_iteration_counts: dict[str, int] = {}

        table_dir = tempfile.mkdtemp(prefix="benchbox_txn_")
        table_path = Path(table_dir) / "orders"

        try:
            for _iteration in range(1, iterations + 1):
                # Reset table to clean baseline for each iteration
                self._setup_transaction_table(
                    spark_session=spark_session,
                    table_path=table_path,
                )

                # Capture pre-phase timestamp before any writes (used by rollback_to_timestamp)
                pre_phase_timestamp = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                # Ordered dispatch: each tuple is (operation_type, zero-arg callable).
                # Lambdas close over stable per-iteration values (self, spark_session,
                # table_path, manager). pre_phase_timestamp uses a default-arg to make the
                # capture explicit. DataFrames are constructed inside lambdas so operations
                # skipped by query_filter never trigger _create_test_orders_df calls.
                # Phase A must run before Phase B (version ops need history created by writes).
                dispatch: list[tuple[Any, Any]] = [
                    # --- Phase A: Write operations (each creates a new Delta version) ---
                    (
                        TransactionOperationType.ATOMIC_INSERT,
                        lambda: manager.execute_atomic_insert(
                            table_path,
                            self._create_test_orders_df(spark_session, start_key=8_000_001, count=20),
                        ),
                    ),
                    (
                        TransactionOperationType.ATOMIC_UPDATE,
                        lambda: manager.execute_atomic_update(
                            table_path, "o_orderkey > 8000000", {"o_orderpriority": "1-URGENT"}
                        ),
                    ),
                    (
                        TransactionOperationType.ATOMIC_DELETE,
                        lambda: manager.execute_atomic_delete(
                            table_path, "o_orderkey >= 8000001 AND o_orderkey <= 8000010"
                        ),
                    ),
                    (
                        TransactionOperationType.ATOMIC_MERGE,
                        lambda: manager.execute_atomic_merge(
                            table_path,
                            self._create_test_orders_df(spark_session, start_key=8_000_001, count=10),
                            "target.o_orderkey = source.o_orderkey",
                            when_matched={"o_orderpriority": "1-URGENT"},
                            when_not_matched=None,
                        ),
                    ),
                    # --- Phase B: Version operations (depend on history from Phase A) ---
                    (
                        TransactionOperationType.ROLLBACK_TO_VERSION,
                        lambda: manager.execute_rollback_to_version(table_path, version=0),
                    ),
                    (
                        TransactionOperationType.ROLLBACK_TO_TIMESTAMP,
                        lambda _ts=pre_phase_timestamp: manager.execute_rollback_to_timestamp(table_path, _ts),
                    ),
                    (
                        TransactionOperationType.TIME_TRAVEL_QUERY,
                        lambda: manager.execute_time_travel_query(table_path, version=0),
                    ),
                    (
                        TransactionOperationType.VERSION_COMPARE,
                        lambda: manager.execute_version_compare(table_path, version1=0, version2=1),
                    ),
                    # --- Phase C: Concurrency/isolation operations ---
                    (
                        TransactionOperationType.CONCURRENT_WRITE,
                        lambda: manager.execute_concurrent_write(
                            table_path,
                            [
                                self._create_test_orders_df(spark_session, start_key=8_000_100 + i * 100, count=5)
                                for i in range(3)
                            ],
                        ),
                    ),
                    (
                        TransactionOperationType.CONFLICT_RESOLUTION,
                        lambda: manager.execute_conflict_resolution(
                            table_path,
                            self._create_test_orders_df(spark_session, start_key=8_000_200, count=5),
                            resolution_strategy="retry",
                        ),
                    ),
                    (
                        TransactionOperationType.SNAPSHOT_ISOLATION,
                        lambda: manager.execute_snapshot_isolation(table_path),
                    ),
                    (
                        TransactionOperationType.READ_YOUR_WRITES,
                        lambda: manager.execute_read_your_writes(
                            table_path,
                            self._create_test_orders_df(spark_session, start_key=8_000_300, count=5),
                        ),
                    ),
                ]

                for op_type, op_callable in dispatch:
                    query_id: str = op_type.value

                    if query_filter and query_id.upper() not in query_filter:
                        continue

                    op_iteration_counts[query_id] = op_iteration_counts.get(query_id, 0) + 1
                    op_iter = op_iteration_counts[query_id]

                    if not manager.supports_operation(op_type):
                        output.append(
                            {
                                "query_id": query_id,
                                "status": "SKIPPED",
                                "execution_time_seconds": 0.0,
                                "rows_returned": 0,
                                "iteration": op_iter,
                                "run_type": "measurement",
                            }
                        )
                        continue

                    _t0 = time.perf_counter()
                    try:
                        result = op_callable()
                    except Exception as exc:  # noqa: BLE001
                        output.append(
                            {
                                "query_id": query_id,
                                "status": "FAILED",
                                "execution_time_seconds": time.perf_counter() - _t0,
                                "rows_returned": 0,
                                "iteration": op_iter,
                                "run_type": "measurement",
                                "error": str(exc),
                            }
                        )
                        continue

                    row: dict[str, Any] = {
                        "query_id": query_id,
                        "status": "SUCCESS" if result.success else "FAILED",
                        "execution_time_seconds": result.duration_ms / 1000.0,
                        "rows_returned": result.rows_affected,
                        "iteration": op_iter,
                        "run_type": "measurement",
                    }
                    if result.error_message:
                        row["error"] = result.error_message
                    output.append(row)

        finally:
            shutil.rmtree(table_dir, ignore_errors=True)

        return output


__all__ = ["TransactionPrimitivesBenchmark", "OperationResult"]
