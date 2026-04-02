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

import math
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

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
from ..utils.file_format import get_delimiter_for_file, is_tpc_format
from .base import DriverIsolationCapability, PlatformAdapter
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

# Default chunk size for Stream Load: 100MB
_DEFAULT_STREAM_LOAD_CHUNK_SIZE = 100 * 1024 * 1024

# Default bucket count for DISTRIBUTED BY HASH
_DEFAULT_BUCKETS = 10

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
        """Create Doris adapter from unified configuration."""
        adapter_config = {}

        # Connection parameters (with env var fallbacks)
        adapter_config["host"] = config.get("host") or os.environ.get("DORIS_HOST", "localhost")
        adapter_config["port"] = config.get("port") or int(os.environ.get("DORIS_PORT", "9030"))
        adapter_config["http_port"] = config.get("http_port") or int(os.environ.get("DORIS_HTTP_PORT", "8030"))
        adapter_config["username"] = (
            config.get("username") or os.environ.get("DORIS_USER") or os.environ.get("DORIS_USERNAME", "root")
        )
        adapter_config["password"] = config.get("password") or os.environ.get("DORIS_PASSWORD", "")

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
            "table_model",
            "default_buckets",
            "enable_partitioning",
            "enable_bloom_filter",
            "enable_bitmap_index",
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

        # Connection configuration
        self.host = config.get("host") or os.environ.get("DORIS_HOST", "localhost")
        self.port = config.get("port") or int(os.environ.get("DORIS_PORT", "9030"))
        self.http_port = config.get("http_port") or int(os.environ.get("DORIS_HTTP_PORT", "8030"))
        self.database = config.get("database", "benchbox")
        self.username = (
            config.get("username") or os.environ.get("DORIS_USER") or os.environ.get("DORIS_USERNAME", "root")
        )
        self.password = config.get("password") or os.environ.get("DORIS_PASSWORD", "")
        self.use_tls = config.get("use_tls", False)

        # Chunked loading config (w8)
        self.stream_load_chunk_size: int = config.get("stream_load_chunk_size", _DEFAULT_STREAM_LOAD_CHUNK_SIZE)

        # Table model config (w11): "duplicate", "aggregate", or "unique"
        self.table_model: str = config.get("table_model", "duplicate").lower()
        if self.table_model not in ("duplicate", "aggregate", "unique"):
            raise ValueError(f"Invalid table_model '{self.table_model}': must be 'duplicate', 'aggregate', or 'unique'")

        # Distribution config (w12)
        self.default_buckets: int = config.get("default_buckets", _DEFAULT_BUCKETS)

        # Partitioning config (w13)
        self.enable_partitioning: bool = config.get("enable_partitioning", False)

        # Index configs (w20, w21)
        self.enable_bloom_filter: bool = config.get("enable_bloom_filter", False)
        self.enable_bitmap_index: bool = config.get("enable_bitmap_index", False)

        # Validate database at init time — it's used in Stream Load URLs and SQL
        if not self._validate_identifier(self.database):
            raise ValueError(f"Invalid database identifier: {self.database}")

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate SQL identifier to prevent injection."""
        if not identifier or not isinstance(identifier, str):
            return False
        if len(identifier) > 128:
            return False
        pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
        return bool(re.match(pattern, identifier))

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
        return conn

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Get schema SQL and translate to Doris dialect
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        cursor = connection.cursor()
        critical_failures = []

        # Execute each statement separately
        statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
        try:
            for stmt in statements:
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

        for table_name, table_path in benchmark.tables.items():
            table_name_lower = table_name.lower()

            if not self._validate_identifier(table_name_lower):
                self.logger.warning(f"Skipping table with invalid identifier: {table_name}")
                table_stats[table_name_lower] = 0
                continue

            data_file = Path(table_path)
            if not data_file.exists():
                self.logger.warning(f"Data file not found: {data_file}")
                table_stats[table_name_lower] = 0
                continue

            table_start = mono_time()

            try:
                if _requests is not None:
                    row_count = self._stream_load_file(table_name_lower, data_file)
                else:
                    row_count = self._insert_load_file(connection, table_name_lower, data_file)

                table_stats[table_name_lower] = row_count
                table_duration = elapsed_seconds(table_start)
                per_table_timings[table_name_lower] = {
                    "rows": row_count,
                    "duration_seconds": table_duration,
                }
                self.log_verbose(f"Loaded {row_count:,} rows into {table_name_lower}")

            except Exception as e:
                self.logger.error(f"Failed to load {table_name_lower}: {e}")
                table_stats[table_name_lower] = 0

        loading_time = elapsed_seconds(start_time)
        total_rows = sum(table_stats.values())
        self.log_operation_complete("Data loading", loading_time, f"Loaded {total_rows:,} total rows")

        return table_stats, loading_time, per_table_timings

    def _stream_load_file(self, table_name: str, data_file: Path) -> int:
        """Load a file into Doris using Stream Load HTTP API.

        Stream Load sends data via HTTP PUT to the FE node, which routes
        it to the appropriate BE nodes for ingestion. Large files are
        automatically split into chunks based on stream_load_chunk_size.

        Args:
            table_name: Target table name (pre-validated)
            data_file: Path to the data file

        Returns:
            Number of rows loaded
        """
        data_file = Path(data_file)
        file_size = data_file.stat().st_size

        # Use chunked loading for large files
        if file_size > self.stream_load_chunk_size:
            return self._stream_load_file_chunked(table_name, data_file)

        return self._stream_load_single(table_name, data_file)

    def _stream_load_single(self, table_name: str, data_file: Path) -> int:
        """Execute a single Stream Load request for the entire file.

        Args:
            table_name: Target table name (pre-validated)
            data_file: Path to the data file

        Returns:
            Number of rows loaded
        """
        delimiter = get_delimiter_for_file(data_file)
        is_tpc = is_tpc_format(data_file)

        scheme = "https" if self.use_tls else "http"
        url = f"{scheme}://{self.host}:{self.http_port}/api/{self.database}/{table_name}/_stream_load"

        headers = {
            "Expect": "100-continue",
            "column_separator": delimiter,
            "format": "csv",
        }

        # TPC format files have trailing delimiter that needs to be trimmed
        if is_tpc:
            headers["trim_double_quotes"] = "true"

        if is_tpc:
            # TPC format: read, strip trailing delimiters, and send
            with open(data_file) as f:
                lines = f.read().splitlines()
            cleaned_lines = []
            for line in lines:
                if line.endswith(delimiter):
                    line = line[: -len(delimiter)]
                cleaned_lines.append(line)
            data = "\n".join(cleaned_lines).encode("utf-8")

            resp = _requests.put(
                url,
                data=data,
                headers=headers,
                auth=(self.username, self.password),
                timeout=600,
            )
        else:
            # Non-TPC: stream file directly without loading into memory
            with open(data_file, "rb") as f:
                resp = _requests.put(
                    url,
                    data=f,
                    headers=headers,
                    auth=(self.username, self.password),
                    timeout=600,
                )

        if resp.status_code != 200:
            raise RuntimeError(f"Stream Load failed with status {resp.status_code}: {resp.text}")

        result = resp.json()
        status = result.get("Status")
        if status not in ("Success", "Publish Timeout"):
            message = result.get("Message", "Unknown error")
            raise RuntimeError(f"Stream Load failed: {status} - {message}")

        return int(result.get("NumberLoadedRows", 0))

    def _stream_load_file_chunked(self, table_name: str, data_file: Path) -> int:
        """Load a large file into Doris using chunked Stream Load requests.

        Splits the file into chunks of approximately stream_load_chunk_size
        bytes at line boundaries and submits each chunk as a separate
        Stream Load request.

        Args:
            table_name: Target table name (pre-validated)
            data_file: Path to the data file

        Returns:
            Total number of rows loaded across all chunks
        """
        delimiter = get_delimiter_for_file(data_file)
        is_tpc = is_tpc_format(data_file)

        scheme = "https" if self.use_tls else "http"
        url = f"{scheme}://{self.host}:{self.http_port}/api/{self.database}/{table_name}/_stream_load"

        headers = {
            "Expect": "100-continue",
            "column_separator": delimiter,
            "format": "csv",
        }
        if is_tpc:
            headers["trim_double_quotes"] = "true"

        total_rows = 0
        chunk_num = 0

        with open(data_file) as f:
            while True:
                chunk_lines: list[str] = []
                chunk_bytes = 0

                for line in f:
                    line = line.rstrip("\n").rstrip("\r")
                    if not line:
                        continue

                    # Strip trailing delimiter for TPC format
                    if is_tpc and line.endswith(delimiter):
                        line = line[: -len(delimiter)]

                    chunk_lines.append(line)
                    chunk_bytes += len(line.encode("utf-8")) + 1  # +1 for newline

                    if chunk_bytes >= self.stream_load_chunk_size:
                        break

                if not chunk_lines:
                    break

                chunk_num += 1
                data = "\n".join(chunk_lines).encode("utf-8")
                self.log_verbose(
                    f"Stream Load chunk {chunk_num} for {table_name}: {len(chunk_lines)} lines, {len(data):,} bytes"
                )

                resp = _requests.put(
                    url,
                    data=data,
                    headers=headers,
                    auth=(self.username, self.password),
                    timeout=600,
                )

                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Stream Load chunk {chunk_num} failed with status {resp.status_code}: {resp.text}"
                    )

                result = resp.json()
                status = result.get("Status")
                if status not in ("Success", "Publish Timeout"):
                    message = result.get("Message", "Unknown error")
                    raise RuntimeError(f"Stream Load chunk {chunk_num} failed: {status} - {message}")

                chunk_rows = int(result.get("NumberLoadedRows", 0))
                total_rows += chunk_rows

        self.log_verbose(
            f"Chunked Stream Load complete for {table_name}: {chunk_num} chunks, {total_rows:,} total rows"
        )
        return total_rows

    def _insert_load_file(self, connection: Any, table_name: str, data_file: Path) -> int:
        """Fallback: load data via batch INSERT statements.

        Used when the requests library is not available for Stream Load.

        Args:
            connection: PyMySQL connection
            table_name: Target table name (pre-validated)
            data_file: Path to the data file

        Returns:
            Number of rows loaded
        """
        delimiter = get_delimiter_for_file(data_file)
        is_tpc = is_tpc_format(data_file)
        row_count = 0
        batch_size = 1000

        cursor = connection.cursor()

        with open(data_file) as f:
            batch = []
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Remove trailing delimiter for TPC format
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
                cursor.execute("SET exec_mem_limit = 8589934592")  # 8GB
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
                "enable_partitioning": self.enable_partitioning,
                "enable_bloom_filter": self.enable_bloom_filter,
                "enable_bitmap_index": self.enable_bitmap_index,
            },
        }

        if connection:
            try:
                cursor = connection.cursor()

                # Get Doris version
                cursor.execute("SELECT version()")
                version_row = cursor.fetchone()
                if version_row:
                    platform_info["platform_version"] = version_row[0]

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
        if scale_factor is None or scale_factor <= 0:
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

            # Check Doris version
            try:
                cursor.execute("SELECT version()")
                version_result = cursor.fetchone()
                if version_result:
                    connection_info["server_version"] = version_result[0]
            except Exception:
                warnings.append("Could not query Doris version")

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


def _build_doris_config(benchmark_config: dict, platform_options: dict) -> dict:
    """Build Doris configuration from benchmark and platform options.

    This function is registered with PlatformHookRegistry to provide
    Doris-specific configuration handling.
    """
    config = {
        "host": platform_options.get("host") or os.environ.get("DORIS_HOST", "localhost"),
        "port": platform_options.get("port") or int(os.environ.get("DORIS_PORT", "9030")),
        "http_port": platform_options.get("http_port") or int(os.environ.get("DORIS_HTTP_PORT", "8030")),
        "username": (
            platform_options.get("username") or os.environ.get("DORIS_USER") or os.environ.get("DORIS_USERNAME", "root")
        ),
        "password": platform_options.get("password") or os.environ.get("DORIS_PASSWORD", ""),
        "database": platform_options.get("database") or os.environ.get("DORIS_DATABASE"),
    }

    # Merge benchmark configuration
    config.update(benchmark_config)

    return config
