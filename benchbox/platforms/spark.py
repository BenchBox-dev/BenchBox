"""Apache Spark platform adapter with distributed SQL query engine optimizations.

Provides Spark-specific optimizations for analytical workloads,
including SparkSession configuration, deployment modes, and query optimization.

Apache Spark is the most widely deployed distributed SQL engine, used by
thousands of organizations for data processing and analytics.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
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
    get_spark_query_plan,
    list_spark_tables,
    optimize_spark_table_definition,
    run_spark_schema_creation_loop,
    validate_spark_identifier,
)
from .base import DriverIsolationCapability, PlatformAdapter
from .base.spark_execution_mixin import SparkDataLoadMixin, SparkQueryExecutionMixin
from .base.spark_logging import suppress_window_exec_warning

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


# Maximum Java version compatible with PySpark's bundled Hadoop.
# Subject.getSubject() was removed in Java 23 (JEP 411), which breaks
# Hadoop's UserGroupInformation used during SparkSession initialization.
_MAX_COMPATIBLE_JAVA_VERSION = 22

_logger = logging.getLogger(__name__)
_SPARK_AUTO_BROADCAST_THRESHOLD = "spark.sql.autoBroadcastJoinThreshold"


def _get_java_version(java_home: str | None = None) -> int | None:
    """Return the major Java version, or None if it cannot be determined."""
    java_bin = "java"
    if java_home:
        java_bin = os.path.join(java_home, "bin", "java")

    try:
        result = subprocess.run(
            [java_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Java version string is on stderr, e.g. 'openjdk version "17.0.17"'
        output = result.stderr + result.stdout
        match = re.search(r'"(\d+)[\.\+]', output)
        if match:
            return int(match.group(1))
    except (OSError, subprocess.TimeoutExpired):
        pass
    return None


def _find_compatible_java_home() -> str | None:
    """Try to find a compatible JDK installation (Java 17 or 21 preferred).

    On macOS, uses /usr/libexec/java_home. On Linux, checks common paths.
    Returns the JAVA_HOME path or None.
    """
    import platform as _platform

    if _platform.system() == "Darwin":
        # Try preferred versions in order
        for version in ("17", "21", "11"):
            try:
                result = subprocess.run(
                    ["/usr/libexec/java_home", "-v", version],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    candidate = result.stdout.strip()
                    ver = _get_java_version(candidate)
                    if ver and ver <= _MAX_COMPATIBLE_JAVA_VERSION:
                        return candidate
            except (OSError, subprocess.TimeoutExpired):
                continue
    else:
        # Linux: check common JDK paths
        for base in ("/usr/lib/jvm", "/usr/java"):
            base_path = Path(base)
            if not base_path.exists():
                continue
            for version in ("17", "21", "11"):
                for candidate_dir in sorted(base_path.glob(f"*-{version}*"), reverse=True):
                    if candidate_dir.is_dir():
                        ver = _get_java_version(str(candidate_dir))
                        if ver and ver <= _MAX_COMPATIBLE_JAVA_VERSION:
                            return str(candidate_dir)
    return None


def _ensure_compatible_java(java_home_override: str | None = None) -> str | None:
    """Ensure a compatible Java is configured for Spark. Returns JAVA_HOME used.

    If the current Java is incompatible (>= 23), attempts to find and configure
    a compatible one. Raises RuntimeError if no compatible Java can be found.
    """
    # If user explicitly provided java_home, validate and use it
    if java_home_override:
        ver = _get_java_version(java_home_override)
        if ver and ver > _MAX_COMPATIBLE_JAVA_VERSION:
            raise RuntimeError(
                f"Specified java_home ({java_home_override}) uses Java {ver}, "
                f"but PySpark requires Java <= {_MAX_COMPATIBLE_JAVA_VERSION}. "
                f"Subject.getSubject() was removed in Java 23 (JEP 411)."
            )
        os.environ["JAVA_HOME"] = java_home_override
        _logger.info(f"Using user-specified JAVA_HOME: {java_home_override}")
        return java_home_override

    # Check current Java version
    current_version = _get_java_version()
    if current_version is None or current_version <= _MAX_COMPATIBLE_JAVA_VERSION:
        return os.environ.get("JAVA_HOME")  # Current Java is fine

    # Current Java is too new - try to find a compatible one
    _logger.warning(
        f"System Java {current_version} is incompatible with PySpark "
        f"(requires <= {_MAX_COMPATIBLE_JAVA_VERSION}). "
        f"Searching for a compatible JDK..."
    )

    compatible_home = _find_compatible_java_home()
    if compatible_home:
        os.environ["JAVA_HOME"] = compatible_home
        compat_ver = _get_java_version(compatible_home)
        _logger.info(f"Auto-selected Java {compat_ver} at {compatible_home} for Spark compatibility")
        return compatible_home

    raise RuntimeError(
        f"System Java version {current_version} is incompatible with PySpark. "
        f"Hadoop's UserGroupInformation uses Subject.getSubject(), which was "
        f"removed in Java 23 (JEP 411). Install Java 17 or 21 and either:\n"
        f"  1. Set JAVA_HOME to point to it before running BenchBox\n"
        f"  2. Use --platform-option java_home=/path/to/jdk17\n"
        f"  3. Install via: brew install openjdk@17"
    )


class SparkAdapter(SparkLikeAdapterMixin, SparkDataLoadMixin, SparkQueryExecutionMixin, PlatformAdapter):
    """Apache Spark platform adapter for distributed SQL query execution.

    Spark is a distributed computing framework for large-scale data processing.
    It supports multiple data sources and provides a unified analytics engine
    for batch processing, streaming, and machine learning.

    Key Features:
    - Distributed query execution across multiple executors
    - Support for local, standalone, and Kubernetes modes
    - Multiple data formats: Parquet, ORC, CSV, Delta Lake, Iceberg
    - Adaptive Query Execution (AQE) for dynamic optimization
    - Catalyst optimizer for query planning
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies
        if not SparkSession:
            available, missing = check_platform_dependencies("spark")
            if not available:
                error_msg = get_dependency_error_message("spark", missing)
                raise ImportError(error_msg)

        self._dialect = "spark"

        # Spark deployment configuration
        self.master = config.get("master") or "local[*]"
        self.app_name = config.get("app_name") or "BenchBox"
        self.deploy_mode = config.get("deploy_mode")  # client or cluster

        # Spark session configuration
        self.warehouse_dir = config.get("warehouse_dir")
        self.database = config.get("database") or "default"

        # Resource configuration
        self.driver_memory = config.get("driver_memory") or "4g"
        self.executor_memory = config.get("executor_memory") or "4g"
        self.executor_cores = config.get("executor_cores") if config.get("executor_cores") is not None else 2
        self.num_executors = config.get("num_executors")

        # Shuffle and optimization settings
        self.shuffle_partitions = (
            config.get("shuffle_partitions") if config.get("shuffle_partitions") is not None else 200
        )
        self.broadcast_threshold = config.get("broadcast_threshold")
        self.adaptive_enabled = config.get("adaptive_enabled") if config.get("adaptive_enabled") is not None else True

        # Table format configuration (parquet, orc, delta, iceberg)
        self.table_format = config.get("table_format") or "parquet"

        # Hive support
        self.enable_hive = config.get("enable_hive") if config.get("enable_hive") is not None else False

        # Extra Spark configuration properties
        self.spark_config = config.get("spark_config") or {}

        # Java home override for compatibility with newer JDKs
        self.java_home = config.get("java_home")

        # Data loading configuration
        self.staging_root = config.get("staging_root")

        # Result cache control - disable by default for accurate benchmarking
        self.disable_cache = config.get("disable_cache") if config.get("disable_cache") is not None else True

        # Store SparkSession reference
        self._spark_session = None

    @property
    def platform_name(self) -> str:
        return "Spark"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Spark-specific CLI arguments."""

        spark_group = parser.add_argument_group("Spark Arguments")
        spark_group.add_argument(
            "--master",
            type=str,
            default="local[*]",
            help="Spark master URL (local[*], spark://host:port, k8s://host:port, yarn)",
        )
        spark_group.add_argument("--app-name", type=str, default="BenchBox", help="Spark application name")
        spark_group.add_argument(
            "--deploy-mode", type=str, choices=["client", "cluster"], help="Spark deploy mode (client or cluster)"
        )
        spark_group.add_argument("--driver-memory", type=str, default="4g", help="Spark driver memory (e.g., 4g, 8g)")
        spark_group.add_argument(
            "--executor-memory", type=str, default="4g", help="Spark executor memory (e.g., 4g, 8g)"
        )
        spark_group.add_argument("--executor-cores", type=int, default=2, help="Number of cores per executor")
        spark_group.add_argument("--num-executors", type=int, help="Number of executors (for YARN/K8s)")
        spark_group.add_argument(
            "--shuffle-partitions",
            type=int,
            default=200,
            help="Number of shuffle partitions (spark.sql.shuffle.partitions)",
        )
        spark_group.add_argument(
            "--table-format",
            type=str,
            choices=["parquet", "orc", "delta", "iceberg"],
            default="parquet",
            help="Table format for creating benchmark tables",
        )
        spark_group.add_argument(
            "--enable-hive", action="store_true", default=False, help="Enable Hive metastore support"
        )
        spark_group.add_argument(
            "--adaptive-enabled", action="store_true", default=True, help="Enable Adaptive Query Execution (AQE)"
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Spark adapter from unified configuration."""
        from benchbox.utils.database_naming import generate_database_name

        adapter_config: dict[str, Any] = {}
        benchmark_name = str(config["benchmark"]).lower()

        # Generate proper database name using benchmark characteristics
        if "database" in config and config["database"]:
            adapter_config["database"] = config["database"]
        else:
            database_name = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="spark",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database"] = database_name

        # Core configuration parameters
        for key in [
            "master",
            "app_name",
            "deploy_mode",
            "driver_memory",
            "executor_memory",
            "executor_cores",
            "num_executors",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        # Optional configuration parameters
        for key in [
            "warehouse_dir",
            "shuffle_partitions",
            "broadcast_threshold",
            "adaptive_enabled",
            "table_format",
            "enable_hive",
            "spark_config",
            "staging_root",
            "disable_cache",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        spark_config = adapter_config.get("spark_config") or {}
        if (
            benchmark_name == "joinorder"
            and "broadcast_threshold" not in adapter_config
            and _SPARK_AUTO_BROADCAST_THRESHOLD not in spark_config
        ):
            adapter_config["broadcast_threshold"] = -1

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Spark platform information.

        Captures comprehensive Spark configuration including:
        - Spark version
        - Deployment mode
        - Resource configuration
        - Executor/driver settings
        """
        platform_info = {
            "platform_type": "spark",
            "platform_name": "Apache Spark",
            "connection_mode": "local" if self.master.startswith("local") else "cluster",
            "master": self.master,
            "configuration": {
                "database": self.database,
                "table_format": self.table_format,
                "driver_memory": self.driver_memory,
                "executor_memory": self.executor_memory,
                "executor_cores": self.executor_cores,
                "shuffle_partitions": self.shuffle_partitions,
                "adaptive_enabled": self.adaptive_enabled,
                "hive_enabled": self.enable_hive,
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

        # Try to get Spark version and extended metadata from session
        if connection:
            try:
                spark = connection
                platform_info["platform_version"] = spark.version

                # Get runtime configuration
                conf = spark.sparkContext.getConf()
                platform_info["configuration"]["spark_master"] = conf.get("spark.master")
                platform_info["configuration"]["spark_app_id"] = spark.sparkContext.applicationId

                # Get executor count if available (cluster mode)
                try:
                    sc = spark.sparkContext
                    executor_ids = sc._jsc.sc().getExecutorIds()
                    if executor_ids:
                        platform_info["configuration"]["num_executors"] = executor_ids.size()
                except Exception:
                    pass

            except Exception as e:
                self.logger.debug(f"Error collecting Spark platform info: {e}")
                if platform_info.get("platform_version") is None:
                    platform_info["platform_version"] = None
        else:
            platform_info["platform_version"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Spark SQL."""
        return "spark"

    def _get_spark_conf(self) -> dict[str, Any]:
        """Get Spark configuration dictionary."""
        conf = {
            "spark.app.name": self.app_name,
            "spark.driver.memory": self.driver_memory,
            "spark.executor.memory": self.executor_memory,
            "spark.executor.cores": str(self.executor_cores),
            "spark.sql.shuffle.partitions": str(self.shuffle_partitions),
        }

        # Adaptive Query Execution
        if self.adaptive_enabled:
            conf["spark.sql.adaptive.enabled"] = "true"
            conf["spark.sql.adaptive.coalescePartitions.enabled"] = "true"
            conf["spark.sql.adaptive.skewJoin.enabled"] = "true"

        # Broadcast threshold
        if self.broadcast_threshold is not None:
            conf[_SPARK_AUTO_BROADCAST_THRESHOLD] = str(self.broadcast_threshold)

        # Number of executors (for YARN/K8s)
        if self.num_executors is not None:
            conf["spark.executor.instances"] = str(self.num_executors)

        # Warehouse directory
        if self.warehouse_dir:
            conf["spark.sql.warehouse.dir"] = self.warehouse_dir

        # Register zstd in Hadoop's codec list - the zstd-jni JAR ships
        # with PySpark but isn't in Hadoop's default codec registry,
        # causing CODEC_NOT_AVAILABLE when reading zstd-compressed files.
        conf["spark.hadoop.io.compression.codecs"] = (
            "org.apache.hadoop.io.compress.DefaultCodec,"
            "org.apache.hadoop.io.compress.GzipCodec,"
            "org.apache.hadoop.io.compress.BZip2Codec,"
            "org.apache.hadoop.io.compress.DeflateCodec,"
            "org.apache.hadoop.io.compress.SnappyCodec,"
            "org.apache.hadoop.io.compress.Lz4Codec,"
            "org.apache.hadoop.io.compress.ZStandardCodec"
        )

        # Disable result cache for benchmarking
        if self.disable_cache:
            conf["spark.sql.inMemoryColumnarStorage.enabled"] = "false"

        # Delta Lake support
        if self.table_format == "delta":
            conf["spark.sql.extensions"] = "io.delta.sql.DeltaSparkSessionExtension"
            conf["spark.sql.catalog.spark_catalog"] = "org.apache.spark.sql.delta.catalog.DeltaCatalog"

        # Iceberg support
        if self.table_format == "iceberg":
            conf["spark.sql.extensions"] = "org.apache.iceberg.spark.extensions.IcebergSparkSessionExtensions"
            conf["spark.sql.catalog.spark_catalog"] = "org.apache.iceberg.spark.SparkSessionCatalog"
            conf["spark.sql.catalog.spark_catalog.type"] = "hive"

        # Merge user-provided config
        conf.update(self.spark_config)

        return conf

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists in Spark.

        Spark databases are equivalent to Hive databases/schemas.
        """
        try:
            if self._spark_session is None:
                return False

            database = connection_config.get("database", self.database)
            databases = [db.name for db in self._spark_session.catalog.listDatabases()]
            return database.lower() in [db.lower() for db in databases]

        except Exception as e:
            self.logger.debug(f"Error checking database existence: {e}")
            return False

    def drop_database(self, **connection_config) -> None:
        """Drop database in Spark.

        Uses DROP DATABASE CASCADE to remove all tables.
        """
        database = connection_config.get("database", self.database)

        if not validate_spark_identifier(database):
            raise ValueError(f"Invalid database identifier: {database}")

        # Check if database exists first
        if not self.check_server_database_exists(database=database):
            self.log_verbose(f"Database {database} does not exist - nothing to drop")
            return

        try:
            self._spark_session.sql(f"DROP DATABASE IF EXISTS {database} CASCADE")
            self.logger.info(f"Dropped database {database}")

        except Exception as e:
            raise RuntimeError(f"Failed to drop Spark database {database}: {e}") from e

    def create_connection(self, **connection_config) -> Any:
        """Create optimized Spark session."""
        self.log_operation_start("Spark session")

        # Ensure compatible Java before attempting SparkSession creation
        java_home = _ensure_compatible_java(self.java_home)
        if java_home:
            self.log_verbose(f"Using JAVA_HOME: {java_home}")

        # Build SparkSession first - check_server_database_exists requires an
        # active session, so handle_existing_database must run after getOrCreate().
        builder = SparkSession.builder.master(self.master)

        # Apply configuration
        spark_conf = self._get_spark_conf()
        for key, value in spark_conf.items():
            builder = builder.config(key, value)

        # Enable Hive support if requested
        if self.enable_hive:
            builder = builder.enableHiveSupport()

        self.log_very_verbose(f"Spark config: master={self.master}, database={self.database}")

        try:
            spark = builder.getOrCreate()
            self._spark_session = spark

            self._configure_runtime_logging(spark)

            # Handle existing database using base class method.
            # This must run after SparkSession is available so that
            # check_server_database_exists can query the catalog.
            self.handle_existing_database(**connection_config)

            # Create database if needed
            target_database = connection_config.get("database", self.database)

            if not self.database_was_reused:
                database_exists = self.check_server_database_exists(database=target_database)

                if not database_exists:
                    self.log_verbose(f"Creating database: {target_database}")
                    spark.sql(f"CREATE DATABASE IF NOT EXISTS {target_database}")
                    self.logger.info(f"Created database {target_database}")

            # Set current database
            spark.sql(f"USE {target_database}")

            self.logger.info(f"Connected to Spark with master {self.master}")

            self.log_operation_complete("Spark session", details=f"Connected to {self.master}")

            return spark

        except Exception as e:
            self.logger.error(f"Failed to create Spark session: {e}")
            raise

    def _configure_runtime_logging(self, spark: Any) -> None:
        """Reduce Spark log noise for benchmark runs.

        Spark's default WARN output is useful during interactive debugging, but the
        benchmark path should not flood stderr with spec-compliant WindowExec warnings
        from global windows used in standard TPC-DS queries like Q44 and Q49.
        """
        spark_log_level = "WARN" if self.verbose else "ERROR"
        spark.sparkContext.setLogLevel(spark_log_level)
        # Suppression must follow setLogLevel - setLogLevel resets all log4j2 loggers,
        # which would undo the WindowExec level override if called after.
        suppress_window_exec_warning(spark)

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Spark-optimized table definitions.

        Spark runs in-process (local mode) so it has filesystem access to
        ``spark.sql.warehouse.dir`` and can clean per-table orphaned directories
        directly via ``_remove_orphaned_table_location``.  Remote Spark Connect
        adapters (Velox/LakeSail) cannot reach that filesystem and use a
        coarser DB-level purge instead.
        """
        start_time = mono_time()

        spark = connection

        try:
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
            # Capture table_format once: the bound method re-reads
            # self.table_format on each call, and pinning the format up front
            # keeps statement N and N+1 in agreement even if a future hook
            # mutates the attribute mid-loop.
            fmt = self.table_format
            v1_table = (fmt or "parquet").lower() in {"parquet", "orc"}
            run_spark_schema_creation_loop(
                spark,
                statements,
                lambda stmt: optimize_spark_table_definition(
                    stmt,
                    table_format=fmt,
                    strip_v1_constraints=v1_table,
                    upcast_smallint=v1_table,
                ),
                logger=self.logger,
                on_location_collision=self._remove_orphaned_table_location,
            )
            self.logger.info("Schema created")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using Spark DataFrame/SQL with DataSourceResolver.

        Delegates to SparkDataLoadMixin._load_data_spark for the shared
        DataFrame-based loading implementation.
        """
        return self._load_data_spark(benchmark, data_dir, connection)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Apply Spark-specific optimizations based on benchmark type."""

        spark = connection

        try:
            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds", "joinorder"]:
                # OLAP-specific optimizations via Spark SQL settings
                spark.conf.set("spark.sql.adaptive.enabled", "true")
                spark.conf.set("spark.sql.adaptive.coalescePartitions.enabled", "true")
                spark.conf.set("spark.sql.adaptive.skewJoin.enabled", "true")

                # Cost-based optimization
                spark.conf.set("spark.sql.cbo.enabled", "true")
                spark.conf.set("spark.sql.cbo.joinReorder.enabled", "true")

                self.logger.debug("Applied OLAP optimizations for Spark")

        except Exception as e:
            self.logger.warning(f"Failed to apply benchmark configuration: {e}")

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
        """Execute query with detailed timing and performance tracking.

        Delegates to SparkQueryExecutionMixin._execute_query_spark for the
        shared execution implementation.
        """
        return self._execute_query_spark(
            connection=connection,
            query=query,
            query_id=query_id,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )

    def _remove_orphaned_table_location(self, spark: Any, table_name: str) -> None:
        """Remove orphaned managed-table directory when catalog entry is gone.

        Spark managed tables store data under the warehouse directory. If a
        prior run was interrupted, the catalog entry may be gone but the
        physical directory remains, causing LOCATION_ALREADY_EXISTS on retry.
        """
        try:
            warehouse_dir = spark.conf.get("spark.sql.warehouse.dir", "spark-warehouse")
            # Resolve relative paths against CWD (Spark's default behavior)
            warehouse_path = Path(warehouse_dir.removeprefix("file:")).resolve()
            # Strip qualifiers (e.g. spark_catalog.db.tbl) and backticks
            leaf_name = table_name.split(".")[-1].strip("`")
            # Current database directory
            current_db = spark.catalog.currentDatabase()
            table_dir = (warehouse_path / f"{current_db}.db" / leaf_name).resolve()
            # Guard: only remove if table_dir is actually inside the warehouse
            if not table_dir.is_relative_to(warehouse_path):
                self.log_verbose(f"Refusing to remove {table_dir}: outside warehouse {warehouse_path}")
                return
            if table_dir.exists():
                shutil.rmtree(table_dir)
                self.log_verbose(f"Removed orphaned table location: {table_dir}")
        except Exception as e:
            self.log_verbose(f"Could not remove orphaned location for {table_name}: {e}")

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan for analysis."""
        return get_spark_query_plan(connection, query)

    def close_connection(self, connection: Any) -> None:
        """Close Spark session."""
        try:
            if connection and hasattr(connection, "stop"):
                connection.stop()
                self._spark_session = None
        except Exception as e:
            self.logger.warning(f"Error closing Spark session: {e}")

    def test_connection(self) -> bool:
        """Test connection to Spark.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Ensure compatible Java
            _ensure_compatible_java(self.java_home)

            # Create a temporary SparkSession for testing
            builder = SparkSession.builder.master(self.master)
            spark_conf = self._get_spark_conf()
            for key, value in spark_conf.items():
                builder = builder.config(key, value)

            spark = builder.getOrCreate()
            self._configure_runtime_logging(spark)

            try:
                # Execute simple query to verify
                spark.sql("SELECT 1").collect()
                return True
            finally:
                spark.stop()
        except Exception as e:
            self.logger.debug(f"Connection test failed: {e}")
            return False

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if Spark supports a specific tuning type.

        Spark supports:
        - PARTITIONING: Via partitionBy in DataFrame write
        - BUCKETING: Via bucketBy in DataFrame write
        - SORTING: Via sortBy in DataFrame write
        - CLUSTERING: Via Z-ordering in Delta Lake
        """
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {
                TuningType.PARTITIONING,
                TuningType.SORTING,
            }
        except ImportError:
            return False

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Spark-specific tuning clauses for CREATE TABLE statements.

        Spark table properties depend on the format:
        - parquet: PARTITIONED BY
        - delta: PARTITIONED BY, CLUSTER BY (Z-ORDER)
        - iceberg: partitioning, sorted_by
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            from benchbox.core.tuning.interface import TuningType

            # Handle partitioning
            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                clauses.append(f"PARTITIONED BY ({', '.join(column_names)})")

            # Handle sorting (clustering for Delta Lake)
            sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
            if sort_columns and self.table_format == "delta":
                sorted_cols = sorted(sort_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                clauses.append(f"CLUSTER BY ({', '.join(column_names)})")

        except ImportError:
            pass

        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to a Spark table.

        Spark tuning is primarily handled at table creation time.
        Post-creation optimization is limited for Parquet/ORC.
        For Delta Lake, we can use OPTIMIZE with Z-ORDER.
        """
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name.lower()
        self.logger.info(f"Applying Spark tunings for table: {table_name}")

        spark = connection

        try:
            from benchbox.core.tuning.interface import TuningType

            # Handle Z-ordering for Delta Lake tables
            if self.table_format == "delta":
                sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
                if sort_columns:
                    sorted_cols = sorted(sort_columns, key=lambda col: col.order)
                    column_names = [col.name for col in sorted_cols]
                    zorder_cols = ", ".join(column_names)
                    try:
                        spark.sql(f"OPTIMIZE {table_name} ZORDER BY ({zorder_cols})")
                        self.logger.info(f"Applied Z-ORDER optimization for {table_name}: {zorder_cols}")
                    except Exception as e:
                        self.logger.warning(f"Failed to apply Z-ORDER for {table_name}: {e}")

            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name for col in sorted_cols]
                self.logger.info(f"Partitioning for {table_name}: {', '.join(column_names)}")

        except ImportError:
            self.logger.warning("Tuning interface not available - skipping tuning application")

    # apply_unified_tuning, apply_platform_optimizations, and
    # apply_constraint_configuration come from SparkLikeAdapterMixin -
    # bodies were identical (or differed only in the platform name in log
    # output) across spark / lakesail / velox.

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables from Spark database."""
        return list_spark_tables(connection)

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE TABLE for query optimization.

        Spark uses ANALYZE TABLE to compute statistics for cost-based optimization.
        """
        analyze_spark_table(connection, table_name, logger=self.logger)


def _build_spark_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    from benchbox.platforms.base.config_utils import build_platform_config

    return build_platform_config(
        platform_type="spark",
        credential_key="spark",
        default_display_name="Apache Spark",
        default_driver_package="pyspark",
        platform_fields=[
            "master",
            "app_name",
            "deploy_mode",
            "driver_memory",
            "executor_memory",
            "executor_cores",
            "num_executors",
            "shuffle_partitions",
            "broadcast_threshold",
            "adaptive_enabled",
            "table_format",
            "enable_hive",
            "spark_config",
            "java_home",
            "staging_root",
        ],
        options=options,
        overrides=overrides,
        info=info,
    )


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("spark", _build_spark_config)
except ImportError:
    # Platform hooks may not be available in all contexts
    pass
