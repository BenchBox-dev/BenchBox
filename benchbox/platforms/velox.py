"""Apache Gluten + Velox Spark acceleration platform adapter.

Provides a BenchBox platform adapter for Apache Gluten with the Velox backend -
a plugin to Apache Spark that offloads physical operators to a highly optimized
native C++ engine (Velox) while preserving Spark's fault tolerance, distributed
scheduling, and DataFrame/SQL APIs.

Key characteristics:
- Gluten intercepts Spark physical plans after Catalyst and executes them with
  Velox - a vectorized, SIMD-optimised C++ engine with unified off-heap memory.
- Operators that Gluten cannot translate fall back transparently to JVM execution.
- Shuffle is accelerated via ColumnarShuffleManager (required, not optional).
- Reference performance: TPC-H ~3.3x overall / up to ~23x on individual queries
  vs Apache Spark (Gluten community numbers, March 2024).

Deployment modes:
  local   - SparkSession.builder.master('local[*]') with the Gluten bundle jar
             on the driver/executor classpath.  The host MUST be Linux (native
             or containerised); see docker/velox/ for the recommended macOS/Windows
             path.
  remote  - Connect to a pre-started Spark-Connect server that already has the
             Gluten plugin wired (mirrors LakeSailAdapter's remote shape).
             The adapter does NOT start or stop the server.

IMPORTANT - macOS / Windows users:
  No prebuilt Gluten bundle jars exist for Darwin or Windows. The only supported
  local development path on these platforms is Docker.  See docker/velox/ for
  the provided linux/amd64 image and compose recipes.  As of Apache Gluten 1.6.0,
  the official release tarball does not ship a prebuilt arm64 jar.
  Do NOT attempt a native macOS build of Gluten/Velox.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from ._spark_helpers import (
    SparkLikeAdapterMixin,
    analyze_spark_table,
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
except ImportError:
    SparkSession = None  # type: ignore[assignment,misc]

# Mandatory Gluten configuration keys - must be present for any meaningful acceleration.
_GLUTEN_PLUGIN_CLASS = "org.apache.gluten.GlutenPlugin"
_COLUMNAR_SHUFFLE_MANAGER = "org.apache.spark.shuffle.sort.ColumnarShuffleManager"


class VeloxAdapter(SparkLikeAdapterMixin, SparkDataLoadMixin, SparkQueryExecutionMixin, PlatformAdapter):
    """Apache Gluten + Velox Spark acceleration platform adapter.

    Accelerates Apache Spark SQL workloads by routing physical operators through
    Velox - a vectorized C++ query engine - via the Apache Gluten plugin.  The
    adapter manages a Gluten-enabled SparkSession (local mode) or connects to a
    pre-started Spark-Connect server that already has Gluten wired (remote mode).

    Key Features:
    - Two deployment modes: local (SparkSession) and remote (Spark-Connect)
    - Mandatory Gluten configuration: plugin, off-heap, ColumnarShuffleManager
    - velox_active probe in get_platform_info() confirms native execution
    - get_query_plan() annotates VeloxColumnar vs JVM-fallback plan nodes
    - Reuses SparkDataLoadMixin / SparkQueryExecutionMixin (no edits to those mixins)
    - Docker-first local dev path on macOS/Windows (see docker/velox/)
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    # Velox uses Apache Spark which handles .tbl / .dat / .zst files natively
    # via Hadoop codec detection — no .csv symlinks needed (unlike LakeSail/Sail).
    _requires_csv_extension: bool = False

    # Spark-Connect (remote mode) does not reliably support df.cache() and
    # has no ClearCache API; local mode supports both. These are overridden
    # per-deployment in __init__ so local runs get the cache fast-path.
    _df_caching_supported: bool = False
    _catalog_clear_cache_supported: bool = False

    def __init__(self, **config):
        super().__init__(**config)

        if not SparkSession:
            available, missing = check_platform_dependencies("velox")
            if not available:
                error_msg = get_dependency_error_message("velox", missing)
                raise ImportError(error_msg)

        self._dialect = "spark"

        # Deployment mode: "local" | "remote"
        self.deployment = config.get("deployment") or config.get("deployment_mode") or "local"

        if self.deployment == "local":
            self._df_caching_supported = True
            self._catalog_clear_cache_supported = True

        # Remote mode: endpoint for Spark-Connect server
        self.endpoint = config.get("endpoint") or "sc://localhost:50051"

        # Local mode: path to the Gluten Velox bundle jar (required for local mode)
        self.gluten_jar_path = config.get("gluten_jar_path") or ""

        # Informational: Gluten version surfaced in platform_info
        self.gluten_version = config.get("gluten_version") or "1.6.0"

        # Off-heap memory for Velox (separate from JVM heap)
        self.offheap_size = config.get("offheap_size") or "8g"

        # Application and resource config (same knobs as LakeSail/Spark)
        self.app_name = config.get("app_name") or "BenchBox-Velox"
        self.database = config.get("database") or "default"
        self.driver_memory = config.get("driver_memory") or "4g"
        self.shuffle_partitions = (
            config.get("shuffle_partitions") if config.get("shuffle_partitions") is not None else 200
        )
        self.adaptive_enabled = config.get("adaptive_enabled") if config.get("adaptive_enabled") is not None else True
        self.table_format = config.get("table_format") or "parquet"
        self.spark_config = config.get("spark_config") or {}
        self.disable_cache = config.get("disable_cache") if config.get("disable_cache") is not None else True

        self._spark_session = None

    @property
    def platform_name(self) -> str:
        return "Velox"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """No-op: Velox is configured exclusively via --platform-option K=V flags.

        Option specs (defaults, choices, parsers, help text) are the single
        source of truth and live in PlatformHookRegistry.register_option_specs(
        "velox", ...) in benchbox/platforms/__init__.py.  Adding parallel
        argparse flags here would create two sources of truth that drift apart.
        The method is required because PlatformAdapter declares it abstract.
        """
        return None

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create VeloxAdapter from unified configuration."""
        from benchbox.platforms.base.config_utils import build_adapter_config

        return cls(
            **build_adapter_config(
                config,
                platform="velox",
                fields=[
                    "deployment",
                    "deployment_mode",
                    "endpoint",
                    "gluten_jar_path",
                    "gluten_version",
                    "offheap_size",
                    "app_name",
                    "driver_memory",
                    "shuffle_partitions",
                    "adaptive_enabled",
                    "table_format",
                    "spark_config",
                    "disable_cache",
                ],
            )
        )

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Velox platform information including velox_active probe."""
        platform_info: dict[str, Any] = {
            "platform_type": "velox",
            "platform_name": "Apache Gluten + Velox",
            "deployment": self.deployment,
            "gluten_version": self.gluten_version,
            "offheap_size": self.offheap_size,
            "configuration": {
                "database": self.database,
                "table_format": self.table_format,
                "driver_memory": self.driver_memory,
                "shuffle_partitions": self.shuffle_partitions,
                "adaptive_enabled": self.adaptive_enabled,
            },
        }

        if self.deployment == "local":
            # Redact the full path but preserve the filename for diagnostics
            jar_name = Path(self.gluten_jar_path).name if self.gluten_jar_path else "<not set>"
            platform_info["gluten_jar"] = jar_name
        else:
            platform_info["endpoint"] = self.endpoint

        if SparkSession:
            try:
                import pyspark

                platform_info["client_library_version"] = getattr(pyspark, "__version__", None)
            except ImportError:
                platform_info["client_library_version"] = None
        else:
            platform_info["client_library_version"] = None

        if connection:
            spark = connection
            try:
                platform_info["platform_version"] = spark.version
            except Exception as e:
                self.logger.debug(f"Could not read Spark version: {e}")
                platform_info["platform_version"] = None

            # velox_active probe: EXPLAIN a scan+aggregate query and look for
            # VeloxColumnar plan nodes to confirm the plugin is live. A bare
            # `SELECT 1` can false-negative because no scan operator is emitted.
            try:
                explain_df = spark.sql("EXPLAIN SELECT count(*) FROM range(10)")
                plan_text = "\n".join(str(row[0]) for row in explain_df.collect())
                platform_info["velox_active"] = "VeloxColumnar" in plan_text
                platform_info["velox_probe_plan"] = plan_text[:500]
            except Exception as e:
                self.logger.debug(f"Velox active probe failed: {e}")
                platform_info["velox_active"] = None
                platform_info["velox_probe_plan"] = None
        else:
            platform_info["platform_version"] = None
            platform_info["velox_active"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect (Spark-compatible)."""
        return "spark"

    def _get_spark_conf(self) -> dict[str, str]:
        """Build the Spark configuration dict.

        For local mode, includes mandatory Gluten configuration.
        For remote mode, sends advisory settings (the server already has them).
        """
        conf: dict[str, str] = {
            "spark.app.name": self.app_name,
            "spark.sql.shuffle.partitions": str(self.shuffle_partitions),
        }

        if self.adaptive_enabled:
            conf["spark.sql.adaptive.enabled"] = "true"
            conf["spark.sql.adaptive.coalescePartitions.enabled"] = "true"
            conf["spark.sql.adaptive.skewJoin.enabled"] = "true"

        if self.disable_cache:
            conf["spark.sql.inMemoryColumnarStorage.enabled"] = "false"

        if self.deployment == "local":
            # Mandatory Gluten configuration - omitting any of these silently
            # forfeits native acceleration or causes OOM.
            conf["spark.plugins"] = _GLUTEN_PLUGIN_CLASS
            conf["spark.memory.offHeap.enabled"] = "true"
            conf["spark.memory.offHeap.size"] = self.offheap_size
            conf["spark.shuffle.manager"] = _COLUMNAR_SHUFFLE_MANAGER
            if self.gluten_jar_path:
                # spark.jars ships the jar to driver + executors at runtime.
                # spark.{driver,executor}.extraClassPath is also required: the
                # Gluten plugin class is loaded by SparkContext.initializeSparkContext
                # *before* spark.jars adds entries to the executor classpath, so
                # without extraClassPath the GlutenPlugin class is not on the JVM
                # classpath at plugin-load time and the plugin silently no-ops.
                # The docker/velox/entrypoint.sh server config sets the same pair.
                conf["spark.jars"] = self.gluten_jar_path
                conf["spark.driver.extraClassPath"] = self.gluten_jar_path
                conf["spark.executor.extraClassPath"] = self.gluten_jar_path

        # Merge user-provided overrides last
        conf.update(self.spark_config)

        # Guard: reject explicit removal of ColumnarShuffleManager in local mode
        if self.deployment == "local":
            sm = conf.get("spark.shuffle.manager", "")
            if sm and sm != _COLUMNAR_SHUFFLE_MANAGER:
                raise ValueError(
                    f"spark.shuffle.manager overridden to '{sm}' via spark_config, but "
                    "Velox requires ColumnarShuffleManager for shuffle acceleration. "
                    "Remove the override or set deployment='remote' to connect to a "
                    "pre-configured server."
                )

        return conf

    def _create_spark_session(self) -> Any:
        """Create a SparkSession with Gluten configuration.

        Local mode: SparkSession.builder.master('local[*]') + mandatory Gluten conf.
        Remote mode: SparkSession.builder.remote(endpoint) + advisory conf overlay.

        Raises:
            ValueError: If local mode is requested but gluten_jar_path is not set or
                        the jar file does not exist.
            RuntimeError: If remote mode is requested and the server is not reachable.
        """
        if self.deployment == "local":
            if not self.gluten_jar_path:
                raise ValueError(
                    "gluten_jar_path is required for local deployment mode. "
                    "Supply the absolute path to the Gluten Velox bundle jar via "
                    "--platform-option gluten_jar_path=<absolute-path> "
                    "(alias: --platform-option jar=<absolute-path>) or via the "
                    "gluten_jar_path config key. "
                    "See docs/platforms/velox_jar_setup.md for obtaining the jar. "
                    "On macOS/Windows use the Docker workflow in docker/velox/ instead."
                )
            if not Path(self.gluten_jar_path).exists():
                raise ValueError(
                    f"Gluten jar not found: {self.gluten_jar_path}\n"
                    "Download the correct bundle for your Spark version and host arch. "
                    "See docs/platforms/velox_jar_setup.md."
                )
            builder = SparkSession.builder.master("local[*]")
        else:
            self._ensure_server_ready()
            builder = SparkSession.builder.remote(self.endpoint)

        spark_conf = self._get_spark_conf()
        for key, value in spark_conf.items():
            builder = builder.config(key, value)

        return builder.getOrCreate()

    # ------------------------------------------------------------------
    # Remote mode helpers (no auto-start, unlike LakeSail)
    # ------------------------------------------------------------------

    def _ensure_server_ready(self) -> None:
        """Verify the remote server is reachable; raise a clear error if not.

        Unlike LakeSailAdapter, VeloxAdapter does NOT auto-start a server.
        The user must pre-start a Gluten-enabled Spark-Connect server
        (e.g., via `docker compose up velox-connect` in docker/velox/).
        """
        if is_spark_connect_reachable(self.endpoint):
            return
        host, port = parse_spark_connect_endpoint(self.endpoint)
        raise RuntimeError(
            f"Cannot connect to Spark-Connect server at {self.endpoint}. "
            "Ensure a Gluten-enabled server is running and reachable.\n"
            "To start one via Docker: cd docker/velox && docker compose up -d velox-connect\n"
            f"Then retry after the server is listening on {host}:{port}."
        )

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def create_connection(self, **connection_config) -> Any:
        """Create a Gluten-enabled SparkSession (local) or Spark-Connect session (remote)."""
        self.log_operation_start("Velox SparkSession")
        self.log_very_verbose(f"Velox config: deployment={self.deployment}, database={self.database}")

        try:
            spark = self._create_spark_session()
            self._spark_session = spark

            self.handle_existing_database(**connection_config)

            target_database = connection_config.get("database", self.database)
            if not validate_spark_identifier(target_database):
                raise ValueError(f"Invalid database identifier: {target_database}")

            if not self.database_was_reused:
                existing = [db.name for db in spark.catalog.listDatabases()]
                if target_database.lower() not in [d.lower() for d in existing]:
                    self.log_verbose(f"Creating database: {target_database}")
                    # Safety: target_database validated by validate_spark_identifier() above
                    spark.sql(f"CREATE DATABASE IF NOT EXISTS {target_database}")
                    self.logger.info(f"Created database {target_database}")

            # Safety: target_database validated by validate_spark_identifier() above
            spark.sql(f"USE {target_database}")
            self.logger.info(f"Connected to Velox ({self.deployment} mode), database={target_database}")
            self.log_operation_complete("Velox SparkSession", details=f"deployment={self.deployment}")
            return spark

        except Exception as e:
            if self._spark_session is not None:
                try:
                    self._spark_session.stop()
                except Exception:
                    pass
                self._spark_session = None
            self.logger.error(f"Failed to create Velox SparkSession: {e}")
            raise

    def close_connection(self, connection: Any) -> None:
        """Stop the SparkSession."""
        try:
            if connection and hasattr(connection, "stop"):
                connection.stop()
                self._spark_session = None
        except Exception as e:
            self.logger.warning(f"Error closing Velox session: {e}")

    def test_connection(self) -> bool:
        """Test that the Velox session can execute a trivial query."""
        try:
            spark = self._create_spark_session()
            try:
                spark.sql("SELECT 1").collect()
                return True
            finally:
                spark.stop()
        except Exception as e:
            self.logger.debug(f"Velox connection test failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Schema + data loading (thin delegates to mixin)
    # ------------------------------------------------------------------

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Velox/Spark optimisations based on benchmark type."""
        spark = connection
        try:
            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
                # AQE settings are already applied at session creation; these are
                # additional CBO optimisations specific to OLAP benchmark shapes.
                spark.conf.set("spark.sql.cbo.enabled", "true")
                spark.conf.set("spark.sql.cbo.joinReorder.enabled", "true")
                self.logger.debug("Applied OLAP optimisations for Velox")
        except Exception as e:
            self.logger.warning(f"Failed to apply benchmark configuration: {e}")

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create benchmark schema via Spark SQL DDL.

        Defends against an orphaned warehouse directory left by a previous
        container run by purging once before the loop (Velox/Spark Connect cannot
        reach the server's filesystem to clean per-table dirs in flight, so the
        DB-level purge is the only mechanism available; see
        ``purge_orphaned_warehouse_directory`` for the safety preconditions).
        """
        start_time = mono_time()
        spark = connection

        try:
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")
            statements = [s.strip() for s in schema_sql.split(";") if s.strip()]
            # Capture table_format once: the optimize lambda is called per
            # statement, and a hook that mutated self.table_format mid-loop
            # (none today, but cheap insurance) would otherwise diverge between
            # statements.
            fmt = self.table_format
            run_spark_schema_creation_loop(
                spark,
                statements,
                lambda stmt: optimize_spark_table_definition(stmt, table_format=fmt),
                logger=self.logger,
                on_pre_loop=lambda s: purge_orphaned_warehouse_directory(s, logger=self.logger),
            )
            self.logger.info("Velox schema created")
        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    # ------------------------------------------------------------------
    # Query plans
    # ------------------------------------------------------------------

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get extended query plan and annotate Velox vs JVM-fallback nodes."""
        import re

        spark = connection
        try:
            result_df = spark.sql(f"EXPLAIN EXTENDED {query}")
            plan_rows = result_df.collect()
            plan_text = "\n".join(str(row[0]) for row in plan_rows)

            # Annotate the plan with native vs fallback summary.
            # `VeloxColumnarToRow` is the native result-materialization node, not
            # a fallback - guard the fallback match with a negative lookbehind.
            has_velox = "VeloxColumnar" in plan_text
            has_fallback = bool(re.search(r"(?<!Velox)ColumnarToRow|RowToColumnar", plan_text))

            annotation_lines = []
            if has_velox:
                annotation_lines.append("# Velox native execution: YES (VeloxColumnar nodes present)")
            else:
                annotation_lines.append("# Velox native execution: NOT DETECTED (no VeloxColumnar nodes)")
            if has_fallback:
                annotation_lines.append(
                    "# JVM fallback: DETECTED (ColumnarToRow/RowToColumnar conversion nodes present)"
                )

            if annotation_lines:
                plan_text = "\n".join(annotation_lines) + "\n\n" + plan_text

            return plan_text
        except Exception as e:
            return f"Could not get query plan: {e}"

    # ------------------------------------------------------------------
    # Tuning (partitioning only - plain Parquet/ORC tables have no DDL
    # sort key; sorting is handled at query time via AQE/CBO)
    # ------------------------------------------------------------------

    def supports_tuning_type(self, tuning_type) -> bool:
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {TuningType.PARTITIONING}
        except ImportError:
            return False

    def generate_tuning_clause(self, table_tuning) -> str:
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""
        clauses = []
        try:
            from benchbox.core.tuning.interface import TuningType

            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                clauses.append(f"PARTITIONED BY ({', '.join(col.name for col in sorted_cols)})")
        except ImportError:
            pass
        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        from benchbox.platforms.base.tuning_utils import log_partition_tunings

        log_partition_tunings(table_tuning, self.logger, "Velox")

    # apply_unified_tuning, apply_platform_optimizations, and
    # apply_constraint_configuration come from SparkLikeAdapterMixin -
    # bodies were identical (or differed only in the platform name in log
    # output) across spark / lakesail / velox.

    # ------------------------------------------------------------------
    # Catalog operations (thin delegates to shared helpers)
    # ------------------------------------------------------------------

    def _get_existing_tables(self, connection: Any) -> list[str]:
        return list_spark_tables(connection)

    def analyze_table(self, connection: Any, table_name: str) -> None:
        analyze_spark_table(connection, table_name, logger=self.logger)


_build_velox_config = make_registered_platform_config_builder(
    "velox",
    __name__,
    "Apache Gluten + Velox",
    "pyspark",
    [
        "deployment",
        "endpoint",
        "gluten_jar_path",
        "gluten_version",
        "offheap_size",
        "app_name",
        "driver_memory",
        "shuffle_partitions",
        "adaptive_enabled",
        "table_format",
        "spark_config",
        "disable_cache",
    ],
)
