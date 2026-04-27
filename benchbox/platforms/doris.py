"""Apache Doris platform adapter for BenchBox benchmarking.

Provides Apache Doris-specific functionality including:
- MySQL protocol connectivity via PyMySQL (port 9030)
- Stream Load HTTP API for efficient bulk data loading (with chunked support)
- Doris-specific DDL with table models (DUPLICATE/AGGREGATE/UNIQUE KEY)
- DISTRIBUTED BY HASH clause generation with configurable bucket counts
- PARTITION BY RANGE for large tables on date columns
- Bloom filter and Bitmap index creation
- Cache disable validation
- EXPLAIN for query plan capture
- SQLGlot 'doris' dialect for SQL transpilation

Apache Doris is a high-performance real-time analytical database based on
MPP architecture, supporting both high-concurrency point queries and
high-throughput complex analysis.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import gzip
import io
import math
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import urlparse, urlunparse

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
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
    FileFormatRegistry,
    GzipHandler,
    NoCompressionHandler,
    ZstdHandler,
    normalize_table_paths,
    resolve_csv_dialect,
)
from .base.sql_execution import execute_sql_query

# Doris dialect for SQLGlot
DORIS_DIALECT = "doris"

try:
    import pymysql
    import pymysql.cursors
except ImportError:
    pymysql = None

try:
    import requests as _requests
except ImportError:
    _requests = None

# Default chunk size for Stream Load: 10MB.
# Smaller chunks ensure each stream load request completes within the timeout,
# especially for Docker deployments on macOS where BE disk I/O is slow.
_DEFAULT_STREAM_LOAD_CHUNK_SIZE = 10 * 1024 * 1024
_DEFAULT_STREAM_LOAD_MAX_FILTER_RATIO = "0"

# Default bucket count for DISTRIBUTED BY HASH
_DEFAULT_BUCKETS = 10

# TPC-DS nullable DECIMAL column positions (0-based) per table.
# dsdgen emits empty string for NULL DECIMAL values; Doris strict mode rejects
# those rows as type-conversion errors. Preprocessing replaces "" with \N at
# these positions so NULL is expressed in the format Doris expects.
# Positions are exact schema column indices from tables.py - trailing-separator
# artifacts (the empty field produced by dsdgen's always-present row-terminating |)
# are intentionally excluded; Doris's CSV parser treats a trailing | as a terminator
# and discards the resulting empty field without a column-count error.
# Derived from benchbox/core/tpcds/schema/tables.py - update if the schema changes.
_TPCDS_DECIMAL_NULL_POSITIONS: dict[str, list[int]] = {
    "call_center": [29, 30],
    "catalog_returns": [18, 19, 20, 21, 22, 23, 24, 25, 26],
    "catalog_sales": [19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33],
    "customer_address": [11],
    "item": [5, 6],
    "promotion": [5],
    "store": [27, 28],
    "store_returns": [11, 12, 13, 14, 15, 16, 17, 18, 19],
    "store_sales": [11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
    "warehouse": [13],
    "web_returns": [15, 16, 17, 18, 19, 20, 21, 22, 23],
    "web_sales": [19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33],
    "web_site": [24, 25],
}


def _fix_tpcds_decimal_nulls(line: str, delimiter: str, positions: list[int]) -> str:
    """Replace empty strings at DECIMAL nullable positions with \\N.

    dsdgen emits ``""`` for NULL DECIMAL values. Doris strict mode rejects
    empty-to-DECIMAL coercions; ``\\N`` is the default Doris null_format
    and is accepted by strict mode for nullable columns.
    """
    fields = line.split(delimiter)
    for pos in positions:
        if pos < len(fields) and fields[pos] == "":
            fields[pos] = r"\N"
    return delimiter.join(fields)


def _format_filter_ratio(value: Any) -> str:
    """Normalize a Doris ``max_filter_ratio`` value."""
    ratio = float(value)
    if math.isnan(ratio) or math.isinf(ratio) or ratio < 0 or ratio > 1:
        raise ValueError(f"stream_load_max_filter_ratio must be between 0 and 1 inclusive, got {value!r}")
    if ratio == 0:
        return "0"
    return format(ratio, "g")


# Regexes for DDL clause injection (_inject_doris_ddl_clauses)
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`\"]?(\w+)[`\"]?\s*\(",
    re.IGNORECASE,
)
# Column definition parser: matches (name, type); known SQL types filter out constraint lines.
_KNOWN_SQL_TYPES = frozenset(
    {
        "int",
        "integer",
        "bigint",
        "smallint",
        "tinyint",
        "largeint",
        "float",
        "double",
        "decimal",
        "numeric",
        "string",
        "text",
        "varchar",
        "char",
        "boolean",
        "bool",
        "date",
        "datetime",
        "timestamp",
        "time",
        "json",
        "jsonb",
        "array",
        "map",
        "struct",
        "bitmap",
        "hll",
        "blob",
        "binary",
        "varbinary",
    }
)
_COL_DEF_RE = re.compile(r'[`"]?(\w+)[`"]?\s+(\w+)', re.MULTILINE)
# Types Doris rejects as key columns (unbounded or unsupported key types)
_NON_KEY_DORIS_TYPES = frozenset({"time", "json", "jsonb", "blob", "binary", "hll", "bitmap"})
_DORIS_ENGINE_VERSION_RE = re.compile(r"doris[-\s]v?(\d+\.\d+\.\d+(?:-[A-Za-z0-9]+)?)", re.IGNORECASE)

# TPC-H table key columns for DUPLICATE KEY model
_TPCH_TABLE_KEYS: dict[str, list[str]] = {
    "lineitem": ["l_orderkey", "l_linenumber"],
    "orders": ["o_orderkey"],
    "customer": ["c_custkey"],
    "part": ["p_partkey"],
    "supplier": ["s_suppkey"],
    "partsupp": ["ps_partkey", "ps_suppkey"],
    "nation": ["n_nationkey"],
    "region": ["r_regionkey"],
}

# TPC-H distribution keys (hash distribution column per table)
_TPCH_DISTRIBUTION_KEYS: dict[str, str] = {
    "lineitem": "l_orderkey",
    "orders": "o_orderkey",
    "customer": "c_custkey",
    "part": "p_partkey",
    "supplier": "s_suppkey",
    "partsupp": "ps_partkey",
    "nation": "n_nationkey",
    "region": "r_regionkey",
}

# TPC-H partition columns (date columns for PARTITION BY RANGE on large tables)
_TPCH_PARTITION_TABLES: dict[str, str] = {
    "lineitem": "l_shipdate",
    "orders": "o_orderdate",
}

# TPC-H partition date ranges
_TPCH_PARTITION_RANGES: dict[str, list[tuple[str, str, str]]] = {
    "lineitem": [
        ("p1992", "1992-01-01", "1993-01-01"),
        ("p1993", "1993-01-01", "1994-01-01"),
        ("p1994", "1994-01-01", "1995-01-01"),
        ("p1995", "1995-01-01", "1996-01-01"),
        ("p1996", "1996-01-01", "1997-01-01"),
        ("p1997", "1997-01-01", "1998-01-01"),
        ("p1998", "1998-01-01", "1999-01-01"),
    ],
    "orders": [
        ("p1992", "1992-01-01", "1993-01-01"),
        ("p1993", "1993-01-01", "1994-01-01"),
        ("p1994", "1994-01-01", "1995-01-01"),
        ("p1995", "1995-01-01", "1996-01-01"),
        ("p1996", "1996-01-01", "1997-01-01"),
        ("p1997", "1997-01-01", "1998-01-01"),
        ("p1998", "1998-01-01", "1999-01-01"),
    ],
}

# Bloom filter index targets: high-cardinality key columns
_TPCH_BLOOM_FILTER_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_orderkey"],
    "orders": ["o_orderkey"],
    "customer": ["c_custkey"],
    "supplier": ["s_suppkey"],
    "part": ["p_partkey"],
    "partsupp": ["ps_partkey"],
}

# Bitmap index targets: low-cardinality columns
_TPCH_BITMAP_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_returnflag", "l_linestatus"],
    "orders": ["o_orderstatus"],
    "part": ["p_type"],
}


def _split_sql_statements(sql: str) -> list[str]:
    """Split SQL on semicolons outside single-quoted string literals."""
    statements: list[str] = []
    current: list[str] = []
    n = len(sql)
    i = 0
    while i < n:
        c = sql[i]
        if c == "'":
            lit_start = i
            i += 1
            while i < n:
                lc = sql[i]
                if lc == "\\" and i + 1 < n:
                    i += 2
                    continue
                if lc == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            current.append(sql[lit_start:i])
        elif c == ";":
            stmt = "".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
            i += 1
        else:
            current.append(c)
            i += 1
    stmt = "".join(current).strip()
    if stmt:
        statements.append(stmt)
    return statements


def _normalize_doris_engine_version(
    mysql_protocol_version: object | None,
    version_comment: object | None,
) -> str | None:
    """Prefer Doris engine version metadata over the MySQL compatibility version."""
    if version_comment is not None:
        comment = str(version_comment).strip()
        match = _DORIS_ENGINE_VERSION_RE.search(comment)
        if match:
            return match.group(1)
        if comment:
            return comment

    if mysql_protocol_version is None:
        return None

    version_text = str(mysql_protocol_version).strip()
    return version_text or None


def _read_doris_version_details(cursor: Any) -> tuple[str | None, str | None, str | None]:
    """Read Doris engine and protocol version details from a live connection."""
    mysql_protocol_version = None
    version_comment = None

    try:
        cursor.execute("SELECT version()")
        version_row = cursor.fetchone()
        if version_row:
            mysql_protocol_version = version_row[0]
    except Exception:
        pass

    try:
        cursor.execute("SELECT @@version_comment")
        comment_row = cursor.fetchone()
        if comment_row:
            version_comment = comment_row[0]
    except Exception:
        pass

    platform_version = _normalize_doris_engine_version(mysql_protocol_version, version_comment)
    mysql_protocol_version_str = str(mysql_protocol_version) if mysql_protocol_version is not None else None
    version_comment_str = str(version_comment) if version_comment is not None else None
    return platform_version, mysql_protocol_version_str, version_comment_str


class _DorisConnectionWrapper:
    """Thin adapter that adds a DuckDB-compatible execute() to a PyMySQL connection.

    PyMySQL exposes execute() only on cursors; BenchBox benchmarks (write_primitives,
    transaction_primitives, metadata_primitives) call connection.execute(sql) directly.
    This wrapper intercepts that call and delegates to a fresh cursor.

    When ddl_optimizer is provided, CREATE TABLE statements are automatically transformed
    into Doris-compatible DDL (DUPLICATE KEY + DISTRIBUTED BY HASH + PROPERTIES) before
    execution, so staging tables created by benchmark setup code get valid Doris DDL.
    """

    def __init__(self, conn: Any, ddl_optimizer: Any = None) -> None:
        self._conn = conn
        self._ddl_optimizer = ddl_optimizer

    def _optimize_if_create(self, stmt: str) -> str:
        if self._ddl_optimizer is not None and "CREATE TABLE" in stmt.upper():
            return self._ddl_optimizer(stmt)
        return stmt

    def execute(self, sql: str, params: Any = None) -> Any:
        if not sql or not sql.strip():
            return self._conn.cursor()

        statements = _split_sql_statements(sql)

        if len(statements) <= 1:
            stmt = self._optimize_if_create(sql.strip())
            cursor = self._conn.cursor()
            cursor.execute(stmt, params)
            return cursor

        last_cursor: Any = None
        for stmt in statements:
            stmt = self._optimize_if_create(stmt)
            c = self._conn.cursor()
            c.execute(stmt)
            last_cursor = c
        return last_cursor if last_cursor is not None else self._conn.cursor()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


class DorisAdapter(PlatformAdapter):
    """Apache Doris platform adapter with Stream Load data loading.

    Supports Apache Doris 2.0+ with vectorized execution engine.
    Uses PyMySQL for MySQL protocol connectivity (port 9030) and
    HTTP Stream Load API for efficient bulk data loading.

    Connection Configuration:
    - Host: Doris FE node hostname
    - Port: 9030 (MySQL protocol, default)
    - HTTP Port: 8030 (Stream Load API, default)
    - Username: Doris user (default: 'root')
    - Password: Doris password (default: empty)

    Environment Variables:
    - DORIS_HOST: FE node hostname
    - DORIS_PORT: MySQL protocol port
    - DORIS_HTTP_PORT: Stream Load HTTP port
    - DORIS_USER or DORIS_USERNAME: Username
    - DORIS_PASSWORD: Password
    - DORIS_DATABASE: Default database name
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    @property
    def platform_name(self) -> str:
        return "Apache Doris"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Apache Doris."""
        return DORIS_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Doris-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            parser.add_argument(
                "--doris-host",
                dest="host",
                default=None,
                help="Doris FE node hostname",
            )
            parser.add_argument(
                "--doris-port",
                dest="port",
                type=int,
                default=None,
                help="Doris MySQL protocol port (default: 9030)",
            )
            parser.add_argument(
                "--doris-http-port",
                dest="http_port",
                type=int,
                default=None,
                help="Doris Stream Load HTTP port (default: 8030)",
            )
            parser.add_argument(
                "--doris-database",
                dest="database",
                help="Doris database name (auto-generated if not specified)",
            )
            parser.add_argument(
                "--doris-username",
                dest="username",
                default=None,
                help="Doris username (default: root)",
            )
            parser.add_argument(
                "--doris-password",
                dest="password",
                help="Doris password",
            )
            parser.add_argument(
                "--doris-use-tls",
                dest="use_tls",
                action="store_true",
                default=False,
                help="Use HTTPS for Stream Load API (default: HTTP)",
            )
        except Exception:
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DorisAdapter:
        """Create Doris adapter from unified configuration.

        Standard connection parameters (host/port/credentials) are resolved
        once by the config builder (_build_doris_config) before this method
        is called.  from_config() passes those resolved values through and
        handles benchmark-derived database naming, which requires the
        benchmark + scale_factor context that the builder carries forward.
        """
        adapter_config = {}

        # Pass through connection parameters already resolved by the config builder.
        # Simple Python defaults cover direct-construction paths (e.g. tests)
        # where no builder ran.
        adapter_config["host"] = config.get("host", "localhost")
        adapter_config["port"] = config.get("port", 9030)
        adapter_config["http_port"] = config.get("http_port", 8030)
        adapter_config["be_http_port"] = config.get("be_http_port", 8040)
        adapter_config["username"] = config.get("username", "root")
        adapter_config["password"] = config.get("password", "")

        # Database name - use provided or generate from benchmark config
        if config.get("database"):
            adapter_config["database"] = config["database"]
        elif db_env := os.environ.get("DORIS_DATABASE"):
            adapter_config["database"] = db_env
        elif config.get("benchmark") and config.get("scale_factor") is not None:
            from benchbox.utils.scale_factor import format_benchmark_name

            benchmark_name = format_benchmark_name(config["benchmark"], config["scale_factor"])
            adapter_config["database"] = f"benchbox_{benchmark_name}".lower().replace("-", "_")
        else:
            adapter_config["database"] = "benchbox"

        # TLS for Stream Load HTTP API
        adapter_config["use_tls"] = config.get("use_tls", False)

        # Force recreate
        adapter_config["force_recreate"] = config.get("force", False)

        # Doris-specific feature config
        for key in [
            "stream_load_chunk_size",
            "stream_load_max_filter_ratio",
            "table_model",
            "default_buckets",
            "replication_num",
            "enable_partitioning",
            "enable_bloom_filter",
            "enable_bitmap_index",
            "verify_ssl",
            "ca_cert_path",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        # Pass through other config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies
        if pymysql is None:
            available, missing = check_platform_dependencies("doris")
            if not available:
                error_msg = get_dependency_error_message("doris", missing)
                raise ImportError(error_msg)

        self._dialect = DORIS_DIALECT

        # Connection configuration.
        # from_config() (and the config builder before it) have already resolved
        # env vars and defaults, so __init__ just consumes what it receives.
        # Simple Python defaults handle the direct-construction path (tests, etc.)
        self.host = config.get("host", "localhost")
        self.port = config.get("port", 9030)
        self.http_port = config.get("http_port", 8030)
        self.be_http_port = config.get("be_http_port", 8040)
        self.database = config.get("database", "benchbox")
        self.username = config.get("username", "root")
        self.password = config.get("password", "")
        self.use_tls = config.get("use_tls", False)
        self.verify_ssl = config.get("verify_ssl") if config.get("verify_ssl") is not None else True
        self.ca_cert_path = config.get("ca_cert_path")

        # Chunked loading config (w8)
        self.stream_load_chunk_size: int = config.get("stream_load_chunk_size", _DEFAULT_STREAM_LOAD_CHUNK_SIZE)
        self.stream_load_max_filter_ratio = _format_filter_ratio(
            config.get("stream_load_max_filter_ratio", _DEFAULT_STREAM_LOAD_MAX_FILTER_RATIO)
        )

        # Table model config (w11): "duplicate", "aggregate", or "unique"
        self.table_model: str = config.get("table_model", "duplicate").lower()
        if self.table_model not in ("duplicate", "aggregate", "unique"):
            raise ValueError(f"Invalid table_model '{self.table_model}': must be 'duplicate', 'aggregate', or 'unique'")

        # Distribution config (w12)
        self.default_buckets: int = config.get("default_buckets", _DEFAULT_BUCKETS)

        # Partitioning config (w13)
        self.enable_partitioning: bool = config.get("enable_partitioning", False)

        # Replication factor for table PROPERTIES; default 1 for single-backend Docker environments
        self.replication_num: int = int(config.get("replication_num", 1))

        # Index configs (w20, w21)
        self.enable_bloom_filter: bool = config.get("enable_bloom_filter", False)
        self.enable_bitmap_index: bool = config.get("enable_bitmap_index", False)

        # Validate database at init time - it's used in Stream Load URLs and SQL
        if not self._validate_identifier(self.database):
            raise ValueError(f"Invalid database identifier: {self.database}")

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate SQL identifier to prevent injection."""
        from benchbox.utils.sql_identifier import is_valid_sql_identifier

        return is_valid_sql_identifier(identifier, max_length=128)

    def _admin_connect(self) -> Any:
        """Create an admin connection (no database selected)."""
        return pymysql.connect(
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
        """Check if a database exists on the Doris server."""
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
            self.logger.debug(f"Failed to check database existence: {e}")
            return False

    def drop_database(
        self,
        schema: str | None = None,
        catalog: str | None = None,
        database: str | None = None,
        **_kwargs,
    ) -> None:
        """Drop a database from Doris server."""
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
        """Create Doris connection via MySQL protocol."""
        self.log_operation_start("Doris connection")

        # Handle existing database
        self.handle_existing_database(**connection_config)

        # Create database if needed
        if not self.check_server_database_exists():
            self._create_database()

        # Connect to target database
        conn = pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.username,
            password=self.password,
            database=self.database,
            connect_timeout=10,
            read_timeout=300,
            write_timeout=300,
            charset="utf8mb4",
        )

        # Verify connection
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchone()
        cursor.close()

        self.log_operation_complete(
            "Doris connection",
            details=f"Connected to {self.host}:{self.port}/{self.database}",
        )
        # Wrap with DDL optimizer so benchmark setup code (write_primitives,
        # transaction_primitives, metadata_primitives) that calls connection.execute()
        # directly gets proper Doris DDL (DUPLICATE KEY + DISTRIBUTED BY HASH).
        return _DorisConnectionWrapper(conn, ddl_optimizer=self._inject_doris_ddl_clauses)

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get schema SQL and translate to Doris dialect
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        scale_factor: float | None = getattr(benchmark, "scale_factor", None)
        cursor = connection.cursor()
        critical_failures = []

        # Execute each statement separately
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        try:
            for stmt in statements:
                stmt = self._inject_doris_ddl_clauses(stmt, scale_factor=scale_factor)
                try:
                    cursor.execute(stmt)
                except Exception as e:
                    is_create_table = stmt.strip().upper().startswith("CREATE TABLE")
                    if is_create_table:
                        critical_failures.append((stmt[:80], str(e)))
                    self.logger.warning(f"Schema statement failed: {e}")
                    # Continue with other statements

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
        """Load benchmark data using Stream Load HTTP API or INSERT for efficiency.

        Uses HTTP Stream Load API (port 8030) for CSV/TPC format files when
        the requests library is available. Falls back to batch INSERT via
        MySQL protocol otherwise.
        """
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
            return {}, loading_time, None

        for table_name, table_path in data_source.tables.items():
            if not self._validate_identifier(table_name):
                self.logger.warning(f"Skipping table with invalid identifier: {table_name}")
                table_stats[table_name] = 0
                continue

            data_files = [f for f in normalize_table_paths(table_path) if f.exists()]
            if not data_files:
                self.logger.warning(f"Data file(s) not found for table: {table_name}")
                table_stats[table_name] = 0
                continue

            table_start = mono_time()
            table_rows = 0

            for data_file in data_files:
                try:
                    dialect = resolve_csv_dialect(data_source, table_name, data_file, benchmark)
                    if _requests is not None:
                        table_rows += self._stream_load_file(table_name, data_file, dialect)
                    else:
                        table_rows += self._insert_load_file(connection, table_name, data_file, dialect)
                except Exception as e:
                    self.logger.error(f"Failed to load {table_name}: {e}")

            table_stats[table_name] = table_rows
            table_duration = elapsed_seconds(table_start)
            per_table_timings[table_name] = {
                "rows": table_rows,
                "duration_seconds": table_duration,
            }
            self.log_verbose(f"Loaded {table_rows:,} rows into {table_name}")

        loading_time = elapsed_seconds(start_time)
        total_rows = sum(table_stats.values())
        self.log_operation_complete("Data loading", loading_time, f"Loaded {total_rows:,} total rows")

        return table_stats, loading_time, per_table_timings

    def _stream_load_file(self, table_name: str, data_file: Path, dialect: CsvDialect) -> int:
        """Load a file into Doris using Stream Load HTTP API.

        Stream Load sends data via HTTP PUT to the FE node, which routes
        it to the appropriate BE nodes for ingestion. Large files are
        automatically split into chunks based on stream_load_chunk_size.

        Args:
            table_name: Target table name (pre-validated)
            data_file: Path to the data file
            dialect: CSV dialect describing delimiter, null handling, etc.

        Returns:
            Number of rows loaded
        """
        data_file = Path(data_file)

        # Parquet files must be sent binary with format=parquet; CSV chunking is invalid.
        if get_data_extension(data_file) == ".parquet":
            return self._stream_load_parquet(table_name, data_file)

        file_size = data_file.stat().st_size

        # Use chunked loading for large files
        if file_size > self.stream_load_chunk_size:
            return self._stream_load_file_chunked(table_name, data_file, dialect)

        return self._stream_load_single(table_name, data_file, dialect)

    @staticmethod
    def _open_data_file_text(path: Path):
        """Open a data file as text, decompressing zstd/gzip if needed.

        Uses latin-1 encoding to handle non-ASCII bytes common in TPC data
        generated by dbgen (e.g., accented characters in customer names).

        Compression is detected via ``FileFormatRegistry.get_compression_handler``
        rather than suffix string compare — but the framework handlers force
        UTF-8 text mode, so we dispatch on handler type and use python-zstandard
        + ``gzip`` directly to preserve latin-1 encoding.
        """
        import contextlib

        handler = FileFormatRegistry.get_compression_handler(path)

        @contextlib.contextmanager
        def _ctx():
            if isinstance(handler, ZstdHandler):
                import zstandard

                dctx = zstandard.ZstdDecompressor()
                with open(path, "rb") as raw, dctx.stream_reader(raw) as reader:
                    yield io.TextIOWrapper(reader, encoding="latin-1", newline="")
            elif isinstance(handler, GzipHandler):
                yield gzip.open(path, "rt", encoding="latin-1")
            elif isinstance(handler, NoCompressionHandler):
                yield open(path, encoding="latin-1")
            else:
                raise ValueError(f"Unsupported compression handler {type(handler).__name__} for {path}")

        return _ctx()

    @staticmethod
    def _open_data_file_binary(path: Path):
        """Open a data file as a binary stream, decompressing zstd/gzip if needed.

        Returns a file-like object suitable for streaming to Doris stream load.
        Re-openable so ``_stream_load_put`` retries can pull a fresh stream.
        """
        import contextlib

        handler = FileFormatRegistry.get_compression_handler(path)

        @contextlib.contextmanager
        def _ctx():
            if isinstance(handler, ZstdHandler):
                import zstandard

                dctx = zstandard.ZstdDecompressor()
                with open(path, "rb") as raw:
                    yield dctx.stream_reader(raw)
            elif isinstance(handler, GzipHandler):
                yield gzip.open(path, "rb")
            elif isinstance(handler, NoCompressionHandler):
                yield open(path, "rb")
            else:
                raise ValueError(f"Unsupported compression handler {type(handler).__name__} for {path}")

        return _ctx()

    def _stream_load_put(self, url: str, data: bytes | Callable[[], Any], headers: dict):
        """Issue a stream load PUT request, handling FE→BE redirect and retrying
        transient connection errors with exponential backoff.

        Doris FE may redirect stream load requests to the BE node. In Docker
        deployments the BE's internal port is not always mapped, so we intercept
        the redirect and rewrite the URL back to the FE host:port.

        The ``Expect: 100-continue`` header prevents the request body from being
        sent before the server acknowledges headers, making redirect retries safe.
        ``data`` may be bytes or a callable returning a fresh binary context
        manager so retries can re-open the source stream safely.
        """
        kwargs = {
            "auth": (self.username, self.password),
            # Large fact tables (e.g. TPC-DS catalog_sales at SF=1 in Docker on macOS)
            # can take several minutes to ingest due to Docker volume I/O overhead.
            # 1800s (30 min) per chunk is generous but avoids spurious timeout failures.
            "timeout": 1800,
            "verify": self.ca_cert_path if self.ca_cert_path else self.verify_ssl,
            "allow_redirects": False,
        }

        _max_attempts = 3
        _backoff_seconds = [5, 15, 45]

        def _put_once(target_url: str):
            if callable(data):
                with data() as body:  # ty: ignore[call-top-callable]
                    return _requests.put(target_url, data=body, headers=headers, **kwargs)
            return _requests.put(target_url, data=data, headers=headers, **kwargs)

        for attempt in range(_max_attempts):
            try:
                resp = _put_once(url)

                if resp.status_code in (301, 302, 303, 307, 308):
                    location = resp.headers.get("Location", "")
                    if location:
                        parsed = urlparse(location)
                        scheme = "https" if self.use_tls else "http"
                        rewritten = urlunparse(
                            parsed._replace(
                                scheme=scheme,
                                netloc=f"{self.host}:{self.be_http_port}",
                            )
                        )
                        resp = _put_once(rewritten)

                return resp

            except (_requests.exceptions.ConnectionError, _requests.exceptions.Timeout) as exc:
                if attempt == _max_attempts - 1:
                    raise
                wait = _backoff_seconds[attempt]
                self.logger.warning(
                    f"Stream Load connection error (attempt {attempt + 1}/{_max_attempts}), retrying in {wait}s: {exc}"
                )
                time.sleep(wait)

        raise RuntimeError("unreachable")

    def _stream_load_headers(
        self,
        *,
        format_name: str,
        delimiter: str | None = None,
        is_tpc: bool = False,
    ) -> dict[str, str]:
        """Build consistent Stream Load headers for Doris imports."""
        headers = {
            "Expect": "100-continue",
            "format": format_name,
            "max_filter_ratio": self.stream_load_max_filter_ratio,
        }
        if delimiter is not None:
            headers["column_separator"] = delimiter
        if is_tpc:
            headers["trim_double_quotes"] = "true"
        return headers

    def _handle_stream_load_response(self, resp: Any, *, context: str) -> dict[str, Any]:
        """Validate a Doris Stream Load response and reject silent partial loads."""
        if resp.status_code != 200:
            raise RuntimeError(f"{context} failed with status {resp.status_code}: {resp.text}")

        result = resp.json()
        status = result.get("Status")
        if status not in ("Success", "Publish Timeout"):
            message = result.get("Message", "Unknown error")
            error_url = result.get("ErrorURL", "")
            if error_url:
                self.logger.error(f"{context} error detail URL: {error_url}")
                try:
                    err_resp = _requests.get(error_url, auth=(self.username, self.password), timeout=30)
                    self.logger.error(f"{context} error rows:\n{err_resp.text[:2000]}")
                except Exception as url_err:
                    self.logger.debug(f"Could not fetch error URL: {url_err}")
            raise RuntimeError(f"{context} failed: {status} - {message}")

        filtered_rows = int(result.get("NumberFilteredRows", 0) or 0)
        unselected_rows = int(result.get("NumberUnselectedRows", 0) or 0)
        if filtered_rows > 0:
            message = (
                f"{context} filtered {filtered_rows} row(s) (max_filter_ratio={self.stream_load_max_filter_ratio})"
            )
            if self.stream_load_max_filter_ratio == "0":
                raise RuntimeError(f"{message}; refusing silent partial load")
            self.logger.warning(message)
        if unselected_rows > 0:
            self.logger.warning(f"{context} skipped {unselected_rows} row(s) via Doris WHERE filtering")

        return result

    def _stream_load_single(self, table_name: str, data_file: Path, dialect: CsvDialect) -> int:
        """Execute a single Stream Load request for the entire file.

        Args:
            table_name: Target table name (pre-validated)
            data_file: Path to the data file
            dialect: CSV dialect describing delimiter, null handling, etc.

        Returns:
            Number of rows loaded
        """
        delimiter = dialect.delimiter
        is_tpc = dialect.null_marker is not None

        scheme = "https" if self.use_tls else "http"
        # Use the FE HTTP port (http_port) as the Stream Load entry point.
        # Doris FE handles routing and redirects to the BE; _stream_load_put rewrites
        # the redirect Location to the external be_http_port for Docker deployments.
        url = f"{scheme}://{self.host}:{self.http_port}/api/{self.database}/{table_name}/_stream_load"

        # strict_mode=true is intentionally omitted: TPC-DS/DI generators produce
        # empty strings for nullable INTEGER columns (e.g. date surrogate keys,
        # ManagerID). strict_mode=true rejects these rows as type-conversion errors.
        # With strict_mode=false (default), empty → NULL for nullable columns, which
        # is the correct semantic. _fix_tpcds_decimal_nulls handles DECIMAL nulls
        # explicitly so they aren't silently coerced to 0.
        headers = self._stream_load_headers(format_name="csv", delimiter=delimiter, is_tpc=is_tpc)

        decimal_positions = _TPCDS_DECIMAL_NULL_POSITIONS.get(table_name, [])

        if is_tpc:
            # TPC format: read all lines, apply DECIMAL-null preprocessing if
            # needed, then send as bytes. Decompresses zstd/gzip if present.
            with self._open_data_file_text(data_file) as f:
                lines = f.read().splitlines()
            if decimal_positions:
                lines = [_fix_tpcds_decimal_nulls(line, delimiter, decimal_positions) for line in lines]
            data = "\n".join(lines).encode("utf-8")
        else:
            # Non-TPC: buffer into memory so retry is safe on transient failures.
            with self._open_data_file_binary(data_file) as f:
                data = f.read()

        resp = self._stream_load_put(url, data, headers)
        result = self._handle_stream_load_response(resp, context="Stream Load")
        return int(result.get("NumberLoadedRows", 0))

    def _stream_load_parquet(self, table_name: str, data_file: Path) -> int:
        """Load a Parquet file into Doris using Stream Load with format=parquet.

        Parquet files cannot be split at arbitrary byte boundaries, so the file
        is streamed as a single request. The stream is reopenable across retries
        and FE→BE redirects, so compressed outer containers such as
        ``.parquet.zst`` are decompressed client-side before upload.

        Args:
            table_name: Target table name
            data_file: Path to the .parquet file

        Returns:
            Number of rows loaded
        """
        scheme = "https" if self.use_tls else "http"
        url = f"{scheme}://{self.host}:{self.http_port}/api/{self.database}/{table_name}/_stream_load"

        headers = self._stream_load_headers(format_name="parquet")
        resp = self._stream_load_put(url, lambda: self._open_data_file_binary(data_file), headers)
        result = self._handle_stream_load_response(resp, context="Stream Load (Parquet)")
        return int(result.get("NumberLoadedRows", 0))

    def _stream_load_file_chunked(self, table_name: str, data_file: Path, dialect: CsvDialect) -> int:
        """Load a large file into Doris using chunked Stream Load requests.

        Splits the file into chunks of approximately stream_load_chunk_size
        bytes at line boundaries and submits each chunk as a separate
        Stream Load request.

        Args:
            table_name: Target table name (pre-validated)
            data_file: Path to the data file
            dialect: CSV dialect describing delimiter, null handling, etc.

        Returns:
            Total number of rows loaded across all chunks
        """
        delimiter = dialect.delimiter
        is_tpc = dialect.null_marker is not None

        scheme = "https" if self.use_tls else "http"
        # Use the FE HTTP port for Stream Load entry (same as _stream_load_single).
        url = f"{scheme}://{self.host}:{self.http_port}/api/{self.database}/{table_name}/_stream_load"

        headers = self._stream_load_headers(format_name="csv", delimiter=delimiter, is_tpc=is_tpc)

        decimal_positions = _TPCDS_DECIMAL_NULL_POSITIONS.get(table_name, [])

        total_rows = 0
        chunk_num = 0

        # Open file with decompression support; use latin-1 to handle non-ASCII TPC data.
        with self._open_data_file_text(data_file) as f:
            while True:
                chunk_lines: list[str] = []
                chunk_bytes = 0

                for line in f:
                    line = line.rstrip("\n").rstrip("\r")
                    if not line:
                        continue

                    if decimal_positions:
                        line = _fix_tpcds_decimal_nulls(line, delimiter, decimal_positions)

                    chunk_lines.append(line)
                    chunk_bytes += len(line.encode("utf-8", errors="replace")) + 1

                    if chunk_bytes >= self.stream_load_chunk_size:
                        break

                if not chunk_lines:
                    break

                chunk_num += 1
                data = "\n".join(chunk_lines).encode("utf-8", errors="replace")
                self.log_verbose(
                    f"Stream Load chunk {chunk_num} for {table_name}: {len(chunk_lines)} lines, {len(data):,} bytes"
                )

                resp = self._stream_load_put(url, data, headers)
                result = self._handle_stream_load_response(resp, context=f"Stream Load chunk {chunk_num}")
                chunk_rows = int(result.get("NumberLoadedRows", 0))
                total_rows += chunk_rows

        self.log_verbose(
            f"Chunked Stream Load complete for {table_name}: {chunk_num} chunks, {total_rows:,} total rows"
        )
        return total_rows

    def _insert_load_file(self, connection: Any, table_name: str, data_file: Path, dialect: CsvDialect) -> int:
        """Fallback: load data via batch INSERT statements.

        Used when the requests library is not available for Stream Load.

        Args:
            connection: PyMySQL connection
            table_name: Target table name (pre-validated)
            data_file: Path to the data file
            dialect: CSV dialect describing delimiter, null handling, etc.

        Returns:
            Number of rows loaded
        """
        delimiter = dialect.delimiter
        is_tpc = dialect.null_marker is not None
        row_count = 0
        batch_size = 1000

        cursor = connection.cursor()

        with open(data_file, encoding="utf-8") as f:
            batch = []
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # INSERT requires exactly N column values, so strip the trailing
                # field separator that dsdgen appends to every row. Stream Load
                # sends data verbatim and relies on Doris's CSV parser to treat
                # the trailing | as a row terminator rather than a column separator.
                if is_tpc and line.endswith(delimiter):
                    line = line[: -len(delimiter)]

                values = line.split(delimiter)
                batch.append(values)

                if len(batch) >= batch_size:
                    self._execute_batch_insert(cursor, table_name, batch)
                    row_count += len(batch)
                    batch = []

            if batch:
                self._execute_batch_insert(cursor, table_name, batch)
                row_count += len(batch)

        connection.commit()
        cursor.close()

        return row_count

    def _execute_batch_insert(self, cursor: Any, table_name: str, rows: list[list[str]]) -> None:
        """Execute a batch INSERT statement.

        Args:
            cursor: PyMySQL cursor
            table_name: Target table name (pre-validated by caller)
            rows: List of row value lists
        """
        if not rows:
            return

        num_cols = len(rows[0])
        placeholders = ", ".join(["%s"] * num_cols)
        # Safety: table_name is pre-validated by _validate_identifier() in caller
        sql = f"INSERT INTO `{table_name}` VALUES ({placeholders})"

        cursor.executemany(sql, rows)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Doris optimizations for benchmark type."""
        cursor = connection.cursor()

        try:
            # Disable query cache for consistent benchmark results (session-level)
            cursor.execute("SET enable_sql_cache = false")
        except Exception as e:
            self.logger.debug(f"Could not disable SQL cache: {e}")

        # w18: Validate cache is actually disabled
        try:
            cursor.execute("SHOW VARIABLES LIKE 'enable_sql_cache'")
            row = cursor.fetchone()
            if row and str(row[1]).lower() not in ("false", "0", "off"):
                self.logger.warning(
                    f"Cache disable validation failed: enable_sql_cache = {row[1]} "
                    "(expected false). Benchmark results may include cached queries."
                )
            else:
                self.log_verbose("Cache disable validated: enable_sql_cache = false")
        except Exception as e:
            self.logger.debug(f"Could not validate cache setting: {e}")

        try:
            # Set parallel execution for OLAP workloads (session-level)
            cursor.execute("SET parallel_fragment_exec_instance_num = 8")
        except Exception as e:
            self.logger.debug(f"Could not set parallel execution: {e}")

        if benchmark_type == "olap":
            try:
                cursor.execute("SET exec_mem_limit = 5368709120")  # 5GB - stays within BE mem_limit=6GB
            except Exception as e:
                self.logger.debug(f"Could not set exec_mem_limit: {e}")

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

        # Doris supports EXPLAIN VERBOSE and EXPLAIN GRAPH
        verbose = explain_options.get("verbose", False) if explain_options else False
        explain_prefix = "EXPLAIN VERBOSE" if verbose else "EXPLAIN"
        explain_query = f"{explain_prefix} {query}"

        try:
            cursor.execute(explain_query)
            plan_rows = cursor.fetchall()
            cursor.close()

            return "\n".join(str(row[0]) for row in plan_rows)

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
        """Close Doris connection."""
        if connection:
            try:
                connection.close()
            except Exception as e:
                self.logger.debug(f"Error closing connection: {e}")

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Doris platform information."""
        platform_info = {
            "platform_type": "doris",
            "platform_name": "Apache Doris",
            "host": self.host,
            "port": self.port,
            "dialect": DORIS_DIALECT,
            "configuration": {
                "database": self.database,
                "http_port": self.http_port,
                "stream_load_available": _requests is not None,
                "table_model": self.table_model,
                "default_buckets": self.default_buckets,
                "stream_load_chunk_size": self.stream_load_chunk_size,
                "stream_load_max_filter_ratio": self.stream_load_max_filter_ratio,
                "enable_partitioning": self.enable_partitioning,
                "enable_bloom_filter": self.enable_bloom_filter,
                "enable_bitmap_index": self.enable_bitmap_index,
            },
        }

        if connection:
            try:
                cursor = connection.cursor()

                platform_version, mysql_protocol_version, version_comment = _read_doris_version_details(cursor)
                if platform_version:
                    platform_info["platform_version"] = platform_version
                if mysql_protocol_version:
                    platform_info["configuration"]["mysql_protocol_version"] = mysql_protocol_version
                if version_comment:
                    platform_info["configuration"]["version_comment"] = version_comment

                # Get current database
                cursor.execute("SELECT database()")
                db_row = cursor.fetchone()
                if db_row:
                    platform_info["configuration"]["current_database"] = db_row[0]

                cursor.close()

            except Exception as e:
                self.logger.debug(f"Error getting platform info: {e}")

        # Add client library version
        if pymysql:
            platform_info["client_library_version"] = pymysql.__version__

        return platform_info

    def test_connection(self) -> bool:
        """Test if connection can be established."""
        try:
            conn = pymysql.connect(
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
        """Get list of existing tables in the database (lowercased for reuse comparison).

        Migration note: databases created before the lower_case_table_names fix
        have lowercase TPC-DI table names (e.g. dimcustomer). Those databases
        pass the reuse check (both sides are lowercased) but fail at query time
        because queries reference the original mixed-case names. Use --force all
        to drop and recreate a stale TPC-DI database after upgrading.
        """
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
    # DDL clause injection
    # ------------------------------------------------------------------ #

    def _inject_doris_ddl_clauses(self, stmt: str, scale_factor: float | None = None) -> str:
        """Post-process a CREATE TABLE statement to be valid Doris OLAP DDL.

        Handles five incompatibilities between standard SQL and Doris OLAP:
        1. Strip inline PRIMARY KEY constraints (parse error in Doris)
        2. Translate TIME column type to VARCHAR(8) (unsupported in OLAP)
        3. Inject DUPLICATE/AGGREGATE/UNIQUE KEY clause (required)
        4. Inject DISTRIBUTED BY HASH clause (required)
        5. Inject PROPERTIES("replication_num"="N") (avoids replication error
           when available backends < default replication factor of 3)

        Key columns are derived from the actual schema column order to satisfy
        Doris's requirement that key columns form a prefix of the schema.
        STRING/TEXT columns are excluded from key selection.
        """
        stripped = stmt.strip()
        # Use regex search (not startswith) so statements with SQL comment preambles
        # (e.g., from build_tpch_staging_tables_sql comment separators) are still processed.
        if not _CREATE_TABLE_RE.search(stripped):
            return stmt

        # Fix 1: strip table-level FOREIGN KEY constraints (shared helper) and PRIMARY KEY.
        stripped = strip_foreign_keys(stripped)
        # Optional leading comma: covers both "col INT, PRIMARY KEY (col)" and
        # bare-form "(PRIMARY KEY (col), col INT)" where PK is the first clause.
        stripped = re.sub(r",?\s*PRIMARY\s+KEY\s*\([^)]*\)", "", stripped, flags=re.IGNORECASE)
        # Column-level: "col TYPE PRIMARY KEY" (no opening paren follows KEY)
        stripped = re.sub(r"\bPRIMARY\s+KEY\b(?!\s*\()", "", stripped, flags=re.IGNORECASE)
        # Clean up any leading comma left by stripping a first-position table-level PK clause.
        stripped = re.sub(r"\(\s*,", "(", stripped)

        # Fix 2: translate TIME column type → VARCHAR(8)
        # Use a positive lookahead to match TIME only in type position (followed by a column
        # definition terminator), not when it is a column name (followed by another type word).
        # This prevents `time DATETIME` from becoming `VARCHAR(8) DATETIME` when SQLGlot
        # quotes the column name `time` as `\`time\`` and the regex then replaces the name.
        stripped = re.sub(
            r"\bTIME\b(?!STAMP)(?=\s*(?:[,\)]|$|NOT\s+NULL|NULL\b|DEFAULT\b|\Z))",
            "VARCHAR(8)",
            stripped,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        name_match = _CREATE_TABLE_RE.search(stripped)
        if not name_match:
            return stripped

        # Preserve the original table name in DDL - Doris has lower_case_table_names=0
        # (case-sensitive) by default, so CREATE TABLE DimCustomer creates "DimCustomer".
        # Queries reference the original-case name; stream load URLs must match too.
        table_name = name_match.group(1)
        table_name_key = table_name.lower()  # lowercase for dict lookups only

        # Find matching ')' of the column-definition block.
        # The regex ends with \( so name_match.end()-1 is the opening paren.
        open_pos = name_match.end() - 1
        depth = 0
        close_pos = -1
        for i in range(open_pos, len(stripped)):
            if stripped[i] == "(":
                depth += 1
            elif stripped[i] == ")":
                depth -= 1
                if depth == 0:
                    close_pos = i
                    break

        if close_pos == -1:
            return stripped

        col_body = stripped[open_pos + 1 : close_pos]

        # Fix 2b: SQLGlot translates VARCHAR(N) → STRING for Doris dialect, but Doris OLAP
        # rejects STRING as a key column type (VARCHAR is allowed). Convert STRING/TEXT back
        # to VARCHAR(65533) so these columns can participate in the key prefix.
        col_body_fixed = re.sub(r"\bSTRING\b", "VARCHAR(65533)", col_body, flags=re.IGNORECASE)
        col_body_fixed = re.sub(r"\bTEXT\b", "VARCHAR(65533)", col_body_fixed, flags=re.IGNORECASE)
        # Fix 2c: Doris SMALLINT is signed 16-bit (−32768..32767). Benchmarks like ClickBench
        # use UInt16 columns (0..65535) that overflow SMALLINT; Doris treats out-of-range
        # integers as NULL in non-strict mode, which then violates NOT NULL and filters the row.
        # Widen SMALLINT → INT (signed 32-bit, covers full UInt16 range). Type-safe widening.
        col_body_fixed = re.sub(r"\bSMALLINT\b", "INT", col_body_fixed, flags=re.IGNORECASE)
        # Fix 2d: SQLGlot translates DuckDB FLOAT[N] (fixed-size array) to ARRAY<FLOAT>[N] for
        # Doris/MySQL dialect. Doris only supports ARRAY<TYPE> without dimension size - the [N]
        # suffix causes a parse error. Strip it.
        col_body_fixed = re.sub(r"(ARRAY<[^>]+>)\[\d+\]", r"\1", col_body_fixed, flags=re.IGNORECASE)
        if col_body_fixed != col_body:
            col_body = col_body_fixed
            stripped = stripped[: open_pos + 1] + col_body + stripped[close_pos:]
            close_pos = open_pos + 1 + len(col_body)

        # Parse (name, type) pairs - filter by known SQL types to skip constraint lines.
        schema_cols: list[tuple[str, str]] = [
            (m.group(1).lower(), m.group(2).lower())
            for m in _COL_DEF_RE.finditer(col_body)
            if m.group(2).lower() in _KNOWN_SQL_TYPES
        ]

        # Key-eligible columns: exclude types Doris rejects as key columns.
        keyable_cols = [name for name, typ in schema_cols if typ not in _NON_KEY_DORIS_TYPES]

        model_keyword = {
            "duplicate": "DUPLICATE KEY",
            "aggregate": "AGGREGATE KEY",
            "unique": "UNIQUE KEY",
        }.get(self.table_model, "DUPLICATE KEY")

        # Fix 3: KEY clause - use longest valid schema prefix from desired keys.
        desired_keys = [k.lower() for k in _TPCH_TABLE_KEYS.get(table_name_key, [])]
        if desired_keys:
            desired_set = set(desired_keys)
            prefix_keys: list[str] = []
            for col_name, col_type in schema_cols:
                if col_name in desired_set and col_type not in _NON_KEY_DORIS_TYPES:
                    prefix_keys.append(col_name)
                else:
                    break  # prefix must be contiguous from position 0
            key_cols = prefix_keys or (keyable_cols[:1] if keyable_cols else None)
        else:
            key_cols = keyable_cols[:1] if keyable_cols else None

        clauses: list[str] = []

        if key_cols:
            cols_str = ", ".join(f"`{c}`" for c in key_cols)
            clauses.append(f"{model_keyword}({cols_str})")

        # PARTITION BY RANGE (optional)
        partition_clause = self.get_partition_clause(table_name_key)
        if partition_clause:
            clauses.append(partition_clause)

        # Fix 4: DISTRIBUTED BY HASH (required).
        # Validate the candidate distribution key exists in the actual schema to prevent
        # cross-contamination when TPC-H key names are applied to non-TPC-H tables
        # (e.g., TPC-DS "customer" table doesn't have "c_custkey").
        schema_col_names = {col_name for col_name, _ in schema_cols}
        dist_key_candidate = _TPCH_DISTRIBUTION_KEYS.get(table_name_key)
        dist_key = (
            dist_key_candidate
            if dist_key_candidate and dist_key_candidate in schema_col_names
            else (key_cols[0] if key_cols else None)
        )
        buckets = self._compute_bucket_count(table_name_key, scale_factor)
        if dist_key:
            clauses.append(f"DISTRIBUTED BY HASH(`{dist_key}`) BUCKETS {buckets}")
        else:
            clauses.append(f"DISTRIBUTED BY RANDOM BUCKETS {buckets}")

        # Fix 5: PROPERTIES with replication_num and HDD storage medium.
        # storage_medium = HDD prevents "Failed to find enough backend" errors on Docker
        # deployments where Doris defaults to requesting SSD-labeled storage backends.
        clauses.append(f'PROPERTIES ("replication_num" = "{self.replication_num}", "storage_medium" = "HDD")')

        suffix = "\n" + "\n".join(clauses)
        return stripped[: close_pos + 1] + suffix + stripped[close_pos + 1 :]

    # ------------------------------------------------------------------ #
    # w11/w12/w13: DDL generation for table model, distribution, partitions
    # ------------------------------------------------------------------ #

    def get_table_model_clause(self, table_name: str) -> str:
        """Generate the table model clause (DUPLICATE/AGGREGATE/UNIQUE KEY).

        For TPC-H tables, selects appropriate key columns per table.
        For unknown tables, uses the first column as key.

        Args:
            table_name: Lowercase table name

        Returns:
            DDL clause string, e.g. ``DUPLICATE KEY(l_orderkey, l_linenumber)``
        """
        model_keyword = {
            "duplicate": "DUPLICATE KEY",
            "aggregate": "AGGREGATE KEY",
            "unique": "UNIQUE KEY",
        }.get(self.table_model, "DUPLICATE KEY")

        key_cols = _TPCH_TABLE_KEYS.get(table_name)
        if key_cols:
            cols_str = ", ".join(key_cols)
            return f"{model_keyword}({cols_str})"

        # Fallback: caller should provide a column name
        return ""

    def get_distribution_clause(self, table_name: str, scale_factor: float | None = None) -> str:
        """Generate DISTRIBUTED BY HASH clause for a table.

        Selects distribution key per table (usually the primary/join column)
        and computes bucket count based on data size.

        Args:
            table_name: Lowercase table name
            scale_factor: Benchmark scale factor for bucket sizing

        Returns:
            DDL clause string, e.g. ``DISTRIBUTED BY HASH(l_orderkey) BUCKETS 16``
        """
        dist_key = _TPCH_DISTRIBUTION_KEYS.get(table_name)
        if not dist_key:
            return f"DISTRIBUTED BY HASH(`{table_name}`) BUCKETS {self.default_buckets}"

        buckets = self._compute_bucket_count(table_name, scale_factor)
        return f"DISTRIBUTED BY HASH({dist_key}) BUCKETS {buckets}"

    def _compute_bucket_count(self, table_name: str, scale_factor: float | None = None) -> int:
        """Compute bucket count based on table size and scale factor.

        Uses a heuristic: larger tables at higher scale factors get more buckets.
        Minimum is 1, maximum is capped at 128.
        """
        if not isinstance(scale_factor, (int, float)) or scale_factor <= 0:
            return self.default_buckets

        # Row count multipliers for TPC-H tables at SF=1
        sf1_rows = {
            "lineitem": 6_000_000,
            "orders": 1_500_000,
            "partsupp": 800_000,
            "customer": 150_000,
            "part": 200_000,
            "supplier": 10_000,
            "nation": 25,
            "region": 5,
        }
        base_rows = sf1_rows.get(table_name, 100_000)
        estimated_rows = base_rows * scale_factor
        # Roughly 1 bucket per 500K rows, minimum default_buckets
        computed = max(self.default_buckets, int(math.ceil(estimated_rows / 500_000)))
        return min(computed, 128)

    def get_partition_clause(self, table_name: str) -> str:
        """Generate PARTITION BY RANGE clause for large tables.

        Only generates partitions when enable_partitioning is True and
        the table has a known date column for range partitioning.

        Args:
            table_name: Lowercase table name

        Returns:
            DDL clause string or empty string if not applicable
        """
        if not self.enable_partitioning:
            return ""

        partition_col = _TPCH_PARTITION_TABLES.get(table_name)
        if not partition_col:
            return ""

        ranges = _TPCH_PARTITION_RANGES.get(table_name, [])
        if not ranges:
            return ""

        partition_defs = []
        for part_name, _start, end in ranges:
            partition_defs.append(f'PARTITION {part_name} VALUES LESS THAN ("{end}")')

        partitions_str = ",\n    ".join(partition_defs)
        return f"PARTITION BY RANGE({partition_col}) (\n    {partitions_str}\n)"

    # ------------------------------------------------------------------ #
    # w20/w21: Bloom filter and Bitmap index creation
    # ------------------------------------------------------------------ #

    def create_bloom_filter_indexes(self, connection: Any, tables: list[str] | None = None) -> list[str]:
        """Create Bloom filter indexes on high-cardinality columns.

        Args:
            connection: Active Doris connection
            tables: List of table names; if None, uses all known TPC-H tables

        Returns:
            List of SQL statements executed
        """
        target_tables = tables or list(_TPCH_BLOOM_FILTER_COLUMNS.keys())
        executed_stmts: list[str] = []
        cursor = connection.cursor()

        try:
            for table_name in target_tables:
                columns = _TPCH_BLOOM_FILTER_COLUMNS.get(table_name, [])
                for col in columns:
                    if not self._validate_identifier(table_name) or not self._validate_identifier(col):
                        continue
                    idx_name = f"idx_bloom_{col}"
                    # Safety: table_name and col validated above
                    stmt = f"CREATE INDEX `{idx_name}` ON `{table_name}` (`{col}`) USING BLOOM_FILTER"
                    try:
                        cursor.execute(stmt)
                        executed_stmts.append(stmt)
                        self.log_verbose(f"Created Bloom filter index: {idx_name} on {table_name}.{col}")
                    except Exception as e:
                        self.logger.warning(f"Failed to create Bloom filter index {idx_name}: {e}")
        finally:
            cursor.close()

        return executed_stmts

    def create_bitmap_indexes(self, connection: Any, tables: list[str] | None = None) -> list[str]:
        """Create Bitmap indexes on low-cardinality columns.

        Args:
            connection: Active Doris connection
            tables: List of table names; if None, uses all known TPC-H tables

        Returns:
            List of SQL statements executed
        """
        target_tables = tables or list(_TPCH_BITMAP_COLUMNS.keys())
        executed_stmts: list[str] = []
        cursor = connection.cursor()

        try:
            for table_name in target_tables:
                columns = _TPCH_BITMAP_COLUMNS.get(table_name, [])
                for col in columns:
                    if not self._validate_identifier(table_name) or not self._validate_identifier(col):
                        continue
                    idx_name = f"idx_bitmap_{col}"
                    # Safety: table_name and col validated above
                    stmt = f"CREATE INDEX `{idx_name}` ON `{table_name}` (`{col}`) USING BITMAP"
                    try:
                        cursor.execute(stmt)
                        executed_stmts.append(stmt)
                        self.log_verbose(f"Created Bitmap index: {idx_name} on {table_name}.{col}")
                    except Exception as e:
                        self.logger.warning(f"Failed to create Bitmap index {idx_name}: {e}")
        finally:
            cursor.close()

        return executed_stmts

    def apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None:
        """Apply tuning configurations to Doris tables."""
        # Doris tuning is primarily handled through DDL (distribution, indexes)

    def generate_tuning_clause(self, table_tuning: TableTuning | None) -> str:
        """Generate Doris-specific tuning clauses."""
        if not table_tuning:
            return ""
        # Doris distribution and properties are handled at schema creation time
        return ""

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration."""
        # Doris tuning is session-based or applied at table creation

    def apply_platform_optimizations(
        self,
        platform_config: PlatformOptimizationConfiguration,
        connection: Any,
    ) -> None:
        """Apply Doris-specific optimizations."""
        # Optimizations applied in configure_for_benchmark

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to Doris.

        Note: Doris does not enforce primary key or foreign key constraints
        in the traditional RDBMS sense. Keys are used for data distribution
        and deduplication, not referential integrity.
        """

    def validate_platform_capabilities(self, benchmark_type: str):
        """Validate Doris-specific capabilities for the benchmark."""
        errors = []
        warnings = []

        if pymysql is None:
            errors.append("pymysql library not available - install with 'pip install pymysql'")
        else:
            try:
                version = pymysql.__version__
                version_parts = version.split(".")
                major = int(version_parts[0])
                if major < 1:
                    warnings.append(f"pymysql version {version} is older - consider upgrading")
            except (AttributeError, ValueError, IndexError):
                warnings.append("Could not determine pymysql version")

        if _requests is None:
            warnings.append(
                "requests library not available - Stream Load disabled, falling back to INSERT loading. "
                "Install with 'pip install requests' for better performance."
            )

        platform_info = {
            "platform": self.platform_name,
            "benchmark_type": benchmark_type,
            "dry_run_mode": self.dry_run_mode,
            "pymysql_available": pymysql is not None,
            "requests_available": _requests is not None,
            "host": self.host,
            "port": self.port,
            "http_port": self.http_port,
            "database": self.database,
        }

        if pymysql:
            platform_info["pymysql_version"] = getattr(pymysql, "__version__", "unknown")

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
        """Validate Doris connection health and capabilities."""
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

            platform_version, mysql_protocol_version, version_comment = _read_doris_version_details(cursor)
            if platform_version:
                connection_info["server_version"] = platform_version
            else:
                warnings.append("Could not query Doris version")
            if mysql_protocol_version:
                connection_info["mysql_protocol_version"] = mysql_protocol_version
            if version_comment:
                connection_info["version_comment"] = version_comment

            # Check current database
            try:
                cursor.execute("SELECT database()")
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

    def _validate_data_integrity(self, benchmark, connection, table_stats: dict) -> tuple:
        """Doris override: backtick-quote table names to preserve case and reserved words.

        Doris treats several common table names (e.g. ``disk``, ``net``) as reserved
        keywords, and mixed-case identifiers such as ``DimCustomer`` only resolve
        reliably when quoted. The base class implementation does not quote identifiers.
        """

        validation_details: dict[str, Any] = {}
        try:
            accessible_tables = []
            inaccessible_tables = []
            for table_name in table_stats:
                try:
                    cursor = connection.cursor()
                    try:
                        cursor.execute(f"SELECT 1 FROM `{table_name}` LIMIT 1")
                        accessible_tables.append(table_name)
                    finally:
                        cursor.close()
                except Exception:
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            validation_details["accessible_tables"] = accessible_tables
            validation_details["constraints_enabled"] = True
            return "PASSED", validation_details
        except Exception as e:
            validation_details["constraints_enabled"] = False
            validation_details["integrity_error"] = str(e)
            return "FAILED", validation_details

    def supports_tuning_type(self, tuning_type: Any) -> bool:
        """Check if Doris supports a specific tuning type."""
        try:
            from benchbox.core.tuning.interface import TuningType

            supported = {
                TuningType.PARTITIONING: True,  # PARTITION BY RANGE
                TuningType.SORTING: True,  # Sort keys in Duplicate model
                TuningType.DISTRIBUTION: True,  # DISTRIBUTED BY HASH
                TuningType.CLUSTERING: False,  # No CLUSTER command
                TuningType.PRIMARY_KEYS: True,  # Unique/Primary key models
                TuningType.FOREIGN_KEYS: False,  # No FK enforcement
            }
            return supported.get(tuning_type, False)
        except ImportError:
            return False


def _build_doris_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build Doris database configuration with credential loading.

    Args:
        platform: Platform name (should be 'doris')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with credentials loaded
    """
    # Intentionally inline - not using build_platform_config because env-var fallback and multi-port
    # int coercion must happen at builder runtime for CLI/test parity. See the Group D TODO notes.
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    # Load saved credentials
    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("doris") or {}

    # Priority: defaults < saved_creds < explicit_options < overrides
    explicit_options = overrides.get("_explicit_platform_options", {})
    merged_options: dict[str, Any] = {}
    merged_options.update(options)
    merged_options.update(saved_creds)
    merged_options.update(explicit_options)
    merged_options.update(overrides)

    name = info.display_name if info else "Apache Doris"
    driver_package = info.driver_package if info else "pymysql"

    config_dict = {
        "type": "doris",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Platform-specific fields
        "host": merged_options.get("host") or os.environ.get("DORIS_HOST", "localhost"),
        "port": int(merged_options.get("port") or os.environ.get("DORIS_PORT", "9030")),
        "http_port": int(merged_options.get("http_port") or os.environ.get("DORIS_HTTP_PORT", "8030")),
        "be_http_port": int(merged_options.get("be_http_port") or os.environ.get("DORIS_BE_HTTP_PORT", "8040")),
        "username": (
            merged_options.get("username") or os.environ.get("DORIS_USER") or os.environ.get("DORIS_USERNAME", "root")
        ),
        "password": merged_options.get("password") or os.environ.get("DORIS_PASSWORD", ""),
        "database": merged_options.get("database") or os.environ.get("DORIS_DATABASE"),
        # Benchmark context
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    return DatabaseConfig(**config_dict)
