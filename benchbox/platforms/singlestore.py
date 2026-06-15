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
from typing import Any, ClassVar

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
from benchbox.platforms.base.ddl_optimizer import BaseDdlOptimizer

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from ..utils.file_format import get_data_extension
from .base import DriverIsolationCapability, PlatformAdapter
from .base.data_loading import (
    CsvDialect,
    DataSourceResolver,  # noqa: F401 - tests patch this module-local name; shared loader resolves it dynamically.
    prepare_local_load_file,
    resolve_csv_dialect,
)
from .base.mysql_wire import MySqlWireLifecycleMixin, NoOpTableTuningMixin, build_database_config
from .base.sql_execution import execute_sql_query  # noqa: F401 - tests patch this module-local execution hook.

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
_TPCH_SHARD_KEYS: dict[str, str] = dict(  # noqa: C408
    lineitem="l_orderkey",
    orders="o_orderkey",
    customer="c_custkey",
    part="p_partkey",
    supplier="s_suppkey",
    partsupp="ps_partkey",
)

# TPC-H sort key columns (primary analytical ordering)
_TPCH_SORT_KEYS: dict[str, list[str]] = {
    **{table: [key] for table, key in _TPCH_SHARD_KEYS.items()},
    "lineitem": ["l_orderkey", "l_linenumber"],
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


class SingleStoreAdapter(NoOpTableTuningMixin, MySqlWireLifecycleMixin, BaseDdlOptimizer, PlatformAdapter):
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
    connection_operation_name = "SingleStore connection"
    database_exists_rethrow_error_code = 2003
    connection_runtime_error_code = 2003
    empty_load_details: ClassVar[dict[str, Any]] = {}
    reset_table_rows_on_load_error = True

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

    def _admin_connect(self) -> Any:
        """Create a connection without selecting a database."""
        return _s2.connect(
            host=self.host,
            port=self.port,
            user=self.username,
            password=self.password,
            connect_timeout=10,
        )

    def _connect_database(self, **connection_config: Any) -> Any:
        return _s2.connect(
            host=self.host,
            port=self.port,
            user=self.username,
            password=self.password,
            database=self.database,
            connect_timeout=10,
            local_infile=True,
        )

    def _transform_schema_statement(self, stmt: str, benchmark: Any) -> str:
        return self._transform_create_statement(stmt)

    def _load_table_name(self, table_name: str) -> str:
        return table_name.lower()

    def _handle_invalid_load_table(self, table_name: str, table_stats: dict[str, int]) -> bool:
        raise ValueError(f"Invalid table identifier: {table_name!r}")

    def _load_resolved_data_file(
        self,
        benchmark: Any,
        connection: Any,
        table_name: str,
        source_table_name: str,
        data_file: Path,
        data_source: Any,
    ) -> int:
        if data_file.suffix.lower() in _PARQUET_EXTENSIONS:
            self.logger.warning(f"Skipping {data_file.name}: LOAD DATA LOCAL INFILE does not support Parquet")
            return 0
        dialect = resolve_csv_dialect(data_source, source_table_name, data_file, benchmark)
        strip_trailing_delim = get_data_extension(data_file) in (".tbl", ".dat")
        return self._load_data_infile(connection, table_name, data_file, dialect, strip_trailing_delim)

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

    def _format_query_plan_rows(self, rows: Any) -> str:
        """Join the first column of each EXPLAIN row into the plan text.

        SingleStore ``EXPLAIN`` returns the plan tree as single-column rows; take
        column 0 so ``SingleStoreQueryPlanParser`` receives clean tree text rather
        than the ``str(tuple)`` repr the default mixin formatter would produce.
        """
        return "\n".join(str(row[0]) if isinstance(row, (tuple, list)) else str(row) for row in rows)

    def get_query_plan_parser(self):
        """Get the SingleStore query plan parser."""
        from benchbox.core.query_plans.parsers.singlestore import SingleStoreQueryPlanParser

        return SingleStoreQueryPlanParser()

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
        """Execute a query and capture its structured plan when enabled.

        Delegates execution to the shared MySQL-wire path, then merges plan
        capture (SUCCESS-guarded; no EXPLAIN issued when capture_plans is off).
        Kept outside the execution path so a strict_plan_capture PlanCaptureError
        propagates rather than being mislabeled as a failed query.
        """
        result = super().execute_query(
            connection,
            query,
            query_id,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )
        self._merge_plan_capture_into_result(result, connection, query, query_id)
        return result

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

    def _populate_connection_health_details(
        self,
        cursor: Any,
        warnings: list[str],
        connection_info: dict[str, Any],
    ) -> None:
        try:
            cursor.execute("SELECT @@memsql_version")
            version_result = cursor.fetchone()
            if version_result:
                connection_info["server_version"] = version_result[0]
        except Exception:
            warnings.append("Could not query SingleStore version")

    _supported_tuning_type_names = ("SORTING", "DISTRIBUTION")


def _build_singlestore_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    return build_database_config(
        platform=platform,
        options=options,
        overrides=overrides,
        info=info,
        default_name="SingleStore",
        default_driver_package="singlestoredb",
        fields={
            "host": lambda m: m.get("host") or os.environ.get("SINGLESTORE_HOST", "localhost"),
            "port": lambda m: (
                m.get("port")
                if m.get("port") is not None
                else int(os.environ.get("SINGLESTORE_PORT", str(_DEFAULT_PORT)))
            ),
            "username": lambda m: m.get("username")
            or os.environ.get("SINGLESTORE_USER")
            or os.environ.get("SINGLESTORE_USERNAME", "root"),
            "password": lambda m: m.get("password") or os.environ.get("SINGLESTORE_PASSWORD"),
            "database": lambda m: m.get("database") or os.environ.get("SINGLESTORE_DATABASE"),
        },
    )
