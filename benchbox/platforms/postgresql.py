"""PostgreSQL platform adapter for BenchBox benchmarking.

Provides PostgreSQL-specific functionality including:
- COPY command for efficient bulk data loading
- EXPLAIN/EXPLAIN ANALYZE for query plan capture
- Support for TimescaleDB extensions (optional)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
        TableTuning,
        TuningColumn,
        UnifiedTuningConfiguration,
    )

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from ..utils.file_format import get_data_extension
from .base import DriverIsolationCapability, PlatformAdapter, PsycopgConnectionMixin
from .base.data_loading import (
    CsvDialect,
    DataSourceResolver,
    normalize_table_paths,
    prepare_local_load_file,
    resolve_csv_dialect,
)

# PostgreSQL dialect for SQLGlot
POSTGRES_DIALECT = "postgres"

try:
    import psycopg
except ImportError:
    psycopg = None


class _PostgresCopySink:
    """File-like sink that lets PyArrow CSVWriter stream into psycopg COPY."""

    closed = False

    def __init__(self, copy: Any) -> None:
        self._copy = copy

    def writable(self) -> bool:
        return True

    def write(self, data: Any) -> int:
        payload = data.to_pybytes() if hasattr(data, "to_pybytes") else data
        self._copy.write(payload)
        return len(payload)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


def _write_parquet_to_copy(data_file: Path, copy: Any) -> None:
    """Stream a Parquet file as CSV directly into PostgreSQL COPY."""
    try:
        import pyarrow.csv as arrow_csv
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - pyarrow is a project dependency
        raise RuntimeError("pyarrow is required to load Parquet files into PostgreSQL-family adapters") from exc

    write_options = arrow_csv.WriteOptions(include_header=True, quoting_style="all_valid")
    parquet_file = pq.ParquetFile(data_file)
    with arrow_csv.CSVWriter(_PostgresCopySink(copy), parquet_file.schema_arrow, write_options=write_options) as writer:
        for batch in parquet_file.iter_batches():
            writer.write_batch(batch)


def _postgres_copy_sql(
    qualified_table: str,
    dialect: CsvDialect,
    *,
    force_csv: bool = False,
) -> str:
    escaped_delim = dialect.delimiter.replace("'", "''")
    if dialect.null_marker is not None and not force_csv:
        escaped_null = dialect.null_marker.replace("'", "''")
        return (
            f"COPY {qualified_table} FROM STDIN WITH (FORMAT text, DELIMITER '{escaped_delim}', NULL '{escaped_null}')"
        )

    header_clause = ", HEADER true" if dialect.has_header else ""
    null_marker = dialect.null_marker if dialect.null_marker is not None else "__BENCHBOX_NO_NULL__"
    escaped_null = null_marker.replace("'", "''")
    return (
        f"COPY {qualified_table} FROM STDIN"
        f" WITH (FORMAT csv, DELIMITER '{escaped_delim}', NULL '{escaped_null}'{header_clause})"
    )


def _add_postgres_compatible_arguments(
    parser: Any,
    *,
    prefix: str,
    platform_label: str,
    include_timescale_toggle: bool = False,
) -> None:
    """Register shared PostgreSQL-compatible CLI arguments.

    These legacy ``--<prefix>-host`` / ``--<prefix>-port`` / … flags are
    registered on the adapter for setup-wizard use (``benchbox platforms setup``).
    The ``benchbox run`` flow does NOT invoke ``add_cli_arguments``; it relies
    on ``register_option_specs`` + ``--platform-option key=value`` exclusively.

    Maintenance note: whenever a field is added or removed from
    ``PlatformHookRegistry.register_option_specs`` for a PG-family platform,
    update this helper and vice-versa so the two registrations stay in sync.
    """
    option_prefix = prefix.strip("-")

    parser.add_argument(
        f"--{option_prefix}-host",
        dest="host",
        default="localhost",
        help=f"{platform_label} server hostname",
    )
    parser.add_argument(
        f"--{option_prefix}-port",
        dest="port",
        type=int,
        default=5432,
        help=f"{platform_label} server port",
    )
    parser.add_argument(
        f"--{option_prefix}-database",
        dest="database",
        help=f"{platform_label} database name (auto-generated if not specified)",
    )
    parser.add_argument(
        f"--{option_prefix}-username",
        dest="username",
        default="postgres",
        help=f"{platform_label} username",
    )
    parser.add_argument(
        f"--{option_prefix}-password",
        dest="password",
        help=f"{platform_label} password",
    )
    parser.add_argument(
        f"--{option_prefix}-schema",
        dest="schema",
        default="public",
        help=f"{platform_label} schema name",
    )
    parser.add_argument(
        f"--{option_prefix}-work-mem",
        dest="work_mem",
        default="256MB",
        help=f"{platform_label} work_mem setting for queries",
    )
    parser.add_argument(
        f"--{option_prefix}-maintenance-work-mem",
        dest="maintenance_work_mem",
        default="512MB",
        help=f"{platform_label} maintenance_work_mem for VACUUM/CREATE INDEX",
    )
    if include_timescale_toggle:
        parser.add_argument(
            f"--{option_prefix}-enable-timescale",
            dest="enable_timescale",
            action="store_true",
            help="Enable TimescaleDB extensions if available",
        )


def _build_postgres_connection_kwargs(config: dict[str, Any], *, default_port: int = 5432) -> dict[str, Any]:
    """Build the common connection kwargs shared by all PG-family from_config methods.

    Extracts host/port/credentials/sslmode, derives the database name from
    benchmark+scale_factor when no explicit database is given, and copies
    through the common GUC and pool settings.  Adapter-specific keys (e.g.
    chunk_interval for TimescaleDB) should be added by the caller after this
    helper returns.

    Args:
        config: Unified config dict passed to from_config.
        default_port: Override default port (e.g. CedarDB uses 5432 by default
            but may differ per deployment; pass ``CEDARDB_DEFAULT_PORT`` here).

    Returns:
        Partial adapter_config dict ready to pass to the adapter constructor.
    """
    from benchbox.utils.scale_factor import format_benchmark_name

    result: dict[str, Any] = {
        "host": config.get("host", "localhost"),
        "port": config.get("port", default_port),
        "username": config.get("username", "postgres"),
        "password": config.get("password"),
        "schema": config.get("schema", "public"),
        "sslmode": config.get("sslmode", "prefer"),
        "admin_database": config.get("admin_database", "postgres"),
        "work_mem": config.get("work_mem", "256MB"),
        "maintenance_work_mem": config.get("maintenance_work_mem", "512MB"),
        "effective_cache_size": config.get("effective_cache_size", "1GB"),
        "max_parallel_workers_per_gather": config.get("max_parallel_workers_per_gather", 2),
        "connect_timeout": config.get("connect_timeout", 10),
        "statement_timeout": config.get("statement_timeout", 0),
        "force_recreate": config.get("force", False),
    }

    if config.get("database"):
        result["database"] = config["database"]
    elif config.get("benchmark") and config.get("scale_factor") is not None:
        benchmark_name = format_benchmark_name(config["benchmark"], config["scale_factor"])
        result["database"] = f"benchbox_{benchmark_name}".lower().replace("-", "_")
    else:
        result["database"] = "benchbox"

    for key in ("tuning_config", "verbose_enabled", "very_verbose"):
        if key in config:
            result[key] = config[key]

    return result


class PostgreSQLAdapter(PsycopgConnectionMixin, PlatformAdapter):
    """PostgreSQL platform adapter with COPY-based data loading.

    Supports PostgreSQL 12+ and optional TimescaleDB extensions.
    Uses psycopg for database connectivity with efficient COPY loading.
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    @property
    def platform_name(self) -> str:
        return "PostgreSQL"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for PostgreSQL."""
        return POSTGRES_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add PostgreSQL-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            _add_postgres_compatible_arguments(
                parser,
                prefix="postgres",
                platform_label="PostgreSQL",
                include_timescale_toggle=True,
            )
        except Exception:
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PostgreSQLAdapter:
        """Create PostgreSQL adapter from unified configuration."""
        adapter_config = _build_postgres_connection_kwargs(config)
        adapter_config["enable_timescale"] = config.get("enable_timescale", False)
        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies
        if psycopg is None:
            available, missing = check_platform_dependencies("postgresql")
            if not available:
                error_msg = get_dependency_error_message("postgresql", missing)
                raise ImportError(error_msg)

        self._dialect = POSTGRES_DIALECT

        # Connection configuration
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 5432)
        self.database = config.get("database", "benchbox")
        self.username = config.get("username", "postgres")
        self.password = config.get("password")
        self.schema = config.get("schema", "public")
        self.sslmode = config.get("sslmode", "prefer")

        # Admin database for metadata operations
        self.admin_database = config.get("admin_database", "postgres")

        # Connection settings
        self.connect_timeout = config.get("connect_timeout", 10)
        self.statement_timeout = config.get("statement_timeout", 0)

        # Performance settings
        self.work_mem = config.get("work_mem", "256MB")
        self.maintenance_work_mem = config.get("maintenance_work_mem", "512MB")
        self.effective_cache_size = config.get("effective_cache_size", "1GB")
        self.max_parallel_workers_per_gather = config.get("max_parallel_workers_per_gather", 2)

        # TimescaleDB support
        self.enable_timescale = config.get("enable_timescale", False)

    def _get_connection_params(self, database: str | None = None) -> dict[str, Any]:
        """Build psycopg connection parameters."""
        params = {
            "host": self.host,
            "port": self.port,
            "dbname": database or self.database,
            "user": self.username,
            "connect_timeout": self.connect_timeout,
            "options": f"-c statement_timeout={self.statement_timeout}" if self.statement_timeout else None,
        }

        if self.password:
            params["password"] = self.password

        if self.sslmode:
            params["sslmode"] = self.sslmode

        # Remove None values
        return {k: v for k, v in params.items() if v is not None}

    def check_server_database_exists(
        self,
        schema: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
        **_: object,
    ) -> bool:
        """Check if a database exists on the PostgreSQL server."""
        db_name = database or self.database

        try:
            # Connect to admin database to check for target database
            params = self._get_connection_params(database=self.admin_database)
            conn = psycopg.connect(**params)
            conn.autocommit = True
            cursor = conn.cursor()

            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (db_name,),
            )
            result = cursor.fetchone()
            cursor.close()
            conn.close()

            return result is not None

        except Exception as e:
            self.logger.debug(f"Failed to check database existence: {e}")
            return False

    def drop_database(
        self,
        schema: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
        **_: object,
    ) -> None:
        """Drop a database from PostgreSQL server."""
        db_name = database or self.database

        if not self._validate_identifier(db_name):
            raise ValueError(f"Invalid database identifier: {db_name}")

        try:
            # Connect to admin database
            params = self._get_connection_params(database=self.admin_database)
            conn = psycopg.connect(**params)
            conn.autocommit = True
            cursor = conn.cursor()

            # Terminate existing connections to the database
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (db_name,),
            )

            # Drop the database
            # Safety: db_name validated by _validate_identifier() above (alphanumeric + underscore only)
            cursor.execute(f'DROP DATABASE IF EXISTS "{db_name}"')

            cursor.close()
            conn.close()
            self.logger.info(f"Dropped database: {db_name}")

        except Exception as e:
            self.logger.warning(f"Failed to drop database {db_name}: {e}")
            raise

    def _create_database(self) -> None:
        """Create the target database if it doesn't exist."""
        if not self._validate_identifier(self.database):
            raise ValueError(f"Invalid database identifier: {self.database}")

        try:
            params = self._get_connection_params(database=self.admin_database)
            conn = psycopg.connect(**params)
            conn.autocommit = True
            cursor = conn.cursor()

            # Create database if not exists
            cursor.execute(
                "SELECT 1 FROM pg_database WHERE datname = %s",
                (self.database,),
            )
            if not cursor.fetchone():
                # Safety: self.database validated by _validate_identifier() above
                cursor.execute(f'CREATE DATABASE "{self.database}"')
                self.logger.info(f"Created database: {self.database}")

            cursor.close()
            conn.close()

        except Exception as e:
            self.logger.error(f"Failed to create database: {e}")
            raise

    def create_connection(self, **connection_config) -> Any:
        """Create PostgreSQL connection."""
        self.log_operation_start("PostgreSQL connection")

        # Handle existing database
        self.handle_existing_database(**connection_config)

        # Create database if needed
        if not self.check_server_database_exists():
            self._create_database()

        # Connect to target database
        params = self._get_connection_params()
        conn = psycopg.connect(**params)

        # Apply session settings
        cursor = conn.cursor()
        settings_applied = []

        guc_statements = [
            (f"SET work_mem = '{self.work_mem}'", f"work_mem={self.work_mem}"),
            (
                f"SET maintenance_work_mem = '{self.maintenance_work_mem}'",
                f"maintenance_work_mem={self.maintenance_work_mem}",
            ),
            (
                f"SET effective_cache_size = '{self.effective_cache_size}'",
                f"effective_cache_size={self.effective_cache_size}",
            ),
            (
                f"SET max_parallel_workers_per_gather = {self.max_parallel_workers_per_gather}",
                f"max_parallel_workers_per_gather={self.max_parallel_workers_per_gather}",
            ),
        ]
        for sql, label in guc_statements:
            try:
                cursor.execute(sql)
                settings_applied.append(label)
            except Exception as e:
                conn.rollback()
                self.logger.debug(f"Could not set {label}: {e}")

        # Create schema if needed
        # Safety: self.schema validated by _validate_identifier() before use in f-string
        if self.schema != "public" and self._validate_identifier(self.schema):
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            cursor.execute(f'SET search_path TO "{self.schema}", public')
            settings_applied.append(f"schema={self.schema}")

        conn.commit()
        cursor.close()

        # Verify connection
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()

        self.log_operation_complete("PostgreSQL connection", details=f"Applied: {', '.join(settings_applied)}")
        return conn

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get schema SQL and translate to PostgreSQL dialect
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        cursor = connection.cursor()

        # Execute each statement separately; on failure rollback and retry without FK constraints
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        for stmt in statements:
            try:
                cursor.execute(self._transform_create_statement(stmt))
            except Exception as e:
                connection.rollback()
                self.logger.warning(f"Schema statement failed: {e}")
                # For CREATE TABLE failures, retry after stripping FOREIGN KEY constraints.
                # Some servers (e.g. CedarDB) reject self-referential FKs at definition time.
                if re.search(r"\bCREATE\s+TABLE\b", stmt, re.IGNORECASE) and "FOREIGN" in stmt.upper():
                    stripped = strip_foreign_keys(stmt)
                    if stripped != stmt:
                        try:
                            cursor.execute(self._transform_create_statement(stripped))
                        except Exception as e2:
                            connection.rollback()
                            self.logger.error(f"Schema statement failed even without FK constraints: {e2}")
                            raise
                    else:
                        raise
                else:
                    raise

        connection.commit()
        cursor.close()

        duration = elapsed_seconds(start_time)
        self.log_operation_complete("Schema creation", duration, "Schema and tables created")
        return duration

    def _transform_create_statement(self, stmt: str) -> str:
        """Transform a CREATE TABLE statement before execution.

        PostgreSQL itself executes the generated DDL unchanged. Subclasses
        with storage-specific DDL variants can override this hook while
        keeping the standard create_schema contract and error handling.
        """
        return stmt

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data using PostgreSQL COPY command for efficiency."""
        start_time = mono_time()
        table_stats = {}

        self.log_operation_start("Data loading", f"source: {data_dir}")
        effective_tuning = self.unified_tuning_configuration if self.tuning_enabled else None

        resolver = DataSourceResolver(
            platform_name=self.platform_name,
            table_mode=self.table_mode,
            platform_config=self.platform_config,
            requested_format=self.requested_table_format,
        )
        data_source = resolver.resolve(benchmark, data_dir)
        if not data_source or not data_source.tables:
            self.logger.warning("No data files found. Ensure benchmark.generate_data() was called first.")
            loading_time = elapsed_seconds(start_time)
            self.log_operation_complete("Data loading", loading_time, "Loaded 0 total rows")
            return {}, loading_time, None

        cursor = connection.cursor()

        for table_name, table_path in data_source.tables.items():
            table_name_lower = table_name.lower()

            if not self._validate_identifier(table_name_lower):
                self.logger.warning(f"Skipping table with invalid identifier: {table_name}")
                table_stats[table_name_lower] = 0
                continue

            data_files = [f for f in normalize_table_paths(table_path) if f.exists()]
            if not data_files:
                self.logger.warning(f"Data file(s) not found for table: {table_name}")
                table_stats[table_name_lower] = 0
                continue

            qualified_table = (
                f'"{self.schema}"."{table_name_lower}"' if self.schema != "public" else f'"{table_name_lower}"'
            )

            load_failed = False
            for data_file in data_files:
                extension = get_data_extension(data_file)
                if extension == ".parquet":
                    dialect = CsvDialect(
                        delimiter=",",
                        has_header=True,
                        null_marker="",
                        normalize_booleans=False,
                        quote='"',
                    )
                    force_csv = True
                else:
                    dialect = resolve_csv_dialect(data_source, table_name, data_file, benchmark)
                    force_csv = extension == ".csv" and dialect.has_header

                try:
                    copy_sql = _postgres_copy_sql(qualified_table, dialect, force_csv=force_csv)
                    with cursor.copy(copy_sql) as copy:
                        if extension == ".parquet":
                            _write_parquet_to_copy(data_file, copy)
                        else:
                            with prepare_local_load_file(
                                data_file,
                                dialect=dialect,
                                strip_trailing_delim=extension == ".tbl",
                            ) as load_path:
                                with open(load_path, encoding="utf-8") as f:
                                    while chunk := f.read(65536):
                                        copy.write(chunk)
                    connection.commit()
                except Exception as e:
                    self.logger.error(f"Failed to load {table_name_lower} chunk {data_file.name}: {e}")
                    connection.rollback()
                    load_failed = True
                    break

            if load_failed:
                table_stats[table_name_lower] = 0
                continue

            try:
                cursor.execute(f"SELECT COUNT(*) FROM {qualified_table}")
                row_count = cursor.fetchone()[0]
                table_stats[table_name_lower] = row_count

                if effective_tuning:
                    self.apply_ctas_sort(table_name_lower, effective_tuning, connection)

                self.log_verbose(f"Loaded {row_count:,} rows into {table_name_lower}")
            except Exception as e:
                self.logger.error(f"Failed to count rows for {table_name_lower}: {e}")
                connection.rollback()
                table_stats[table_name_lower] = 0

        cursor.close()
        loading_time = elapsed_seconds(start_time)

        total_rows = sum(table_stats.values())
        self.log_operation_complete("Data loading", loading_time, f"Loaded {total_rows:,} total rows")

        return table_stats, loading_time, None

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> list[str] | None:
        """PostgreSQL CTAS table-rewrite sorting is intentionally unsupported.

        DROP+CTAS+RENAME would strip indexes, constraints, and other schema metadata.
        PostgreSQL physical ordering should instead be handled via schema/index strategy.
        """
        return None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply PostgreSQL optimizations for benchmark type."""
        cursor = connection.cursor()

        if benchmark_type == "olap":
            # OLAP optimizations
            cursor.execute("SET enable_seqscan = on")
            cursor.execute("SET enable_hashjoin = on")
            cursor.execute("SET enable_mergejoin = on")
            cursor.execute("SET random_page_cost = 1.1")  # Assume fast storage
            cursor.execute("SET cpu_tuple_cost = 0.01")
        elif benchmark_type == "oltp":
            # OLTP optimizations
            cursor.execute("SET synchronous_commit = on")
            cursor.execute("SET random_page_cost = 4.0")

        connection.commit()
        cursor.close()

    def get_query_plan(
        self,
        connection: Any,
        query: str,
        explain_options: dict[str, Any] | None = None,
    ) -> str:
        """Get query execution plan using EXPLAIN ANALYZE."""
        cursor = connection.cursor()

        # Build EXPLAIN options
        options = ["ANALYZE", "BUFFERS", "FORMAT TEXT"]
        if explain_options:
            if explain_options.get("verbose"):
                options.append("VERBOSE")
            if explain_options.get("costs", True):
                options.append("COSTS")

        options_str = ", ".join(options)
        explain_query = f"EXPLAIN ({options_str}) {query}"

        try:
            cursor.execute(explain_query)
            plan_rows = cursor.fetchall()
            cursor.close()

            return "\n".join(row[0] for row in plan_rows)

        except Exception as e:
            cursor.close()
            return f"Failed to get query plan: {e}"

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE on a table to update statistics."""
        if not self._validate_identifier(table_name):
            self.logger.warning(f"Invalid table identifier: {table_name}")
            return

        cursor = connection.cursor()
        qualified_table = f'"{self.schema}"."{table_name}"' if self.schema != "public" else f'"{table_name}"'

        try:
            cursor.execute(f"ANALYZE {qualified_table}")
            connection.commit()
        except Exception as e:
            self.logger.warning(f"ANALYZE failed for {table_name}: {e}")
        finally:
            cursor.close()

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get PostgreSQL platform information."""
        platform_info = {
            "platform_type": "postgresql",
            "platform_name": "PostgreSQL",
            "host": self.host,
            "port": self.port,
            "dialect": POSTGRES_DIALECT,
            "configuration": {
                "database": self.database,
                "schema": self.schema,
                "work_mem": self.work_mem,
                "maintenance_work_mem": self.maintenance_work_mem,
                "max_parallel_workers_per_gather": self.max_parallel_workers_per_gather,
            },
        }

        if connection:
            try:
                cursor = connection.cursor()

                # Get PostgreSQL version
                cursor.execute("SELECT version()")
                version_row = cursor.fetchone()
                if version_row:
                    platform_info["platform_version"] = version_row[0].split()[1] if version_row[0] else None

                # Check for TimescaleDB
                cursor.execute(
                    """
                    SELECT extname, extversion
                    FROM pg_extension
                    WHERE extname = 'timescaledb'
                    """
                )
                timescale = cursor.fetchone()
                if timescale:
                    platform_info["configuration"]["timescaledb_version"] = timescale[1]

                # Get database size
                cursor.execute(
                    "SELECT pg_size_pretty(pg_database_size(%s))",
                    (self.database,),
                )
                size_row = cursor.fetchone()
                if size_row:
                    platform_info["configuration"]["database_size"] = size_row[0]

                cursor.close()

            except Exception as e:
                self.logger.debug(f"Error getting platform info: {e}")

        # Add client library version
        if psycopg:
            platform_info["client_library_version"] = psycopg.__version__

        return platform_info

    def test_connection(self) -> bool:
        """Test if connection can be established."""
        try:
            params = self._get_connection_params()
            conn = psycopg.connect(**params)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            self.logger.debug(f"Connection test failed: {e}")
            return False

    def apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None:
        """Apply tuning configurations to PostgreSQL tables."""
        # PostgreSQL tuning is primarily handled through indexes and ANALYZE

    def generate_tuning_clause(self, table_tuning: TableTuning | None) -> str:
        """Generate PostgreSQL-specific tuning clauses."""
        if not table_tuning:
            return ""
        # PostgreSQL doesn't use WITH clause for table tuning like columnar stores
        return ""

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration."""
        # Most PostgreSQL tuning is session-based and already applied in create_connection

    def apply_platform_optimizations(
        self,
        platform_config: PlatformOptimizationConfiguration,
        connection: Any,
    ) -> None:
        """Apply PostgreSQL-specific optimizations."""
        # Optimizations applied in configure_for_benchmark

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to PostgreSQL."""
        # PostgreSQL enforces constraints by default
        # Could defer foreign key checks if needed

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate PostgreSQL-specific capabilities for the benchmark.

        Args:
            benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')

        Returns:
            ValidationResult with PostgreSQL capability validation status
        """
        errors = []
        warnings = []

        # Check if psycopg is available
        if psycopg is None:
            errors.append("psycopg library not available - install with 'pip install psycopg[binary]'")
        else:
            # Check psycopg version
            try:
                version = psycopg.__version__
                # Warn if using versions older than psycopg3
                version_parts = version.split(".")
                major = int(version_parts[0])
                if major < 3:
                    warnings.append(
                        f"psycopg version {version} is older - consider upgrading to 3.1+ for better performance"
                    )
            except (AttributeError, ValueError, IndexError):
                warnings.append("Could not determine psycopg version")

        # Check work_mem configuration
        if hasattr(self, "work_mem") and self.work_mem:
            try:
                # Parse work_mem if it's a string (e.g., "256MB")
                work_mem_str = str(self.work_mem).upper()
                if work_mem_str.endswith("GB"):
                    memory_mb = float(work_mem_str[:-2]) * 1024
                elif work_mem_str.endswith("MB"):
                    memory_mb = float(work_mem_str[:-2])
                elif work_mem_str.endswith("KB"):
                    memory_mb = float(work_mem_str[:-2]) / 1024
                else:
                    memory_mb = float(work_mem_str) / (1024 * 1024)  # Assume bytes

                if memory_mb < 64:
                    warnings.append(f"work_mem ({self.work_mem}) may be too low for complex analytical queries")
            except (ValueError, TypeError):
                warnings.append(f"Could not parse work_mem setting: {self.work_mem}")

        # Platform-specific details
        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
            "psycopg_available": psycopg is not None,
            "host": getattr(self, "host", None),
            "port": getattr(self, "port", None),
            "database": getattr(self, "database", None),
            "schema": getattr(self, "schema", None),
            "work_mem": getattr(self, "work_mem", None),
        }

        if psycopg:
            platform_info["psycopg_version"] = getattr(psycopg, "__version__", "unknown")

        # Import ValidationResult here to avoid circular imports
        try:
            from benchbox.core.validation import ValidationResult

            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                details=platform_info,
            )
        except ImportError:
            # Fallback if validation module not available
            return None

    def validate_connection_health(self, connection: Any):
        """Validate PostgreSQL connection health and capabilities.

        Args:
            connection: PostgreSQL connection object

        Returns:
            ValidationResult with connection health status
        """
        errors = []
        warnings = []
        connection_info = {}

        try:
            cursor = connection.cursor()

            # Test basic query execution
            cursor.execute("SELECT 1 as test_value")
            result = cursor.fetchone()
            if result[0] != 1:
                errors.append("Basic query execution test failed")
            else:
                connection_info["basic_query_test"] = "passed"

            # Check PostgreSQL version
            try:
                cursor.execute("SELECT version()")
                version_result = cursor.fetchone()
                if version_result:
                    connection_info["server_version"] = version_result[0]
                    # Extract major version number
                    version_match = re.search(r"PostgreSQL (\d+)", version_result[0])
                    if version_match:
                        major_version = int(version_match.group(1))
                        if major_version < 12:
                            warnings.append(f"PostgreSQL {major_version} is older than recommended minimum (12)")
            except Exception:
                warnings.append("Could not query PostgreSQL version")

            # Check available work_mem setting
            try:
                cursor.execute("SHOW work_mem")
                work_mem_result = cursor.fetchone()
                if work_mem_result:
                    connection_info["work_mem_setting"] = work_mem_result[0]
            except Exception:
                warnings.append("Could not query work_mem setting")

            # Check if TimescaleDB extension is available
            try:
                cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'timescaledb'")
                timescale_result = cursor.fetchone()
                connection_info["timescaledb_available"] = timescale_result is not None
            except Exception:
                connection_info["timescaledb_available"] = False

            cursor.close()

        except Exception as e:
            errors.append(f"Connection health check failed: {str(e)}")

        # Import ValidationResult here to avoid circular imports
        try:
            from benchbox.core.validation import ValidationResult

            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                details={
                    "platform": self.platform_name,
                    "connection_type": type(connection).__name__,
                    **connection_info,
                },
            )
        except ImportError:
            # Fallback if validation module not available
            return None

    _supported_tuning_type_names = ("PARTITIONING", "CLUSTERING", "PRIMARY_KEYS", "FOREIGN_KEYS")


def _build_postgresql_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build PostgreSQL database configuration with credential loading.

    This function is registered with PlatformHookRegistry to provide
    PostgreSQL-specific configuration handling.
    """
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("postgresql") or {}

    explicit_options = overrides.get("_explicit_platform_options", {})

    merged_options: dict[str, Any] = {"schema": "public"}
    merged_options.update(options)  # registered defaults (lowest priority)
    merged_options.update(saved_creds)  # saved credentials win over defaults
    merged_options.update(explicit_options)  # explicit CLI flags win over credentials
    merged_options.update(overrides)  # runtime overrides (highest priority)

    name = info.display_name if info else "PostgreSQL"
    driver_package = info.driver_package if info else "psycopg"

    config_dict = {
        "type": "postgresql",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        "host": merged_options.get("host", "localhost"),
        "port": merged_options.get("port", 5432),
        "username": merged_options.get("username", "postgres"),
        "password": merged_options.get("password"),
        "database": merged_options.get("database"),
        "admin_database": merged_options.get("admin_database", "postgres"),
        "sslmode": merged_options.get("sslmode", "prefer"),
        "work_mem": merged_options.get("work_mem", "256MB"),
        "maintenance_work_mem": merged_options.get("maintenance_work_mem", "512MB"),
        "effective_cache_size": merged_options.get("effective_cache_size", "1GB"),
        "max_parallel_workers_per_gather": merged_options.get("max_parallel_workers_per_gather", 2),
        "enable_timescale": merged_options.get("enable_timescale", False),
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    return DatabaseConfig(**config_dict)
