"""Transaction Primitives benchmark implementation.

Tests database transaction semantics and overhead using TPC-H schema.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

    from benchbox.utils.cloud_storage import DatabricksPath

from benchbox.base import BaseBenchmark
from benchbox.core.connection import DatabaseConnection
from benchbox.core.operations import OperationExecutor
from benchbox.core.primitives_benchmark_utils import (
    build_tpch_staging_tables_sql,
    quote_identifier,
    table_exists,
)
from benchbox.core.transaction_primitives.generator import TransactionPrimitivesDataGenerator
from benchbox.core.transaction_primitives.operations import TransactionOperationsManager
from benchbox.core.transaction_primitives.schema import STAGING_TABLES, get_all_staging_tables_sql, get_create_table_sql
from benchbox.utils.cloud_storage import create_path_handler
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

# DataFrame support - lazy import to avoid circular dependencies
_dataframe_operations_module = None

# Type alias for paths that could be local or cloud
PathLike = Union[Path, "CloudPath", "DatabricksPath"]


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


class TransactionPrimitivesBenchmark(BaseBenchmark, OperationExecutor):
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

    def get_data_source_benchmark(self) -> Optional[str]:
        """Transaction Primitives benchmark shares TPC-H data.

        Returns:
            "tpch" to indicate data sharing
        """
        return "tpch"

    @property
    def output_dir(self) -> PathLike:
        """Get the output directory.

        Returns:
            Output directory path
        """
        return self._output_dir

    @output_dir.setter
    def output_dir(self, value: Union[str, Path]) -> None:
        """Set the output directory and update data generator.

        Args:
            value: New output directory path
        """
        self._output_dir = create_path_handler(value)
        # Configure data generator with new path
        if hasattr(self, "data_generator"):
            self.data_generator.output_dir = self._output_dir
            # Also update the underlying TPC-H generator
            if hasattr(self.data_generator, "tpch_generator"):
                self.data_generator.tpch_generator.output_dir = self._output_dir

    def generate_data(self, tables: Optional[list[str]] = None) -> list[Union[str, Path]]:
        """Generate Transaction Primitives data.

        This generates/reuses TPC-H base data. Staging tables are created
        during benchmark setup via SQL.

        Args:
            tables: Optional list of tables to generate. If None, generates all.

        Returns:
            List of paths to generated data files
        """
        self.log_verbose(f"Generating Transaction Primitives data at scale factor {self.scale_factor}...")

        # Generate/reuse TPC-H base data
        self.tables = self.data_generator.generate()

        self.log_verbose(f"Base TPC-H data available: {len(self.tables)} tables")

        return list(self.tables.values())

    def ensure_auxiliary_data_files(self) -> None:
        """Ensure auxiliary data files (bulk load test files) exist.

        This is called by the runner when reusing data from manifest to ensure
        that bulk load test files are present even if they weren't generated
        during the original data generation.

        Uses file locking to prevent concurrent generation conflicts.
        """
        self.log_verbose("Checking for auxiliary data files (bulk load files)...")

        # Check if bulk load files exist, regenerate if missing
        bulk_files_exist = self.data_generator.check_bulk_load_files_exist()

        if not bulk_files_exist:
            self.log_verbose("Bulk load files missing - generating now...")

            # Acquire lock to prevent concurrent generation
            if self.data_generator._acquire_bulk_load_lock(timeout=300):
                try:
                    # Double-check after acquiring lock
                    if not self.data_generator.check_bulk_load_files_exist():
                        bulk_files = self.data_generator.generate_bulk_load_files()
                        self.log_verbose(f"✅ Generated {len(bulk_files)} bulk load files")
                    else:
                        self.log_verbose("✅ Files generated by another process")
                except Exception as e:
                    # Log warning but don't fail - some bulk load tests might not work
                    self.log_verbose(f"⚠️ Warning: Failed to generate bulk load files: {e}")
                finally:
                    self.data_generator._release_bulk_load_lock()
            else:
                self.log_verbose("⚠️ Warning: Could not acquire lock for file generation (timeout)")
        else:
            self.log_verbose("✅ Bulk load files already exist")

    def _acquire_setup_lock(self, connection: DatabaseConnection, timeout_seconds: int = 300) -> bool:
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

    def _release_setup_lock(self, connection: DatabaseConnection) -> None:
        """Release the staging table setup lock.

        Args:
            connection: Database connection
        """
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

    def setup(self, connection: DatabaseConnection, force: bool = False) -> dict[str, Any]:
        """Setup benchmark for execution.

        Creates and populates staging tables from TPC-H base tables.

        Uses an exclusive database lock to prevent concurrent setup operations
        that could waste resources or cause conflicts.

        Args:
            connection: Database connection
            force: If True, drop existing staging tables first

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
                )

        # Acquire exclusive lock to prevent concurrent setup operations
        # This eliminates race conditions during staging table population
        if not self._acquire_setup_lock(connection, timeout_seconds=300):
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
                create_sql = get_create_table_sql(table_name, if_not_exists=True)
                try:
                    connection.execute(create_sql)

                    # Track newly created tables (didn't exist before)
                    if not table_existed:
                        created_tables.append(table_name)
                        self.log_verbose(f"✅ Created {table_name}")
                    else:
                        self.log_verbose(f"Table {table_name} already exists")
                except Exception as e:
                    raise RuntimeError(f"Failed to create {table_name}: {e}")

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
                            )

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
            self._release_setup_lock(connection)

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

    def load_data(self, connection: DatabaseConnection, **kwargs) -> dict[str, Any]:
        """Load data into database (standard benchmark interface).

        For Transaction Primitives, data loading is handled by the platform adapter
        loading .tbl files for both base TPC-H tables and staging tables.
        This method just verifies that data was loaded correctly.

        Args:
            connection: Database connection
            **kwargs: Additional arguments (unused)

        Returns:
            Dictionary with loading results
        """
        # Verify that tables exist and have data
        return self.setup(connection, force=False)

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

    def get_operation(self, operation_id: str) -> Any:
        """Get a specific write operation.

        Args:
            operation_id: Operation identifier

        Returns:
            WriteOperation object

        Raises:
            ValueError: If operation_id is invalid
        """
        return self.operations_manager.get_operation(operation_id)

    def get_all_operations(self) -> dict[str, Any]:
        """Get all available write operations.

        Returns:
            Dictionary mapping operation IDs to WriteOperation objects
        """
        return self.operations_manager.get_all_operations()

    def get_operations_by_category(self, category: str) -> dict[str, Any]:
        """Get operations filtered by category.

        Args:
            category: Category name (e.g., 'insert', 'update', 'delete')

        Returns:
            Dictionary mapping operation IDs to WriteOperation objects
        """
        return self.operations_manager.get_operations_by_category(category)

    def get_operation_categories(self) -> list[str]:
        """Get list of available operation categories.

        Returns:
            List of category names
        """
        return self.operations_manager.get_operation_categories()

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

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return {
            "name": self._name,
            "version": self._version,
            "description": self._description,
            "scale_factor": self.scale_factor,
            "total_operations": self.operations_manager.get_operation_count(),
            "categories": self.get_operation_categories(),
            "tables": list(STAGING_TABLES.keys()),
            "data_source": "tpch",
        }

    def get_query(self, query_id: Union[int, str], **kwargs) -> str:
        """Get write SQL for a specific operation.

        Args:
            query_id: Operation identifier
            **kwargs: Additional parameters (not used for transaction primitives)

        Returns:
            Write SQL string

        Raises:
            ValueError: If query_id is invalid
        """
        operation = self.operations_manager.get_operation(str(query_id))
        return operation.write_sql

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all write operations SQL.

        Args:
            dialect: Target SQL dialect (not yet implemented for write operations)

        Returns:
            Dictionary mapping operation IDs to write SQL
        """
        operations = self.operations_manager.get_all_operations()
        return {op_id: op.write_sql for op_id, op in operations.items()}

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get write operations SQL filtered by category.

        Args:
            category: Operation category (insert, update, delete, ddl, transaction)

        Returns:
            Dictionary mapping operation IDs to write SQL for the category
        """
        operations = self.operations_manager.get_operations_by_category(category)
        return {op_id: op.write_sql for op_id, op in operations.items()}

    def execute_operation(
        self,
        operation_id: str,
        connection: DatabaseConnection,
    ) -> OperationResult:
        """Execute a transaction operation and validate results.

        Note: Transaction operations contain their own BEGIN/COMMIT/ROLLBACK logic,
        so no transaction wrapping is performed by this method.

        Args:
            operation_id: ID of operation to execute
            connection: Database connection

        Returns:
            OperationResult with execution metrics

        Raises:
            ValueError: If connection is invalid
            RuntimeError: If staging tables not initialized
        """
        # Validate connection
        if not connection:
            raise ValueError("Connection is None")
        if not hasattr(connection, "execute"):
            raise ValueError(f"Invalid connection type: {type(connection).__name__}")

        # Get operation to check if it requires setup
        operation = self.operations_manager.get_operation(operation_id)

        # Check staging tables exist and auto-initialize if needed
        if operation.requires_setup and not self.is_setup(connection):
            self.log_verbose("Staging tables not initialized - running setup() automatically...")
            try:
                self.setup(connection, force=False)
                self.log_verbose("Setup completed successfully")
            except Exception as e:
                raise RuntimeError(f"Failed to initialize staging tables before executing '{operation_id}': {e}") from e

        try:
            # Execute transaction SQL (operations already contain BEGIN/COMMIT/ROLLBACK)
            self.log_verbose(f"Executing transaction operation: {operation_id}")
            write_sql = self._replace_placeholders(operation.write_sql)
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
            )

        except Exception as e:
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

    def run_benchmark(
        self,
        connection: DatabaseConnection,
        operation_ids: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
    ) -> list[OperationResult]:
        """Run write operations benchmark.

        Args:
            connection: Database connection
            operation_ids: Optional list of specific operations to run
            categories: Optional list of categories to run

        Returns:
            List of OperationResult objects
        """
        # Determine which operations to run
        if operation_ids:
            operations = {op_id: self.get_operation(op_id) for op_id in operation_ids}
        elif categories:
            operations = {}
            for category in categories:
                operations.update(self.get_operations_by_category(category))
        else:
            operations = self.get_all_operations()

        self.log_verbose(f"Running {len(operations)} write operations...")

        # Execute each operation
        results = []
        for op_id in operations:
            result = self.execute_operation(op_id, connection)
            results.append(result)

            # Log result
            status = "✓" if result.success and result.validation_passed else "✗"
            self.log_verbose(
                f"{status} {op_id}: {result.write_duration_ms:.2f}ms write, "
                f"{result.validation_duration_ms:.2f}ms validation"
            )

        return results

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
        global _dataframe_operations_module
        if _dataframe_operations_module is None:
            from benchbox.core.transaction_primitives import dataframe_operations

            _dataframe_operations_module = dataframe_operations

        is_valid, _ = _dataframe_operations_module.validate_transaction_primitives_platform(platform_name)
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
        global _dataframe_operations_module
        if _dataframe_operations_module is None:
            from benchbox.core.transaction_primitives import dataframe_operations

            _dataframe_operations_module = dataframe_operations

        # Validate platform first
        is_valid, error_msg = _dataframe_operations_module.validate_transaction_primitives_platform(platform_name)
        if not is_valid:
            raise ValueError(error_msg)

        manager = _dataframe_operations_module.get_dataframe_transaction_manager(
            platform_name, spark_session=spark_session
        )

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
        global _dataframe_operations_module
        if _dataframe_operations_module is None:
            from benchbox.core.transaction_primitives import dataframe_operations

            _dataframe_operations_module = dataframe_operations

        # First check if platform is potentially valid
        is_valid, error_msg = _dataframe_operations_module.validate_transaction_primitives_platform(platform_name)
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


__all__ = ["TransactionPrimitivesBenchmark", "OperationResult"]
