"""Write Primitives benchmark implementation.

Tests fundamental database write operations using TPC-H schema.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

if TYPE_CHECKING:
    from benchbox.core.write_primitives.dataframe_operations import (
        DataFrameWriteCapabilities,
        DataFrameWriteOperationsManager,
    )

from benchbox.core.connection import DatabaseConnection
from benchbox.core.primitives_benchmark_utils import (
    build_tpch_staging_tables_sql,
    quote_identifier,
    table_exists,
)
from benchbox.core.transactional.benchmark_base import TransactionalBenchmarkBase
from benchbox.core.write_primitives.generator import WritePrimitivesDataGenerator
from benchbox.core.write_primitives.operations import WriteOperationsManager
from benchbox.core.write_primitives.schema import (
    STAGING_TABLES,
    TABLES,
    get_all_staging_tables_sql,
    get_create_table_sql,
)
from benchbox.sql_compat.rules.execution_filter.duckdb_write_primitives import (
    DUCKDB_WRITE_PRIMITIVES_CATEGORY_SKIPS,
    DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS,
)
from benchbox.sql_compat.rules.execution_filter.postgres_write_primitives import (
    POSTGRES_WRITE_PRIMITIVES_CATEGORY_SKIPS,
    POSTGRES_WRITE_PRIMITIVES_OPERATION_SKIPS,
)
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

_POSTGRES_OPERATION_SKIP_DIALECTS = frozenset({"postgres", "postgresql"})

# Staging tables whose source TPC-H table is optional: if the source is absent
# (e.g. a minimal fixture that loads only orders/lineitem), population is skipped
# with a logged note rather than raising. supplier backs GDPR delete ops;
# customer backs the SCD Type 2 dimension ops. In a full run the adapter loads
# all 8 base tables, so these populate normally. Value = the capability lost when
# the source is missing.
_OPTIONAL_WHEN_SOURCE_MISSING = {
    "delete_ops_supplier": "GDPR deletion operations will not be available.",
    "scd2_ops_dim_customer": "SCD Type 2 dimension operations will not be available.",
    "scd2_ops_stage_customer": "SCD Type 2 dimension operations will not be available.",
}


def _pk_lock_bypass_required(dialect: str) -> bool:
    """Return True if PK-based lock DDL should be bypassed for this platform.

    Consults the sql_compat registry (REGISTRY.resolve) for the platform decision.
    Every write_primitives-capable platform must have a registered rule in
    benchbox/sql_compat/rules/schema_emit/pk_capability.py.

    Args:
        dialect: Platform dialect string (e.g. "starrocks", "snowflake").
    """
    # Load PK capability rules into REGISTRY on first call (idempotent).
    import benchbox.sql_compat.rules.schema_emit.pk_capability  # noqa: F401
    from benchbox.sql_compat.actions import CompatAction
    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform=dialect.lower(),
        platform_version=None,
        benchmark="write_primitives",
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
    """Result of executing a write operation.

    Attributes:
        operation_id: ID of the operation
        success: Whether operation succeeded
        write_duration_ms: Time to execute write SQL
        rows_affected: Number of rows affected by write
        validation_duration_ms: Time to execute validation queries
        validation_passed: Whether all validations passed
        validation_results: Details of each validation
        cleanup_duration_ms: Time to execute cleanup
        cleanup_success: Whether cleanup succeeded
        error: Error message if operation failed
        cleanup_warning: Warning message for transaction cleanup failures
        executed_sql: The final write SQL actually executed (after platform overrides,
            dialect rewrites, and placeholder replacement); used for plan capture.
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
    status: str = "SUCCESS"
    error: Optional[str] = None
    cleanup_warning: Optional[str] = None
    skip_reason: Optional[str] = None
    executed_sql: Optional[str] = None


def _check_validation_query(val_query: Any, actual_rows: int, val_result: list | None = None) -> bool:
    """Check whether a validation query passes based on expected row or scalar-value criteria.

    Three validation modes (mutually exclusive at load time — see catalog loader):
    - expected_rows: exact row-count match
    - expected_rows_min/max: row-count range
    - expected_value_min/max: scalar value(s) from each row's first column must
      fall in [min, max]. Used by approximate-aggregate sketch ops where a
      tolerance-bounded number certifies correctness without strict cross-engine
      equality. Multi-row results (e.g. partition-aggregation validation
      queries) must have *every* row in range, not just the first.
    """
    expected_rows = val_query.expected_rows
    if expected_rows is not None:
        return actual_rows == expected_rows
    if val_query.expected_rows_min is not None or val_query.expected_rows_max is not None:
        min_val = val_query.expected_rows_min if val_query.expected_rows_min is not None else 0
        max_val = val_query.expected_rows_max if val_query.expected_rows_max is not None else float("inf")
        return min_val <= actual_rows <= max_val
    if (
        getattr(val_query, "expected_value_min", None) is not None
        and getattr(val_query, "expected_value_max", None) is not None
    ):
        if not val_result:
            return False
        for row in val_result:
            if not row:
                return False
            try:
                scalar = float(row[0])
            except (TypeError, ValueError):
                return False
            if not (val_query.expected_value_min <= scalar <= val_query.expected_value_max):
                return False
        return True
    return True


def _resolve_validation_sql(val_query: Any, platform_key: str | None) -> tuple[str | None, str | None]:
    """Resolve the effective validation SQL for the active platform.

    Returns (sql, skip_reason). If skip_reason is not None, the validation must be
    skipped (still treated as passed since skip = "not applicable on this engine",
    not "failed"). Mirrors `_get_effective_write_sql` for the operation-level
    overrides.
    """
    overrides = val_query.platform_overrides or {}
    if not platform_key or platform_key not in overrides:
        return val_query.sql, None
    override = overrides[platform_key]
    if override is None:
        return None, (
            f"Validation '{val_query.id}' explicitly skipped on platform '{platform_key}' "
            "via null platform_overrides entry"
        )
    return override, None


