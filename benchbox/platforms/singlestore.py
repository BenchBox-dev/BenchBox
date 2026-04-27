"""SingleStore platform adapter for BenchBox benchmarking.

Provides SingleStore-specific functionality including:
- MySQL wire protocol connectivity via singlestoredb SDK (port 3306)
- LOAD DATA LOCAL INFILE for efficient bulk data loading
- Columnstore DDL with shard key configuration for analytics
- Support for both Helios (cloud) and self-managed deployments
- SQLGlot 'mysql' dialect for SQL transpilation

SingleStore (formerly MemSQL) is a distributed SQL database designed for
real-time analytics and transactions with both row and column storage.
For analytical benchmarks (TPC-H, TPC-DS), columnstore tables provide
dramatically better performance than the default rowstore.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
from benchbox.platforms.base.ddl_optimizer import BaseDdlOptimizer
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
        TableTuning,
        UnifiedTuningConfiguration,
    )

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from ..utils.file_format import get_data_extension
from .base import DriverIsolationCapability, PlatformAdapter
from .base.data_loading import (
    CsvDialect,
    DataSourceResolver,
    normalize_table_paths,
    prepare_local_load_file,
    resolve_csv_dialect,
)
from .base.sql_execution import execute_sql_query

# SQLGlot dialect - SingleStore is MySQL-compatible
SINGLESTORE_DIALECT = "mysql"

try:
    import singlestoredb as _s2
except ImportError:
    _s2 = None

# Default port for SingleStore MySQL protocol
_DEFAULT_PORT = 3306

# TPC-H shard key columns (best join/filter column per table).
# NOTE: Only TPC-H tables are mapped. TPC-DS and other benchmark tables
# will fall back to SHARD KEY () (random distribution), which is functional
# but suboptimal for join-heavy queries. Add TPC-DS mappings when needed.
_TPCH_SHARD_KEYS: dict[str, str] = {
    "lineitem": "l_orderkey",
    "orders": "o_orderkey",
    "customer": "c_custkey",
    "part": "p_partkey",
    "supplier": "s_suppkey",
    "partsupp": "ps_partkey",
}

# TPC-H sort key columns (primary analytical ordering)
_TPCH_SORT_KEYS: dict[str, list[str]] = {
    "lineitem": ["l_orderkey", "l_linenumber"],
    "orders": ["o_orderkey"],
    "customer": ["c_custkey"],
    "part": ["p_partkey"],
    "supplier": ["s_suppkey"],
    "partsupp": ["ps_partkey", "ps_suppkey"],
}

# Small dimension tables that benefit from REFERENCE TABLE (replicated everywhere)
# avoids broadcast joins for nation/region lookups
_REFERENCE_TABLES = {"nation", "region"}

# Parquet files cannot be loaded via LOAD DATA LOCAL INFILE
_PARQUET_EXTENSIONS = {".parquet"}


def _col_in_stmt(col_name: str, stmt: str) -> bool:
    """Return True if col_name appears as a column identifier in the CREATE TABLE stmt."""
    pattern = rf"(?<![a-zA-Z0-9_]){re.escape(col_name)}(?![a-zA-Z0-9_])"
    return bool(re.search(pattern, stmt, re.IGNORECASE))


_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`?\w+`?\.)?`?(\w+)`?",
    re.IGNORECASE,
)


def _extract_create_table_name(stmt: str) -> str | None:
    """Extract lowercase table name from a CREATE TABLE statement, or return None."""
    m = _CREATE_TABLE_RE.match(stmt.strip())
    return m.group(1).lower() if m else None


class SingleStoreAdapter(BaseDdlOptimizer, PlatformAdapter):
    """SingleStore platform adapter with LOAD DATA LOCAL INFILE bulk loading.

    Supports SingleStore 8.0+ with columnstore analytical tables.
    Uses singlestoredb SDK for MySQL protocol connectivity and
    LOAD DATA LOCAL INFILE for efficient bulk data loading.

    Connection Configuration:
    - Host: SingleStore node hostname or Helios endpoint
    - Port: 3306 (default MySQL protocol port)
    - Username: SingleStore user (default: 'root')
    - Password: SingleStore password
    - Database: Target database name

    Environment Variables:
    - SINGLESTORE_HOST: Node hostname
    - SINGLESTORE_PORT: MySQL protocol port
    - SINGLESTORE_USER or SINGLESTORE_USERNAME: Username
    - SINGLESTORE_PASSWORD: Password
    - SINGLESTORE_DATABASE: Default database name
    """

    _platform_key: ClassVar[str] = "singlestore"

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    @property
    def platform_name(self) -> str:
        return "SingleStore"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for SingleStore (MySQL-compatible)."""
        return SINGLESTORE_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add SingleStore-specific CLI arguments.

        Legacy flags for the setup wizard (``benchbox platforms setup``).
        The ``benchbox run`` flow uses ``--platform-option key=val`` instead
        and does NOT call ``add_cli_arguments``.  Keep in sync with the
        option specs registered in ``benchbox/platforms/__init__.py``.
        """
        if not hasattr(parser, "add_argument"):
            return
        try:
            parser.add_argument(
                "--singlestore-host",
                dest="host",
                default=None,
                help="SingleStore node hostname or Helios endpoint",
            )
            parser.add_argument(
                "--singlestore-port",
                dest="port",
                type=int,
                default=None,
                help="SingleStore MySQL protocol port (default: 3306)",
            )
            parser.add_argument(
                "--singlestore-database",
                dest="database",
                help="SingleStore database name (auto-generated if not specified)",
            )
            parser.add_argument(
                "--singlestore-username",
                dest="username",
                default=None,
                help="SingleStore username (default: root)",
            )
            parser.add_argument(
                "--singlestore-password",
                dest="password",
                help="SingleStore password",
            )
        except Exception as e:
            import logging

            logging.getLogger(__name__).debug("Failed to register CLI arguments: %s", e)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> SingleStoreAdapter:
        """Create SingleStore adapter from unified configuration.

        Standard connection parameters (host/port/credentials) are resolved
        once by the config builder (_build_singlestore_config) before this
        method is called.  from_config() passes those resolved values through
        and handles benchmark-derived database naming, which requires the
        benchmark + scale_factor context that the builder carries forward.
        """
        adapter_config: dict[str, Any] = {}

        # Pass through connection parameters already resolved by the config builder.
        for key in ["host", "port", "username", "password"]:
            if config.get(key) is not None:
                adapter_config[key] = config[key]

        # Database name - use provided or generate from benchmark config
        if config.get("database"):
            adapter_config["database"] = config["database"]
        elif db_env := os.environ.get("SINGLESTORE_DATABASE"):
            adapter_config["database"] = db_env
        elif config.get("benchmark") and config.get("scale_factor") is not None:
            from benchbox.utils.scale_factor import format_benchmark_name

            benchmark_name = format_benchmark_name(config["benchmark"], config["scale_factor"])
            adapter_config["database"] = f"benchbox_{benchmark_name}".lower().replace("-", "_")

        # Pass through other config
        for key in ["force_recreate", "tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]
        if "force" in config:
            adapter_config["force_recreate"] = config["force"]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)

        if _s2 is None:
            available, missing = check_platform_dependencies("singlestore")
            if not available:
                error_msg = get_dependency_error_message("singlestore", missing)
                raise ImportError(error_msg)

        self._dialect = SINGLESTORE_DIALECT

        # Connection configuration.
        # The config builder (_build_singlestore_config) is the single owner of
        # env var resolution for the standard CLI path. __init__ just consumes
        # whatever it receives; simple Python defaults cover direct-construction
        # paths (e.g. tests) where no builder ran.
        self.host = config.get("host", "localhost")
        self.port = config.get("port", _DEFAULT_PORT)
        self.database = config.get("database", "benchbox")
        self.username = config.get("username", "root")
        self.password = config.get("password")

        if not self._validate_identifier(self.database):
            raise ValueError(f"Invalid database identifier: {self.database}")

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate SQL identifier to prevent injection."""
        if not identifier or not isinstance(identifier, str):
            return False
        if len(identifier) > 128:
            return False
        return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", identifier))

    def _admin_connect(self) -> Any:
        """Create a connection without selecting a database."""
        return _s2.connect(
            host=self.host,
            port=self.port,
            user=self.username,
            password=self.password,
            connect_timeout=10,
        )

    def check_server_database_exists(
        self,
        schema: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
        **_kwargs,
    ) -> bool:
        """Check if a database exists on the SingleStore server."""
        db_name = database or self.database

        try:
            conn = self._admin_connect()
            try:
                cursor = conn.cursor()
                cursor.execute("SHOW DATABASES")
                databases = [row[0] for row in cursor.fetchall()]
                cursor.close()
                return db_name in databases
            finally:
                conn.close()
        except Exception as e:
            # CR_CONN_HOST_ERROR (2003) means the server is unreachable, not that the
            # database is absent. Re-raise so callers get an actionable error instead of
            # silently treating an unreachable server as a missing database.
            if e.args and e.args[0] == 2003:
                raise
            self.logger.debug(f"Failed to check database existence: {e}")
            return False

    def drop_database(
        self,
        schema: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
        **_kwargs,
    ) -> None:
        """Drop a database from the SingleStore server."""
        db_name = database or self.database

        if not self._validate_identifier(db_name):
            raise ValueError(f"Invalid database identifier: {db_name}")

        conn = self._admin_connect()
        try:
            cursor = conn.cursor()
            # Safety: db_name validated by _validate_identifier() above
            cursor.execute(f"DROP DATABASE IF EXISTS `{db_name}`")
            cursor.close()
            self.logger.info(f"Dropped database: {db_name}")
        except Exception as e:
            self.logger.warning(f"Failed to drop database {db_name}: {e}")
            raise
        finally:
            conn.close()

    def _create_database(self) -> None:
        """Create the target database if it doesn't exist."""
        if not self._validate_identifier(self.database):
            raise ValueError(f"Invalid database identifier: {self.database}")

        conn = self._admin_connect()
        try:
            cursor = conn.cursor()
            # Safety: self.database validated by _validate_identifier() above
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.database}`")
            cursor.close()
            self.logger.info(f"Created database: {self.database}")
        except Exception as e:
            self.logger.error(f"Failed to create database: {e}")
            raise
        finally:
            conn.close()

    def create_connection(self, **connection_config) -> Any:
        """Create SingleStore connection via MySQL protocol (singlestoredb SDK)."""
        self.log_operation_start("SingleStore connection")

        try:
            self.handle_existing_database(**connection_config)

            if not self.check_server_database_exists():
                self._create_database()

            conn = _s2.connect(
                host=self.host,
                port=self.port,
                user=self.username,
                password=self.password,
                database=self.database,
                connect_timeout=10,
                local_infile=True,
            )

            # Verify connection
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()

            self.log_operation_complete(
                "SingleStore connection",
                details=f"Connected to {self.host}:{self.port}/{self.database}",
            )
            return conn
        except Exception as e:
            if e.args and e.args[0] == 2003:
                raise RuntimeError(
                    f"Cannot connect to SingleStore at {self.host}:{self.port} — "
                    f"verify the server is running and connection settings are correct"
                ) from e
            raise

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        cursor = connection.cursor()
        critical_failures = []

        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        try:
            for stmt in statements:
                try:
                    transformed = self._transform_create_statement(stmt)
                    cursor.execute(transformed)
                except Exception as e:
                    is_create_table = stmt.strip().upper().startswith("CREATE TABLE")
                    if is_create_table:
                        critical_failures.append((stmt[:80], str(e)))
                    self.logger.warning(f"Schema statement failed: {e}")
            connection.commit()
        finally:
            cursor.close()

        if critical_failures:
            failed_summary = "; ".join(f"{s}: {err}" for s, err in critical_failures)
            raise RuntimeError(f"{len(critical_failures)} critical CREATE TABLE statement(s) failed: {failed_summary}")

        duration = elapsed_seconds(start_time)
        self.log_operation_complete("Schema creation", duration, "Schema and tables created")
        return duration

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data using LOAD DATA LOCAL INFILE."""
        start_time = mono_time()
        table_stats = {}
        per_table_timings = {}

        self.log_operation_start("Data loading", f"source: {data_dir}")

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
            return {}, loading_time, {}

        for table_name, table_path in data_source.tables.items():
            table_name_lower = table_name.lower()

            if not self._validate_identifier(table_name_lower):
                raise ValueError(f"Invalid table identifier: {table_name!r}")

            data_files = [f for f in normalize_table_paths(table_path) if f.exists()]
            if not data_files:
                self.logger.warning(f"Data file not found for {table_name_lower}")
                table_stats[table_name_lower] = 0
                continue

            table_start = mono_time()
            table_rows = 0

            try:
                for data_file in data_files:
                    if data_file.suffix.lower() in _PARQUET_EXTENSIONS:
                        self.logger.warning(
                            f"Skipping {data_file.name}: LOAD DATA LOCAL INFILE does not support Parquet"
                        )
                        continue
                    dialect = resolve_csv_dialect(data_source, table_name, data_file, benchmark)
                    # Strip trailing delimiter for TPC-H .tbl and TPC-DS .dat files:
                    # both dbgen and dsdgen emit a spurious trailing pipe after every
                    # record. CSV files must NOT be stripped: a trailing comma means the
                    # last field is empty/NULL, not a junk terminator.
                    strip_trailing_delim = get_data_extension(data_file) in (".tbl", ".dat")
                    table_rows += self._load_data_infile(
                        connection, table_name_lower, data_file, dialect, strip_trailing_delim
                    )
                table_stats[table_name_lower] = table_rows
                table_duration = elapsed_seconds(table_start)
                per_table_timings[table_name_lower] = {
                    "rows": table_rows,
                    "duration_seconds": table_duration,
                }
                self.log_verbose(f"Loaded {table_rows:,} rows into {table_name_lower}")

            except Exception as e:
                self.logger.error(f"Failed to load {table_name_lower}: {e}")
                table_stats[table_name_lower] = 0

        loading_time = elapsed_seconds(start_time)
        total_rows = sum(table_stats.values())
        self.log_operation_complete("Data loading", loading_time, f"Loaded {total_rows:,} total rows")

        return table_stats, loading_time, per_table_timings

    def _load_data_infile(
        self,
        connection: Any,
        table_name: str,
        data_file: Path,
        dialect: CsvDialect,
        strip_trailing_delim: bool = False,
    ) -> int:
        """Load a data file using LOAD DATA LOCAL INFILE.

        Decompression, trailing-delimiter stripping, and boolean normalisation
        are handled by prepare_local_load_file() — this method only builds and
        executes the LOAD DATA SQL.

        Args:
            connection: Active SingleStore connection (local_infile=True)
            table_name: Target table name (pre-validated)
            data_file: Path to the data file
            dialect: Resolved CSV dialect (delimiter, has_header, null_marker, normalize_booleans)
            strip_trailing_delim: Strip trailing field delimiter from each row.
                True for .tbl files; False for .dat, .csv, and everything else.

        Returns:
            Number of rows loaded
        """
        with prepare_local_load_file(
            data_file, dialect=dialect, strip_trailing_delim=strip_trailing_delim
        ) as load_path:
            cursor = connection.cursor()
            try:
                # Count existing rows so we return only the delta (correct on retry)
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                pre_row = cursor.fetchone()
                pre_count = int(pre_row[0]) if pre_row else 0

                # Safety: load_path is framework-controlled (tempfile or data_dir),
                # not user input.  Escaping here is defence-in-depth only.
                escaped_path = str(load_path).replace("\\", "\\\\").replace("'", "\\'")
                escaped_delim = dialect.delimiter.replace("\\", "\\\\").replace("'", "\\'")
                clauses = [
                    f"LOAD DATA LOCAL INFILE '{escaped_path}'",
                    f"INTO TABLE `{table_name}`",
                    f"FIELDS TERMINATED BY '{escaped_delim}' OPTIONALLY ENCLOSED BY '\"'",
                ]
                if dialect.null_marker is not None:
                    escaped_null = dialect.null_marker.replace("\\", "\\\\").replace("'", "\\'")
                    clauses.append(f"NULL DEFINED BY '{escaped_null}'")
                clauses.append("LINES TERMINATED BY '\\n'")
                if dialect.has_header:
                    clauses.append("IGNORE 1 LINES")
                sql = " ".join(clauses)
                cursor.execute(sql)

                # LOAD DATA doesn't return rowcount reliably; use delta COUNT(*)
                cursor.execute(f"SELECT COUNT(*) FROM `{table_name}`")
                post_row = cursor.fetchone()
                post_count = int(post_row[0]) if post_row else 0
                return post_count - pre_count
            finally:
                cursor.close()

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply SingleStore session settings for benchmark execution."""
        cursor = connection.cursor()
        try:
            try:
                # Disable query cache for reproducible results
                cursor.execute("SET SESSION query_cache_type = 0")
            except Exception as e:
                self.logger.debug(f"Could not disable query cache: {e}")

            try:
                # Allow large result sets
                cursor.execute("SET SESSION max_allowed_packet = 1073741824")
            except Exception as e:
                self.logger.debug(f"Could not set max_allowed_packet: {e}")
        finally:
            cursor.close()

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
        return execute_sql_query(
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

    def get_query_plan(
        self,
        connection: Any,
        query: str,
        explain_options: dict[str, Any] | None = None,
    ) -> str:
        """Get query execution plan using EXPLAIN."""
        cursor = connection.cursor()

        explain_query = f"EXPLAIN {query}"

        try:
            cursor.execute(explain_query)
            plan_rows = cursor.fetchall()
            cursor.close()
            return "\n".join(str(row) for row in plan_rows)
        except Exception as e:
            cursor.close()
            return f"Failed to get query plan: {e}"

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE on a table to update statistics."""
        if not self._validate_identifier(table_name):
            self.logger.warning(f"Invalid table identifier: {table_name}")
            return

        cursor = connection.cursor()
        try:
            # Safety: table_name validated by _validate_identifier() above
            cursor.execute(f"ANALYZE TABLE `{table_name}`")
        except Exception as e:
            self.logger.warning(f"ANALYZE failed for {table_name}: {e}")
        finally:
            cursor.close()

    def close_connection(self, connection: Any) -> None:
        """Close SingleStore connection."""
        if connection:
            try:
                connection.close()
            except Exception as e:
                self.logger.debug(f"Error closing connection: {e}")

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get SingleStore platform information."""
        platform_info: dict[str, Any] = {
            "platform_type": "singlestore",
            "platform_name": "SingleStore",
            "host": self.host,
            "port": self.port,
            "dialect": SINGLESTORE_DIALECT,
            "configuration": {
                "database": self.database,
                "singlestoredb_available": _s2 is not None,
            },
        }

        if connection:
            try:
                cursor = connection.cursor()

                cursor.execute("SELECT @@memsql_version")
                version_row = cursor.fetchone()
                if version_row:
                    platform_info["platform_version"] = version_row[0]

                cursor.execute("SELECT DATABASE()")
                db_row = cursor.fetchone()
                if db_row:
                    platform_info["configuration"]["current_database"] = db_row[0]

                cursor.close()
            except Exception as e:
                self.logger.debug(f"Error getting platform info: {e}")

        if _s2:
            platform_info["client_library_version"] = getattr(_s2, "__version__", "unknown")

        return platform_info

    def test_connection(self) -> bool:
        """Test if connection can be established."""
        try:
            conn = _s2.connect(
                host=self.host,
                port=self.port,
                user=self.username,
                password=self.password,
                connect_timeout=10,
            )
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()
            return True
        except Exception as e:
            self.logger.debug(f"Connection test failed: {e}")
            return False

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables in the database."""
        try:
            cursor = connection.cursor()
            cursor.execute("SHOW TABLES")
            result = cursor.fetchall()
            cursor.close()
            return [row[0].lower() for row in result]
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    # ------------------------------------------------------------------ #
    # DDL transformation - inject columnstore, shard/sort keys
    # ------------------------------------------------------------------ #

    def _transform_create_statement(self, stmt: str) -> str:
        """Transform a CREATE TABLE statement for SingleStore columnstore DDL.

        Handles non-CREATE-TABLE passthrough, table-name normalization (MySQL
        lower_case_table_names=0 detail), then delegates to
        optimize_table_definition() for the registered DDL_OPTIMIZE transforms.

        Args:
            stmt: A single SQL statement (no trailing semicolon)

        Returns:
            Transformed SQL statement
        """
        stripped = stmt.strip()
        upper = stripped.upper()

        if not upper.startswith("CREATE TABLE"):
            return stmt

        # Extract table name from CREATE TABLE [schema.]`name` or CREATE TABLE name
        table_match = _CREATE_TABLE_RE.match(stripped)
        if not table_match:
            return stmt

        table_name = table_match.group(1).lower()

        # Normalize table name to lowercase with backtick quoting.
        # SingleStore uses lower_case_table_names=0 (case-sensitive), so DimDate ≠ dimdate.
        # load_data always uses table_name.lower(), so CREATE TABLE must match.
        orig_name = table_match.group(1)
        if orig_name != table_name:
            name_start = table_match.start(1)
            name_end = table_match.end(1)
            if name_start > 0 and stripped[name_start - 1] == "`":
                name_start -= 1
            if name_end < len(stripped) and stripped[name_end] == "`":
                name_end += 1
            stripped = stripped[:name_start] + f"`{table_name}`" + stripped[name_end:]

        return self.optimize_table_definition(stripped, table_name)

    # -- Registered transformer methods (transformer_id keys) ------------- #

    def singlestore_strip_foreign_keys(self, stmt: str) -> str:
        """Remove FOREIGN KEY clauses (SingleStore error 2752)."""
        return strip_foreign_keys(stmt)

    def singlestore_reference_table(self, stmt: str) -> str:
        """Rewrite CREATE TABLE to CREATE REFERENCE TABLE for small dimension tables."""
        table_name = _extract_create_table_name(stmt)
        if table_name is None:
            return stmt
        if self.is_reference_table(table_name):
            return re.sub(r"CREATE\s+TABLE", "CREATE REFERENCE TABLE", stmt, count=1, flags=re.IGNORECASE)
        return stmt

    def singlestore_inject_shard_key(self, stmt: str) -> str:
        """Inject SHARD KEY clause for columnstore tables (skipped for REFERENCE TABLE)."""
        if re.search(r"\bCREATE\s+REFERENCE\s+TABLE\b", stmt, re.IGNORECASE):
            return stmt
        table_name = _extract_create_table_name(stmt)
        if table_name is None:
            return stmt
        # SingleStore derives an implicit shard key from PRIMARY KEY; adding
        # an explicit SHARD KEY () would cause error 1706.
        has_primary_key = bool(re.search(r"\bPRIMARY\s+KEY\b", stmt, re.IGNORECASE))
        shard_col = _TPCH_SHARD_KEYS.get(table_name)
        if shard_col and _col_in_stmt(shard_col, stmt):
            clause = f"SHARD KEY ({shard_col})"
        elif not has_primary_key:
            clause = "SHARD KEY ()"
        else:
            return stmt
        last_paren = stmt.rfind(")")
        if last_paren == -1:
            return stmt
        before = stmt[:last_paren].rstrip()
        after = stmt[last_paren + 1 :].strip()
        result = f"{before},\n{clause}\n)"
        if after:
            result += f"\n{after}"
        return result

    def singlestore_inject_sort_key(self, stmt: str) -> str:
        """Inject SORT KEY clause for columnstore tables (skipped for REFERENCE TABLE)."""
        if re.search(r"\bCREATE\s+REFERENCE\s+TABLE\b", stmt, re.IGNORECASE):
            return stmt
        table_name = _extract_create_table_name(stmt)
        if table_name is None:
            return stmt
        sort_cols = _TPCH_SORT_KEYS.get(table_name, [])
        present_sort_cols = [c for c in sort_cols if _col_in_stmt(c, stmt)]
        if not present_sort_cols:
            return stmt
        clause = f"SORT KEY ({', '.join(present_sort_cols)})"
        last_paren = stmt.rfind(")")
        if last_paren == -1:
            return stmt
        before = stmt[:last_paren].rstrip()
        after = stmt[last_paren + 1 :].strip()
        result = f"{before},\n{clause}\n)"
        if after:
            result += f"\n{after}"
        return result

    # ------------------------------------------------------------------ #
    # DDL generation - columnstore tables with shard keys
    # ------------------------------------------------------------------ #

    def get_shard_key_clause(self, table_name: str) -> str:
        """Generate SHARD KEY clause for a table.

        Uses well-known join/filter columns for TPC tables.
        Falls back to an empty shard key (random distribution) for unknowns.

        Args:
            table_name: Lowercase table name

        Returns:
            DDL clause string, e.g. ``SHARD KEY (l_orderkey)``
        """
        shard_col = _TPCH_SHARD_KEYS.get(table_name)
        if shard_col:
            return f"SHARD KEY ({shard_col})"
        return "SHARD KEY ()"

    def get_sort_key_clause(self, table_name: str) -> str:
        """Generate SORT KEY clause for columnstore sort ordering.

        Args:
            table_name: Lowercase table name

        Returns:
            DDL clause string, e.g. ``SORT KEY (l_orderkey, l_linenumber)``
        """
        sort_cols = _TPCH_SORT_KEYS.get(table_name)
        if sort_cols:
            cols_str = ", ".join(sort_cols)
            return f"SORT KEY ({cols_str})"
        return ""

    def is_reference_table(self, table_name: str) -> bool:
        """Return True if this table should be a REFERENCE TABLE.

        Reference tables are fully replicated to every leaf node, which
        eliminates broadcast joins for small dimension tables like
        nation and region.

        Args:
            table_name: Lowercase table name

        Returns:
            True if the table should be created as a REFERENCE TABLE
        """
        return table_name in _REFERENCE_TABLES

    # ------------------------------------------------------------------ #
    # Tuning hooks (stubs - DDL carries the analytical optimizations)
    # ------------------------------------------------------------------ #

    def apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None:
        """Apply tuning configurations to SingleStore tables."""

    def generate_tuning_clause(self, table_tuning: TableTuning | None) -> str:
        """Generate SingleStore-specific tuning clauses."""
        return ""

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration."""

    def apply_platform_optimizations(
        self,
        platform_config: PlatformOptimizationConfiguration,
        connection: Any,
    ) -> None:
        """Apply SingleStore-specific optimizations."""

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations.

        Note: SingleStore does not enforce foreign key constraints.
        Primary keys are used for shard-key alignment, not FK enforcement.
        """

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate SingleStore-specific capabilities for the benchmark."""
        errors = []
        warnings = []

        if _s2 is None:
            errors.append("singlestoredb library not available - install with 'uv add singlestoredb'")
        else:
            try:
                version = getattr(_s2, "__version__", "unknown")
                self.logger.debug(f"singlestoredb version: {version}")
            except Exception:
                pass

        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
            "singlestoredb_available": _s2 is not None,
            "host": self.host,
            "port": self.port,
            "database": self.database,
        }

        try:
            from benchbox.core.validation import ValidationResult

            return ValidationResult(
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                details=platform_info,
            )
        except ImportError:
            return None

    def validate_connection_health(self, connection: Any):
        """Validate SingleStore connection health and capabilities."""
        errors = []
        warnings = []
        connection_info = {}

        try:
            cursor = connection.cursor()

            cursor.execute("SELECT 1 as test_value")
            result = cursor.fetchone()
            if result[0] != 1:
                errors.append("Basic query execution test failed")
            else:
                connection_info["basic_query_test"] = "passed"

            try:
                cursor.execute("SELECT @@memsql_version")
                version_result = cursor.fetchone()
                if version_result:
                    connection_info["server_version"] = version_result[0]
            except Exception:
                warnings.append("Could not query SingleStore version")

            try:
                cursor.execute("SELECT DATABASE()")
                db_result = cursor.fetchone()
                if db_result:
                    connection_info["current_database"] = db_result[0]
            except Exception:
                warnings.append("Could not query current database")

            cursor.close()
        except Exception as e:
            errors.append(f"Connection health check failed: {str(e)}")

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
            return None

    def supports_tuning_type(self, tuning_type: Any) -> bool:
        """Check if SingleStore supports a specific tuning type."""
        try:
            from benchbox.core.tuning.interface import TuningType

            supported = {
                TuningType.PARTITIONING: False,  # Not used in standard benchmarks
                TuningType.SORTING: True,  # SORT KEY
                TuningType.DISTRIBUTION: True,  # SHARD KEY
                TuningType.CLUSTERING: False,  # No CLUSTER command
                TuningType.PRIMARY_KEYS: False,  # No enforced PKs
                TuningType.FOREIGN_KEYS: False,  # No FK enforcement
            }
            return supported.get(tuning_type, False)
        except ImportError:
            return False


def _build_singlestore_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build SingleStore database configuration with credential loading.

    Args:
        platform: Platform name (should be 'singlestore')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with credentials loaded
    """
    # Intentionally inline - not using build_platform_config because env-var fallback and int coercion
    # must happen at builder runtime for CLI/test parity. See the Group D TODO investigation notes.
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    # Load saved credentials
    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("singlestore") or {}

    # Priority: defaults < saved_creds < explicit_options < overrides
    explicit_options = overrides.get("_explicit_platform_options", {})
    merged_options: dict[str, Any] = {}
    merged_options.update(options)
    merged_options.update(saved_creds)
    merged_options.update(explicit_options)
    merged_options.update(overrides)

    name = info.display_name if info else "SingleStore"
    driver_package = info.driver_package if info else "singlestoredb"

    config_dict = {
        "type": "singlestore",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Platform-specific fields
        "host": merged_options.get("host") or os.environ.get("SINGLESTORE_HOST", "localhost"),
        "port": (
            merged_options.get("port")
            if merged_options.get("port") is not None
            else int(os.environ.get("SINGLESTORE_PORT", str(_DEFAULT_PORT)))
        ),
        "username": (
            merged_options.get("username")
            or os.environ.get("SINGLESTORE_USER")
            or os.environ.get("SINGLESTORE_USERNAME", "root")
        ),
        "password": merged_options.get("password") or os.environ.get("SINGLESTORE_PASSWORD"),
        "database": merged_options.get("database") or os.environ.get("SINGLESTORE_DATABASE"),
        # Benchmark context
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    return DatabaseConfig(**config_dict)
