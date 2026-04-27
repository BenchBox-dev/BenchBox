"""pg_duckdb platform adapter for BenchBox benchmarking.

Extends PostgreSQL adapter with pg_duckdb-specific functionality:
- DuckDB vectorized execution engine on PostgreSQL heap tables
- GUC parameter configuration (duckdb.force_execution, thread tuning)
- MotherDuck deployment mode for hybrid cloud queries

pg_duckdb is a PostgreSQL extension that embeds DuckDB's columnar-vectorized
analytics engine inside PostgreSQL, accelerating OLAP queries without requiring
SQL changes or data migration.

Deployment modes:
- self-hosted: Self-hosted PostgreSQL with pg_duckdb extension (default)
- motherduck: MotherDuck-connected mode for hybrid local+cloud queries

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from .postgresql import POSTGRES_DIALECT, PostgreSQLAdapter, _build_postgres_connection_kwargs

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


class PgDuckDBAdapter(PostgreSQLAdapter):
    """pg_duckdb platform adapter with DuckDB-accelerated query execution.

    Extends PostgreSQLAdapter with pg_duckdb-specific features:
    - DuckDB vectorized execution for analytical queries
    - Configurable force_execution and thread tuning
    - MotherDuck hybrid cloud mode

    Requires PostgreSQL 14+ with pg_duckdb 1.0+ extension installed.
    """

    @property
    def platform_name(self) -> str:
        return "pg_duckdb"

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for pg_duckdb (PostgreSQL-compatible)."""
        return POSTGRES_DIALECT

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add pg_duckdb-specific CLI arguments."""
        if not hasattr(parser, "add_argument"):
            return
        try:
            # Inherit PostgreSQL connection arguments
            parser.add_argument(
                "--pgduckdb-host",
                dest="host",
                default="localhost",
                help="PostgreSQL server hostname (with pg_duckdb installed)",
            )
            parser.add_argument(
                "--pgduckdb-port",
                dest="port",
                type=int,
                default=5432,
                help="PostgreSQL server port",
            )
            parser.add_argument(
                "--pgduckdb-database",
                dest="database",
                help="PostgreSQL database name (auto-generated if not specified)",
            )
            parser.add_argument(
                "--pgduckdb-username",
                dest="username",
                default="postgres",
                help="PostgreSQL username",
            )
            parser.add_argument(
                "--pgduckdb-password",
                dest="password",
                help="PostgreSQL password",
            )
            parser.add_argument(
                "--pgduckdb-schema",
                dest="schema",
                default="public",
                help="PostgreSQL schema name",
            )
            # pg_duckdb-specific options
            parser.add_argument(
                "--pgduckdb-force-execution",
                dest="force_execution",
                action="store_true",
                default=True,
                help="Force DuckDB execution engine for all queries (default: True)",
            )
            parser.add_argument(
                "--pgduckdb-threads",
                dest="postgres_scan_threads",
                type=int,
                default=0,
                help="Threads for PostgreSQL table scanning (0 = auto)",
            )
        except Exception:
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> PgDuckDBAdapter:
        """Create pg_duckdb adapter from unified configuration."""
        adapter_config = _build_postgres_connection_kwargs(config)
        adapter_config["force_execution"] = config.get("force_execution", True)
        adapter_config["postgres_scan_threads"] = config.get("postgres_scan_threads", 0)
        adapter_config["compare_native"] = config.get("compare_native", False)
        adapter_config["duckdb_db_path"] = config.get("duckdb_db_path")
        adapter_config["deployment_mode"] = config.get("deployment_mode", "self-hosted")
        if config.get("motherduck_token"):
            adapter_config["motherduck_token"] = config["motherduck_token"]
        return cls(**adapter_config)

    def __init__(self, **config):
        # Determine deployment mode with priority:
        # 1. deployment_mode (from factory via colon syntax: pg-duckdb:motherduck)
        # 2. Default to 'self-hosted'
        deployment_mode = config.get("deployment_mode", "self-hosted")
        self.deployment_mode = deployment_mode.lower()

        # Validate deployment mode
        valid_modes = {"self-hosted", "motherduck"}
        if self.deployment_mode not in valid_modes:
            raise ValueError(
                f"Invalid pg_duckdb deployment mode '{self.deployment_mode}'. "
                f"Valid modes: {', '.join(sorted(valid_modes))}"
            )

        # Configure for MotherDuck mode if specified
        if self.deployment_mode == "motherduck":
            self._configure_motherduck_mode(config)

        super().__init__(**config)

        # pg_duckdb-specific configuration
        self.force_execution = config.get("force_execution", True)
        self.postgres_scan_threads = config.get("postgres_scan_threads", 0)

        # Native DuckDB comparison (triggered by --platform-option compare_native=true).
        # from_config() normalizes the string "true"/"false" to bool; direct callers
        # may pass either type, so coerce here once.
        raw_compare = config.get("compare_native", False)
        self.compare_native: bool = (
            str(raw_compare).lower() == "true" if isinstance(raw_compare, str) else bool(raw_compare)
        )
        self.duckdb_db_path: str | None = config.get("duckdb_db_path")

        # MotherDuck token (set in _configure_motherduck_mode or from env)
        self.motherduck_token = config.get("motherduck_token") or os.environ.get("MOTHERDUCK_TOKEN")

    def _configure_motherduck_mode(self, config: dict) -> None:
        """Configure adapter for MotherDuck hybrid mode.

        MotherDuck mode connects pg_duckdb to a MotherDuck cloud database,
        enabling hybrid queries that join local PostgreSQL tables with
        cloud-hosted MotherDuck data.

        Credentials via:
        - Config parameter: motherduck_token
        - Environment variable: MOTHERDUCK_TOKEN
        """
        token = config.get("motherduck_token") or os.environ.get("MOTHERDUCK_TOKEN")
        if not token:
            raise ValueError(
                "MotherDuck deployment mode requires authentication token.\n"
                "Provide via --platform-option motherduck_token=<token> or "
                "set MOTHERDUCK_TOKEN environment variable.\n"
                "Get your token at https://app.motherduck.com/token"
            )
        config["motherduck_token"] = token

    def create_connection(self, **connection_config) -> Any:
        """Create PostgreSQL connection and configure pg_duckdb extension."""
        conn = super().create_connection(**connection_config)

        cursor = conn.cursor()
        try:
            # Verify pg_duckdb extension is installed
            cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_duckdb'")
            result = cursor.fetchone()
            if result:
                self.logger.info(f"pg_duckdb extension version: {result[0]}")
            else:
                # Try to create the extension
                self.logger.info("pg_duckdb extension not found, attempting to create...")
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_duckdb")
                conn.commit()
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_duckdb'")
                result = cursor.fetchone()
                if result:
                    self.logger.info(f"Created pg_duckdb extension version: {result[0]}")
                else:
                    raise RuntimeError(
                        "pg_duckdb extension is not available on this PostgreSQL server. "
                        "Install pg_duckdb (https://github.com/duckdb/pg_duckdb) or use "
                        "the 'postgresql' or 'duckdb' platform instead."
                    )

            # Set pg_duckdb GUC parameters
            if self.force_execution:
                cursor.execute("SET duckdb.force_execution = true")
                self.logger.info("Enabled duckdb.force_execution for DuckDB query routing")

            if self.postgres_scan_threads > 0:
                cursor.execute(f"SET duckdb.threads_for_postgres_scan = {int(self.postgres_scan_threads)}")
                self.logger.info(f"Set duckdb.threads_for_postgres_scan = {self.postgres_scan_threads}")

            # Configure MotherDuck if in motherduck mode
            if self.deployment_mode == "motherduck" and self.motherduck_token:
                cursor.execute(
                    psycopg_sql.SQL("SET duckdb.motherduck_token = {}").format(
                        psycopg_sql.Literal(self.motherduck_token)
                    )
                )
                self.logger.info("Configured MotherDuck token for hybrid queries")

            conn.commit()

        except RuntimeError:
            cursor.close()
            raise
        except Exception as e:
            self.logger.error(f"Failed to configure pg_duckdb extension: {e}")
            cursor.close()
            raise RuntimeError(f"pg_duckdb configuration failed: {e}") from e
        finally:
            if not cursor.closed:
                cursor.close()

        return conn

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply pg_duckdb optimizations for benchmark type.

        pg_duckdb benefits from PostgreSQL OLAP settings but also adds
        DuckDB-specific execution configuration.
        """
        # Apply PostgreSQL OLAP optimizations first
        super().configure_for_benchmark(connection, benchmark_type)

        cursor = connection.cursor()
        try:
            if benchmark_type == "olap":
                # Ensure DuckDB execution is forced for analytical workloads
                cursor.execute("SET duckdb.force_execution = true")

            connection.commit()
        except Exception as e:
            self.logger.debug(f"Could not set pg_duckdb benchmark optimizations: {e}")
        finally:
            cursor.close()

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get pg_duckdb platform information."""
        platform_info = super().get_platform_info(connection)

        # Override platform type and name
        platform_info["platform_type"] = "pg_duckdb"
        platform_info["platform_name"] = "pg_duckdb"

        # Add pg_duckdb-specific configuration
        platform_info["configuration"]["force_execution"] = self.force_execution
        platform_info["configuration"]["postgres_scan_threads"] = self.postgres_scan_threads
        platform_info["configuration"]["deployment_mode"] = self.deployment_mode

        if connection:
            try:
                cursor = connection.cursor()

                # Get pg_duckdb version
                cursor.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_duckdb'")
                result = cursor.fetchone()
                if result:
                    platform_info["pg_duckdb_version"] = result[0]

                cursor.close()
            except Exception as e:
                self.logger.debug(f"Error getting pg_duckdb info: {e}")

        return platform_info

    def run_native_comparison(
        self,
        query_results: list[dict],
        query_sql_map: dict[str, str],
        scale_factor: float,
    ) -> Any:
        """Compare pg_duckdb query timings against native DuckDB execution.

        Replays each query from query_results on a native DuckDB connection,
        then computes per-query timing deltas. Triggered via
        --platform-option compare_native=true (self.compare_native must be True).

        The native DuckDB connection uses self.duckdb_db_path when provided
        (--platform-option duckdb_db_path=/path/to/db.duckdb), otherwise opens
        an in-memory database. The in-memory path is useful for structural
        timing comparisons (empty tables); point to a populated DuckDB file for
        meaningful end-to-end comparison.

        Timing caveat: pg_duckdb timings are *averaged* across all measurement
        rows (potentially multiple warm iterations), while native DuckDB
        timings are a single cold run. Positive deltas therefore overstate the
        gap when pg_duckdb has had warmup benefit. Interpret deltas as
        directional, not exact.

        Args:
            query_results: List of query result dicts from the pg_duckdb run.
                Each dict must have 'query_id' and 'ms' (execution time in ms).
                Only measurement rows (run_type == 'measurement' or absent) are used;
                warmup rows are skipped.
            query_sql_map: Mapping of query_id -> SQL string for native replay.
            scale_factor: Scale factor of the benchmark (carried into the result).

        Returns:
            NativeComparison instance, or None if compare_native is False or
            duckdb is not importable.
        """
        if not self.compare_native:
            return None

        try:
            import duckdb as _duckdb
        except ImportError:
            self.logger.warning(
                "compare_native=true requested but duckdb package is not installed. "
                "Install duckdb to enable native comparison."
            )
            return None

        from benchbox.core.results.models import NativeComparison, NativeComparisonEntry

        # Build pg_duckdb timing lookup: query_id -> mean ms over measurement rows
        pg_timings: dict[str, list[float]] = {}
        for row in query_results:
            qid = row.get("query_id") or row.get("id")
            run_type = row.get("run_type", "measurement")
            if qid and run_type != "warmup" and qid in query_sql_map:
                ms = row.get("ms") or row.get("execution_time_ms")
                if ms is not None:
                    pg_timings.setdefault(qid, []).append(float(ms))

        if not pg_timings:
            self.logger.info("run_native_comparison: no matching measurement rows found")
            return None

        db_path = self.duckdb_db_path or ":memory:"
        entries: list[NativeComparisonEntry] = []

        try:
            native_conn = _duckdb.connect(db_path, read_only=bool(self.duckdb_db_path))
        except Exception as exc:
            self.logger.warning(f"run_native_comparison: could not open DuckDB at {db_path!r}: {exc}")
            return None

        try:
            for query_id, pg_ms_list in sorted(pg_timings.items()):
                sql = query_sql_map[query_id]
                pg_mean_ms = sum(pg_ms_list) / len(pg_ms_list)
                t0 = time.monotonic()
                try:
                    native_conn.execute(sql).fetchall()
                    native_ms = (time.monotonic() - t0) * 1000
                except Exception as exc:
                    self.logger.debug(f"Native DuckDB query {query_id} failed: {exc}")
                    continue
                entries.append(
                    NativeComparisonEntry(
                        query_id=query_id,
                        pg_duckdb_ms=round(pg_mean_ms, 3),
                        duckdb_ms=round(native_ms, 3),
                        delta_ms=round(pg_mean_ms - native_ms, 3),
                    )
                )
        finally:
            native_conn.close()

        if not entries:
            return None

        deltas = [e.delta_ms for e in entries]
        return NativeComparison(
            generated_at=datetime.now(tz=timezone.utc).isoformat(),
            scale_factor=scale_factor,
            total_queries=len(entries),
            mean_delta_ms=round(sum(deltas) / len(deltas), 3),
            max_delta_ms=round(max(deltas), 3),
            entries=entries,
        )

    def supports_tuning_type(self, tuning_type: Any) -> bool:
        """Check if pg_duckdb supports a specific tuning type.

        pg_duckdb operates on standard PostgreSQL heap tables, so tuning
        capabilities match PostgreSQL. The main optimization is the DuckDB
        execution engine itself, which benefits less from B-tree indexes
        for analytical queries.
        """
        try:
            from benchbox.core.tuning.interface import TuningType

            supported = {
                TuningType.PARTITIONING: True,  # PostgreSQL declarative partitioning
                TuningType.SORTING: False,  # No native sort keys
                TuningType.DISTRIBUTION: False,  # Not distributed
                TuningType.CLUSTERING: True,  # CLUSTER command available
                TuningType.PRIMARY_KEYS: True,  # Full constraint support
                TuningType.FOREIGN_KEYS: True,  # Full constraint support
            }
            return supported.get(tuning_type, False)
        except ImportError:
            return False


def _build_pg_duckdb_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: PlatformInfo | None,
) -> DatabaseConfig:
    """Build pg_duckdb database configuration with credential loading.

    This function is registered with PlatformHookRegistry to provide
    pg_duckdb-specific configuration handling.
    """
    from benchbox.platforms.base.config_utils import POSTGRES_FAMILY_BASE_OPTIONS, build_platform_config

    return build_platform_config(
        platform_type="pg-duckdb",
        credential_key="pg-duckdb",
        default_display_name="pg_duckdb",
        default_driver_package="psycopg",
        base_options={
            **POSTGRES_FAMILY_BASE_OPTIONS,
            "force_execution": True,
            "postgres_scan_threads": 0,
            "compare_native": False,
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
            "force_execution",
            "postgres_scan_threads",
            "compare_native",
            "duckdb_db_path",
        ],
        options=options,
        overrides=overrides,
        info=info,
    )
