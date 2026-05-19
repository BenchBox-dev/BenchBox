"""pg_mooncake platform adapter for BenchBox benchmarking.

Extends PostgreSQL adapter with pg_mooncake-specific functionality:
- Mooncake table access method (USING mooncake) with Parquet/Iceberg storage
- DuckDB-powered vectorized execution on columnar data
- Object storage backend support (S3/GCS/Azure)

pg_mooncake is a PostgreSQL extension that adds native columnstore tables
with DuckDB-powered vectorized execution. Data is stored in Parquet format
with Iceberg metadata, providing 5-20x columnar compression and top-10
ClickBench performance.

Deployment modes:
- self-hosted: Self-hosted PostgreSQL with pg_mooncake extension (default)

Storage modes:
- local: Data stored on local disk (default)
- s3: Data stored in S3 bucket

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

from .postgresql import POSTGRES_DIALECT, PostgreSQLAdapter

if TYPE_CHECKING:
    from benchbox.core.platform_registry import PlatformInfo
    from benchbox.core.schemas import DatabaseConfig

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg import sql as psycopg_sql
except ImportError:
    psycopg = None
    psycopg_sql = None  # type: ignore[assignment]


class PgMooncakeAdapter(PostgreSQLAdapter):
    """pg_mooncake platform adapter with columnstore tables and DuckDB execution.

    Extends PostgreSQLAdapter with pg_mooncake-specific features:
    - Mooncake table access method (USING mooncake)
    - DuckDB-powered vectorized execution on Parquet data
    - Object storage backend configuration (S3/GCS)

    Requires PostgreSQL 15+ with pg_mooncake extension installed.
    """

    @property
    def platform_name(self) -> str:
        return "pg_mooncake"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for pg_mooncake (PostgreSQL-compatible)."""
        return POSTGRES_DIALECT

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PgMooncakeAdapter:
        """Create pg_mooncake adapter from unified configuration."""
        adapter_config = {}

        # Connection parameters (inherited from PostgreSQL)
        adapter_config["host"] = config.get("host", "localhost")
        adapter_config["port"] = config.get("port", 5432)
        adapter_config["username"] = config.get("username", "postgres")
        adapter_config["password"] = config.get("password")
        adapter_config["schema"] = config.get("schema", "public")
        adapter_config["sslmode"] = config.get("sslmode", "prefer")

        # Database name - use provided or generate from benchmark config
        if config.get("database"):
            adapter_config["database"] = config["database"]
        elif config.get("benchmark") and config.get("scale_factor") is not None:
            from benchbox.utils.scale_factor import format_benchmark_name

            benchmark_name = format_benchmark_name(config["benchmark"], config["scale_factor"])
            adapter_config["database"] = f"benchbox_{benchmark_name}".lower().replace("-", "_")
        else:
            adapter_config["database"] = "benchbox"

        # Admin database for CREATE/DROP DATABASE operations
        adapter_config["admin_database"] = config.get("admin_database", "postgres")

        # Performance settings (inherited from PostgreSQL)
        adapter_config["work_mem"] = config.get("work_mem", "256MB")
        adapter_config["maintenance_work_mem"] = config.get("maintenance_work_mem", "512MB")
        adapter_config["effective_cache_size"] = config.get("effective_cache_size", "1GB")
        adapter_config["max_parallel_workers_per_gather"] = config.get("max_parallel_workers_per_gather", 2)

        # Connection pool settings
        adapter_config["connect_timeout"] = config.get("connect_timeout", 10)
        adapter_config["statement_timeout"] = config.get("statement_timeout", 0)

        # pg_mooncake-specific settings
        adapter_config["storage_mode"] = config.get("storage_mode", "local")
        adapter_config["mooncake_bucket"] = config.get("mooncake_bucket")

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Pass through other config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)

        # pg_mooncake-specific configuration
        self.storage_mode = config.get("storage_mode", "local")

        # Validate storage mode
        valid_storage_modes = {"local", "s3"}
        if self.storage_mode not in valid_storage_modes:
            raise ValueError(
                f"Invalid pg_mooncake storage mode '{self.storage_mode}'. "
                f"Valid modes: {', '.join(sorted(valid_storage_modes))}"
            )

        # Object storage settings
        self.mooncake_bucket = config.get("mooncake_bucket") or os.environ.get("MOONCAKE_S3_BUCKET")

        if self.storage_mode == "s3" and not self.mooncake_bucket:
            raise ValueError(
                "S3 storage mode requires bucket configuration.\n"
                "Provide via --platform-option mooncake_bucket=s3://bucket/path or "
                "set MOONCAKE_S3_BUCKET environment variable."
            )

    def create_connection(self, **connection_config) -> Any:
        """Create PostgreSQL connection and configure pg_mooncake extension."""
        conn = super().create_connection(**connection_config)

        cursor = conn.cursor()
        try:
            # Verify pg_mooncake extension is installed
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_mooncake'")
            result = cursor.fetchone()
            if result:
                self.logger.info(f"pg_mooncake extension version: {result[0]}")
            else:
                # Try to create the extension
                self.logger.info("pg_mooncake extension not found, attempting to create...")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_mooncake CASCADE")
                conn.commit()
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_mooncake'")
                result = cursor.fetchone()
                if result:
                    self.logger.info(f"Created pg_mooncake extension version: {result[0]}")
                else:
                    raise RuntimeError(
                        "pg_mooncake extension is not available on this PostgreSQL server. "
                        "Install pg_mooncake (https://github.com/Mooncake-Labs/pg_mooncake) or use "
                        "the 'postgresql' or 'duckdb' platform instead."
                    )

            # Configure object storage if in S3 mode
            if self.storage_mode == "s3" and self.mooncake_bucket:
                cursor.execute(
                    psycopg_sql.SQL("SET mooncake.default_bucket = {}").format(
                        psycopg_sql.Literal(self.mooncake_bucket)
                    )
                )
                self.logger.info(f"Set mooncake.default_bucket = {self.mooncake_bucket}")

            conn.commit()

        except RuntimeError:
            cursor.close()
            raise
        except Exception as e:
            self.logger.error(f"Failed to configure pg_mooncake extension: {e}")
            cursor.close()
            raise RuntimeError(f"pg_mooncake configuration failed: {e}") from e
        finally:
            if not cursor.closed:
                cursor.close()

        return conn

    def _transform_create_statement(self, stmt: str) -> str:
        """Leave CREATE TABLE statements as heap tables for bulk loading.

        pg_mooncake 0.2.0 does not support PostgreSQL COPY directly into
        mooncake access-method tables. BenchBox first loads ordinary heap
        tables through the PostgreSQL parent path, then promotes each loaded
        table into a mooncake mirror with the original benchmark table name.
        """
        return stmt

    def _add_columnstore_access_method(self, ddl_statement: str) -> str:
        """Add USING mooncake to CREATE TABLE statements.

        Transforms:
            CREATE TABLE foo (col1 INT, col2 TEXT);
        Into:
            CREATE TABLE foo (col1 INT, col2 TEXT) USING mooncake;

        Only modifies CREATE TABLE statements. Other DDL (CREATE INDEX,
        ALTER TABLE, etc.) is passed through unchanged.

        Note: This parser assumes DDL from BenchBox's schema generators, which
        produce clean single-statement DDL without embedded comments or extra
        semicolons. It does not handle arbitrary user-authored SQL.
        """
        stripped = ddl_statement.strip()
        upper = stripped.upper()

        # Only modify CREATE TABLE statements
        if not upper.startswith("CREATE TABLE"):
            return ddl_statement

        # Don't double-add if already has the pg_mooncake access method.
        if "USING MOONCAKE" in upper:
            return ddl_statement

        if stripped.endswith(";"):
            return stripped[:-1] + " USING mooncake;"
        return stripped + " USING mooncake"

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: str | os.PathLike,
    ) -> tuple[dict[str, int], float, None]:
        """Load through PostgreSQL heap tables, then create mooncake mirrors."""
        table_stats, loading_time, extra = super().load_data(benchmark, connection, data_dir)
        loaded_tables = [table for table, rows in table_stats.items() if rows > 0]
        if loaded_tables:
            table_stats = self._promote_loaded_tables_to_mooncake(connection, loaded_tables, table_stats)
        return table_stats, loading_time, extra

    def _promote_loaded_tables_to_mooncake(
        self,
        connection: Any,
        table_names: list[str],
        table_stats: dict[str, int],
    ) -> dict[str, int]:
        """Rename loaded heap tables and expose mooncake mirrors under original names."""
        if not self._validate_identifier(self.schema):
            raise ValueError(f"Invalid pg_mooncake schema identifier: {self.schema}")

        cursor = connection.cursor()
        updated_stats = dict(table_stats)
        try:
            for table_name in table_names:
                table_name_lower = table_name.lower()
                if not self._validate_identifier(table_name_lower):
                    self.logger.warning(f"Skipping mooncake mirror for invalid table identifier: {table_name}")
                    continue

                staging_table = self._mooncake_staging_table_name(table_name_lower)
                qualified_table = self._qualified_identifier(table_name_lower)
                source_name = self._mooncake_table_reference(staging_table)
                target_name = self._mooncake_table_reference(table_name_lower)

                cursor.execute(f'ALTER TABLE {qualified_table} RENAME TO "{staging_table}"')
                cursor.execute("CALL mooncake.create_table(%s, %s)", (target_name, source_name))
                cursor.execute(f"SELECT COUNT(*) FROM {qualified_table}")
                updated_stats[table_name_lower] = cursor.fetchone()[0]

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
        return updated_stats

    def _mooncake_staging_table_name(self, table_name: str) -> str:
        """Return a PostgreSQL-safe staging table name for a loaded heap table."""
        suffix_budget = 63 - len("__bb_moon_src_")
        return f"__bb_moon_src_{table_name[:suffix_budget]}"

    def _qualified_identifier(self, table_name: str) -> str:
        if self.schema != "public":
            return f'"{self.schema}"."{table_name}"'
        return f'"{table_name}"'

    def _mooncake_table_reference(self, table_name: str) -> str:
        if self.schema != "public":
            return f"{self.schema}.{table_name}"
        return table_name

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
        """Execute one benchmark query outside lingering pg_mooncake transactions.

        pg_mooncake routes mirror-table scans through DuckDB and can reject a
        later scan with "DuckDB execution is not supported inside functions"
        when the previous DB-API SELECT left a transaction open. Close the
        transaction boundary around each benchmark query and retry that
        pg_mooncake-specific transient error once after rollback.
        """
        self._close_mooncake_query_transaction(connection, action="commit", phase="before query")
        result = super().execute_query(
            connection,
            query,
            query_id,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )
        if self._is_duckdb_inside_function_error(result):
            self._close_mooncake_query_transaction(connection, action="rollback", phase="after DuckDB function error")
            self.log_verbose(f"Retrying pg_mooncake query {query_id} after closing transaction")
            result = super().execute_query(
                connection,
                query,
                query_id,
                benchmark_type=benchmark_type,
                scale_factor=scale_factor,
                validate_row_count=validate_row_count,
                stream_id=stream_id,
            )

        self._close_mooncake_query_transaction(connection, action="commit", phase="after query")
        return result

    def _close_mooncake_query_transaction(self, connection: Any, *, action: str, phase: str) -> None:
        closer = getattr(connection, action, None)
        if not callable(closer):
            return
        try:
            closer()
        except Exception as exc:
            self.logger.debug("Failed to %s pg_mooncake transaction %s: %s", action, phase, exc)

    def _is_duckdb_inside_function_error(self, result: dict[str, Any]) -> bool:
        if result.get("status") != "FAILED":
            return False
        return "DuckDB execution is not supported inside functions" in str(result.get("error", ""))

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Return tables and end the catalog transaction before mooncake reads.

        pg_mooncake 0.2.0 routes user-table reads through DuckDB. After a
        PostgreSQL catalog query, the next mooncake table scan can fail with
        "DuckDB execution is not supported inside functions" until the current
        transaction is closed. Keep this workaround local to pg_mooncake.
        """
        cursor = connection.cursor()
        should_commit = False
        try:
            cursor.execute(
                """
                SELECT c.relname
                FROM pg_catalog.pg_class c
                JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                WHERE c.relkind = 'r'
                  AND n.nspname = %s
                ORDER BY c.relname
                """,
                (self.schema,),
            )
            tables = [row[0].lower() for row in cursor.fetchall()]
            should_commit = True
            return tables
        except Exception as e:
            self.logger.warning(f"Failed to get pg_mooncake tables: {e}")
            connection.rollback()
            return []
        finally:
            cursor.close()
            if should_commit:
                try:
                    connection.commit()
                except Exception as e:
                    self.logger.debug(f"Failed to close pg_mooncake catalog transaction: {e}")

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get pg_mooncake platform information."""
        platform_info = super().get_platform_info(connection)

        # Override platform type and name
        platform_info["platform_type"] = "pg_mooncake"
        platform_info["platform_name"] = "pg_mooncake"

        # Add pg_mooncake-specific configuration
        platform_info["configuration"]["storage_mode"] = self.storage_mode
        if self.mooncake_bucket:
            platform_info["configuration"]["mooncake_bucket"] = self.mooncake_bucket

        if connection:
            try:
                cursor = connection.cursor()

                # Get pg_mooncake version
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_mooncake'")
                result = cursor.fetchone()
                if result:
                    platform_info["pg_mooncake_version"] = result[0]

                cursor.close()
            except Exception as e:
                self.logger.debug(f"Error getting pg_mooncake info: {e}")

        return platform_info

    def run_migration_phase(
        self,
        connection: Any,
        table_names: list[str] | None = None,
    ) -> Any:
        """Migrate PostgreSQL heap tables to pg_mooncake columnstore format.

        Executes ALTER TABLE ... SET ACCESS METHOD columnar for each table,
        recording wall time and storage delta. Returns a MigrationPhase result
        capturing per-table stats and totals, or None if no tables are given.

        This method is safe to call on tables already in columnstore format;
        ALTER TABLE is a no-op in that case (measured but harmless).

        Args:
            connection: Active psycopg connection to the benchmark database.
            table_names: Tables to migrate. When None, discovers all heap tables
                in the adapter's schema from pg_catalog automatically.

        Returns:
            MigrationPhase instance, or None if table_names resolves to empty.
        """
        from benchbox.core.results.models import MigrationPhase, MigrationTableStats

        cursor = connection.cursor()
        try:
            # Discover heap tables when not provided explicitly
            if table_names is None:
                cursor.execute(
                    """
                    SELECT c.relname
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.relkind = 'r'
                      AND n.nspname = %s
                      AND c.relam = (SELECT oid FROM pg_catalog.pg_am WHERE amname = 'heap')
                    ORDER BY c.relname
                    """,
                    (self.schema,),
                )
                table_names = [row[0] for row in cursor.fetchall()]

            if not table_names:
                return None

            def _get_storage_bytes(table: str) -> int:
                # pg_total_relation_size() accepts a regclass text argument;
                # build the qualified name with Identifier quoting, then cast.
                qualified = psycopg_sql.SQL("{}.{}").format(
                    psycopg_sql.Identifier(self.schema),
                    psycopg_sql.Identifier(table),
                )
                cursor.execute(
                    psycopg_sql.SQL("SELECT pg_catalog.pg_total_relation_size({}::regclass)").format(qualified),
                )
                row = cursor.fetchone()
                return int(row[0]) if row and row[0] is not None else 0

            per_table: dict[str, MigrationTableStats] = {}
            phase_start = time.monotonic()
            tables_migrated = 0
            tables_failed = 0
            total_before = 0
            total_after = 0

            for table in table_names:
                before_bytes = _get_storage_bytes(table)
                total_before += before_bytes
                t0 = time.monotonic()
                try:
                    cursor.execute(
                        psycopg_sql.SQL("ALTER TABLE {}.{} SET ACCESS METHOD columnar").format(
                            psycopg_sql.Identifier(self.schema),
                            psycopg_sql.Identifier(table),
                        )
                    )
                    connection.commit()
                    elapsed_ms = round((time.monotonic() - t0) * 1000)
                    after_bytes = _get_storage_bytes(table)
                    total_after += after_bytes
                    per_table[table] = MigrationTableStats(
                        duration_ms=elapsed_ms,
                        status="completed",
                        storage_before_bytes=before_bytes,
                        storage_after_bytes=after_bytes,
                        storage_delta_bytes=after_bytes - before_bytes,
                    )
                    tables_migrated += 1
                    self.logger.info(f"Migrated {table}: {before_bytes} -> {after_bytes} bytes ({elapsed_ms} ms)")
                except Exception as exc:
                    connection.rollback()
                    elapsed_ms = round((time.monotonic() - t0) * 1000)
                    per_table[table] = MigrationTableStats(
                        duration_ms=elapsed_ms,
                        status="failed",
                        storage_before_bytes=before_bytes,
                        storage_after_bytes=before_bytes,
                        storage_delta_bytes=0,
                        error_message=str(exc),
                    )
                    tables_failed += 1
                    self.logger.warning(f"Migration failed for {table}: {exc}")

            phase_ms = round((time.monotonic() - phase_start) * 1000)
            status = "completed" if tables_failed == 0 else "partial" if tables_migrated > 0 else "failed"

            return MigrationPhase(
                duration_ms=phase_ms,
                status=status,
                tables_migrated=tables_migrated,
                tables_failed=tables_failed,
                storage_before_bytes=total_before,
                storage_after_bytes=total_after,
                storage_delta_bytes=total_after - total_before,
                per_table_stats=per_table,
            )
        finally:
            cursor.close()

    def supports_tuning_type(self, tuning_type: Any) -> bool:
        """Check if pg_mooncake supports a specific tuning type.

        pg_mooncake columnstore tables have different tuning characteristics
        than PostgreSQL heap tables:
        - No B-tree indexes on columnstore tables
        - No CLUSTER support (Parquet-based storage)
        - Partitioning handled at the Iceberg/Parquet level
        """
        try:
            from benchbox.core.tuning.interface import TuningType

            supported = {
                TuningType.PARTITIONING: False,  # Columnstore handles its own partitioning
                TuningType.SORTING: False,  # No native sort keys on columnstore
                TuningType.DISTRIBUTION: False,  # Not distributed
                TuningType.CLUSTERING: False,  # No CLUSTER on columnstore tables
                TuningType.PRIMARY_KEYS: False,  # Columnstore tables don't support constraints
                TuningType.FOREIGN_KEYS: False,  # Columnstore tables don't support constraints
            }
            return supported.get(tuning_type, False)
        except ImportError:
            return False


def _build_pg_mooncake_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: PlatformInfo | None,
) -> DatabaseConfig:
    """Build pg_mooncake database configuration with credential loading.

    This function is registered with PlatformHookRegistry to provide
    pg_mooncake-specific configuration handling.
    """
    from benchbox.platforms.base.config_utils import POSTGRES_FAMILY_BASE_OPTIONS, build_platform_config

    return build_platform_config(
        platform_type="pg-mooncake",
        credential_key="pg-mooncake",
        default_display_name="pg_mooncake",
        default_driver_package="psycopg",
        base_options={
            **POSTGRES_FAMILY_BASE_OPTIONS,
            "storage_mode": "local",
        },
        platform_fields=[
            "host",
            "port",
            "username",
            "password",
            "database",
            "admin_database",
            "sslmode",
            "work_mem",
            "maintenance_work_mem",
            "effective_cache_size",
            "max_parallel_workers_per_gather",
            "storage_mode",
            "mooncake_bucket",
        ],
        options=options,
        overrides=overrides,
        info=info,
    )