class WritePrimitivesBenchmark(TransactionalBenchmarkBase["OperationResult"]):
    """Write Primitives benchmark implementation.

    Tests fundamental write operations (INSERT, UPDATE, DELETE, BULK_LOAD,
    MERGE, DDL, TRANSACTION) using TPC-H schema as foundation.

    Implements OperationExecutor interface to support operation-based execution
    through the platform adapter.

    Attributes:
        scale_factor: Scale factor (1.0 = standard size)
        output_dir: Data output directory
        operations_manager: Operation manager
        data_generator: Data generator
    """

    _benchmark_label = "Write Primitives"
    _staging_tables = STAGING_TABLES

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize Write Primitives benchmark.

        Args:
            scale_factor: Scale factor (1.0 = standard size)
            output_dir: Data output directory
            **config: Additional configuration
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, quiet=quiet, **config)

        self._name = "Write Primitives Benchmark"
        self._version = "1.0"
        self._description = "Write Primitives benchmark - Testing fundamental write operations using TPC-H schema"

        # Setup directories
        if output_dir is None:
            # Reuse the canonical TPC-H datagen directory
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)

        self.output_dir = output_dir

        # Initialize components
        self.operations_manager = WriteOperationsManager()
        self.data_generator = WritePrimitivesDataGenerator(scale_factor, self.output_dir, **config)

        # Data files mapping
        self.tables: dict[str, Path] = {}

        # Tracks the SQL dialect from the most recent setup() call so that
        # _quote_identifier() can use the correct quoting character (e.g. backticks
        # for StarRocks which uses MySQL mode where double-quotes are string literals).
        self._setup_dialect: str = "standard"

    def _acquire_setup_lock(
        self, connection: DatabaseConnection, timeout_seconds: int = 300, dialect: str = "standard"
    ) -> bool:
        """Acquire an exclusive lock for staging table setup to prevent concurrent populations.

        Uses a dedicated lock table to prevent multiple processes from simultaneously
        populating staging tables, which could waste resources and cause conflicts.

        Args:
            connection: Database connection
            timeout_seconds: Maximum seconds to wait for lock (default: 300)
            dialect: SQL dialect (e.g. 'datafusion', 'standard')

        Returns:
            True if lock acquired, False if timeout

        Note:
            Caller must call _release_setup_lock() when done, preferably in a finally block.
            Lock is automatically released on connection close/crash.
        """
        if _pk_lock_bypass_required(dialect):
            return True

        # Create lock table if it doesn't exist (atomic operation)
        try:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS write_primitives_setup_lock (
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
                    f"INSERT INTO write_primitives_setup_lock (lock_name, holder_info) "
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
                f"SELECT acquired_at FROM write_primitives_setup_lock WHERE lock_name = '{escaped_lock_name}'"
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
            dialect: SQL dialect (e.g. 'datafusion', 'standard')
        """
        if _pk_lock_bypass_required(dialect):
            return

        try:
            lock_name = "staging_table_setup"
            # Escape lock name for DELETE query
            escaped_lock_name = lock_name.replace("'", "''")
            connection.execute(f"DELETE FROM write_primitives_setup_lock WHERE lock_name = '{escaped_lock_name}'")
            self.log_verbose("Released setup lock")
        except Exception as e:
            self.log_verbose(f"Warning: Could not release setup lock: {e}")

    def _quote_identifier(self, identifier: str) -> str:
        """Quote SQL identifier to prevent SQL injection.

        Uses double quotes (SQL standard) for most dialects. Uses backticks for
        StarRocks, which runs in MySQL mode where double-quotes are string literals.

        Args:
            identifier: Table, column, or schema name

        Returns:
            Quoted identifier safe for SQL

        Raises:
            ValueError: If identifier contains dangerous characters
        """
        if self._setup_dialect == "starrocks":
            escaped = identifier.replace("`", "``")
            return f"`{escaped}`"
        return quote_identifier(identifier)

    def _get_effective_write_sql(
        self,
        operation: Any,
        platform_key: str | None = None,
        sql_override: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Resolve effective write SQL (including platform overrides) or return skip reason.

        Args:
            operation: WriteOperation with write_sql and platform_overrides
            platform_key: Platform dialect key (e.g. 'datafusion', 'duckdb') passed by adapter
            sql_override: Pre-processed SQL from adapter (e.g. bulk_load rewrite)

        Returns:
            Tuple of (effective_sql, skip_reason). If skip_reason is not None,
            the operation should be skipped.
        """
        # Adapter-preprocessed SQL takes priority
        if sql_override is not None:
            return sql_override, None

        if getattr(operation, "aggregate_state", None) is not None:
            platform_label = platform_key or "SQL"
            return None, (
                f"Operation '{operation.id}' is DataFrame aggregate-state only and is unsupported on "
                f"platform '{platform_label}'."
            )

        if (platform_key or "").lower() in _POSTGRES_OPERATION_SKIP_DIALECTS:
            category = getattr(operation, "category", "")
            if category in POSTGRES_WRITE_PRIMITIVES_CATEGORY_SKIPS:
                return None, (
                    f"Operation '{operation.id}' is skipped on PostgreSQL-family platforms: "
                    f"{POSTGRES_WRITE_PRIMITIVES_CATEGORY_SKIPS[category]}"
                )
            if operation.id in POSTGRES_WRITE_PRIMITIVES_OPERATION_SKIPS:
                return None, (
                    f"Operation '{operation.id}' is skipped on PostgreSQL-family platforms: "
                    f"{POSTGRES_WRITE_PRIMITIVES_OPERATION_SKIPS[operation.id]}"
                )

        if (platform_key or "").lower() == "duckdb":
            category = getattr(operation, "category", "")
            if category in DUCKDB_WRITE_PRIMITIVES_CATEGORY_SKIPS:
                return None, (
                    f"Operation '{operation.id}' is skipped on DuckDB: "
                    f"{DUCKDB_WRITE_PRIMITIVES_CATEGORY_SKIPS[category]}"
                )
            if operation.id in DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS:
                return None, (
                    f"Operation '{operation.id}' is skipped on DuckDB: "
                    f"{DUCKDB_WRITE_PRIMITIVES_OPERATION_SKIPS[operation.id]}"
                )

        effective_sql = operation.write_sql

        if platform_key and operation.platform_overrides and platform_key in operation.platform_overrides:
            override = operation.platform_overrides[platform_key]
            if override is None:
                return None, f"Operation '{operation.id}' is unsupported on platform '{platform_key}'."
            effective_sql = override

        if (missing_file := self._check_bulk_load_file_dependencies(operation)) is not None:
            return None, (
                f"Operation '{operation.id}' is skipped because required bulk-load files are missing: {missing_file}"
            )

        return effective_sql, None

    def _check_bulk_load_file_dependencies(self, operation: Any) -> str | None:
        """Return a comma-separated list of missing file-dependency paths, if any.

        Only operations that declare `file_dependencies` are checked. Missing files
        are treated as a non-fatal skip reason to keep benchmark runs stable when
        auxiliary data has not been generated yet.
        """
        dependencies = list(getattr(operation, "file_dependencies", []))
        if not dependencies:
            return None

        files_dir = getattr(self.data_generator, "files_dir", None)
        if files_dir is None:
            return ", ".join(dependencies)

        missing: list[str] = []
        for filename in dependencies:
            try:
                if "*" in filename:
                    matches = list(files_dir.glob(filename))
                    if not matches:
                        missing.append(filename)
                else:
                    dependency_path = files_dir / filename
                    if not dependency_path.exists():
                        missing.append(filename)
            except Exception:
                missing.append(filename)

        if not missing:
            return None

        return ", ".join(missing)

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

    @staticmethod
    def _scd2_row_hash_expr(acctbal_expr: str) -> str:
        """Build the portable SCD2 change-detection fingerprint expression.

        Concatenates the tracked dimension attributes into a single string so
        changed rows are detectable with a plain ``<>`` comparison on every
        engine (no engine-specific hash function needed). The dimension seed and
        the 'unchanged'/'new' staging groups pass ``c_acctbal`` so their
        fingerprints match the dimension; the 'changed' staging group passes a
        bumped expression so its fingerprint differs and triggers a new version.

        Args:
            acctbal_expr: SQL expression for the account-balance attribute
                (``c_acctbal`` for an unchanged value, ``c_acctbal + 100`` for a
                simulated change).

        Returns:
            A portable SQL string expression yielding the row fingerprint.
        """
        return f"c_name || '|' || c_address || '|' || CAST({acctbal_expr} AS VARCHAR) || '|' || c_mktsegment"

    def _get_population_sql(self, table_name: str, source_table: str) -> str:
        """Get the INSERT SQL to populate a staging table from its source.

        Uses table-specific logic for subset/projection population.

        Args:
            table_name: Staging table name
            source_table: Source TPC-H table name

        Returns:
            SQL INSERT statement
        """
        quoted_table = self._quote_identifier(table_name)
        quoted_source = self._quote_identifier(source_table)

        if table_name == "merge_ops_target":
            # Take first 50% of orders for merge target
            return (
                f"INSERT INTO {quoted_table} SELECT * FROM {quoted_source} "
                f"WHERE o_orderkey <= (SELECT CAST(MAX(o_orderkey) * 0.5 AS INTEGER) FROM {quoted_source})"
            )
        elif table_name == "merge_ops_source":
            # Take second 50% of orders for merge source
            return (
                f"INSERT INTO {quoted_table} SELECT * FROM {quoted_source} "
                f"WHERE o_orderkey > (SELECT CAST(MAX(o_orderkey) * 0.5 AS INTEGER) FROM {quoted_source})"
            )
        elif table_name == "merge_ops_lineitem_target":
            # Take first 50% of lineitems
            return (
                f"INSERT INTO {quoted_table} SELECT * FROM {quoted_source} "
                f"WHERE l_orderkey <= (SELECT CAST(MAX(l_orderkey) * 0.5 AS INTEGER) FROM {quoted_source})"
            )
        elif table_name == "scd2_ops_dim_customer":
            # SCD Type 2 dimension seeded one current version per customer business
            # key. row_hash is a portable change-detection fingerprint over the
            # tracked attributes; valid_from is a fixed historical seed date and
            # valid_to is the open-ended sentinel. Built from the full customer
            # table so it scales with the scale factor.
            fingerprint = self._scd2_row_hash_expr("c_acctbal")
            return (
                f"INSERT INTO {quoted_table} "
                f"SELECT c_custkey AS sk, c_custkey, c_name, c_address, c_acctbal, c_mktsegment, "
                f"{fingerprint} AS row_hash, true AS is_current, "
                f"DATE '1990-01-01' AS valid_from, DATE '9999-12-31' AS valid_to "
                f"FROM {quoted_source}"
            )
        elif table_name == "scd2_ops_stage_customer":
            # SCD Type 2 incoming-change batch derived dynamically from the customer
            # table (range-bounded so it runs at any scale factor). Three disjoint
            # groups tag the SCD2 cases the catalog ops target:
            #   changed   - existing keys whose tracked attribute moved (acctbal
            #               bumped) so the fingerprint differs from the dimension;
            #   unchanged - existing keys copied verbatim (fingerprint matches, so a
            #               re-run produces zero new versions);
            #   new       - brand-new business keys (custkey offset beyond the
            #               current max) that have no current version yet.
            fp_changed = self._scd2_row_hash_expr("c_acctbal + 100")
            fp_same = self._scd2_row_hash_expr("c_acctbal")
            effective = "DATE '2026-01-01'"
            return (
                f"INSERT INTO {quoted_table} "
                f"SELECT c_custkey, c_name, c_address, c_acctbal + 100, c_mktsegment, "
                f"{fp_changed} AS row_hash, {effective} AS effective_ts, 'changed' AS change_type "
                f"FROM {quoted_source} WHERE c_custkey BETWEEN 1 AND 20;\n"
                f"INSERT INTO {quoted_table} "
                f"SELECT c_custkey, c_name, c_address, c_acctbal, c_mktsegment, "
                f"{fp_same} AS row_hash, {effective} AS effective_ts, 'unchanged' AS change_type "
                f"FROM {quoted_source} WHERE c_custkey BETWEEN 21 AND 40;\n"
                f"INSERT INTO {quoted_table} "
                f"SELECT c_custkey + (SELECT MAX(c_custkey) FROM {quoted_source}), "
                f"c_name, c_address, c_acctbal, c_mktsegment, "
                f"{fp_same} AS row_hash, {effective} AS effective_ts, 'new' AS change_type "
                f"FROM {quoted_source} WHERE c_custkey BETWEEN 1 AND 20"
            )
        elif table_name == "ddl_truncate_target":
            # Take all rows but only 3 columns for truncate testing
            return f"INSERT INTO {quoted_table} SELECT o_orderkey, o_custkey, o_orderdate FROM {quoted_source}"
        else:
            # Full copy for other tables
            return f"INSERT INTO {quoted_table} SELECT * FROM {quoted_source}"

    def _populate_staging_tables(self, connection: DatabaseConnection, tables: dict[str, str]) -> dict[str, int]:
        """Populate staging tables from source tables.

        Args:
            connection: Database connection
            tables: Mapping of staging_table_name -> source_table_name

        Returns:
            Mapping of table_name -> row_count
        """
        status: dict[str, int] = {}

        for table_name, source_table in tables.items():
            quoted_table = self._quote_identifier(table_name)

            # Check if table needs population
            try:
                result = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
                current_count = result[0] if result else 0
            except Exception:
                current_count = 0

            if current_count == 0:
                # Validate source table exists and has data before copying
                try:
                    quoted_source = self._quote_identifier(source_table)
                    source_result = connection.execute(f"SELECT COUNT(*) FROM {quoted_source}").fetchone()
                    source_count = source_result[0] if source_result else 0
                except Exception as e:
                    # Source table doesn't exist - skip population for optional tables
                    # (see _OPTIONAL_WHEN_SOURCE_MISSING). Minimal test fixtures load
                    # only orders/lineitem, so these are skipped rather than raising.
                    if table_name in _OPTIONAL_WHEN_SOURCE_MISSING:
                        self.log_verbose(
                            f"Skipping {table_name} population - source table '{source_table}' does not exist. "
                            f"{_OPTIONAL_WHEN_SOURCE_MISSING[table_name]}"
                        )
                        status[table_name] = 0
                        continue
                    else:
                        raise RuntimeError(
                            f"Cannot validate source table '{source_table}' before populating '{table_name}': {e}"
                        ) from e

                if source_count == 0:
                    # Required tables (orders, lineitem) must have data
                    if table_name in ["update_ops_orders", "delete_ops_orders", "delete_ops_lineitem"]:
                        raise RuntimeError(
                            f"Source table '{source_table}' is empty (0 rows). "
                            f"Cannot populate staging table '{table_name}'. "
                            f"Please ensure TPC-H data is loaded before running setup()."
                        )
                    else:
                        # Optional tables can be skipped if source is empty
                        self.log_verbose(f"Skipping {table_name} population - source table '{source_table}' is empty.")
                        status[table_name] = 0
                        continue

                # Table is empty - populate it
                self.log_verbose(f"Populating {table_name} from {source_table} ({source_count} rows)...")
                populate_sql = self._get_population_sql(table_name, source_table)
                connection.execute(populate_sql)

                result = connection.execute(f"SELECT COUNT(*) FROM {quoted_table}").fetchone()
                status[table_name] = result[0] if result else 0
                self.log_verbose(f"Populated {table_name} with {status[table_name]} rows")
            else:
                # Table already has data
                status[table_name] = current_count
                self.log_verbose(f"Table {table_name} already populated ({current_count} rows)")

        return status

    def setup(self, connection: DatabaseConnection, force: bool = False, dialect: str = "standard") -> dict[str, Any]:
        """Setup benchmark for execution.

        Creates and populates staging tables from TPC-H base tables.

        Uses an exclusive database lock to prevent concurrent setup operations
        that could waste resources or cause conflicts.

        Args:
            connection: Database connection
            force: If True, drop existing staging tables first
            dialect: SQL dialect (e.g. 'datafusion', 'standard')

        Returns:
            Dictionary with setup status and details

        Raises:
            RuntimeError: If required tables don't exist or setup fails
        """
        # Set dialect first so any downstream call to _quote_identifier() (including
        # teardown paths reached if validation below raises) uses the correct quoting.
        self._setup_dialect = dialect
        self.log_verbose("Setting up Write Primitives benchmark...")

        # Validate TPC-H base tables exist
        required_tables = ["orders", "lineitem"]
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
                "Check write_primitives_setup_lock table for stale locks."
            )

        try:
            # Drop existing staging tables if force=True (done once before loop)
            if force:
                for table_name in STAGING_TABLES:
                    try:
                        quoted = self._quote_identifier(table_name)
                        connection.execute(f"DROP TABLE IF EXISTS {quoted}")
                        self.log_verbose(f"Dropped existing {table_name} (force mode)")
                    except Exception as e:
                        self.log_verbose(f"Warning: Could not drop {table_name}: {e}")

            # Create staging tables
            created_tables = []
            for table_name in STAGING_TABLES:
                table_existed = self._table_exists(connection, table_name)
                create_sql = get_create_table_sql(table_name, dialect=dialect, if_not_exists=True)
                try:
                    connection.execute(create_sql)
                    if not table_existed:
                        created_tables.append(table_name)
                        self.log_verbose(f"Created {table_name}")
                    else:
                        self.log_verbose(f"Table {table_name} already exists")
                except Exception as e:
                    raise RuntimeError(f"Failed to create {table_name}: {e}") from e

            # Populate staging tables from TPC-H base tables
            table_population_map = {
                "update_ops_orders": "orders",
                "delete_ops_orders": "orders",
                "delete_ops_lineitem": "lineitem",
                "delete_ops_supplier": "supplier",
                "merge_ops_target": "orders",
                "merge_ops_source": "orders",
                "merge_ops_lineitem_target": "lineitem",
                "scd2_ops_dim_customer": "customer",
                "scd2_ops_stage_customer": "customer",
                "ddl_truncate_target": "orders",
            }

            population_status = self._populate_staging_tables(connection, table_population_map)

            # Count rows in non-populated staging tables
            status: dict[str, int] = dict(population_status)
            for table_name in STAGING_TABLES:
                if table_name not in status:
                    try:
                        quoted = self._quote_identifier(table_name)
                        result = connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
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
        self.log_verbose("Tearing down Write Primitives benchmark...")

        for table_name in STAGING_TABLES:
            try:
                quoted = self._quote_identifier(table_name)
                connection.execute(f"DROP TABLE IF EXISTS {quoted}")
                self.log_verbose(f"Dropped {table_name}")
            except Exception as e:
                self.log_verbose(f"Warning: Could not drop {table_name}: {e}")

        self.log_verbose("Teardown complete")

    def cleanup_auxiliary_files(self) -> None:
        """Remove auxiliary data files (bulk load test files).

        This removes the write_primitives_auxiliary subdirectory containing
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

        For Write Primitives, data loading is handled by the platform adapter
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

        Truncates and repopulates staging tables that are populated from TPC-H base tables.

        Args:
            connection: Database connection
        """
        self.log_verbose("Resetting Write Primitives staging tables...")

        reset_map = {
            "update_ops_orders": "orders",
            "delete_ops_orders": "orders",
            "delete_ops_lineitem": "lineitem",
            "delete_ops_supplier": "supplier",
            "merge_ops_target": "orders",
            "merge_ops_source": "orders",
            "merge_ops_lineitem_target": "lineitem",
            "scd2_ops_dim_customer": "customer",
            "scd2_ops_stage_customer": "customer",
            "ddl_truncate_target": "orders",
        }

        for table_name in reset_map:
            try:
                quoted = self._quote_identifier(table_name)
                connection.execute(f"TRUNCATE TABLE {quoted}")
                self.log_verbose(f"Truncated {table_name}")
            except Exception as e:
                self.log_verbose(f"Warning: Could not truncate {table_name}: {e}")

        # Repopulate all tables using the shared method
        self._populate_staging_tables(connection, reset_map)
        self.log_verbose("Reset complete")

    def is_setup(self, connection: DatabaseConnection) -> bool:
        """Check if staging tables are ready.

        Args:
            connection: Database connection

        Returns:
            True if all staging tables exist and have data
        """
        try:
            # Check that required staging tables exist and have data
            # Note: delete_ops_supplier is optional (only needed if supplier table exists)
            required_tables = [
                "update_ops_orders",
                "delete_ops_orders",
                "delete_ops_lineitem",
                "merge_ops_target",
                "merge_ops_source",
                "merge_ops_lineitem_target",
                "ddl_truncate_target",
            ]

            for table_name in required_tables:
                quoted = self._quote_identifier(table_name)
                result = connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()
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
            Uses write_primitives_auxiliary subdirectory to isolate auxiliary files.
        """
        if "{file_path}" in sql:
            # Replace with the auxiliary files directory path
            # This uses a subdirectory to keep bulk load files separate from TPC-H data
            if self.output_dir:
                file_path = str(self.output_dir / "write_primitives_auxiliary")
            else:
                file_path = ""

            # Escape single quotes in path to prevent SQL injection
            # SQL standard: '' (two single quotes) escapes a single quote
            file_path = file_path.replace("'", "''")

            # Validate path doesn't contain other dangerous characters
            # Allow common path characters: alphanumeric, /, \, ., -, _, :, space
            if re.search(r"[^\w\s/\\\.\-:]", file_path.replace("''", "'")):
                # Contains unusual characters - log warning
                self.log_verbose(f"Warning: File path contains unusual characters: {file_path}")

            sql = sql.replace("{file_path}", file_path)
        return sql

    def get_schema(self, dialect: str = "standard") -> dict[str, dict]:
        """Get the Write Primitives schema definitions.

        Args:
            dialect: SQL dialect to use for data types

        Returns:
            Dictionary mapping table names to their schema definitions
        """
        normalized: dict[str, dict[str, Any]] = {}

        # The 8 base TPC-H tables (fixed by the spec) plus the write-primitives
        # staging tables. Anything else in TABLES (e.g. operation-created sketch
        # tables) is created at execution time, not loaded, so it is excluded.
        loadable_table_names = {
            "region",
            "nation",
            "customer",
            "supplier",
            "part",
            "partsupp",
            "orders",
            "lineitem",
            *STAGING_TABLES.keys(),
        }

        for table_name, table_def in TABLES.items():
            if table_name not in loadable_table_names:
                continue

            # Write Primitives staging tables are already dict-shaped.
            if isinstance(table_def, dict) and "columns" in table_def:
                normalized[table_name] = table_def
                continue

            # TPC-H base tables are Table objects from benchbox.core.tpch.schema.
            if hasattr(table_def, "columns"):
                columns = []
                for col in getattr(table_def, "columns", []):
                    col_type = col.get_sql_type() if hasattr(col, "get_sql_type") else "VARCHAR"
                    columns.append(
                        {
                            "name": col.name,
                            "type": col_type,
                            "nullable": getattr(col, "nullable", False),
                            "primary_key": getattr(col, "primary_key", False),
                        }
                    )

                normalized[table_name] = {
                    "name": getattr(table_def, "name", table_name),
                    "columns": columns,
                }

        return normalized

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get CREATE TABLE SQL for all required tables.

        Includes both TPC-H base tables and Write Primitives staging tables.
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
            staging_heading="Write Primitives Staging Tables",
            get_staging_tables_sql=get_all_staging_tables_sql,
        )

    def get_query(self, query_id: Union[int, str], **kwargs: Any) -> str:
        """Get SQL for a SQL-runnable write operation."""
        operation = self.operations_manager.get_operation(str(query_id))
        if operation.aggregate_state is not None:
            raise ValueError(f"Operation '{operation.id}' is DataFrame aggregate-state only and is not exposed as SQL")
        return operation.write_sql

    def get_all_operations(self) -> dict[str, Any]:
        """Return SQL-operable operations.

        Aggregate-state operations are routed through the DataFrame execution
        path and intentionally excluded here so SQL-only counts and defaults
        match legacy write-primitives behavior.
        """
        return {
            op_id: operation
            for op_id, operation in self.operations_manager.get_all_operations().items()
            if operation.aggregate_state is None and operation.category.lower() != "sketch"
        }

    def get_operation_categories(self) -> list[str]:
        """Get categories for SQL-operable operations."""
        return sorted({operation.category for operation in self.get_all_operations().values()})

    def get_operations_by_category(self, category: str) -> dict[str, Any]:
        """Get SQL-operable operations filtered by category."""
        normalized = category.lower()
        return {
            op_id: operation
            for op_id, operation in self.get_all_operations().items()
            if operation.category.lower() == normalized
        }

    def get_benchmark_info(self) -> dict[str, Any]:
        """Return benchmark metadata using SQL operation count/category."""
        return {
            "name": self._name,
            "version": self._version,
            "description": self._description,
            "scale_factor": self.scale_factor,
            "total_operations": len(self.get_all_operations()),
            "categories": self.get_operation_categories(),
            "tables": list(self._staging_tables.keys()),
            "data_source": "tpch",
        }

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get SQL-runnable write operations, excluding DataFrame-only aggregate-state ops."""
        _ = dialect
        operations = self.operations_manager.get_all_operations()
        return {
            op_id: op.write_sql
            for op_id, op in operations.items()
            if op.aggregate_state is None and op.category.lower() != "sketch"
        }

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get SQL-runnable write operations for a category."""
        operations = self.operations_manager.get_operations_by_category(category)
        return {
            op_id: op.write_sql
            for op_id, op in operations.items()
            if op.aggregate_state is None and op.category.lower() != "sketch"
        }

    def execute_operation(
        self,
        operation_id: str,
        connection: DatabaseConnection,
        **kwargs: Any,
    ) -> OperationResult:
        """Execute a write operation and validate results.

        Note: Write Primitives v2 does not use transaction-based cleanup.
        Operations either have explicit cleanup SQL or accumulate data.

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

        try:
            effective_sql, skip_reason = self._get_effective_write_sql(
                operation, platform_key=platform_key, sql_override=sql_override
            )
            if skip_reason is not None:
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

            # Execute write SQL (with placeholder replacement)
            self.log_verbose(f"Executing write operation: {operation_id}")
            if effective_sql is None:
                raise RuntimeError(f"No executable SQL resolved for operation '{operation_id}'")
            effective_sql = self._rewrite_transactional_sql_for_platform(effective_sql, platform_key)
            write_sql = self._replace_placeholders(effective_sql)
            write_start = time.perf_counter()
            write_result = connection.execute(write_sql)
            write_duration_ms = (time.perf_counter() - write_start) * 1000

            rows_affected = self._extract_rows_affected(write_result, operation_id)

            # Execute validation queries
            validation_passed, validation_results, validation_duration_ms = self._run_operation_validation(
                operation, connection, operation_id, platform_key=platform_key
            )

            # Execute cleanup if specified
            cleanup_success, cleanup_warning, cleanup_duration_ms = self._run_operation_cleanup(
                operation, connection, operation_id
            )

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
                status="SUCCESS",
                cleanup_warning=cleanup_warning,
                executed_sql=write_sql,
            )

        except Exception as e:
            self._rollback_connection_after_error(connection)
            error_msg = f"Operation {operation_id} failed: {str(e)}"
            self.log_verbose(error_msg)

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
                status="FAILED",
                error=error_msg,
                cleanup_warning="Write operation failed during execution. Run reset() to ensure clean state.",
            )

    def _extract_rows_affected(self, write_result: Any, operation_id: str) -> int:
        """Extract rows_affected from the write result object."""
        rows_affected = getattr(write_result, "rowcount", None)
        if rows_affected is None:
            self.log_verbose(f"Warning: Platform doesn't support rowcount for {operation_id}")
            return -1  # Sentinel value indicating "unknown"
        if rows_affected == -1:
            self.log_verbose(f"Note: rowcount not applicable for {operation_id}")
        return rows_affected

    def _run_operation_validation(
        self,
        operation: Any,
        connection: DatabaseConnection,
        operation_id: str,
        platform_key: str | None = None,
    ) -> tuple[bool, list[dict], float]:
        """Run validation queries for a write operation.

        Resolves per-platform validation SQL via `ValidationQuery.platform_overrides`
        before execution: a string override replaces the default sql for that
        platform; an explicit `null` override skips that validation with a logged
        reason (the op stays passed because skip means "not applicable on this
        engine"). Platforms with no override key fall through to the default sql.
        """
        self.log_verbose(f"Validating operation: {operation_id}")
        validation_start = time.perf_counter()
        validation_results = []
        validation_passed = True

        for val_query in operation.validation_queries:
            effective_sql, skip_reason = _resolve_validation_sql(val_query, platform_key)

            if skip_reason is not None:
                self.log_verbose(f"Skipping validation '{val_query.id}' for {operation_id}: {skip_reason}")
                validation_results.append(
                    {
                        "query_id": val_query.id,
                        "sql": val_query.sql,
                        "expected_rows": val_query.expected_rows,
                        "actual_rows": 0,
                        "passed": True,
                        "skipped": True,
                        "skip_reason": skip_reason,
                        "sample": [],
                    }
                )
                continue

            val_sql = self._replace_placeholders(effective_sql)
            val_result = connection.execute(val_sql).fetchall()
            actual_rows = len(val_result)
            passed = _check_validation_query(val_query, actual_rows, val_result)
            validation_passed = validation_passed and passed

            validation_results.append(
                {
                    "query_id": val_query.id,
                    "sql": effective_sql,
                    "expected_rows": val_query.expected_rows,
                    "actual_rows": actual_rows,
                    "passed": passed,
                    "sample": val_result[:5] if val_result else [],
                }
            )

        validation_duration_ms = (time.perf_counter() - validation_start) * 1000
        return validation_passed, validation_results, validation_duration_ms

    def _run_operation_cleanup(
        self, operation: Any, connection: DatabaseConnection, operation_id: str
    ) -> tuple[bool, str | None, float]:
        """Run cleanup SQL for a write operation if specified."""
        self.log_verbose(f"Cleaning up operation: {operation_id}")
        cleanup_start = time.perf_counter()
        cleanup_success = True
        cleanup_warning = None

        if operation.cleanup_sql:
            try:
                connection.execute(operation.cleanup_sql)
                self.log_verbose(f"Executed cleanup SQL for {operation_id}")
            except Exception as e:
                cleanup_error = str(e)
                self.log_verbose(f"Cleanup SQL failed for {operation_id}: {cleanup_error}")
                cleanup_success = False
                cleanup_warning = (
                    f"Write operation '{operation_id}' cleanup failed. "
                    f"Database may be in modified state. Run reset() to restore staging tables. "
                    f"Error: {cleanup_error}"
                )
                self.log_verbose(f"WARNING: {cleanup_warning}")

        cleanup_duration_ms = (time.perf_counter() - cleanup_start) * 1000
        return cleanup_success, cleanup_warning, cleanup_duration_ms

    # ========================================================================
    # DataFrame Mode Support
    # ========================================================================

    def supports_dataframe_mode(self) -> bool:
        """Check if this benchmark supports DataFrame execution mode.

        Write Primitives supports DataFrame mode for platforms like Polars,
        PySpark, and Pandas that can perform write operations.

        Returns:
            True - Write Primitives supports DataFrame mode
        """
        return True

    def skip_dataframe_data_loading(self) -> bool:
        """Write Primitives DataFrame execution manages SQL-parity loading internally."""
        return True

    def get_dataframe_operations(self, platform_name: str) -> "DataFrameWriteOperationsManager | None":
        """Get DataFrame write operations manager for a platform.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")

        Returns:
            DataFrameWriteOperationsManager if platform supports DataFrame writes,
            None otherwise.

        Example:
            benchmark = WritePrimitivesBenchmark()
            manager = benchmark.get_dataframe_operations("polars-df")
            if manager:
                result = manager.execute_insert(
                    table_path="/data/orders",
                    dataframe=orders_df,
                    mode="append"
                )
        """
        from benchbox.core.write_primitives.dataframe_operations import (
            get_dataframe_write_manager,
        )

        return get_dataframe_write_manager(platform_name)

    def get_dataframe_capabilities(self, platform_name: str) -> "DataFrameWriteCapabilities | None":
        """Get DataFrame write capabilities for a platform.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")

        Returns:
            DataFrameWriteCapabilities if platform supports DataFrame writes,
            None otherwise.
        """
        manager = self.get_dataframe_operations(platform_name)
        if manager is None:
            return None
        return manager.get_capabilities()

    def execute_dataframe_workload(
        self,
        *,
        ctx: Any,
        adapter: Any,
        benchmark_config: Any,
        query_filter: set[str] | None = None,
        monitor: Any | None = None,
        run_options: Any | None = None,
    ) -> list[dict[str, Any]]:
        """Execute Write Primitives with SQL-equivalent behavior in DataFrame mode.

        This path intentionally routes DataFrame-mode execution through the same
        SQL operation catalog and benchmark logic used by SQL adapters so each
        operation ID performs equivalent work.
        """
        _ = (ctx, monitor, run_options)
        config_options = getattr(benchmark_config, "options", {}) or {}
        warmup_iterations = int(config_options.get("power_warmup_iterations", 1) or 1)
        measurement_iterations = int(config_options.get("power_iterations", 3) or 3)

        try:
            results: list[dict[str, Any]] = []

            # Keep iteration semantics aligned with SQL runners:
            # warmup iteration index=0, measurement iterations index=1..N.
            for _warmup_idx in range(max(warmup_iterations, 0)):
                warmup_rows = self._execute_dataframe_sql_parity_workload(query_filter=query_filter, adapter=adapter)
                for row in warmup_rows:
                    warmup_row = dict(row)
                    warmup_row["run_type"] = "warmup"
                    warmup_row["iteration"] = 0
                    warmup_row["stream_id"] = 0
                    results.append(warmup_row)

            for measurement_idx in range(1, measurement_iterations + 1):
                measurement_rows = self._execute_dataframe_sql_parity_workload(
                    query_filter=query_filter, adapter=adapter
                )
                for row in measurement_rows:
                    measurement_row = dict(row)
                    measurement_row["run_type"] = "measurement"
                    measurement_row["iteration"] = measurement_idx
                    measurement_row["stream_id"] = 0
                    results.append(measurement_row)

            return results
        except Exception as e:
            return [
                {
                    "query_id": "WR_PARITY_EXECUTION",
                    "status": "FAILED",
                    "execution_time_seconds": 0.0,
                    "rows_returned": 0,
                    "error": f"DataFrame SQL-parity execution failed: {e}",
                }
            ]

    def _execute_dataframe_sql_parity_workload(
        self,
        *,
        query_filter: set[str] | None = None,
        adapter: Any = None,
    ) -> list[dict[str, Any]]:
        """Run write primitive operations through DuckDB for SQL/dataframe parity.

        Ops with an `aggregate_state` spec on their catalog entry route through
        the platform's DataFrameWriteOperationsManager via
        ``manager.execute_aggregate_persist`` then ``execute_aggregate_merge``
        instead of the DuckDB parity path. This keeps DataFrame-layer sketch
        ops (HLL, Top-K) measured on their actual engine when the platform
        supports them, while leaving CRUD parity ops on the DuckDB path.
        """
        from benchbox.platforms.duckdb import DuckDBAdapter

        data_dir = Path(self.output_dir)
        parity_db_path = data_dir / "_write_primitives_df_parity.duckdb"

        # Partition ops: aggregate-state ones bypass the DuckDB parity path.
        all_op_ids = self._select_dataframe_operation_ids(query_filter=query_filter)
        operations = self.operations_manager.get_all_operations()
        agg_state_op_ids = [op_id for op_id in all_op_ids if operations[op_id].aggregate_state is not None]
        sql_parity_op_ids = [op_id for op_id in all_op_ids if operations[op_id].aggregate_state is None]

        results: list[dict[str, Any]] = []

        # Aggregate-state ops first — they don't need the parity DuckDB.
        for op_id in agg_state_op_ids:
            results.append(self._execute_aggregate_state_op(op_id, adapter=adapter))

        if not sql_parity_op_ids:
            return results

        parity_adapter = DuckDBAdapter(database_path=str(parity_db_path))
        connection = parity_adapter.create_connection(database_path=str(parity_db_path), force_recreate=True)
        try:
            parity_adapter.create_schema(self, connection)
            parity_adapter.load_data(self, connection, data_dir)

            for op_id in sql_parity_op_ids:
                op_result = self.execute_operation(op_id, connection)
                status = "SUCCESS" if op_result.success and op_result.validation_passed else "FAILED"
                error = op_result.error
                if status == "FAILED" and not error and not op_result.validation_passed:
                    error = f"Validation failed for operation '{op_id}'"

                results.append(
                    {
                        "query_id": op_id,
                        "status": status,
                        "execution_time_seconds": op_result.write_duration_ms / 1000.0,
                        "rows_returned": op_result.rows_affected,
                        **({"error": error} if error else {}),
                    }
                )
            return results
        finally:
            try:
                parity_adapter.close_connection(connection)
            finally:
                try:
                    parity_db_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _execute_aggregate_state_op(self, op_id: str, *, adapter: Any) -> dict[str, Any]:
        """Run an AGGREGATE_PERSIST + AGGREGATE_MERGE cycle for a catalog op.

        Routes through the platform's DataFrameWriteOperationsManager and the
        sketch factories in `dataframe_operations.py`. Today only PySpark
        advertises support; other platforms surface a structured "skipped"
        result without crashing the workload.
        """
        import shutil

        op = self.operations_manager.get_operation(op_id)
        spec = op.aggregate_state
        if spec is None:  # defensive — caller already filtered
            return {
                "query_id": op_id,
                "status": "FAILED",
                "execution_time_seconds": 0.0,
                "rows_returned": 0,
                "error": f"Operation '{op_id}' has no aggregate_state spec",
            }

        platform_name = self._resolve_platform_name(adapter)
        if platform_name not in spec.supported_platforms:
            return {
                "query_id": op_id,
                "status": "SKIPPED",
                "execution_time_seconds": 0.0,
                "rows_returned": 0,
                "error": (
                    f"Aggregate-state op '{op_id}' not supported on platform "
                    f"'{platform_name}' (supports: {','.join(spec.supported_platforms) or 'none'})"
                ),
            }

        try:
            from benchbox.core.write_primitives.dataframe_operations import (
                get_dataframe_write_manager,
                make_pyspark_hll_merge_extract,
                make_pyspark_hll_persist_builder,
                make_pyspark_topk_merge_extract,
                make_pyspark_topk_persist_builder,
                pyspark_supports_approx_top_k,
            )

            spark = self._extract_spark_session(adapter)
            if spark is None:
                return {
                    "query_id": op_id,
                    "status": "FAILED",
                    "execution_time_seconds": 0.0,
                    "rows_returned": 0,
                    "error": f"Adapter for '{platform_name}' did not expose a SparkSession for op '{op_id}'",
                }

            if spec.sketch_type == "topk" and not pyspark_supports_approx_top_k(spark):
                return {
                    "query_id": op_id,
                    "status": "SKIPPED",
                    "execution_time_seconds": 0.0,
                    "rows_returned": 0,
                    "error": (
                        f"Top-K aggregate-state op '{op_id}' requires Spark 4.1+; "
                        f"runtime version {getattr(spark, 'version', 'unknown')}"
                    ),
                }

            output_dir = Path(self.output_dir)
            source_path = self._resolve_aggregate_source_path(spec.source_table, adapter, output_dir, spark)
            target_path = output_dir / spec.target_subdir

            # Clear stale state from prior iterations.
            if target_path.exists():
                shutil.rmtree(target_path, ignore_errors=True)

            manager = get_dataframe_write_manager("pyspark-df", spark_session=spark)
            if manager is None:
                return {
                    "query_id": op_id,
                    "status": "FAILED",
                    "execution_time_seconds": 0.0,
                    "rows_returned": 0,
                    "error": f"No DataFrameWriteOperationsManager for pyspark-df (op '{op_id}')",
                }

            if spec.sketch_type == "hll":
                state_builder = make_pyspark_hll_persist_builder(
                    spark_session=spark,
                    source_path=source_path,
                    group_cols=spec.group_cols,
                    value_col=spec.value_col,
                    sketch_alias=spec.sketch_alias,
                )
                merge_extract = make_pyspark_hll_merge_extract(spark_session=spark, sketch_col=spec.sketch_alias)
            else:  # topk
                state_builder = make_pyspark_topk_persist_builder(
                    spark_session=spark,
                    source_path=source_path,
                    group_cols=spec.group_cols,
                    value_col=spec.value_col,
                    sketch_alias=spec.sketch_alias,
                )
                merge_extract = make_pyspark_topk_merge_extract(spark_session=spark, sketch_col=spec.sketch_alias)

            t0 = mono_time()
            persist = manager.execute_aggregate_persist(target_path, state_builder)
            if not persist.success:
                return {
                    "query_id": op_id,
                    "status": "FAILED",
                    "execution_time_seconds": elapsed_seconds(t0),
                    "rows_returned": 0,
                    "error": f"AGGREGATE_PERSIST failed: {persist.error_message or 'unknown error'}",
                }
            merge = manager.execute_aggregate_merge(target_path, merge_extract)
            elapsed = elapsed_seconds(t0)
            if not merge.success:
                return {
                    "query_id": op_id,
                    "status": "FAILED",
                    "execution_time_seconds": elapsed,
                    "rows_returned": int(persist.rows_affected),
                    "error": f"AGGREGATE_MERGE failed: {merge.error_message or 'unknown error'}",
                }

            # Validate the extracted scalar against bounds in the first
            # validation_query (aggregate-state ops carry only one).
            aggregate_value = float(merge.metrics.get("aggregate_value", 0.0))
            validation_pass, validation_error = self._validate_aggregate_value(op, aggregate_value)
            if not validation_pass:
                return {
                    "query_id": op_id,
                    "status": "FAILED",
                    "execution_time_seconds": elapsed,
                    "rows_returned": int(persist.rows_affected),
                    "error": validation_error,
                }

            # Cleanup the state directory so repeat measurement iterations
            # start clean.
            shutil.rmtree(target_path, ignore_errors=True)

            return {
                "query_id": op_id,
                "status": "SUCCESS",
                "execution_time_seconds": elapsed,
                "rows_returned": int(persist.rows_affected),
                "aggregate_value": aggregate_value,
            }
        except Exception as exc:
            return {
                "query_id": op_id,
                "status": "FAILED",
                "execution_time_seconds": 0.0,
                "rows_returned": 0,
                "error": f"Aggregate-state op '{op_id}' raised: {exc}",
            }

    @staticmethod
    def _resolve_platform_name(adapter: Any) -> str:
        """Map an adapter instance to the platform identifier used in catalog specs."""
        if adapter is None:
            return ""
        name = getattr(adapter, "platform_name", None) or getattr(adapter, "name", None) or ""
        return str(name).strip().lower().replace("-df", "").replace("_df", "")

    @staticmethod
    def _extract_spark_session(adapter: Any) -> Any:
        """Pull a SparkSession out of a PySpark adapter, if present."""
        for attr in ("spark", "_spark", "spark_session", "session"):
            value = getattr(adapter, attr, None)
            if value is not None:
                return value
        return None

    def _resolve_aggregate_source_path(self, source_table: str, adapter: Any, output_dir: Path, spark: Any) -> Path:
        """Resolve the on-disk source path for an aggregate-state op.

        Aggregate-state ops read from a Parquet directory the persist builder
        passes through `spark.read.parquet(...)`. Today the workload runner
        prepares this on demand from BenchBox's TBL fixtures by writing a
        Parquet copy under ``output_dir/_aggregate_state_sources/<table>``
        if one isn't already present.
        """
        cache_dir = output_dir / "_aggregate_state_sources" / source_table
        if cache_dir.exists() and any(cache_dir.iterdir()):
            return cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

        # Find the TBL fixture for the table at the active scale factor.
        # benchbox/datagen writes them to `<run_root>/datagen/tpch_<sf-label>/<table>.tbl`
        # with optional numeric shards and compression suffixes.
        # We probe upward from output_dir to locate that fixture root.
        from benchbox.utils.scale_factor import format_scale_factor

        scale = float(getattr(self, "scale_factor", 0.01) or 0.01)
        scale_label = f"tpch_{format_scale_factor(scale)}"
        candidate_roots = [
            output_dir.parent / "datagen" / scale_label,
            output_dir / "datagen" / scale_label,
            Path.cwd() / "benchmark_runs" / "datagen" / scale_label,
        ]
        tbl_files = self._find_aggregate_tbl_sources(source_table, candidate_roots)
        if not tbl_files:
            raise RuntimeError(
                f"Could not locate {source_table}.tbl fixture for scale {scale} "
                f"under any of {[str(r) for r in candidate_roots]}"
            )

        # Read the TBL via DuckDB (handles zst), write a Parquet file Spark
        # can consume via spark.read.parquet(<dir>) since Spark accepts both
        # single-file and directory paths.
        import duckdb

        from benchbox.platforms.base.data_loading import escape_sql_string_literal

        column_specs = self._tbl_column_specs(source_table)
        column_list = ", ".join(f"'{name}': '{type_}'" for name, type_ in column_specs)
        escaped_paths = [escape_sql_string_literal(str(path)) for path in tbl_files]
        path_list = "[" + ", ".join(f"'{path}'" for path in escaped_paths) + "]"
        target_file = cache_dir / "data.parquet"
        conn = duckdb.connect()
        try:
            conn.execute(
                f"COPY (SELECT * FROM read_csv({path_list}, delim='|', "
                f"columns={{{column_list}}}, header=false)) "
                f"TO '{target_file}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            conn.close()

        return cache_dir

    @staticmethod
    def _find_aggregate_tbl_sources(source_table: str, candidate_roots: list[Path]) -> list[Path]:
        """Find actual TPC fixture files for aggregate-state parquet conversion."""
        patterns = (
            f"{source_table}.tbl",
            f"{source_table}.tbl.[0-9]*",
            f"{source_table}.tbl.gz",
            f"{source_table}.tbl.[0-9]*.gz",
            f"{source_table}.tbl.zst",
            f"{source_table}.tbl.[0-9]*.zst",
        )
        for root in candidate_roots:
            if not root.exists():
                continue
            files = sorted({path for pattern in patterns for path in root.glob(pattern) if path.is_file()})
            if files:
                return files
        return []

    @staticmethod
    def _tbl_column_specs(source_table: str) -> list[tuple[str, str]]:
        """Column specs for the TBL fixtures the aggregate-state ops read.

        Today only `lineitem` is a documented source; extend as new
        aggregate-state ops land for other tables.
        """
        if source_table == "lineitem":
            return [
                ("l_orderkey", "BIGINT"),
                ("l_partkey", "BIGINT"),
                ("l_suppkey", "BIGINT"),
                ("l_linenumber", "INTEGER"),
                ("l_quantity", "DOUBLE"),
                ("l_extendedprice", "DOUBLE"),
                ("l_discount", "DOUBLE"),
                ("l_tax", "DOUBLE"),
                ("l_returnflag", "VARCHAR"),
                ("l_linestatus", "VARCHAR"),
                ("l_shipdate", "DATE"),
                ("l_commitdate", "DATE"),
                ("l_receiptdate", "DATE"),
                ("l_shipinstruct", "VARCHAR"),
                ("l_shipmode", "VARCHAR"),
                ("l_comment", "VARCHAR"),
            ]
        raise NotImplementedError(
            f"Aggregate-state source table '{source_table}' has no TBL column spec; "
            f"add one to WritePrimitivesBenchmark._tbl_column_specs."
        )

    @staticmethod
    def _validate_aggregate_value(op: Any, value: float) -> tuple[bool, str | None]:
        """Apply the first validation_query's expected_value_min/max bounds."""
        if not op.validation_queries:
            return True, None
        vq = op.validation_queries[0]
        lo = vq.expected_value_min
        hi = vq.expected_value_max
        if lo is None or hi is None:
            return True, None
        if value < float(lo) or value > float(hi):
            return False, (
                f"Aggregate scalar {value:.4f} outside bounds [{lo}, {hi}] for op '{op.id}' validation '{vq.id}'"
            )
        return True, None

    def _select_dataframe_operation_ids(self, query_filter: set[str] | None = None) -> list[str]:
        """Select operation IDs honoring DataFrame query filters."""
        operation_ids = list(self.operations_manager.get_all_operations().keys())
        if not query_filter:
            return operation_ids

        normalized_filter = {str(query_id).strip().upper() for query_id in query_filter}
        return [
            op_id
            for op_id in operation_ids
            if op_id.upper() in normalized_filter or f"Q{op_id}".upper() in normalized_filter
        ]


__all__ = ["WritePrimitivesBenchmark", "OperationResult"]
