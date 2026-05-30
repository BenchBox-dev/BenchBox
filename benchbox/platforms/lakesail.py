"""LakeSail Sail platform adapter for Spark-compatible SQL benchmarking.

Provides a high-performance Spark-compatible SQL adapter using LakeSail Sail,
a Rust-based drop-in replacement for Apache Spark built on DataFusion.

LakeSail Sail connects via the Spark Connect protocol, so it uses the standard
PySpark client library. This adapter targets a running Sail server endpoint
rather than creating a local SparkSession directly.

Key characteristics:
- 4x faster execution with 94% lower hardware costs vs Apache Spark (TPC-H SF100)
- Zero rewrite migration: Uses standard PySpark client via Spark Connect protocol
- Dual execution modes: Multi-threaded single-host or distributed cluster
- Built on DataFusion with Rust workers

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import argparse
import subprocess
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from ._spark_helpers import (
    SparkLikeAdapterMixin,
    analyze_spark_table,
    get_spark_query_plan,
    is_spark_connect_reachable,
    list_spark_tables,
    optimize_spark_table_definition,
    parse_spark_connect_endpoint,
    purge_orphaned_warehouse_directory,
    run_spark_schema_creation_loop,
    validate_spark_identifier,
)
from .base import DriverIsolationCapability, PlatformAdapter
from .base.config_utils import make_registered_platform_config_builder
from .base.spark_execution_mixin import SparkDataLoadMixin, SparkQueryExecutionMixin

try:
    from pyspark.sql import SparkSession
    from pyspark.sql.types import (
        DoubleType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
    )
except ImportError:
    SparkSession = None
    StructType = None
    StructField = None
    StringType = None
    IntegerType = None
    LongType = None
    DoubleType = None


class LakeSailAdapter(SparkLikeAdapterMixin, SparkDataLoadMixin, SparkQueryExecutionMixin, PlatformAdapter):
    """LakeSail Sail platform adapter for Spark-compatible SQL execution.

    LakeSail Sail is a Rust-based, drop-in replacement for Apache Spark that
    delivers significant performance improvements while maintaining full Spark
    SQL and DataFrame API compatibility via the Spark Connect protocol.

    This adapter connects to a running Sail server using the standard PySpark
    Spark Connect client rather than creating a local SparkSession directly.

    Key Features:
    - Spark Connect protocol for client-server communication
    - DataFusion-based query optimizer and execution engine
    - Support for local (single-node) and distributed cluster modes
    - Spark SQL dialect compatibility via SQLGlot transpilation
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    # Sail's CSV reader accepts zstd but doesn't auto-detect from file
    # extensions, so we must pass it explicitly (unlike Apache Spark).
    _csv_compression_codecs: frozenset[str] = SparkDataLoadMixin._csv_compression_codecs | frozenset({"zstd"})

    # Sail's file scanner only recognises the .csv extension for CSV reads.
    # Files with .dat or .tbl extensions are symlinked to .csv before loading.
    _requires_csv_extension: bool = True

    # Spark Connect does not implement PlanNode::Persist - df.cache() and
    # df.unpersist() are no-ops. Without a working cache, the count()-before-
    # write pattern in SparkDataLoadMixin would double-scan every parquet file.
    # Setting False switches to write-first, then one SQL COUNT(*) delta per
    # table after all chunks have been appended.
    _df_caching_supported: bool = False

    # Spark Connect does not implement PlanNode::ClearCache, so disable_cache
    # must not call spark.catalog.clearCache() in the shared query mixin.
    _catalog_clear_cache_supported: bool = False

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies (uses same pyspark package as Spark)
        if not SparkSession:
            available, missing = check_platform_dependencies("spark")
            if not available:
                error_msg = get_dependency_error_message("spark", missing)
                raise ImportError(error_msg)

        self._dialect = "spark"

        # LakeSail Sail server endpoint
        self.endpoint = config.get("endpoint") or "sc://localhost:50051"
        self.app_name = config.get("app_name") or "BenchBox-LakeSail"

        # Database configuration
        self.database = config.get("database") or "default"

        # Resource configuration (passed to Spark Connect session)
        self.driver_memory = config.get("driver_memory") or "4g"
        self.shuffle_partitions = (
            config.get("shuffle_partitions") if config.get("shuffle_partitions") is not None else 200
        )
        self.adaptive_enabled = config.get("adaptive_enabled") if config.get("adaptive_enabled") is not None else True

        # LakeSail-specific settings
        self.sail_mode = config.get("sail_mode") or "local"  # local or distributed
        self.sail_workers = config.get("sail_workers")  # worker count for distributed mode
        self.table_format = config.get("table_format") or "parquet"

        # Extra Spark configuration properties
        self.spark_config = config.get("spark_config") or {}

        # Result cache control. When True, disable in-memory columnar caching at
        # session creation via spark.sql.inMemoryColumnarStorage.enabled=false.
        # LakeSail keeps the same default benchmark semantics as Spark, but skips
        # the unsupported per-query clearCache() call via
        # _catalog_clear_cache_supported=False.
        self.disable_cache = config.get("disable_cache") if config.get("disable_cache") is not None else True

        # Store SparkSession reference
        self._spark_session = None

        # Subprocess handle for auto-started local server (managed lifecycle)
        self._managed_server_process = None

    @property
    def platform_name(self) -> str:
        return "LakeSail"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add LakeSail-specific CLI arguments."""
        lakesail_group = parser.add_argument_group("LakeSail Arguments")
        lakesail_group.add_argument(
            "--lakesail-endpoint",
            type=str,
            default="sc://localhost:50051",
            help="LakeSail Sail server endpoint (Spark Connect URL, e.g., sc://host:port)",
        )
        lakesail_group.add_argument(
            "--lakesail-mode",
            type=str,
            choices=["local", "distributed"],
            default="local",
            help="LakeSail deployment mode (local or distributed)",
        )
        lakesail_group.add_argument(
            "--lakesail-workers",
            type=int,
            help="Number of workers for distributed mode",
        )
        lakesail_group.add_argument(
            "--app-name",
            type=str,
            default="BenchBox-LakeSail",
            help="Application name for the Spark Connect session",
        )
        lakesail_group.add_argument(
            "--driver-memory",
            type=str,
            default="4g",
            help="Driver memory (e.g., 4g, 8g)",
        )
        lakesail_group.add_argument(
            "--shuffle-partitions",
            type=int,
            default=200,
            help="Number of shuffle partitions (spark.sql.shuffle.partitions)",
        )
        lakesail_group.add_argument(
            "--table-format",
            type=str,
            choices=["parquet", "orc"],
            default="parquet",
            help="Table format for creating benchmark tables",
        )
        lakesail_group.add_argument(
            "--adaptive-enabled",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Enable or disable Adaptive Query Execution (AQE)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create LakeSail adapter from unified configuration."""
        from benchbox.platforms.base.config_utils import build_adapter_config

        return cls(
            **build_adapter_config(
                config,
                platform="lakesail",
                fields=[
                    "endpoint",
                    "app_name",
                    "driver_memory",
                    "sail_mode",
                    "sail_workers",
                    "shuffle_partitions",
                    "adaptive_enabled",
                    "table_format",
                    "spark_config",
                    "disable_cache",
                ],
            )
        )

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get LakeSail platform information."""
        platform_info = {
            "platform_type": "lakesail",
            "platform_name": "LakeSail Sail",
            "connection_mode": self.sail_mode,
            "endpoint": self.endpoint,
            "configuration": {
                "database": self.database,
                "table_format": self.table_format,
                "driver_memory": self.driver_memory,
                "shuffle_partitions": self.shuffle_partitions,
                "adaptive_enabled": self.adaptive_enabled,
                "sail_mode": self.sail_mode,
                "sail_workers": self.sail_workers,
            },
        }

        # Get client library version
        if SparkSession:
            try:
                import pyspark

                platform_info["client_library_version"] = pyspark.__version__
            except (ImportError, AttributeError):
                platform_info["client_library_version"] = None
        else:
            platform_info["client_library_version"] = None

        # Try to get version info from connection
        if connection:
            try:
                spark = connection
                platform_info["platform_version"] = spark.version
            except Exception as e:
                self.logger.debug(f"Error collecting LakeSail platform info: {e}")
                platform_info["platform_version"] = None
        else:
            platform_info["platform_version"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for LakeSail (Spark-compatible)."""
        return "spark"

    def _get_spark_conf(self) -> dict[str, Any]:
        """Get Spark Connect configuration dictionary for Sail server."""
        conf = {
            "spark.app.name": self.app_name,
            "spark.sql.shuffle.partitions": str(self.shuffle_partitions),
        }

        # Adaptive Query Execution
        if self.adaptive_enabled:
            conf["spark.sql.adaptive.enabled"] = "true"
            conf["spark.sql.adaptive.coalescePartitions.enabled"] = "true"
            conf["spark.sql.adaptive.skewJoin.enabled"] = "true"

        # Disable result cache for benchmarking
        if self.disable_cache:
            conf["spark.sql.inMemoryColumnarStorage.enabled"] = "false"

        # Merge user-provided config
        conf.update(self.spark_config)

        return conf

    def _create_spark_session(self) -> Any:
        """Create a Spark Connect session with current adapter configuration."""
        builder = SparkSession.builder.remote(self.endpoint)
        for key, value in self._get_spark_conf().items():
            builder = builder.config(key, value)
        return builder.getOrCreate()

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists on the Sail server."""
        owns_session = False
        spark = self._spark_session
        try:
            if spark is None:
                spark = self._create_spark_session()
                owns_session = True

            database = connection_config.get("database", self.database)
            databases = [db.name for db in spark.catalog.listDatabases()]
            return database.lower() in [db.lower() for db in databases]

        except Exception as e:
            self.logger.debug(f"Error checking database existence: {e}")
            return False
        finally:
            if owns_session and spark is not None:
                try:
                    spark.stop()
                except Exception:
                    pass

    def drop_database(self, **connection_config) -> None:
        """Drop database on the Sail server."""
        database = connection_config.get("database", self.database)

        if not validate_spark_identifier(database):
            raise ValueError(f"Invalid database identifier: {database}")

        if not self.check_server_database_exists(database=database):
            self.log_verbose(f"Database {database} does not exist - nothing to drop")
            return

        owns_session = False
        spark = self._spark_session
        try:
            if spark is None:
                spark = self._create_spark_session()
                owns_session = True

            spark.sql(f"DROP DATABASE IF EXISTS {database} CASCADE")
            self.logger.info(f"Dropped database {database}")
        except Exception as e:
            raise RuntimeError(f"Failed to drop database {database}: {e}") from e
        finally:
            if owns_session and spark is not None:
                try:
                    spark.stop()
                except Exception:
                    pass

    def _auto_start_local_server(self) -> None:
        """Start pysail Spark Connect server as a managed subprocess (local mode only)."""
        import atexit
        import sys
        import time

        host, port = parse_spark_connect_endpoint(self.endpoint)
        self.log_verbose("Sail server not running - auto-starting local pysail server...")
        proc = subprocess.Popen(
            [sys.executable, "-m", "pysail", "spark", "server", "--ip", host, "--port", str(port)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        # Register atexit handler as safety net in case close_connection is never called
        def _cleanup_server():
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()

        atexit.register(_cleanup_server)

        # Wait up to 10 seconds for the server to accept connections
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            # Check if the process crashed before we even connect
            if proc.poll() is not None:
                stderr_output = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
                detail = f": {stderr_output}" if stderr_output else ""
                raise RuntimeError(
                    f"pysail server exited immediately (code {proc.returncode}){detail}. "
                    f"Start it manually: {sys.executable} -m pysail spark server"
                )
            time.sleep(0.5)
            if is_spark_connect_reachable(self.endpoint):
                self._managed_server_process = proc
                self._managed_server_atexit = _cleanup_server
                self.log_verbose("pysail server started and ready")
                return

        # Timeout - collect stderr for diagnostics
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        stderr_output = proc.stderr.read().decode(errors="replace").strip() if proc.stderr else ""
        detail = f"\nServer stderr: {stderr_output}" if stderr_output else ""
        raise RuntimeError(
            f"Auto-started pysail server did not become ready within 10 seconds.{detail}\n"
            f"Start it manually: {sys.executable} -m pysail spark server"
        )

    def _ensure_server_ready(self) -> None:
        """Ensure the Sail server is reachable; auto-start in local mode if not."""
        if is_spark_connect_reachable(self.endpoint):
            return

        if self.sail_mode == "local":
            try:
                import pysail  # noqa: F401
            except ImportError:
                raise RuntimeError(
                    f"Cannot connect to LakeSail Sail at {self.endpoint} and 'pysail' is not installed. "
                    "Install it with: uv add pysail\n"
                    "Then start the server manually: python -m pysail spark server"
                ) from None
            self._auto_start_local_server()
        else:
            host, port = parse_spark_connect_endpoint(self.endpoint)
            raise RuntimeError(
                f"Cannot connect to LakeSail Sail server at {self.endpoint}. "
                f"Ensure the server is running and reachable at {host}:{port}."
            )

    def create_connection(self, **connection_config) -> Any:
        """Create a Spark Connect session to the LakeSail Sail server."""
        self.log_operation_start("LakeSail Spark Connect session")

        self.log_very_verbose(f"LakeSail config: endpoint={self.endpoint}, database={self.database}")

        try:
            self._ensure_server_ready()
            spark = self._create_spark_session()
            self._spark_session = spark

            # Handle existing database using base class method.
            # This must run after session creation so server-side database checks work.
            self.handle_existing_database(**connection_config)

            # Create database if needed
            target_database = connection_config.get("database", self.database)
            if not validate_spark_identifier(target_database):
                raise ValueError(f"Invalid database identifier: {target_database}")

            if not self.database_was_reused:
                database_exists = self.check_server_database_exists(database=target_database)

                if not database_exists:
                    self.log_verbose(f"Creating database: {target_database}")
                    # Safety: target_database validated by validate_spark_identifier() above
                    spark.sql(f"CREATE DATABASE IF NOT EXISTS {target_database}")
                    self.logger.info(f"Created database {target_database}")

            # Safety: target_database validated by validate_spark_identifier() above
            # LakeSail's DataFusion-based parser requires explicit DATABASE keyword
            spark.sql(f"USE DATABASE {target_database}")

            self.logger.info(f"Connected to LakeSail Sail at {self.endpoint}")
            self.log_operation_complete("LakeSail Spark Connect session", details=f"Connected to {self.endpoint}")

            return spark

        except Exception as e:
            if self._spark_session is not None:
                try:
                    self._spark_session.stop()
                except Exception:
                    pass
                self._spark_session = None
            self.logger.error(f"Failed to connect to LakeSail Sail: {e}")
            raise

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Spark SQL DDL on Sail server.

        Defends against an orphaned warehouse directory left by a previous
        Sail session by running the same DB-level purge Velox uses; pysail's
        in-memory catalog keeps this rare but a long-running server with
        on-disk warehouse data hits the same LOCATION_ALREADY_EXISTS trap.
        Spark Connect cannot reach the server filesystem to clean per-table
        dirs, so the DB-level purge is the only mechanism available.
        """
        start_time = mono_time()

        spark = connection

        try:
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
            # Capture table_format once: see Velox.create_schema for rationale.
            fmt = self.table_format
            run_spark_schema_creation_loop(
                spark,
                statements,
                lambda stmt: optimize_spark_table_definition(stmt, table_format=fmt),
                logger=self.logger,
                on_pre_loop=lambda s: purge_orphaned_warehouse_directory(s, logger=self.logger),
            )
            self.logger.info("Schema created")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Sail-specific optimizations based on benchmark type."""
        spark = connection

        try:
            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
                spark.conf.set("spark.sql.adaptive.enabled", "true")
                spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "true")
                spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")
                spark.conf.set("spark.sql.cbo.enabled", "true")
                spark.conf.set("spark.sql.cbo.joinReorder.enabled", "true")

                self.logger.debug("Applied OLAP optimizations for LakeSail Sail")

        except Exception as e:
            self.logger.warning(f"Failed to apply benchmark configuration: {e}")

    def _get_dialect_queries(self, benchmark: Any, benchmark_slug: str, connection: Any | None = None) -> dict:
        """Use LakeSail-specific query rules where Spark syntax compatibility diverges."""
        if benchmark_slug == "vector_search" and hasattr(benchmark, "get_queries"):
            try:
                return benchmark.get_queries(
                    dialect="lakesail",
                    platform_version=self._get_runtime_platform_version(connection),
                )
            except TypeError:
                return benchmark.get_queries(dialect="lakesail")
        return super()._get_dialect_queries(benchmark, benchmark_slug, connection)

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan from Sail server."""
        return get_spark_query_plan(connection, query)

    def close_connection(self, connection: Any) -> None:
        """Close Spark Connect session and stop any auto-started local server."""
        try:
            if connection and hasattr(connection, "stop"):
                connection.stop()
                self._spark_session = None
        except Exception as e:
            self.logger.warning(f"Error closing LakeSail session: {e}")

        if self._managed_server_process is not None:
            try:
                self._managed_server_process.terminate()
                self._managed_server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._managed_server_process.kill()
            except Exception as e:
                self.logger.debug(f"Error stopping managed pysail server: {e}")
            finally:
                self._managed_server_process = None

            # Unregister atexit handler since we've cleaned up explicitly
            if hasattr(self, "_managed_server_atexit"):
                import atexit

                atexit.unregister(self._managed_server_atexit)
                del self._managed_server_atexit

    def test_connection(self) -> bool:
        """Test connection to LakeSail Sail server."""
        try:
            spark = self._create_spark_session()

            try:
                spark.sql("SELECT 1").collect()
                return True
            finally:
                spark.stop()
        except Exception as e:
            self.logger.debug(f"Connection test failed: {e}")
            return False

    _supported_tuning_type_names = ("PARTITIONING", "SORTING")

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Spark-compatible tuning clauses for CREATE TABLE statements."""
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            from benchbox.core.tuning.interface import TuningType

            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                clauses.append(f"PARTITIONED BY ({', '.join(column_names)})")

        except ImportError:
            pass

        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a table on Sail server."""
        from benchbox.platforms.base.tuning_utils import log_partition_tunings

        log_partition_tunings(table_tuning, self.logger, "LakeSail")

    # apply_unified_tuning, apply_platform_optimizations, and
    # apply_constraint_configuration come from SparkLikeAdapterMixin -
    # bodies were identical (or differed only in the platform name in log
    # output) across spark / lakesail / velox.

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables from Sail server."""
        return list_spark_tables(connection)

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE TABLE for query optimization."""
        analyze_spark_table(connection, table_name, logger=self.logger)


_build_lakesail_config = make_registered_platform_config_builder(
    "lakesail",
    __name__,
    "LakeSail Sail",
    "pyspark",
    [
        "endpoint",
        "app_name",
        "driver_memory",
        "sail_mode",
        "sail_workers",
        "shuffle_partitions",
        "adaptive_enabled",
        "table_format",
        "spark_config",
        "disable_cache",
    ],
)
