"""SQLite platform adapter for testing and lightweight benchmarks.

Provides SQLite-specific functionality for BenchBox testing and small-scale benchmarks.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

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

from .base import DriverIsolationCapability, PlatformAdapter

try:
    import sqlite3
except ImportError:
    sqlite3 = None

_TPCH_TABLES: frozenset[str] = frozenset(
    {"customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"}
)

_TPCH_HELPER_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_bb_tpch_lineitem_order_supp_dates "
    "ON lineitem (l_orderkey, l_suppkey, l_receiptdate, l_commitdate)",
    "CREATE INDEX IF NOT EXISTS idx_bb_tpch_orders_status_order ON orders (o_orderstatus, o_orderkey)",
    "CREATE INDEX IF NOT EXISTS idx_bb_tpch_supplier_nation_supp ON supplier (s_nationkey, s_suppkey)",
    "CREATE INDEX IF NOT EXISTS idx_bb_tpch_nation_name_key ON nation (n_name, n_nationkey)",
)


class SQLiteAdapter(PlatformAdapter):
    """SQLite platform adapter for testing and lightweight usage."""

    driver_isolation_capability = DriverIsolationCapability.NOT_APPLICABLE

    @property
    def platform_name(self) -> str:
        return "SQLite"

    @staticmethod
    def add_cli_arguments(parser) -> None:  # type: ignore[override]
        """Add SQLite-specific CLI arguments.

        Kept minimal for testing; provides database path and basic options.

        NOTE: These flags (``--sqlite-database``, etc.) are legacy and are NOT
        exposed by ``benchbox run``.  Use ``--platform-option database_path=<path>``
        instead, which is registered in PlatformHookRegistry and appears in
        ``benchbox run --help``.
        """
        if not hasattr(parser, "add_argument"):
            return
        try:
            parser.add_argument(
                "--sqlite-database",
                dest="database_path",
                help="SQLite database path (auto-generated when --benchmark/--scale provided)",
            )
            parser.add_argument(
                "--sqlite-timeout",
                dest="timeout",
                type=float,
                default=30.0,
                help="SQLite connection timeout in seconds",
            )
            parser.add_argument(
                "--sqlite-check-same-thread",
                dest="check_same_thread",
                action="store_true",
                help="Enable SQLite check_same_thread flag",
            )
        except Exception:
            # Be resilient in non-argparse parser usages in tests
            pass

    @classmethod
    def from_config(cls, config: dict[str, Any]):  # type: ignore[override]
        """Create SQLite adapter from unified configuration.

        Handles configuration from multiple sources:
        - connection_string: Path to database file (from DatabaseConfig)
        - database_path: Direct path specification (from options or CLI)
        - Auto-generation: Creates path in benchmark_runs/databases if needed
        """
        from pathlib import Path

        from benchbox.utils.database_naming import generate_database_filename

        # Extract SQLite-specific configuration
        adapter_config = {}

        # Database path handling - check multiple sources
        # Priority: database_path > connection_string > auto-generate
        if config.get("database_path"):
            adapter_config["database_path"] = config["database_path"]
        elif config.get("connection_string"):
            # Extract from connection_string (set by platform_defaults.py)
            adapter_config["database_path"] = config["connection_string"]
        elif config.get("benchmark") and config.get("scale_factor") is not None:
            # Generate database path using canonical benchmark_runs/databases path.
            from benchbox.utils.path_utils import get_benchmark_runs_databases_path

            if config.get("output_dir"):
                data_dir = get_benchmark_runs_databases_path(
                    config["benchmark"],
                    config["scale_factor"],
                    base_dir=Path(config["output_dir"]) / "databases",
                )
            else:
                data_dir = get_benchmark_runs_databases_path(config["benchmark"], config["scale_factor"])

            db_filename = generate_database_filename(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="sqlite",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database_path"] = str(data_dir / db_filename)
            # Create directory if it doesn't exist
            data_dir.mkdir(parents=True, exist_ok=True)
        else:
            # No database path and no benchmark/scale to generate one - raise error
            from ..core.exceptions import ConfigurationError

            raise ConfigurationError(
                "SQLite requires database path configuration.\n"
                "Either pass --platform-option database_path=<path> or provide --benchmark and --scale."
            )

        # Extract optional configuration parameters
        adapter_config["timeout"] = config.get("timeout", 30.0)
        adapter_config["check_same_thread"] = config.get("check_same_thread", False)

        # Force recreate (if database should be replaced)
        # force_recreate may arrive via config["options"] (from DatabaseConfig.model_dump() in the
        # execution pipeline) or directly at the top level (direct API usage / old code path).
        _opts = config.get("options") or {}
        adapter_config["force_recreate"] = bool(
            config.get("force_recreate") or _opts.get("force_recreate") or config.get("force")
        )

        # Pass through other relevant config (verbose settings, tuning config, etc.)
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get SQLite platform information."""
        platform_info = {
            "platform_type": "sqlite",
            "platform_name": "SQLite",
            "connection_mode": "memory" if self.database_path == ":memory:" else "file",
            "configuration": {
                "database_path": self.database_path,
                "timeout": self.timeout,
                "check_same_thread": self.check_same_thread,
            },
        }

        # Get SQLite version
        try:
            import sqlite3

            # sqlite3 is built into Python, so we use "builtin" for the client library version
            platform_info["client_library_version"] = "builtin"
            platform_info["platform_version"] = sqlite3.sqlite_version
        except (ImportError, AttributeError):
            platform_info["client_library_version"] = None
            platform_info["platform_version"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for SQLite."""
        return "sqlite"

    def __init__(self, **config):
        super().__init__(**config)
        if sqlite3 is None:
            raise ImportError("SQLite not available (should be included with Python)")

        # SQLite configuration
        self.database_path = config.get("database_path", ":memory:")
        self.timeout = config.get("timeout", 30.0)
        self.check_same_thread = config.get("check_same_thread", False)

    def get_database_path(self, **connection_config) -> str | None:
        """Get the database file path for SQLite."""
        # Return connection_config database_path if provided and not None
        db_path = connection_config.get("database_path")
        if db_path is not None:
            return db_path
        # Otherwise return instance database_path
        return self.database_path

    def create_connection(self, **connection_config) -> Any:
        """Create SQLite connection."""
        self.log_operation_start("SQLite connection")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        db_path = self.get_database_path(**connection_config)
        self.log_very_verbose(f"SQLite database path: {db_path}")

        # Create connection
        conn = sqlite3.connect(db_path, timeout=self.timeout, check_same_thread=self.check_same_thread)

        # Apply SQLite optimizations
        optimizations_applied = []

        # Enable foreign keys (disabled by default in SQLite)
        conn.execute("PRAGMA foreign_keys = ON")
        optimizations_applied.append("foreign_keys=ON")

        # Optimize for better performance
        conn.execute("PRAGMA journal_mode = WAL")
        optimizations_applied.append("journal_mode=WAL")

        conn.execute("PRAGMA synchronous = NORMAL")
        optimizations_applied.append("synchronous=NORMAL")

        conn.execute("PRAGMA cache_size = 10000")
        optimizations_applied.append("cache_size=10000")

        conn.execute("PRAGMA temp_store = MEMORY")
        optimizations_applied.append("temp_store=MEMORY")

        self.log_operation_complete("SQLite connection", details=f"Applied: {', '.join(optimizations_applied)}")

        return conn

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using benchmark's SQL definitions."""
        start_time = mono_time()
        self.log_operation_start("Schema creation", f"benchmark: {benchmark.__class__.__name__}")

        # Use common schema creation helper
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

        self.log_very_verbose(f"Executing schema creation script ({len(schema_sql)} characters)")

        # Execute schema creation
        connection.executescript(schema_sql)
        connection.commit()

        duration = elapsed_seconds(start_time)
        self.log_operation_complete("Schema creation", duration, "Schema and tables created")
        return duration

    def apply_table_tunings(self, table_tuning: TableTuning, connection: Any) -> None:
        """Apply tuning configurations to SQLite (limited support)."""
        # SQLite has limited tuning options
        # Most tuning is handled through connection pragmas

    def generate_tuning_clause(self, table_tuning: TableTuning) -> str:
        """Generate SQLite-specific tuning clauses (none supported)."""
        return ""

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration (limited support in SQLite)."""
        # SQLite doesn't support tuning features

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply SQLite-specific optimizations."""
        # Basic optimizations are applied in create_connection

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to SQLite."""
        if foreign_key_config and hasattr(foreign_key_config, "enabled"):
            if foreign_key_config.enabled:
                connection.execute("PRAGMA foreign_keys = ON")
            else:
                connection.execute("PRAGMA foreign_keys = OFF")

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data into SQLite."""
        from benchbox.platforms.base.data_loading import DataLoader

        loader = DataLoader(
            adapter=self,
            benchmark=benchmark,
            connection=connection,
            data_dir=data_dir,
            tuning_config=self.unified_tuning_configuration if self.tuning_enabled else None,
        )
        table_stats, loading_time = loader.load()
        helper_index_time = self._apply_benchmark_helper_indexes(benchmark, connection)
        # DataLoader doesn't provide per-table timings yet
        return table_stats, loading_time + helper_index_time, None

    def _apply_benchmark_helper_indexes(self, benchmark: Any, connection: Any) -> float:
        """Apply small SQLite indexes needed to keep local benchmark smoke runs terminating."""
        if not _is_tpch_benchmark(benchmark):
            return 0.0

        existing_tables = set(self._get_existing_tables(connection))
        if not _TPCH_TABLES.issubset(existing_tables):
            missing = ", ".join(sorted(_TPCH_TABLES - existing_tables))
            self.log_very_verbose(f"Skipping SQLite TPC-H helper indexes; missing tables: {missing}")
            return 0.0

        start_time = mono_time()
        created = 0
        for statement in _TPCH_HELPER_INDEXES:
            try:
                connection.execute(statement)
                created += 1
            except Exception as exc:
                self.logger.warning("SQLite helper index creation failed: %s", exc)

        if created:
            connection.commit()
            self.log_verbose(f"Applied {created} SQLite TPC-H helper index(es)")

        return elapsed_seconds(start_time)

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """SQLite does not support efficient post-load CTAS sorting in this workflow."""
        return None

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in the SQLite database.

        Override the base class implementation with SQLite-specific query.
        SQLite uses sqlite_master table instead of information_schema.

        Args:
            connection: SQLite connection

        Returns:
            List of table names (lowercase)
        """
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            result = cursor.fetchall()
            # Convert to lowercase for consistent comparison
            return [row[0].lower() for row in result]
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply SQLite optimizations for benchmark type."""
        if benchmark_type == "olap":
            # OLAP optimizations
            connection.execute("PRAGMA query_only = false")
            connection.execute("PRAGMA read_uncommitted = true")
        elif benchmark_type == "oltp":
            # OLTP optimizations
            connection.execute("PRAGMA synchronous = FULL")

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
        start_time = mono_time()
        self.log_verbose(f"Executing query {query_id}")
        self.log_very_verbose(f"Query SQL (first 200 chars): {query[:200]}{'...' if len(query) > 200 else ''}")

        try:
            cursor = connection.cursor()
            cursor.execute(query)
            results = cursor.fetchall()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(results)

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

            # Use centralized helper to build result with consistent validation field mapping
            # Note: SQLite returns "results" instead of "first_row" for backward compatibility
            result = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=results[0] if results else None,
                validation_result=validation_result,
            )
            # Include full results for SQLite compatibility
            result["results"] = results
            return result

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
            }

    def run_power_test(self, benchmark, **kwargs) -> dict[str, Any]:
        """Run TPC power test (not implemented for SQLite)."""
        raise NotImplementedError("Power test not implemented for SQLite adapter")

    def run_throughput_test(self, benchmark, **kwargs) -> dict[str, Any]:
        """Run TPC throughput test (not implemented for SQLite)."""
        raise NotImplementedError("Throughput test not implemented for SQLite adapter")

    def run_maintenance_test(self, benchmark, **kwargs) -> dict[str, Any]:
        """Run TPC maintenance test (not implemented for SQLite)."""
        raise NotImplementedError("Maintenance test not implemented for SQLite adapter")


def _is_tpch_benchmark(benchmark: Any) -> bool:
    benchmark_id = str(getattr(benchmark, "benchmark_id", "") or getattr(benchmark, "id", "")).lower()
    if benchmark_id in {"tpch", "tpc-h"}:
        return True
    class_name = benchmark.__class__.__name__.lower()
    display_name = str(getattr(benchmark, "_name", "") or getattr(benchmark, "name", "")).lower()
    return "tpch" in class_name or "tpc-h" in display_name
