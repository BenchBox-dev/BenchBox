"""QuestDB platform adapter for BenchBox benchmarking.

Provides QuestDB-specific functionality including:
- PostgreSQL wire protocol connectivity (port 8812)
- REST API CSV import for efficient bulk data loading
- InfluxDB Line Protocol (ILP) ingestion on port 9009
- QuestDB-specific DDL handling (designated timestamp, partitioning)
- Time-series optimized schema creation with symbol types and partitioning

QuestDB is a high-performance open-source time-series database optimized
for fast ingestion and SQL queries. It supports the PostgreSQL wire protocol
for query execution, a REST API for data import, and ILP for high-throughput
ingestion.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import re
import socket
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
from benchbox.platforms.questdb_rewriter import rewrite as _rewriter_rewrite
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
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
from .base.sql_execution import execute_sql_query

# QuestDB uses PostgreSQL wire protocol, so we use the postgres dialect
QUESTDB_DIALECT = "postgres"

try:
    import psycopg
except ImportError:
    psycopg = None

# ──────────────────────────────────────────────────────────────────────
# TPC-H designated timestamp columns per table.
# QuestDB requires exactly one designated timestamp column for time-series
# ordering and partitioning. These are the most query-relevant date columns.
# ──────────────────────────────────────────────────────────────────────
TPCH_TIMESTAMP_COLUMNS: dict[str, str] = {
    "lineitem": "l_shipdate",
    "orders": "o_orderdate",
    "partsupp": None,  # no date column
    "part": None,
    "supplier": None,
    "customer": None,
    "nation": None,
    "region": None,
}

# ──────────────────────────────────────────────────────────────────────
# TPC-H columns that should use QuestDB's ``symbol`` type.
# Symbol columns are indexed, interned strings ideal for low-cardinality
# fields (< ~100k distinct values). They significantly improve filter
# and GROUP BY performance.
# ──────────────────────────────────────────────────────────────────────
TPCH_SYMBOL_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_returnflag", "l_linestatus", "l_shipinstruct", "l_shipmode"],
    "orders": ["o_orderstatus", "o_orderpriority"],
    "part": ["p_brand", "p_type", "p_container", "p_mfgr"],
    "supplier": [],
    "partsupp": [],
    "customer": ["c_mktsegment"],
    "nation": ["n_name"],
    "region": ["r_name"],
}

# ──────────────────────────────────────────────────────────────────────
# Default partition granularity per TPC-H table.
# Tables without a designated timestamp cannot be partitioned.
# ──────────────────────────────────────────────────────────────────────
TPCH_PARTITION_DEFAULTS: dict[str, str] = {
    "lineitem": "MONTH",
    "orders": "MONTH",
}

# All date/timestamp columns across TPC-H tables
TPCH_DATE_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_shipdate", "l_commitdate", "l_receiptdate"],
    "orders": ["o_orderdate"],
}


class QuestDBAdapter(PsycopgConnectionMixin, PlatformAdapter):
    """QuestDB platform adapter with REST API and ILP data loading.

    Supports QuestDB 7.0+ via PostgreSQL wire protocol (port 8812).
    Uses psycopg for database connectivity, REST API for bulk loading,
    and optionally ILP (port 9009) for high-throughput ingestion.

    QuestDB-specific considerations:
    - No traditional database creation (single database per instance)
    - Tables support designated timestamp columns and partitioning
    - No foreign key constraints
    - DROP TABLE does not support IF EXISTS in all versions
    - COPY FROM STDIN is a no-op in QuestDB; REST API /imp is the only bulk loader
    - Symbol type for low-cardinality string columns
    - PARTITION BY for time-series tables
    """

    plan_capture_phase_eligible = True

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    _max_identifier_length = 127  # QuestDB supports identifiers up to 127 chars (PostgreSQL caps at 63)

    @property
    def platform_name(self) -> str:
        return "QuestDB"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for QuestDB (PostgreSQL-compatible)."""
        return QUESTDB_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add QuestDB-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            parser.add_argument(
                "--questdb-host",
                dest="host",
                default="localhost",
                help="QuestDB server hostname",
            )
            parser.add_argument(
                "--questdb-pg-port",
                dest="pg_port",
                type=int,
                default=8812,
                help="QuestDB PostgreSQL wire protocol port",
            )
            parser.add_argument(
                "--questdb-http-port",
                dest="http_port",
                type=int,
                default=9000,
                help="QuestDB REST API HTTP port",
            )
            parser.add_argument(
                "--questdb-ilp-port",
                dest="ilp_port",
                type=int,
                default=9009,
                help="QuestDB ILP (InfluxDB Line Protocol) port",
            )
            parser.add_argument(
                "--questdb-username",
                dest="username",
                default="admin",
                help="QuestDB username",
            )
            parser.add_argument(
                "--questdb-password",
                dest="password",
                default="quest",
                help="QuestDB password",
            )
            parser.add_argument(
                "--questdb-database",
                dest="database",
                default="qdb",
                help="QuestDB database name",
            )
            parser.add_argument(
                "--questdb-use-tls",
                dest="use_tls",
                action="store_true",
                default=False,
                help="Use HTTPS for REST API endpoints (default: HTTP)",
            )
            parser.add_argument(
                "--questdb-loading-method",
                dest="loading_method",
                choices=["rest", "ilp"],
                default="rest",
                help="Data loading method: 'rest' (CSV import, default) or 'ilp' (InfluxDB Line Protocol)",
            )
            parser.add_argument(
                "--questdb-partition-by",
                dest="partition_by",
                choices=["DAY", "MONTH", "YEAR", "NONE"],
                default=None,
                help="Partition granularity for time-series tables (default: auto per table)",
            )
        except Exception:
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> QuestDBAdapter:
        """Create QuestDB adapter from unified configuration."""
        adapter_config = {}

        # Connection parameters
        adapter_config["host"] = config.get("host", "localhost")
        adapter_config["pg_port"] = config.get("pg_port", config.get("port", 8812))
        adapter_config["http_port"] = config.get("http_port", 9000)
        adapter_config["ilp_port"] = config.get("ilp_port", 9009)
        adapter_config["ilp_host"] = config.get("ilp_host", config.get("host", "localhost"))
        adapter_config["username"] = config.get("username", "admin")
        adapter_config["password"] = config.get("password", "quest")
        adapter_config["database"] = config.get("database", "qdb")

        # Connection settings
        adapter_config["connect_timeout"] = config.get("connect_timeout", 10)
        adapter_config["use_tls"] = config.get("use_tls", False)

        # QuestDB-specific settings
        adapter_config["loading_method"] = config.get("loading_method", "rest")
        adapter_config["partition_by"] = config.get("partition_by")
        adapter_config["parquet_chunk_rows"] = config.get("parquet_chunk_rows", 200_000)

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Pass through other config
        for key in [
            "tuning_config",
            "tuning_enabled",
            "unified_tuning_configuration",
            "verbose_enabled",
            "very_verbose",
            "capture_plans",
            "show_query_plans",
            "enable_validation",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies
        if psycopg is None:
            available, missing = check_platform_dependencies("questdb", packages=["psycopg"])
            if not available:
                error_msg = get_dependency_error_message("questdb", missing)
                raise ImportError(error_msg)

        self._dialect = QUESTDB_DIALECT

        # Connection configuration
        self.host = config.get("host", "localhost")
        self.pg_port = config.get("pg_port", 8812)
        self.http_port = config.get("http_port", 9000)
        self.ilp_port = config.get("ilp_port", 9009)
        self.ilp_host = config.get("ilp_host", config.get("host", "localhost"))
        self.database = config.get("database", "qdb")
        self.username = config.get("username", "admin")
        self.password = config.get("password", "quest")

        # Connection settings
        self.connect_timeout = config.get("connect_timeout", 10)
        self.use_tls = config.get("use_tls", False)

        # QuestDB-specific settings
        self.loading_method = config.get("loading_method", "rest")
        self.partition_by = config.get("partition_by")
        self.parquet_chunk_rows = int(config.get("parquet_chunk_rows", 200_000))

        # QuestDB does not support database management (single DB per instance)
        self.skip_database_management = True

    def _get_connection_params(self) -> dict[str, Any]:
        """Build psycopg connection parameters for QuestDB PG wire protocol."""
        params = {
            "host": self.host,
            "port": self.pg_port,
            "dbname": self.database,
            "user": self.username,
            "connect_timeout": self.connect_timeout,
        }

        if self.password:
            params["password"] = self.password

        return {k: v for k, v in params.items() if v is not None}

    def create_connection(self, **connection_config) -> Any:
        """Create QuestDB connection via PostgreSQL wire protocol."""
        self.log_operation_start("QuestDB connection")

        # Handle existing database (skipped for QuestDB - single DB per instance)
        self.handle_existing_database(**connection_config)

        # Connect via PG wire protocol
        params = self._get_connection_params()
        conn = psycopg.connect(**params)

        # QuestDB requires autocommit mode for PG wire protocol
        conn.autocommit = True

        # Verify connection
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()

        self.log_operation_complete(
            "QuestDB connection",
            details=f"Connected to {self.host}:{self.pg_port}",
        )
        return conn

    def check_benchmark_tables_exist(self, **connection_config) -> bool | None:
        """Validate that required benchmark tables exist and are non-empty.

        QuestDB is a server-based database (skip_database_management=True) but we still need
        to check if the required benchmark tables for the current benchmark exist. If the
        expected tables don't exist or are stale from a previous benchmark, schema creation
        and data loading will proceed.
        """
        # Guard against missing psycopg dependency
        if psycopg is None:
            msg = "psycopg is required for QuestDB but is not installed"
            raise ImportError(msg)

        if self.force_recreate:
            self.log_verbose("Force recreate enabled - will recreate schema and reload data")
            return False

        # For external databases like QuestDB, validate that the expected tables for
        # the current benchmark exist (not just any tables from a previous benchmark)
        try:
            params = self._get_connection_params()
            test_conn = psycopg.connect(**params)
            test_conn.autocommit = True

            try:
                # Get expected table names from the current benchmark
                benchmark = getattr(self, "benchmark", None) or getattr(self, "benchmark_instance", None)
                if benchmark is None:
                    self.log_verbose("Benchmark not available - treating as fresh database")
                    return False

                expected_tables = self._get_expected_tables(benchmark)
                if not expected_tables:
                    # Benchmarks that initialize tables={} (e.g. clickbench, which populates
                    # tables only after downloading data) will always take this path, meaning
                    # QuestDB reuse detection is disabled for them. Acceptable for now since
                    # QuestDB is primarily used with TPC benchmarks that pre-declare tables.
                    self.log_verbose("Benchmark has no tables - treating as fresh database")
                    return False
                expected_tables = set(expected_tables)

                # Query QuestDB for all table names
                with test_conn.cursor() as cursor:
                    cursor.execute("SELECT table_name FROM tables()")
                    existing_tables = {str(row[0]).lower() for row in cursor.fetchall()}

                # Check if all expected tables are present
                missing_tables = expected_tables - existing_tables
                if missing_tables:
                    self.log_verbose(
                        f"Expected benchmark tables not found: {', '.join(sorted(missing_tables))} "
                        "- treating as fresh database (will create schema)"
                    )
                    return False

                # All expected tables exist; verify they are non-empty.
                # A prior partial run may have created the schema without ever
                # completing data loading, leaving every table as an empty
                # schema object. LIMIT 1 is O(1) regardless of table size.
                empty_tables = []
                with test_conn.cursor() as row_cursor:
                    for tname in sorted(expected_tables):
                        if not self._validate_identifier(tname.lower()):
                            continue
                        row_cursor.execute(f'SELECT 1 FROM "{tname}" LIMIT 1')
                        if row_cursor.fetchone() is None:
                            empty_tables.append(tname)

                if empty_tables:
                    self.log_verbose(
                        f"Tables exist but are empty: {', '.join(empty_tables)} "
                        "- treating as fresh database (will reload data)"
                    )
                    return False

                self.log_verbose(
                    f"Found all {len(expected_tables)} expected benchmark tables with data - "
                    "attempting to reuse existing database"
                )
                return True

            finally:
                test_conn.close()

        except (psycopg.Error, OSError) as e:
            self.logger.debug(f"Error checking existing tables: {e}")
            self.log_verbose("Unable to verify existing tables - treating as fresh database")
            return False

    # ──────────────────────────────────────────────────────────────
    # Schema creation with designated timestamp, partitioning, and
    # QuestDB-specific data types (symbol, timestamp)
    # ──────────────────────────────────────────────────────────────

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions.

        QuestDB has specific DDL requirements:
        - No foreign key constraints
        - Tables can have designated timestamps and partitioning
        - DROP TABLE syntax may differ from standard PostgreSQL
        - Symbol type for low-cardinality string columns
        - PARTITION BY for time-series tables
        """
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get schema SQL and translate to PostgreSQL dialect
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        cursor = connection.cursor()
        critical_failures = []
        try:
            # Drop any stale tables left over from a previous partially-failed
            # schema creation. Without this, tables that succeeded on the prior
            # run (e.g. those without SYMBOL columns) block re-creation with
            # "table already exists" while other tables rebuild cleanly.
            # Skipped for dry-run (no DDL should execute) and when we've
            # already confirmed the existing database is being reused.
            if not self.dry_run and not getattr(self, "database_was_reused", False):
                benchmark_tables = getattr(benchmark, "tables", None)
                if isinstance(benchmark_tables, dict):
                    droppable = [
                        name
                        for name in benchmark_tables
                        if isinstance(name, str) and self._validate_identifier(name.lower())
                    ]
                    if droppable:
                        self.log_notice(
                            f"Pre-dropping {len(droppable)} benchmark table(s) before schema creation: "
                            f"{', '.join(droppable)}"
                        )
                    for table_name in droppable:
                        try:
                            self.log_notice(f'Dropping table if it exists: "{table_name}"')
                            cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
                        except Exception as drop_err:
                            self.logger.warning(f"Pre-create DROP TABLE {table_name} skipped: {drop_err}")

            # Execute each statement separately
            statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
            for stmt in statements:
                stmt_upper = stmt.upper()

                # Skip standalone ALTER TABLE ... ADD FOREIGN KEY statements
                if "ALTER" in stmt_upper and "FOREIGN KEY" in stmt_upper:
                    self.log_verbose("Skipping ALTER TABLE foreign key constraint (unsupported by QuestDB)")
                    continue

                # Strip inline FK and PK constraints from CREATE TABLE statements
                if "CREATE TABLE" in stmt_upper and ("FOREIGN KEY" in stmt_upper or "REFERENCES" in stmt_upper):
                    stmt = strip_foreign_keys(stmt)
                    self.log_verbose("Stripped foreign key constraints from CREATE TABLE (unsupported by QuestDB)")

                if "CREATE TABLE" in stmt_upper and "PRIMARY KEY" in stmt_upper:
                    stmt = self._strip_pk_constraints(stmt)
                    self.log_verbose("Stripped primary key constraints from CREATE TABLE (unsupported by QuestDB)")

                # Adapt DROP TABLE statements for QuestDB
                if "DROP TABLE" in stmt_upper:
                    stmt = self._adapt_drop_table(stmt)

                # Apply QuestDB-specific type mappings and timestamp/partition
                if "CREATE TABLE" in stmt_upper:
                    stmt = self._apply_questdb_schema_enhancements(stmt)

                try:
                    cursor.execute(stmt)
                except Exception as e:
                    is_create_table = stmt.strip().upper().startswith("CREATE TABLE")
                    if is_create_table:
                        critical_failures.append((stmt[:80], str(e)))
                    self.logger.warning(f"Schema statement failed: {e}")
                    # Continue with other statements
        finally:
            cursor.close()

        if critical_failures:
            failed_summary = "; ".join(f"{s}: {err}" for s, err in critical_failures)
            raise RuntimeError(f"{len(critical_failures)} critical CREATE TABLE statement(s) failed: {failed_summary}")

        duration = elapsed_seconds(start_time)
        self.log_operation_complete("Schema creation", duration, "Schema and tables created")
        return duration

    def _apply_questdb_schema_enhancements(self, stmt: str) -> str:
        """Apply QuestDB-specific enhancements to a CREATE TABLE statement.

        Applies the following transformations:
        1. Map low-cardinality string columns to ``symbol`` type
        2. Map date columns to ``timestamp`` type
        3. Add designated timestamp column via ``timestamp(col)``
        4. Add ``PARTITION BY`` clause for time-series tables

        Args:
            stmt: A CREATE TABLE SQL statement.

        Returns:
            Enhanced CREATE TABLE statement with QuestDB-specific features.
        """
        table_name = self._extract_table_name(stmt)
        if not table_name:
            return stmt

        table_name_lower = table_name.lower()

        # 1. Map symbol columns (low-cardinality strings -> symbol)
        symbol_cols = TPCH_SYMBOL_COLUMNS.get(table_name_lower, [])
        for col in symbol_cols:
            stmt = self._map_column_to_symbol(stmt, col)

        # 2. Map date columns to timestamp type
        date_cols = TPCH_DATE_COLUMNS.get(table_name_lower, [])
        for col in date_cols:
            stmt = self._map_column_to_timestamp(stmt, col)

        # 3. Add designated timestamp and partition by
        ts_col = TPCH_TIMESTAMP_COLUMNS.get(table_name_lower)
        if ts_col:
            partition = self._get_partition_for_table(table_name_lower)
            stmt = self._add_timestamp_and_partition(stmt, ts_col, partition)

        return stmt

    def _extract_table_name(self, stmt: str) -> str | None:
        """Extract table name from a CREATE TABLE statement.

        Args:
            stmt: SQL statement.

        Returns:
            Table name (unquoted, lowercase) or None.
        """
        match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"']?(\w+)[\"']?", stmt, re.IGNORECASE)
        return match.group(1) if match else None

    def _map_column_to_symbol(self, stmt: str, column_name: str) -> str:
        """Replace a VARCHAR/TEXT/CHAR column type with QuestDB symbol type.

        Also strips any trailing ``NOT NULL`` / ``NULL`` nullability modifier:
        QuestDB's parser rejects nullability constraints on ``SYMBOL`` columns
        (only ``CAPACITY``, ``NOCACHE``/``CACHE``, and ``INDEX`` are accepted
        after ``SYMBOL``).

        Limitation: only nullability is stripped. A trailing ``CHECK (...)`` or
        ``DEFAULT ...`` clause on the source column would survive the rewrite
        and produce invalid QuestDB DDL. Benchmark schemas currently in use
        (TPC-H, TPC-DS) do not emit those on VARCHAR/TEXT columns.

        Args:
            stmt: CREATE TABLE statement.
            column_name: Column to convert.

        Returns:
            Modified statement.
        """
        # Match column definition: column_name + source type + optional NOT NULL/NULL.
        pattern = (
            rf"(\b{re.escape(column_name)}\b)\s+"
            r"(?:VARCHAR|TEXT|CHAR|CHARACTER\s+VARYING)(?:\s*\(\s*\d+\s*\))?"
            r"(?:\s+NOT\s+NULL|\s+NULL)?"
        )
        replacement = r"\1 SYMBOL"
        return re.sub(pattern, replacement, stmt, count=1, flags=re.IGNORECASE)

    def _map_column_to_timestamp(self, stmt: str, column_name: str) -> str:
        """Replace a DATE column type with QuestDB timestamp type.

        Args:
            stmt: CREATE TABLE statement.
            column_name: Column to convert.

        Returns:
            Modified statement.
        """
        pattern = rf"(\b{re.escape(column_name)}\b)\s+(?:DATE|TIMESTAMP)"
        replacement = r"\1 TIMESTAMP"
        return re.sub(pattern, replacement, stmt, count=1, flags=re.IGNORECASE)

    def _get_partition_for_table(self, table_name_lower: str) -> str:
        """Determine partition granularity for a table.

        Uses the adapter-level ``partition_by`` override if set, otherwise
        falls back to per-table defaults from TPCH_PARTITION_DEFAULTS.

        Args:
            table_name_lower: Lowercased table name.

        Returns:
            Partition string (e.g. "MONTH") or "NONE".
        """
        if self.partition_by is not None:
            return self.partition_by
        return TPCH_PARTITION_DEFAULTS.get(table_name_lower, "NONE")

    def _add_timestamp_and_partition(self, stmt: str, ts_column: str, partition: str) -> str:
        """Append designated timestamp and partition clause to CREATE TABLE.

        QuestDB syntax:
            CREATE TABLE t (...) timestamp(col) PARTITION BY MONTH;

        Args:
            stmt: CREATE TABLE statement (without trailing semicolon).
            ts_column: Designated timestamp column name.
            partition: Partition granularity (DAY, MONTH, YEAR, NONE).

        Returns:
            Statement with timestamp() and PARTITION BY appended.
        """
        # Strip trailing whitespace/semicolons
        stmt = stmt.rstrip().rstrip(";").rstrip()

        suffix = f" timestamp({ts_column})"
        if partition and partition.upper() != "NONE":
            suffix += f" PARTITION BY {partition.upper()}"

        return stmt + suffix

    def _strip_pk_constraints(self, stmt: str) -> str:
        """Strip PRIMARY KEY constraints from CREATE TABLE statements.

        QuestDB 9.3.4 rejects `PRIMARY KEY (col_list)` with:
          "Schema statement failed: unsupported column type: KEY"

        Removes both forms:
          - Unnamed: `, PRIMARY KEY (col1, col2)`
          - Named:   `, CONSTRAINT name PRIMARY KEY (col1, col2)`
            Constraint name may be bare (``pk_t``), double-quoted (``"pk_t"``),
            or backtick-quoted (`` `pk_t` ``).

        Column-level `PRIMARY KEY` keywords on individual column definitions
        are also removed (e.g., `col_id INT PRIMARY KEY`).

        The FK cleanup pass already removes trailing `,)` artifacts, but we
        apply it again here in case the PK clause was the last item.
        """
        # Named constraint form: CONSTRAINT name PRIMARY KEY (col_list)
        # Name may be bare (pk_t), double-quoted ("pk_t"), or backtick-quoted (`pk_t`)
        # [^)]* is intentionally simple: PRIMARY KEY column lists in benchmark DDL
        # are always bare identifiers, never function calls with nested parens.
        stmt = re.sub(
            r',?\s*CONSTRAINT\s+(?:"[^"]+"|`[^`]+`|\w+)\s+PRIMARY\s+KEY\s*\([^)]*\)',
            "",
            stmt,
            flags=re.IGNORECASE,
        )
        # Unnamed table-level form: PRIMARY KEY (col_list)
        stmt = re.sub(
            r",?\s*PRIMARY\s+KEY\s*\([^)]*\)",
            "",
            stmt,
            flags=re.IGNORECASE,
        )
        # Column-level form: col_name type PRIMARY KEY
        stmt = re.sub(
            r"\s+PRIMARY\s+KEY\b",
            "",
            stmt,
            flags=re.IGNORECASE,
        )
        # Clean up any trailing commas before closing paren
        stmt = re.sub(r",\s*\)", ")", stmt)
        return stmt

    def _adapt_drop_table(self, stmt: str) -> str:
        """Adapt DROP TABLE statements for QuestDB compatibility.

        QuestDB supports DROP TABLE but syntax may vary by version.
        Ensure IF EXISTS is used for idempotent schema creation.
        """
        stmt_upper = stmt.upper().strip()
        if "DROP TABLE" in stmt_upper and "IF EXISTS" not in stmt_upper:
            # Insert IF EXISTS after DROP TABLE
            stmt = re.sub(r"(?i)(DROP\s+TABLE)\s+", r"\1 IF EXISTS ", stmt, count=1)
        return stmt

    # ──────────────────────────────────────────────────────────────
    # Data loading: REST CSV import (default) and ILP
    # ──────────────────────────────────────────────────────────────

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data using configured loading method.

        Supports two methods:
        - ``rest`` (default): QuestDB REST API CSV import via /imp endpoint
        - ``ilp``: InfluxDB Line Protocol ingestion via TCP port 9009
        """
        start_time = mono_time()
        table_stats = {}

        method = self.loading_method
        self.log_operation_start("Data loading", f"source: {data_dir}, method: {method}")

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

            total_rows = 0
            for data_file in data_files:
                try:
                    dialect = resolve_csv_dialect(data_source, table_name_lower, data_file, benchmark)
                    if method == "ilp":
                        rows = self._load_table_via_ilp(table_name_lower, data_file, dialect)
                        source = "ILP"
                    elif get_data_extension(data_file) == ".parquet":
                        rows = self._load_parquet_via_chunked_csv(table_name_lower, data_file)
                        source = "REST/parquet-csv"
                    else:
                        rows = self._load_table_via_rest_api(table_name_lower, data_file, dialect)
                        source = "REST"
                except Exception as e:
                    self.logger.error(f"Failed to load {table_name_lower} chunk {data_file.name}: {e}")
                    continue
                total_rows += rows
                self.log_verbose(f"Loaded {rows:,} rows into {table_name_lower} from {data_file.name} (via {source})")

            table_stats[table_name_lower] = total_rows

        loading_time = elapsed_seconds(start_time)

        total_rows = sum(table_stats.values())
        self.log_operation_complete("Data loading", loading_time, f"Loaded {total_rows:,} total rows")

        # Populate transactional staging tables (txn_*) derived from just-loaded base
        # tables. The standard setup() path acquires a lock via a PRIMARY KEY table that
        # QuestDB 9.3.4 rejects ("unsupported column type: KEY"), so we populate directly.
        self._populate_transactional_staging_tables(benchmark, connection)

        return table_stats, loading_time, None

    def _populate_transactional_staging_tables(self, benchmark: Any, connection: Any) -> None:
        """Populate transactional staging tables from already-loaded base tables.

        transaction_primitives derives txn_orders/txn_lineitem/txn_customer from TPC-H
        base tables via INSERT...SELECT. The standard benchmark.setup() acquires a lock
        using a table with column-level PRIMARY KEY syntax that QuestDB 9.3.4 rejects,
        so we populate the staging tables directly here after base tables are loaded,
        bypassing the lock mechanism.
        """
        staging_tables = getattr(benchmark, "_staging_tables", None)
        if not isinstance(staging_tables, dict) or not callable(getattr(benchmark, "_populate_staging_table", None)):
            return

        staging_source: dict[str, str] = {
            "txn_orders": "orders",
            "txn_lineitem": "lineitem",
            "txn_customer": "customer",
        }

        for staging_name, source_name in staging_source.items():
            if staging_name not in staging_tables:
                continue
            try:
                result = connection.execute(f"SELECT COUNT(*) FROM {staging_name}").fetchone()
                if result and result[0] > 0:
                    self.log_verbose(f"{staging_name} already populated ({result[0]:,} rows), skipping")
                    continue
                # count = 0: table exists but is empty - fall through to populate
            except Exception:
                pass  # table doesn't exist yet - fall through to populate
            try:
                self.log_verbose(f"Populating {staging_name} from {source_name}...")
                benchmark._populate_staging_table(connection, staging_name, source_name)
                count_result = connection.execute(f"SELECT COUNT(*) FROM {staging_name}").fetchone()
                count = count_result[0] if count_result else 0
                self.log_verbose(f"Populated {staging_name} ({count:,} rows)")
            except Exception as e:
                self.logger.warning(f"Failed to populate staging table {staging_name}: {e}")

    def _load_table_via_rest_api(self, table_name: str, data_file: Path, dialect: CsvDialect) -> int:
        """Load data into a table using QuestDB REST API /imp endpoint.

        Args:
            table_name: Target table name
            data_file: Path to the data file (CSV or TPC format)
            dialect: CSV dialect describing delimiter, null handling, etc.

        Returns:
            Number of rows loaded
        """
        import requests

        url = f"{'https' if self.use_tls else 'http'}://{self.host}:{self.http_port}/imp"

        params = {
            "name": table_name,
            "overwrite": "false",
            "durable": "true",
            "delimiter": dialect.delimiter,
        }

        # Strip trailing delimiter for TPC-H .tbl and TPC-DS .dat files: both
        # dbgen and dsdgen emit a spurious trailing pipe after every record. CSV
        # files must NOT be stripped: a trailing comma means the last field is
        # empty/NULL, not a junk terminator — stripping it drops that field and
        # causes a column-count mismatch on import.
        strip_trailing_delim = get_data_extension(data_file) in (".tbl", ".dat")
        with prepare_local_load_file(
            data_file, dialect=dialect, strip_trailing_delim=strip_trailing_delim
        ) as load_path:
            with open(load_path, "rb") as upload_stream:
                files = {"data": (f"{table_name}.csv", upload_stream, "text/csv")}
                response = requests.post(url, params=params, files=files, timeout=300)
        response.raise_for_status()

        # QuestDB /imp returns text/plain; parse "Rows imported" from the table.
        # Example line: |  Rows imported  |  3  |
        match = re.search(r"Rows imported\s*\|\s*(\d+)", response.text)
        if match:
            return int(match.group(1))

        # Fallback: query via SQL if the response format is unexpected
        return self._count_table_rows_via_http(table_name)

    def _load_parquet_via_chunked_csv(self, table_name: str, data_file: Path) -> int:
        """Load a parquet file into QuestDB by converting to CSV chunks.

        QuestDB's /imp REST endpoint accepts CSV only and has a default HTTP
        receive buffer limit (~128 MB).  Large parquet files (e.g. tpcds_obt at
        1.1 GB) exceed this limit, causing a ConnectionResetError when uploaded
        in one shot.

        This method reads the parquet file in row-group chunks (using pyarrow),
        converts each chunk to CSV, and POSTs each chunk to /imp with
        ``overwrite=false`` (append mode).  ``create_schema`` always runs before
        ``load_data``, so the table exists and is empty at this point -
        appending to an empty table is equivalent to a fresh insert while
        preserving the QuestDB-specific schema (SYMBOL columns, designated
        timestamp, PARTITION BY) created during DDL execution.

        Every chunk includes a CSV header row and is posted with
        ``forceHeader=true`` so QuestDB maps columns by name rather than by
        position.  QuestDB ≤9.3.x historically mapped CSV positionally even
        when headers were present (issue questdb/questdb#1758, fixed in
        PR #1789); always sending a named header is the safe baseline that
        works correctly on both old and new behaviour.

        Args:
            table_name: Target table name
            data_file: Path to the .parquet file

        Returns:
            Total number of rows loaded

        Raises:
            ImportError: If pyarrow is not installed
            RuntimeError: If any chunk upload fails
        """
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:
            raise ImportError(
                "pyarrow is required to load parquet files into QuestDB. Install it with: uv add pyarrow"
            ) from exc

        import io

        import requests

        url = f"{'https' if self.use_tls else 'http'}://{self.host}:{self.http_port}/imp"
        total_rows = 0

        pf = pq.ParquetFile(data_file)
        for batch in pf.iter_batches(batch_size=self.parquet_chunk_rows):
            # Always include the CSV header row and set forceHeader=true so
            # QuestDB maps by column name, not position.  Without this, chunks
            # after the first arrive headerless; QuestDB may assign synthetic
            # names (f0, f1, …) and silently corrupt column order.
            csv_buf = io.BytesIO()
            batch.to_pandas().to_csv(csv_buf, index=False, header=True)
            csv_buf.seek(0)

            params = {
                "name": table_name,
                "overwrite": "false",
                "durable": "true",
                "delimiter": ",",
                "forceHeader": "true",
            }
            files = {"data": (f"{table_name}.csv", csv_buf, "text/csv")}
            response = requests.post(url, params=params, files=files, timeout=600)
            response.raise_for_status()

            match = re.search(r"Rows imported\s*\|\s*(\d+)", response.text)
            chunk_rows = int(match.group(1)) if match else len(batch)
            total_rows += chunk_rows
            self.log_verbose(f"Loaded chunk of {chunk_rows:,} rows into {table_name} (parquet → CSV)")

        return total_rows

    def _load_table_via_ilp(self, table_name: str, data_file: Path, dialect: CsvDialect) -> int:
        """Load data into a table using InfluxDB Line Protocol (ILP) over TCP.

        ILP format per line:
            measurement,tag1=val1 field1=val1,field2=val2 timestamp_nanos

        For benchmark data we treat all columns as fields (no tags) since
        QuestDB handles the measurement name as the table name.

        Args:
            table_name: Target table name (used as ILP measurement).
            data_file: Path to the data file (CSV or TPC format).
            dialect: CSV dialect describing delimiter, null handling, etc.

        Returns:
            Number of rows sent.
        """
        rows_sent = 0

        # Read column headers from the table schema via PG wire protocol
        # For TPC .tbl files there are no headers, so we need the schema
        column_names = self._get_table_columns(table_name)
        if not column_names:
            raise RuntimeError(f"Cannot determine column names for table '{table_name}' (needed for ILP)")

        ts_col = TPCH_TIMESTAMP_COLUMNS.get(table_name.lower())

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30)
        try:
            sock.connect((self.ilp_host, self.ilp_port))

            # Strip trailing delimiter for TPC-H .tbl and TPC-DS .dat files: both
            # dbgen and dsdgen emit a spurious trailing pipe after every record.
            # CSV files must NOT be stripped: a trailing comma means the last field
            # is empty/NULL, not a junk terminator — stripping it drops that field.
            strip_trailing_delim = get_data_extension(data_file) in (".tbl", ".dat")
            with prepare_local_load_file(
                data_file, dialect=dialect, strip_trailing_delim=strip_trailing_delim
            ) as load_path:
                with open(load_path, encoding="utf-8") as stream:
                    reader = csv.reader(stream, delimiter=dialect.delimiter)
                    batch: list[str] = []
                    for row in reader:
                        if len(row) != len(column_names):
                            continue
                        line = self._row_to_ilp_line(table_name, column_names, row, ts_col)
                        if line:
                            batch.append(line)
                            rows_sent += 1

                        # Flush in batches of 1000 lines
                        if len(batch) >= 1000:
                            sock.sendall(("\n".join(batch) + "\n").encode("utf-8"))
                            batch = []

                    # Final flush
                    if batch:
                        sock.sendall(("\n".join(batch) + "\n").encode("utf-8"))
        finally:
            sock.close()

        return rows_sent

    def _get_table_columns(self, table_name: str) -> list[str]:
        """Get column names for a table by querying QuestDB REST API.

        Args:
            table_name: Table name to inspect.

        Returns:
            List of column names, or empty list on failure.
        """
        import requests

        if not self._validate_identifier(table_name):
            return []

        url = f"{'https' if self.use_tls else 'http'}://{self.host}:{self.http_port}/exec"
        params = {"query": f'SHOW COLUMNS FROM "{table_name}"'}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            dataset = result.get("dataset", [])
            return [row[0] for row in dataset if row]
        except Exception:
            return []

    @staticmethod
    def _row_to_ilp_line(
        measurement: str,
        column_names: list[str],
        values: list[str],
        ts_column: str | None,
    ) -> str | None:
        """Convert a single CSV row to an ILP line.

        Args:
            measurement: ILP measurement name (table name).
            column_names: Column names matching ``values`` positionally.
            values: Column values from CSV.
            ts_column: Optional designated timestamp column name.

        Returns:
            ILP line string, or None if conversion fails.
        """
        fields: list[str] = []
        timestamp_ns: str | None = None

        for col_name, val in zip(column_names, values):
            val = val.strip()
            if not val:
                continue

            if ts_column and col_name == ts_column:
                # Convert date to nanosecond epoch for ILP timestamp field
                timestamp_ns = _date_to_epoch_ns(val)
                continue

            # Attempt to detect numeric vs string
            escaped = _ilp_escape_field(col_name, val)
            if escaped:
                fields.append(escaped)

        if not fields:
            return None

        line = f"{_ilp_escape_measurement(measurement)} {','.join(fields)}"
        if timestamp_ns:
            line += f" {timestamp_ns}"
        return line

    def _count_table_rows_via_http(self, table_name: str) -> int:
        """Count rows in a table via QuestDB REST API."""
        import requests

        if not self._validate_identifier(table_name):
            return 0

        url = f"{'https' if self.use_tls else 'http'}://{self.host}:{self.http_port}/exec"
        params = {"query": f'SELECT count() FROM "{table_name}"'}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            result = response.json()
            dataset = result.get("dataset", [])
            if dataset and len(dataset) > 0:
                return int(dataset[0][0])
        except Exception:
            pass
        return 0

    # ──────────────────────────────────────────────────────────────
    # Platform optimizations and benchmark configuration
    # ──────────────────────────────────────────────────────────────

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply QuestDB optimizations for benchmark type.

        QuestDB has limited session-level configuration compared to PostgreSQL.
        Most optimizations are handled at the table/schema level via
        designated timestamp columns, partitioning, and symbol types.

        For OLAP benchmarks (TPC-H, TPC-DS), we configure:
        - cairo.sql.parallel.filter.enabled for parallel query execution
        - cairo.page.frame.max.rows for scan performance
        """
        self.log_verbose(f"Configuring QuestDB for {benchmark_type} benchmark")

        cursor = connection.cursor()
        try:
            if benchmark_type in ("olap", "tpch", "tpcds"):
                # Enable parallel filter execution for analytical queries
                try:
                    cursor.execute("SET cairo.sql.parallel.filter.enabled = true")
                except Exception as e:
                    self.logger.debug(f"Could not set parallel filter: {e}")

                # Increase page frame size for large scans
                try:
                    cursor.execute("SET cairo.page.frame.max.rows = 1000000")
                except Exception as e:
                    self.logger.debug(f"Could not set page frame max rows: {e}")

            elif benchmark_type == "timeseries":
                try:
                    cursor.execute("SET cairo.sql.parallel.filter.enabled = true")
                except Exception as e:
                    self.logger.debug(f"Could not set parallel filter: {e}")
        finally:
            cursor.close()

    def apply_platform_optimizations(
        self,
        platform_config: PlatformOptimizationConfiguration,
        connection: Any,
    ) -> None:
        """Apply QuestDB-specific platform optimizations.

        Applies session-level settings from the tuning configuration:
        - Parallel query execution
        - Page frame sizing
        - JIT compilation settings
        """
        self.log_verbose("Applying QuestDB platform optimizations")

        cursor = connection.cursor()
        try:
            # Enable parallel execution
            try:
                cursor.execute("SET cairo.sql.parallel.filter.enabled = true")
            except Exception as e:
                self.logger.debug(f"Could not set parallel filter: {e}")

            # Enable JIT compilation for filters
            try:
                cursor.execute("SET cairo.sql.jit.mode = on")
            except Exception as e:
                self.logger.debug(f"Could not set JIT mode: {e}")

            # Increase page frame for analytical workloads
            try:
                cursor.execute("SET cairo.page.frame.max.rows = 1000000")
            except Exception as e:
                self.logger.debug(f"Could not set page frame max rows: {e}")
        finally:
            cursor.close()

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to QuestDB.

        QuestDB does not support foreign keys or traditional primary keys.
        Constraints are a no-op for this platform.
        """

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
        """Execute a single query and return detailed results."""
        query = _rewriter_rewrite(query)
        result = execute_sql_query(
            connection,
            query,
            query_id,
            log_verbose=self.log_verbose,
            build_query_result_with_validation=self._build_query_result_with_validation,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )

        # Capture and merge the structured query plan (SUCCESS-guarded in the
        # helper; no EXPLAIN issued when capture_plans is off). The rewriter is
        # idempotent, so re-rewriting inside get_query_plan is safe.
        self._merge_plan_capture_into_result(result, connection, query, query_id)

        return result

    def get_query_plan(
        self,
        connection: Any,
        query: str,
        explain_options: dict[str, Any] | None = None,
    ) -> str:
        """Get query execution plan using EXPLAIN.

        QuestDB supports EXPLAIN for query plans but with fewer options
        than standard PostgreSQL. The plan is returned as a ``QUERY PLAN`` text
        column (one row per line). On failure returns an error string (which the
        plan-capture parser rejects via its error-sentinel guard, so capture
        degrades silently rather than fabricating a plan).
        """
        query = _rewriter_rewrite(query)
        # In TPC-DS streaming paths a per-stream cursor is passed as
        # `connection`; detect by checking for a callable .cursor() method.
        _owns_cursor = callable(getattr(connection, "cursor", None))
        cursor = connection.cursor() if _owns_cursor else connection

        explain_query = f"EXPLAIN {query}"

        try:
            cursor.execute(explain_query)
            plan_rows = cursor.fetchall()
            if _owns_cursor:
                cursor.close()

            return "\n".join(str(row[0]) for row in plan_rows)

        except Exception as e:
            if _owns_cursor:
                cursor.close()
            return f"Failed to get query plan: {e}"

    def get_query_plan_parser(self):
        """Get the QuestDB query plan parser."""
        from benchbox.core.query_plans.parsers.questdb import QuestDBQueryPlanParser

        return QuestDBQueryPlanParser()

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get QuestDB platform information."""
        platform_info = {
            "platform_type": "questdb",
            "platform_name": "QuestDB",
            "host": self.host,
            "pg_port": self.pg_port,
            "http_port": self.http_port,
            "dialect": QUESTDB_DIALECT,
            "configuration": {
                "database": self.database,
                "loading_method": self.loading_method,
                "partition_by": self.partition_by,
                "ilp_port": self.ilp_port,
            },
        }

        if connection:
            try:
                cursor = connection.cursor()

                # Get QuestDB version
                cursor.execute("SELECT build")
                version_row = cursor.fetchone()
                if version_row:
                    platform_info["version"] = str(version_row[0])

                cursor.close()
            except Exception as e:
                self.logger.debug(f"Could not get QuestDB version: {e}")
                platform_info["version"] = "unknown"

        return platform_info

    def check_database_exists(self, **connection_config) -> bool:
        """Check if QuestDB is reachable.

        QuestDB uses a single database per instance, so this just tests connectivity.
        """
        try:
            params = self._get_connection_params()
            conn = psycopg.connect(**params)
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return True
        except Exception:
            return False

    def get_database_path(self, **connection_config) -> str | None:
        """QuestDB is server-based, no local file path."""
        return None

    def table_exists(self, connection: Any, table_name: str) -> bool:
        """Check if a table exists in QuestDB."""
        if not self._validate_identifier(table_name):
            return False

        try:
            cursor = connection.cursor()
            cursor.execute("SELECT table_name FROM tables() WHERE table_name = %s", (table_name,))
            result = cursor.fetchone()
            cursor.close()
            return result is not None
        except Exception:
            return False

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables in QuestDB.

        Overrides the base implementation which calls connection.execute() - a
        DuckDB-style API that psycopg connections do not support.  QuestDB
        exposes its table catalog via the ``tables()`` function.
        """
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT table_name FROM tables()")
            rows = cursor.fetchall()
            cursor.close()
            return [row[0].lower() for row in rows]
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    def drop_table(self, connection: Any, table_name: str) -> None:
        """Drop a table from QuestDB."""
        if not self._validate_identifier(table_name):
            self.logger.warning(f"Invalid table identifier: {table_name}")
            return

        try:
            cursor = connection.cursor()
            self.log_notice(f'Dropping table if it exists: "{table_name}"')
            cursor.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            cursor.close()
        except Exception as e:
            self.logger.warning(f"Failed to drop table {table_name}: {e}")


