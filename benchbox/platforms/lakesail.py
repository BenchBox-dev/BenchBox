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


class LakeSailAdapter(SparkDataLoadMixin, SparkQueryExecutionMixin, PlatformAdapter):
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

        # Result cache control - disable by default for accurate benchmarking
        self.disable_cache = config.get("disable_cache") if config.get("disable_cache") is not None else True

        # Store SparkSession reference
        self._spark_session = None

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
        from benchbox.utils.database_naming import generate_database_name

        adapter_config: dict[str, Any] = {}

        # Generate proper database name using benchmark characteristics
        if "database" in config and config["database"]:
            adapter_config["database"] = config["database"]
        else:
            database_name = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="lakesail",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database"] = database_name

        # Core configuration parameters
        for key in [
            "endpoint",
            "app_name",
            "driver_memory",
            "sail_mode",
            "sail_workers",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        # Optional configuration parameters
        for key in [
            "shuffle_partitions",
            "adaptive_enabled",
            "table_format",
            "spark_config",
            "disable_cache",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

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

        if not self._validate_identifier(database):
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

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate SQL identifier to prevent injection attacks."""
        if not identifier:
            return False
        import re

        pattern = r"^[a-zA-Z_][a-zA-Z0-9_]*$"
        return bool(re.match(pattern, identifier)) and len(identifier) <= 128

    def create_connection(self, **connection_config) -> Any:
        """Create a Spark Connect session to the LakeSail Sail server."""
        self.log_operation_start("LakeSail Spark Connect session")

        self.log_very_verbose(f"LakeSail config: endpoint={self.endpoint}, database={self.database}")

        try:
            spark = self._create_spark_session()
            self._spark_session = spark

            # Handle existing database using base class method.
            # This must run after session creation so server-side database checks work.
            self.handle_existing_database(**connection_config)

            # Create database if needed
            target_database = connection_config.get("database", self.database)
            if not self._validate_identifier(target_database):
                raise ValueError(f"Invalid database identifier: {target_database}")

            if not self.database_was_reused:
                database_exists = self.check_server_database_exists(database=target_database)

                if not database_exists:
                    self.log_verbose(f"Creating database: {target_database}")
                    # Safety: target_database validated by _validate_identifier() above
                    spark.sql(f"CREATE DATABASE IF NOT EXISTS {target_database}")
                    self.logger.info(f"Created database {target_database}")

            # Safety: target_database validated by _validate_identifier() above
            spark.sql(f"USE {target_database}")

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
        """Create schema using Spark SQL DDL on Sail server."""
        start_time = mono_time()

        spark = connection

        try:
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                if not statement:
                    continue

                # Normalize table names to lowercase for Spark consistency
                statement = self._normalize_table_name_in_sql(statement)

                # Add USING clause for table format
                statement = self._optimize_table_definition(statement)

                try:
                    spark.sql(statement)
                    self.logger.debug(f"Executed schema statement: {statement[:100]}...")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        table_name = self._extract_table_name(statement)
                        if table_name and self._validate_identifier(table_name):
                            # Safety: table_name validated by _validate_identifier() above
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
        """Load data into Sail server via Spark Connect.

        Delegates to SparkDataLoadMixin._load_data_spark for the shared
        DataFrame-based loading implementation.
        """
        return self._load_data_spark(benchmark, data_dir, connection)

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
        """Execute query via Spark Connect to Sail server with timing.

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
        """Normalize table names in SQL to lowercase."""
        return normalize_table_name_in_sql(sql)

    def _optimize_table_definition(self, statement: str) -> str:
        """Add USING clause for the specified table format."""
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        import re

        statement = re.sub(r"\s+USING\s+\w+", "", statement, flags=re.IGNORECASE)

        if self.table_format == "orc":
            if ")" in statement:
                statement = statement.rstrip(";").rstrip() + " USING ORC"
        else:
            if ")" in statement:
                statement = statement.rstrip(";").rstrip() + " USING PARQUET"

        return statement

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan from Sail server."""
        spark = connection
        try:
            result_df = spark.sql(f"EXPLAIN EXTENDED {query}")
            plan_rows = result_df.collect()
            return "\n".join([str(row[0]) for row in plan_rows])
        except Exception as e:
            return f"Could not get query plan: {e}"

    def close_connection(self, connection: Any) -> None:
        """Close Spark Connect session."""
        try:
            if connection and hasattr(connection, "stop"):
                connection.stop()
                self._spark_session = None
        except Exception as e:
            self.logger.warning(f"Error closing LakeSail session: {e}")

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

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if LakeSail supports a specific tuning type."""
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {
                TuningType.PARTITIONING,
                TuningType.SORTING,
            }
        except ImportError:
            return False

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

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration."""
        if not unified_config:
            return

        self.apply_constraint_configuration(unified_config.primary_keys, unified_config.foreign_keys, connection)

        if unified_config.platform_optimizations:
            self.apply_platform_optimizations(unified_config.platform_optimizations, connection)

        for _table_name, table_tuning in unified_config.table_tunings.items():
            self.apply_table_tunings(table_tuning, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Sail-specific platform optimizations."""
        if not platform_config:
            return

        spark = connection

        if hasattr(platform_config, "spark") and platform_config.spark:
            for key, value in platform_config.spark.items():
                try:
                    spark.conf.set(f"spark.{key}", str(value))
                    self.logger.debug(f"Applied Sail config: spark.{key} = {value}")
                except Exception as e:
                    self.logger.warning(f"Failed to apply Sail config spark.{key}: {e}")

        self.logger.info("LakeSail platform optimizations applied")

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations (informational only, like Spark)."""
        if primary_key_config and primary_key_config.enabled:
            self.logger.info("Primary key constraints enabled for LakeSail (informational only, not enforced)")

        if foreign_key_config and foreign_key_config.enabled:
            self.logger.info("Foreign key constraints enabled for LakeSail (informational only, not enforced)")

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables from Sail server."""
        spark = connection
        try:
            tables = spark.catalog.listTables()
            return [t.name.lower() for t in tables]
        except Exception:
            return []

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE TABLE for query optimization."""
        spark = connection
        try:
            spark.sql(f"ANALYZE TABLE {table_name.lower()} COMPUTE STATISTICS")
            self.logger.debug(f"Analyzed table {table_name}")
        except Exception as e:
            self.logger.warning(f"Failed to analyze table {table_name}: {e}")


def _build_lakesail_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build LakeSail database configuration with credential loading."""
    from benchbox.platforms.azure.config_utils import build_platform_config

    return build_platform_config(
        platform_type="lakesail",
        credential_key="lakesail",
        default_display_name="LakeSail Sail",
        default_driver_package="pyspark",
        platform_fields=[
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
        options=options,
        overrides=overrides,
        info=info,
    )


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("lakesail", _build_lakesail_config)
except ImportError:
    pass
