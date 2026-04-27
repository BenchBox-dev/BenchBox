"""Workload execution helpers for ClickHouse."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.cloud_storage import get_cloud_path_info, is_cloud_path
from benchbox.utils.printing import emit

from .query_transformer import ClickHouseQueryTransformer

logger = logging.getLogger(__name__)


class ClickHouseWorkloadMixin:
    """Provide schema management and workload execution utilities."""

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using ClickHouse-optimized table definitions."""
        start_time = mono_time()

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)

        try:
            # Get schema SQL directly from benchmark to avoid sqlglot translation issues
            effective_config = self.get_effective_tuning_configuration()
            schema_sql = benchmark.get_create_tables_sql(
                dialect="duckdb",  # Use duckdb as it's compatible with ClickHouse for schema
                tuning_config=effective_config,
            )

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                # Optimize table definitions for ClickHouse
                statement = self._optimize_table_definition(statement)
                connection.execute(statement)
                self.logger.debug(f"Executed schema statement: {statement[:100]}...")

            self.logger.info(f"Schema created (PKs: {enable_primary_keys}, FKs: {enable_foreign_keys})")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for ClickHouse."""
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Transform SQL for ClickHouse compatibility
        # ClickHouse doesn't like "NOT NULL" on already non-nullable types
        # Replace "Nullable(Type) NOT NULL" patterns
        import re

        # [^)]+  would stop at the first ) inside Nullable(Decimal(38, 0)) NOT NULL;
        # use an alternation that allows one level of nested parens.
        statement = re.sub(
            r"Nullable\((?:[^()]+|\([^)]*\))+\)\s+NOT\s+NULL",
            lambda m: m.group(0).replace(" NOT NULL", ""),
            statement,
            flags=re.IGNORECASE,
        )

        # Include ClickHouse MergeTree engine and ORDER BY clause if not present
        statement_upper = statement.upper()

        # Include ENGINE if not present
        if "ENGINE" not in statement_upper:
            if statement.endswith(";"):
                statement = statement[:-1] + " ENGINE = MergeTree();"
            else:
                statement = statement + " ENGINE = MergeTree()"

        # Include ORDER BY if not present
        statement_upper = statement.upper()
        if "ORDER BY" not in statement_upper:
            # Extract primary key columns if any exist in the statement
            pk_columns = self._extract_primary_key_columns(statement)
            if pk_columns:
                # Use primary key columns for ORDER BY to satisfy ClickHouse requirement
                order_by_clause = f" ORDER BY ({', '.join(pk_columns)})"
            else:
                # Use tuple() for tables without primary keys
                order_by_clause = " ORDER BY tuple()"

            if statement.endswith(";"):
                statement = statement[:-1] + order_by_clause + ";"
            else:
                statement = statement + order_by_clause

        return statement

    def _extract_primary_key_columns(self, statement: str) -> list[str]:
        """Extract primary key column names from a CREATE TABLE statement.

        Args:
            statement: CREATE TABLE SQL statement

        Returns:
            List of primary key column names
        """
        import re

        # Look for PRIMARY KEY constraints in different formats
        pk_columns = []

        # Pattern 1: column_name TYPE PRIMARY KEY
        # (?:\((?:[^()]+|\([^)]*\))*\))? handles one level of nesting e.g. Nullable(Decimal(10,2))
        inline_pk_pattern = r"(\w+)\s+\w+(?:\((?:[^()]+|\([^)]*\))*\))?\s+PRIMARY\s+KEY"
        inline_matches = re.findall(inline_pk_pattern, statement, re.IGNORECASE)
        pk_columns.extend(inline_matches)

        # Pattern 2: PRIMARY KEY (col1, col2, ...)
        composite_pk_pattern = r"PRIMARY\s+KEY\s*\(\s*([^)]+)\s*\)"
        composite_matches = re.findall(composite_pk_pattern, statement, re.IGNORECASE)
        for match in composite_matches:
            # Split by comma and clean up column names
            cols = [col.strip() for col in match.split(",")]
            pk_columns.extend(cols)

        return pk_columns

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using ClickHouse's optimized CSV import capabilities."""
        from benchbox.platforms.base.data_loading import DataLoader

        # Check if using cloud storage and log
        if is_cloud_path(str(data_dir)):
            path_info = get_cloud_path_info(str(data_dir))
            self.log_verbose(f"Loading data from cloud storage: {path_info['provider']} bucket '{path_info['bucket']}'")
            emit(f"  Loading data from {path_info['provider']} cloud storage")

        # Create ClickHouse-specific handler factory
        def clickhouse_handler_factory(file_path, adapter, benchmark_instance, table_name=None, data_source=None):
            from benchbox.platforms.base.data_loading import (
                ClickHouseNativeHandler,
                DataSource,
                FileFormatRegistry,
                resolve_csv_dialect,
            )

            # Determine the true base extension (handles names like *.tbl.1.zst)
            base_ext = FileFormatRegistry.get_base_data_extension(file_path)

            # Create ClickHouse native handler for supported formats
            if base_ext in (".tbl", ".dat", ".csv"):
                dialect_source = data_source or DataSource(source_type="clickhouse_handler", tables={})
                dialect = resolve_csv_dialect(
                    dialect_source, table_name or file_path.stem, file_path, benchmark_instance
                )
                return ClickHouseNativeHandler(dialect.delimiter, adapter, benchmark_instance)
            elif base_ext == ".parquet":
                # Delimiter is unused for Parquet - file() reads the format natively.
                # We route through ClickHouseNativeHandler so load_table() uses
                # INSERT INTO ... SELECT * FROM file(path, 'Parquet') instead of
                # falling back to the generic row-by-row ParquetHandler.
                return ClickHouseNativeHandler(",", adapter, benchmark_instance)
            return None  # Fall back to generic handler

        loader = DataLoader(
            adapter=self,
            benchmark=benchmark,
            connection=connection,
            data_dir=data_dir,
            handler_factory=clickhouse_handler_factory,
            tuning_config=self.unified_tuning_configuration if self.tuning_enabled else None,
        )
        table_stats, loading_time = loader.load()
        # DataLoader doesn't provide per-table timings yet
        return table_stats, loading_time, None

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in the ClickHouse database.

        Override the base class implementation with ClickHouse-specific query.

        Args:
            connection: ClickHouse connection (server or local)

        Returns:
            List of table names (lowercase for consistency)
        """
        try:
            if self.deployment_mode == "local":
                # For local mode (chdb), use SHOW TABLES
                result = connection.execute("SHOW TABLES")
                if result:
                    # Handle different result formats from chdb
                    tables = []
                    for row in result:
                        if isinstance(row, (list, tuple)):
                            tables.append(str(row[0]).lower())
                        else:
                            tables.append(str(row).lower())
                    return tables
                return []
            else:
                # For server mode, use system.tables query
                result = connection.execute("SELECT name FROM system.tables WHERE database = currentDatabase()")
                return [row[0].lower() for row in result] if result else []
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    def get_table_row_count(self, connection: Any, table: str) -> int:
        """Get row count using ClickHouse execute() API.

        Overrides base implementation that uses cursor() - ClickHouseLocalClient
        and ClickHouseCloudClient expose execute() but not cursor().

        Args:
            connection: ClickHouse connection (local, server, or cloud)
            table: Table name

        Returns:
            Row count as integer, or 0 if unable to determine
        """
        try:
            result = connection.execute(f"SELECT COUNT(*) FROM {table}")
            if result:
                row = result[0]
                return int(row[0])
            return 0
        except Exception as e:
            self.logger.debug(f"Failed to get row count for {table}: {e}")
            return 0

    def _get_constraint_configuration(self) -> tuple[bool, bool]:
        """Extract constraint configuration settings from tuning config.

        Override base implementation to ensure ClickHouse always has primary keys enabled,
        since ClickHouse MergeTree engine requires ORDER BY (derived from PRIMARY KEY).

        Returns:
            Tuple of (enable_primary_keys, enable_foreign_keys)
        """
        effective_config = self.get_effective_tuning_configuration()

        # ClickHouse always needs primary keys for MergeTree engine, even in no-tuning mode
        enable_primary_keys = True

        # Foreign keys follow normal tuning configuration
        enable_foreign_keys = effective_config.foreign_keys.enabled if effective_config else False

        return enable_primary_keys, enable_foreign_keys

    def _validate_data_integrity(
        self,
        benchmark: Any,
        connection: Any,
        table_stats: dict[str, int],
    ) -> tuple[str, dict[str, Any]]:
        """Validate data integrity and table accessibility for ClickHouse.

        Override base implementation to use execute() instead of cursor()
        which is not available in ClickHouseLocalClient.

        Args:
            benchmark: Benchmark instance
            connection: ClickHouse connection (server or local)
            table_stats: Dictionary of table names to row counts

        Returns:
            Tuple of (status, details) where status is "PASSED" or "FAILED"
        """
        validation_details: dict[str, Any] = {}

        try:
            execute_fn = getattr(connection, "execute", None)
            if not callable(execute_fn):
                raise TypeError("ClickHouse connection must expose an execute() method")

            accessible_tables = []
            inaccessible_tables = []

            for table_name in table_stats:
                try:
                    # ClickHouseLocalClient and ClickHouse server clients both expose execute().
                    execute_fn(f"SELECT 1 FROM {table_name} LIMIT 1")
                    accessible_tables.append(table_name)
                except Exception as e:
                    self.logger.debug(f"Table {table_name} inaccessible: {e}")
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            else:
                validation_details["accessible_tables"] = accessible_tables
                validation_details["constraints_enabled"] = True
                return "PASSED", validation_details

        except Exception as e:
            validation_details["constraints_enabled"] = False
            validation_details["integrity_error"] = str(e)
            return "FAILED", validation_details

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query with detailed timing and profiling."""
        start_time = mono_time()

        try:
            # Apply ClickHouse-specific query transformations for SQL compatibility
            transformer = ClickHouseQueryTransformer(verbose=self.very_verbose)
            transformed_query = transformer.transform(query)
            # Session settings stay generic; analyzer-sensitive query rewrites live in the benchmark.
            transformed_query = transformer.add_query_settings(transformed_query)

            # Log transformations if any were applied
            if transformer.get_transformations_applied() and self.verbose_enabled:
                self.log_verbose(
                    f"Query {query_id}: Applied transformations: {', '.join(transformer.get_transformations_applied())}"
                )

            # Execute the transformed query
            result = connection.execute(transformed_query)

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

            # Validate row count if enabled and benchmark type is provided
            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                # Log validation result
                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

                # If validation failed, mark query as failed
                if not validation_result.is_valid:
                    return {
                        "query_id": query_id,
                        "status": "FAILED",
                        "execution_time_seconds": execution_time,
                        "rows_returned": actual_row_count,
                        "row_count_validation": {
                            "expected": validation_result.expected_row_count,
                            "actual": actual_row_count,
                            "status": "FAILED",
                            "error": validation_result.error_message,
                        },
                        "error": validation_result.error_message,
                        "first_row": result[0] if result else None,
                        "translated_query": None,
                    }

            # Build successful result
            result_dict = {
                "query_id": query_id,
                "status": "SUCCESS",
                "execution_time_seconds": execution_time,
                "rows_returned": actual_row_count,
                "first_row": result[0] if result else None,
                "translated_query": None,  # Translation handled by base adapter
            }

            # Include validation metadata if validation was performed
            if validation_result:
                row_count_validation = {
                    "expected": validation_result.expected_row_count,
                    "actual": actual_row_count,
                    "status": "PASSED" if validation_result.is_valid else "SKIPPED",
                }
                if validation_result.warning_message:
                    row_count_validation["warning"] = validation_result.warning_message
                result_dict["row_count_validation"] = row_count_validation

            return result_dict

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            error_type = type(e).__name__
            # Always populate `error` with a non-empty string - some exceptions
            # (e.g. chdb errors raised with no message) yield empty str(e).
            error_message = str(e) or repr(e) or error_type

            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": error_message,
                "error_type": error_type,
            }


__all__ = ["ClickHouseWorkloadMixin"]