# ──────────────────────────────────────────────────────────────────────
# ILP helper functions
# ──────────────────────────────────────────────────────────────────────


def _ilp_escape_measurement(measurement: str) -> str:
    """Escape an ILP measurement name (commas, spaces, equals)."""
    return measurement.replace(",", r"\,").replace(" ", r"\ ").replace("=", r"\=")


def _ilp_escape_tag_key(key: str) -> str:
    """Escape an ILP tag key."""
    return key.replace(",", r"\,").replace("=", r"\=").replace(" ", r"\ ")


def _ilp_escape_field(col_name: str, value: str) -> str | None:
    """Format a column value as an ILP field-set entry.

    Returns ``col_name=value`` with appropriate ILP type quoting:
    - Integers: ``42i``
    - Floats: ``3.14``
    - Strings: ``"hello"``

    Args:
        col_name: Column (field) name.
        value: String value from CSV.

    Returns:
        ILP field string, or None if value is empty.
    """
    if not value:
        return None

    escaped_key = _ilp_escape_tag_key(col_name)

    # Try integer
    try:
        int_val = int(value)
        return f"{escaped_key}={int_val}i"
    except ValueError:
        pass

    # Try float
    try:
        float_val = float(value)
        return f"{escaped_key}={float_val}"
    except ValueError:
        pass

    # String - escape double quotes and backslashes
    escaped_val = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'{escaped_key}="{escaped_val}"'


