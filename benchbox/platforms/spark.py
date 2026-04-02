"""Apache Spark platform adapter with distributed SQL query engine optimizations.

Provides Spark-specific optimizations for analytical workloads,
including SparkSession configuration, deployment modes, and query optimization.

Apache Spark is the most widely deployed distributed SQL engine, used by
thousands of organizations for data processing and analytics.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.sql_utils import normalize_table_name_in_sql
from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        ForeignKeyConfiguration,
        PlatformOptimizationConfiguration,
        PrimaryKeyConfiguration,
        UnifiedTuningConfiguration,
    )

from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from .base import DriverIsolationCapability, PlatformAdapter
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


class SparkAdapter(SparkDataLoadMixin, SparkQueryExecutionMixin, PlatformAdapter):
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
            conf["spark.sql.autoBroadcastJoinThreshold"] = str(self.broadcast_threshold)

        # Number of executors (for YARN/K8s)
        if self.num_executors is not None:
            conf["spark.executor.instances"] = str(self.num_executors)

        # Warehouse directory
        if self.warehouse_dir:
            conf["spark.sql.warehouse.dir"] = self.warehouse_dir

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

        if not self._validate_identifier(database):
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

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate SQL identifier to prevent injection attacks."""
        if not identifier:
            return False
        import re

        pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
        return bool(re.match(pattern, identifier)) and len(identifier) <= 128

    def create_connection(self, **connection_config) -> Any:
        """Create optimized Spark session."""
        self.log_operation_start("Spark session")

        # Handle existing database using base class method
        self.handle_existing_database(**connection_config)

        # Build SparkSession
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

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Spark-optimized table definitions."""
        start_time = mono_time()

        spark = connection

        try:
            # Use common schema creation helper
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                if not statement:
                    continue

                # Normalize table names to lowercase for Spark consistency
                statement = self._normalize_table_name_in_sql(statement)

                # Optimize table definition for Spark
                statement = self._optimize_table_definition(statement)

                try:
                    spark.sql(statement)
                    self.logger.debug(f"Executed schema statement: {statement[:100]}...")
                except Exception as e:
                    # If table already exists, drop and recreate
                    if "already exists" in str(e).lower():
                        table_name = self._extract_table_name(statement)
                        if table_name:
                            spark.sql(f"DROP TABLE IF EXISTS {table_name}")
                            spark.sql(statement)
                    else:
                        raise

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
            if benchmark_type.lower() in ["olap", "analytics", "tpch", "tpcds"]:
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

    def _extract_table_name(self, statement: str) -> str | None:
        """Extract table name from CREATE TABLE statement."""
        from benchbox.core.sql_utils import extract_table_name

        return extract_table_name(statement)

    def _normalize_table_name_in_sql(self, sql: str) -> str:
        """Normalize table names in SQL to lowercase for Spark."""
        return normalize_table_name_in_sql(sql)

    def _optimize_table_definition(self, statement: str) -> str:
        """Optimize table definition for Spark.

        Spark SQL table creation depends on the format:
        - For Parquet/ORC: simple CREATE TABLE with USING clause
        - For Delta Lake: CREATE TABLE with USING DELTA
        - For Iceberg: CREATE TABLE with USING ICEBERG
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        import re

        # Remove any USING clause that might already exist
        statement = re.sub(r"\s+USING\s+\w+", "", statement, flags=re.IGNORECASE)

        # Add USING clause for the specified format
        if self.table_format == "delta":
            # Delta Lake format
            if ")" in statement:
                statement = statement.rstrip(";").rstrip() + " USING DELTA"
        elif self.table_format == "iceberg":
            # Iceberg format
            if ")" in statement:
                statement = statement.rstrip(";").rstrip() + " USING ICEBERG"
        elif self.table_format == "orc":
            # ORC format
            if ")" in statement:
                statement = statement.rstrip(";").rstrip() + " USING ORC"
        else:
            # Default to Parquet
            if ")" in statement:
                statement = statement.rstrip(";").rstrip() + " USING PARQUET"

        return statement

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan for analysis."""
        spark = connection
        try:
            result_df = spark.sql(f"EXPLAIN EXTENDED {query}")
            plan_rows = result_df.collect()
            return "\n".join([str(row[0]) for row in plan_rows])
        except Exception as e:
            return f"Could not get query plan: {e}"

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
            # Create a temporary SparkSession for testing
            builder = SparkSession.builder.master(self.master)
            spark_conf = self._get_spark_conf()
            for key, value in spark_conf.items():
                builder = builder.config(key, value)

            spark = builder.getOrCreate()

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

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration to Spark."""
        if not unified_config:
            return

        # Apply constraint configurations (informational only in Spark)
        self.apply_constraint_configuration(unified_config.primary_keys, unified_config.foreign_keys, connection)

        # Apply platform optimizations
        if unified_config.platform_optimizations:
            self.apply_platform_optimizations(unified_config.platform_optimizations, connection)

        # Apply table-level tunings
        for _table_name, table_tuning in unified_config.table_tunings.items():
            self.apply_table_tunings(table_tuning, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Spark-specific platform optimizations.

        Spark optimizations include:
        - Adaptive Query Execution (AQE)
        - Cost-based optimization
        - Join reordering
        - Memory management
        """
        if not platform_config:
            return

        spark = connection

        # Apply Spark-specific settings from platform config
        if hasattr(platform_config, "spark") and platform_config.spark:
            for key, value in platform_config.spark.items():
                try:
                    spark.conf.set(f"spark.{key}", str(value))
                    self.logger.debug(f"Applied Spark config: spark.{key} = {value}")
                except Exception as e:
                    self.logger.warning(f"Failed to apply Spark config spark.{key}: {e}")

        self.logger.info("Spark platform optimizations applied")

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations to Spark.

        Note: Spark SQL does not enforce constraints. They are informational only.
        """
        if primary_key_config and primary_key_config.enabled:
            self.logger.info("Primary key constraints enabled for Spark (informational only, not enforced)")

        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info("Foreign key constraints enabled for Spark (informational only, not enforced)")

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables from Spark database."""
        spark = connection
        try:
            tables = spark.catalog.listTables()
            return [t.name.lower() for t in tables]
        except Exception:
            return []

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE TABLE for query optimization.

        Spark uses ANALYZE TABLE to compute statistics for cost-based optimization.
        """
        spark = connection
        try:
            spark.sql(f"ANALYZE TABLE {table_name.lower()} COMPUTE STATISTICS")
            self.logger.debug(f"Analyzed table {table_name}")
        except Exception as e:
            self.logger.warning(f"Failed to analyze table {table_name}: {e}")


def _build_spark_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build Spark database configuration with credential loading.

    Args:
        platform: Platform name (should be 'spark')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with configuration loaded
    """
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    # Load saved credentials
    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("spark") or {}

    # Build merged options: saved_creds < options < overrides
    merged_options = {}
    merged_options.update(saved_creds)
    merged_options.update(options)
    merged_options.update(overrides)

    name = info.display_name if info else "Apache Spark"
    driver_package = info.driver_package if info else "pyspark"

    config_dict = {
        "type": "spark",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Platform-specific fields at top-level
        "master": merged_options.get("master"),
        "app_name": merged_options.get("app_name"),
        "deploy_mode": merged_options.get("deploy_mode"),
        "driver_memory": merged_options.get("driver_memory"),
        "executor_memory": merged_options.get("executor_memory"),
        "executor_cores": merged_options.get("executor_cores"),
        "num_executors": merged_options.get("num_executors"),
        "shuffle_partitions": merged_options.get("shuffle_partitions"),
        "broadcast_threshold": merged_options.get("broadcast_threshold"),
        "adaptive_enabled": merged_options.get("adaptive_enabled"),
        "table_format": merged_options.get("table_format"),
        "enable_hive": merged_options.get("enable_hive"),
        "spark_config": merged_options.get("spark_config"),
        "staging_root": merged_options.get("staging_root"),
        # Benchmark context for config-aware database naming
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    # Only include explicit database override if provided
    if "database" in overrides and overrides["database"]:
        config_dict["database"] = overrides["database"]

    return DatabaseConfig(**config_dict)


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("spark", _build_spark_config)
except ImportError:
    # Platform hooks may not be available in all contexts
    pass
