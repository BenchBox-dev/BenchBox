"""MotherDuck platform adapter for serverless DuckDB cloud.

MotherDuck is the managed cloud version of DuckDB, providing serverless
analytics with cloud storage integration. This adapter inherits DuckDB's
SQL dialect and benchmark compatibility while implementing MotherDuck-specific
authentication and connection handling.

Authentication:
- Uses MOTHERDUCK_TOKEN environment variable or config file
- Token can also be passed via --motherduck-token <token>

Connection:
- Uses DuckDB's native MotherDuck integration: md:database_name
- Supports hybrid queries accessing both local and cloud data

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from benchbox.core.config_inheritance import (
    resolve_dialect_for_query_translation,
)
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.dependencies import get_package_install_message

try:
    import duckdb
except ImportError:
    duckdb = None

from .base import DriverIsolationCapability, PlatformAdapter
from .base.config_utils import make_platform_config_builder
from .duckdb import _build_duckdb_ctas_sort_sql, _create_duckdb_external_views

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn

logger = logging.getLogger(__name__)

_MOTHERDUCK_TOKEN_RE = re.compile(r"(motherduck_token=)[^&\s,;)]*", flags=re.IGNORECASE)


def _redact_motherduck_token(message: str, token: str | None = None) -> str:
    """Remove MotherDuck token material from adapter errors."""
    redacted = message.replace(token, "****") if token else message
    return _MOTHERDUCK_TOKEN_RE.sub(r"\1****", redacted)


# MotherDuck credentials include ``database``; route through the shared
# credential-aware builder so saved setup values reach adapter config.
_build_motherduck_config = make_platform_config_builder(
    "motherduck",
    __name__,
    "MotherDuck",
    "duckdb",
    [
        "database",
        "memory_limit",
        "token_env_var",
    ],
)


class MotherDuckAdapter(PlatformAdapter):
    """MotherDuck platform adapter - serverless DuckDB in the cloud.

    This adapter enables running benchmarks against MotherDuck, allowing
    direct comparison with local DuckDB performance.

    Authentication:
        Set MOTHERDUCK_TOKEN environment variable, or provide via CLI flag:
        --motherduck-token <your-motherduck-token>

    Example usage:
        benchbox run --platform motherduck --benchmark tpch --scale 0.01 \\
            --platform-option database=my_benchmark_db
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True

    def __init__(self, **config):
        """Initialize MotherDuck adapter.

        Args:
            **config: Configuration options:
                - token: MotherDuck authentication token (or use MOTHERDUCK_TOKEN env)
                - database: MotherDuck database name (default: benchbox)
                - memory_limit: Local memory limit for hybrid queries
        """
        super().__init__(**config)

        if duckdb is None:
            raise ImportError(
                "MotherDuck requires the duckdb package.\n"
                + get_package_install_message("duckdb", "")
                + "\n\nNote: MotherDuck support requires DuckDB >= 0.9.0"
            )

        # Use inherited dialect from DuckDB
        self._dialect = "duckdb"

        # Authentication
        self.token = config.get("token") or os.environ.get("MOTHERDUCK_TOKEN")
        if not self.token:
            raise ValueError(
                "MotherDuck requires authentication token.\n"
                "Set MOTHERDUCK_TOKEN environment variable, or provide via:\n"
                "  --motherduck-token <your-token>\n"
                "\nGet your token at: https://app.motherduck.com/token-request"
            )

        # Database configuration
        self.database = config.get("database", "benchbox")
        self.memory_limit = config.get("memory_limit", "4GB")

        # Connection state
        self.connection = None

        logger.info(f"MotherDuck adapter initialized for database: {self.database}")

    @property
    def platform_name(self) -> str:
        """Return platform display name."""
        return "MotherDuck"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add MotherDuck-specific CLI arguments."""
        md_group = parser.add_argument_group("MotherDuck Arguments")
        md_group.add_argument(
            "--motherduck-database",
            type=str,
            default="benchbox",
            help="MotherDuck database name (default: benchbox)",
        )
        md_group.add_argument(
            "--motherduck-token",
            type=str,
            help="MotherDuck authentication token (or use MOTHERDUCK_TOKEN env)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create MotherDuck adapter from unified configuration."""
        adapter_config = {
            "benchmark": config.get("benchmark"),
        }

        # Map the legacy argparse-style key and normalized DatabaseConfig key.
        database = config.get("motherduck_database") or config.get("database")
        if database:
            adapter_config["database"] = database
        if config.get("motherduck_token"):
            adapter_config["token"] = config["motherduck_token"]
        if config.get("memory_limit"):
            adapter_config["memory_limit"] = config["memory_limit"]

        return cls(**adapter_config)

    def get_target_dialect(self) -> str:
        """Get the SQL dialect for query translation.

        MotherDuck uses DuckDB's SQL dialect, inherited via config_inheritance.
        """
        return resolve_dialect_for_query_translation("motherduck")

    def create_connection(self, connection_config: Optional[dict[str, Any]] = None):
        """Create connection to MotherDuck.

        Uses DuckDB's native MotherDuck integration with connection string:
        md:database_name?motherduck_token=TOKEN

        Returns:
            DuckDB connection connected to MotherDuck
        """
        if self.connection is not None:
            return self.connection

        # Build MotherDuck connection string
        connection_string = f"md:{self.database}?motherduck_token={self.token}"

        try:
            logger.info(f"Connecting to MotherDuck database: {self.database}")
            self.connection = duckdb.connect(connection_string)

            # Set memory limit for local operations
            self.connection.execute(f"SET memory_limit = '{self.memory_limit}'")

            # Test connection
            result = self.connection.execute("SELECT 1 AS test").fetchone()
            if result and result[0] == 1:
                logger.info("MotherDuck connection successful")
            else:
                raise ConnectionError("MotherDuck connection test failed")

            return self.connection

        except Exception as e:
            safe_error = _redact_motherduck_token(str(e), self.token)
            logger.error(f"Failed to connect to MotherDuck: {safe_error}")
            raise ConnectionError(
                f"Failed to connect to MotherDuck: {safe_error}\nCheck your MOTHERDUCK_TOKEN and network connection."
            ) from e

    def close_connection(self, connection=None):
        """Close MotherDuck connection."""
        conn = connection or self.connection
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.warning(f"Error closing MotherDuck connection: {e}")
        if connection is None:
            self.connection = None

    def get_query_plan(self, connection: Any, query: str) -> str | None:
        """Get MotherDuck query execution plan using EXPLAIN (ANALYZE, FORMAT JSON).

        MotherDuck uses DuckDB's SQL dialect; EXPLAIN format is identical.
        DuckDB EXPLAIN rows are (explain_key, explain_value) tuples; column 1 is the JSON payload.
        """
        analyze = getattr(self, "analyze_plans", True)
        explain_options = "ANALYZE, FORMAT JSON" if analyze else "FORMAT JSON"
        try:
            rows = (connection or self.connection).execute(f"EXPLAIN ({explain_options}) {query}").fetchall()
            # column 0 is the key (e.g. "analyzed_plan"), column 1 is the JSON value
            parts = [str(row[1]) for row in rows if len(row) > 1]
            return "\n".join(parts) if parts else None
        except Exception as e:
            logger.debug(f"Failed to get MotherDuck query plan: {e}")
            return None

    def get_query_plan_parser(self):
        """Get MotherDuck query plan parser (reuses DuckDB parser)."""
        from benchbox.core.query_plans.parsers.duckdb import DuckDBQueryPlanParser

        return DuckDBQueryPlanParser()

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
        """Execute a query against MotherDuck.

        Args:
            connection: Active database connection (falls back to self.connection or creates one).
            query: SQL query to execute.
            query_id: Query identifier for result tracking.
            benchmark_type: Benchmark type for optional row-count validation.
            scale_factor: Scale factor for optional row-count validation.
            validate_row_count: Whether to validate row count.
            stream_id: Stream identifier for multi-stream benchmarks.

        Returns:
            Dict with query_id, status, execution_time_seconds, rows_returned, etc.
        """
        conn = connection or self.connection
        if conn is None:
            conn = self.create_connection()

        start_time = mono_time()
        try:
            result = conn.execute(query)
            rows = result.fetchall()
            execution_time = elapsed_seconds(start_time)
            logger.debug(f"Query {query_id} completed in {execution_time:.3f}s, returned {len(rows)} rows")
            result_dict = {
                "query_id": query_id,
                "stream_id": stream_id,
                "status": "SUCCESS",
                "execution_time_seconds": execution_time,
                "rows_returned": len(rows),
                "first_row": rows[0] if rows else None,
                "error": None,
            }

            # Capture structured query plan if enabled
            if self.capture_plans:
                query_plan, plan_capture_time_ms = self.capture_query_plan(conn, query, query_id)
                if query_plan:
                    result_dict["query_plan"] = query_plan
                    result_dict["plan_fingerprint"] = query_plan.plan_fingerprint
                if plan_capture_time_ms is not None:
                    result_dict["plan_capture_time_ms"] = plan_capture_time_ms

            return result_dict
        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            logger.error(f"Query {query_id} failed after {execution_time:.2f}s: {e}")
            return {
                "query_id": query_id,
                "stream_id": stream_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get MotherDuck platform information for results traceability."""
        info: dict[str, Any] = {
            "platform_type": "motherduck",
            "platform_name": self.platform_name,
            "platform_version": "unknown",
            "connection_mode": "remote",
            "configuration": {
                "database": self.database,
            },
            "client_library_version": getattr(duckdb, "__version__", None) if duckdb else None,
        }

        # Probe engine version from active connection
        conn = connection or self.connection
        if conn:
            try:
                result = conn.execute("SELECT version()").fetchone()
                if result:
                    info["platform_version"] = result[0]
                    info["engine_version"] = result[0]
                    info["engine_version_source"] = "sql_query"
            except Exception:
                logger.debug("Failed to probe MotherDuck engine version via SELECT version()", exc_info=True)

        return info

    def get_platform_metadata(self) -> dict[str, Any]:
        """Get platform metadata including MotherDuck-specific info."""
        metadata = {
            "platform_type": "motherduck",
            "platform_name": self.platform_name,
            "dialect": self._dialect,
            "database": self.database,
            "inherits_from": "duckdb",
        }

        # Add DuckDB version info if connected
        if self.connection:
            try:
                result = self.connection.execute("SELECT version()").fetchone()
                if result:
                    metadata["duckdb_version"] = result[0]
            except Exception:
                pass

        return metadata

    def test_connection(self) -> bool:
        """Test MotherDuck connection."""
        try:
            conn = self.create_connection()
            result = conn.execute("SELECT 1").fetchone()
            return result is not None and result[0] == 1
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False

    def create_schema(self, benchmark, connection) -> float:
        """Create database schema for the benchmark.

        MotherDuck uses DuckDB's SQL dialect, so schema creation follows
        the same pattern as local DuckDB.

        Args:
            benchmark: Benchmark instance with schema definitions
            connection: DuckDB connection to MotherDuck

        Returns:
            Time taken to create schema in seconds
        """
        start_time = time.perf_counter()

        # Get CREATE TABLE statements from benchmark
        schema_sql = benchmark.get_create_tables_sql(dialect="duckdb")

        # Execute each statement
        for statement in schema_sql.split(";"):
            statement = statement.strip()
            if statement:
                connection.execute(statement)

        return time.perf_counter() - start_time

    def load_data(self, benchmark, connection, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data into MotherDuck.

        Data can be loaded directly from local files into MotherDuck using
        DuckDB's file reading capabilities with MotherDuck's cloud backend.

        Args:
            benchmark: Benchmark instance
            connection: DuckDB connection to MotherDuck
            data_dir: Path to benchmark data directory

        Returns:
            Tuple of (row_counts, load_time, manifest)
        """
        start_time = time.perf_counter()
        row_counts: dict[str, int] = {}
        effective_tuning = self.unified_tuning_configuration if self.tuning_enabled else None

        # Get table files from data directory
        for table_file in data_dir.glob("*.parquet"):
            table_name = table_file.stem

            # Load parquet file directly into MotherDuck
            logger.info(f"Loading {table_name} from {table_file}")
            connection.execute(f"""
                INSERT INTO {table_name}
                SELECT * FROM read_parquet('{table_file}')
            """)

            # Get row count
            result = connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
            row_counts[table_name] = result[0] if result else 0

            if effective_tuning:
                self.apply_ctas_sort(table_name, effective_tuning, connection)

        load_time = time.perf_counter() - start_time
        return row_counts, load_time, None

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Create MotherDuck external views over Parquet/Delta sources."""
        return _create_duckdb_external_views(self, benchmark, connection, data_dir)

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build MotherDuck CTAS SQL using DuckDB-compatible syntax."""
        return _build_duckdb_ctas_sort_sql(table_name, sort_columns)

    def apply_platform_optimizations(self, platform_config, connection) -> None:
        """Apply platform-specific optimizations.

        MotherDuck handles optimization automatically - this is a no-op.
        """

    def apply_constraint_configuration(self, primary_key_config, foreign_key_config, connection) -> None:
        """Apply constraint configuration.

        MotherDuck/DuckDB doesn't enforce constraints by default,
        so this is typically a no-op unless explicitly configured.
        """

    def configure_for_benchmark(self, connection, benchmark_type: str) -> None:
        """Configure MotherDuck for benchmark execution.

        MotherDuck automatically handles most optimizations. We can set
        some DuckDB-level configurations for local processing if needed.

        Args:
            connection: DuckDB connection to MotherDuck
            benchmark_type: Type of benchmark (e.g., "olap")
        """
        # MotherDuck handles optimization automatically
        # Set reasonable defaults for analytical workloads
        try:
            connection.execute(f"SET memory_limit = '{self.memory_limit}'")
        except Exception as e:
            logger.warning(f"Could not set memory_limit: {e}")


__all__ = ["MotherDuckAdapter"]