def _build_questdb_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build QuestDB database configuration from CLI platform options.

    Args:
        platform: Platform name (should be 'questdb')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with connection parameters at the top level so that
        ``QuestDBAdapter.from_config()`` can read them via ``config.get()``.
    """
    import os

    from benchbox.core.schemas import DatabaseConfig

    merged: dict[str, Any] = {}
    merged.update(options)
    merged.update(overrides)

    name = info.display_name if info else "QuestDB"
    driver_package = info.driver_package if info else "psycopg"

    config_dict: dict[str, Any] = {
        "type": "questdb",
        "name": name,
        "options": merged,
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Connection parameters at top level so from_config() can read them via config.get()
        "host": merged.get("host") or os.environ.get("QUESTDB_HOST", "localhost"),
        "pg_port": int(merged.get("pg_port") or os.environ.get("QUESTDB_PG_PORT", "8812")),
        "http_port": int(merged.get("http_port") or os.environ.get("QUESTDB_HTTP_PORT", "9000")),
        "ilp_port": int(merged.get("ilp_port") or os.environ.get("QUESTDB_ILP_PORT", "9009")),
        "username": merged.get("username") or os.environ.get("QUESTDB_USER", "admin"),
        "password": merged.get("password") or os.environ.get("QUESTDB_PASSWORD", "quest"),
        "database": merged.get("database") or os.environ.get("QUESTDB_DATABASE", "qdb"),
        "loading_method": merged.get("loading_method", "rest"),
    }
    return DatabaseConfig(**config_dict)


def _date_to_epoch_ns(date_str: str) -> str | None:
    """Convert a date string to nanosecond epoch for ILP timestamp.

    Supports formats: YYYY-MM-DD, YYYY-MM-DD HH:MM:SS

    Args:
        date_str: Date string.

    Returns:
        Nanosecond epoch string, or None on failure.
    """
    from datetime import datetime, timezone

    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
            epoch_s = int(dt.timestamp())
            return str(epoch_s * 1_000_000_000)
        except ValueError:
            continue
    return None
