"""Snowpark Connect platform adapter for PySpark-compatible execution on Snowflake.

Snowpark Connect provides a PySpark DataFrame API compatibility layer that executes
on Snowflake's native query engine. This is NOT Apache Spark - it translates
DataFrame operations to Snowflake SQL, providing a familiar API without requiring
a Spark cluster.

Key Features:
- PySpark DataFrame API compatibility
- Native Snowflake query execution
- No Spark cluster required
- Snowflake's query optimization

Limitations (compared to Apache Spark):
- RDD APIs not supported
- DataFrame.hint() is a no-op
- DataFrame.repartition() is a no-op
- Some advanced Spark features unavailable

Usage:
    from benchbox.platforms.snowpark_connect import SnowparkConnectAdapter

    adapter = SnowparkConnectAdapter(
        account="my-account",
        user="my-user",
        password="my-password",
        warehouse="COMPUTE_WH",
        database="BENCHBOX",
    )

    # Run TPC-H benchmark with PySpark API
    session = adapter.create_connection()
    adapter.create_schema(benchmark, session)
    adapter.load_data(benchmark, session, source_dir)
    result = adapter.execute_query(session, "SELECT * FROM lineitem LIMIT 10", "Q1")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    pass

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.cloud_spark import SparkTuningMixin
from benchbox.utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from benchbox.utils.file_format import is_parquet_format

try:
    from snowflake.snowpark import Session
    from snowflake.snowpark.exceptions import SnowparkSQLException

    SNOWPARK_AVAILABLE = True
except ImportError:
    Session = None
    SnowparkSQLException = Exception
    SNOWPARK_AVAILABLE = False

logger = logging.getLogger(__name__)


class SnowparkConnectAdapter(SparkTuningMixin, PlatformAdapter):
    """Snowpark Connect adapter for PySpark-compatible execution on Snowflake.

    Snowpark Connect provides a PySpark DataFrame API that executes natively
    on Snowflake. Unlike traditional Spark platforms, there is no Spark cluster -
    DataFrame operations are translated to Snowflake SQL.

    Execution Model:
    - Create Snowpark Session with Snowflake credentials
    - Execute DataFrame operations (translated to SQL)
    - Results retrieved directly from Snowflake
    - No Spark cluster startup/shutdown

    Key Features:
    - PySpark-compatible DataFrame API
    - Native Snowflake query optimization
    - Zero Spark infrastructure management
    - Instant "startup" (no cluster provisioning)

    Limitations:
    - RDD APIs not supported (DataFrame only)
    - DataFrame.hint() is a no-op
    - DataFrame.repartition() is a no-op
    - Some Spark UDFs may not be compatible

    Billing:
    - Standard Snowflake credit consumption
    - Based on warehouse size and query duration
    """

    plan_capture_phase_eligible = True

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    def __init__(
        self,
        account: str | None = None,
        user: str | None = None,
        password: str | None = None,
        warehouse: str = "COMPUTE_WH",
        database: str = "BENCHBOX",
        schema: str = "PUBLIC",
        role: str | None = None,
        authenticator: str | None = None,
        private_key_path: str | None = None,
        private_key_passphrase: str | None = None,
        warehouse_size: str = "MEDIUM",
        session_parameters: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Snowpark Connect adapter.

        Args:
            account: Snowflake account identifier (e.g., "xy12345.us-east-1").
            user: Snowflake username.
            password: Snowflake password.
            warehouse: Virtual warehouse name (default: COMPUTE_WH).
            database: Database name (default: BENCHBOX).
            schema: Schema name (default: PUBLIC).
            role: Role to use for the session.
            authenticator: Authentication method (snowflake, externalbrowser, oauth).
            private_key_path: Path to private key for key pair authentication.
            private_key_passphrase: Passphrase for private key.
            warehouse_size: Warehouse size (default: MEDIUM).
            session_parameters: Additional Snowpark session parameters.
            **kwargs: Additional platform options.
        """
        if not SNOWPARK_AVAILABLE:
            deps_satisfied, missing = check_platform_dependencies("snowpark-connect")
            if not deps_satisfied:
                raise ConfigurationError(get_dependency_error_message("snowpark-connect", missing))

        if not account:
            raise ConfigurationError(
                "account is required for Snowpark Connect. "
                "Provide your Snowflake account identifier (e.g., 'xy12345.us-east-1')."
            )

        if not user:
            raise ConfigurationError("user is required for Snowpark Connect.")

        # Password or key-based auth required
        if not password and not private_key_path:
            raise ConfigurationError("Either password or private_key_path is required for authentication.")

        self.account = account
        self.user = user
        self.password = password
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self.role = role
        self.authenticator = authenticator
        self.private_key_path = private_key_path
        self.private_key_passphrase = private_key_passphrase
        self.warehouse_size = warehouse_size
        self.session_parameters = session_parameters or {}

        # Snowpark Session (lazy initialization)
        self._session: Any = None

        # Metrics tracking
        self._query_count = 0
        self._total_execution_time_seconds = 0.0

        # Benchmark configuration
        self._benchmark_type: str | None = None
        self._scale_factor: float = 1.0

        super().__init__(**kwargs)

    def _build_connection_parameters(self) -> dict[str, Any]:
        """Build Snowpark connection parameters.

        Returns:
            Dict of connection parameters for Snowpark Session.
        """
        params = {
            "account": self.account,
            "user": self.user,
            "warehouse": self.warehouse,
            "database": self.database,
            "schema": self.schema,
        }

        if self.password:
            params["password"] = self.password

        if self.role:
            params["role"] = self.role

        if self.authenticator:
            params["authenticator"] = self.authenticator

        if self.private_key_path:
            # Load private key for key pair authentication
            from cryptography.hazmat.backends import default_backend
            from cryptography.hazmat.primitives import serialization

            with open(self.private_key_path, "rb") as key_file:
                private_key = serialization.load_pem_private_key(
                    key_file.read(),
                    password=(self.private_key_passphrase.encode() if self.private_key_passphrase else None),
                    backend=default_backend(),
                )
            params["private_key"] = private_key

        return params

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Return platform metadata.

        Args:
            connection: Not used (Snowpark Connect manages sessions internally).

        Returns:
            Dict with platform information including name, version, and capabilities.
        """
        return {
            "platform": "snowpark-connect",
            "display_name": "Snowpark Connect for Spark",
            "vendor": "Snowflake",
            "type": "pyspark_compatible",
            "account": self.account,
            "warehouse": self.warehouse,
            "database": self.database,
            "supports_sql": True,
            "supports_dataframe": True,
            "billing_model": "Snowflake credits",
            "limitations": [
                "RDD APIs not supported",
                "DataFrame.hint() is no-op",
                "DataFrame.repartition() is no-op",
            ],
        }

    def create_connection(self, **kwargs: Any) -> Any:
        """Create a Snowpark Session.

        Returns:
            Snowpark Session object.

        Raises:
            ConfigurationError: If connection fails.
        """
        try:
            if self._session is not None:
                # Check if session is still valid
                try:
                    self._session.sql("SELECT 1").collect()
                    logger.info("Using existing Snowpark session")
                    return self._session
                except Exception:
                    # Session invalid, create new one
                    self._session = None

            logger.info(f"Creating Snowpark session for {self.account}")
            connection_params = self._build_connection_parameters()

            # Add session parameters
            if self.session_parameters:
                connection_params["session_parameters"] = self.session_parameters

            self._session = Session.builder.configs(connection_params).create()

            # Verify connection
            result = self._session.sql("SELECT CURRENT_VERSION()").collect()
            version = result[0][0] if result else "unknown"

            logger.info(f"Connected to Snowflake {version} via Snowpark")
            return self._session

        except SnowparkSQLException as e:
            raise ConfigurationError(f"Failed to connect to Snowflake: {e}") from e
        except Exception as e:
            raise ConfigurationError(f"Snowpark session creation failed: {e}") from e

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create database and schema if they don't exist.

        Args:
            benchmark: Benchmark instance. Snowpark Connect only needs the
                configured database/schema here.
            connection: Active Snowpark session.
        """
        session = connection or self._session
        if session is None:
            raise ConfigurationError("No active session. Call create_connection() first.")

        self._session = session
        start_time = mono_time()

        session.sql(f"CREATE DATABASE IF NOT EXISTS {self.database}").collect()
        logger.info(f"Database '{self.database}' created or already exists")

        session.sql(f"USE DATABASE {self.database}").collect()

        session.sql(f"CREATE SCHEMA IF NOT EXISTS {self.schema}").collect()
        session.sql(f"USE SCHEMA {self.schema}").collect()
        logger.info(f"Schema '{self.schema}' created or already exists")
        return elapsed_seconds(start_time)

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load benchmark data into Snowflake tables.

        Args:
            benchmark: Benchmark instance.
            connection: Active Snowpark session.
            data_dir: Local directory containing table data files.

        Returns:
            Tuple of table row counts, elapsed seconds, and optional per-table timings.
        """
        session = connection or self._session
        if session is None:
            raise ConfigurationError("No active session. Call create_connection() first.")

        self._session = session
        start_time = mono_time()
        source_path = Path(data_dir)
        if not source_path.exists():
            raise ConfigurationError(f"Source directory not found: {data_dir}")

        table_stats: dict[str, int] = {}
        per_table_timings: dict[str, float] = {}

        for table in self._resolve_table_names(benchmark):
            table_start = mono_time()
            # Find data files for this table
            table_files = list(source_path.glob(f"{table}.*")) + list(source_path.glob(f"{table}/*.parquet"))

            if not table_files:
                logger.warning(f"No data files found for table {table}")
                continue

            # For Parquet files, use Snowpark DataFrame API
            if all(is_parquet_format(file_path) for file_path in table_files):
                for file_path in table_files:
                    # Create internal stage and upload
                    stage_name = f"@~/{table}"
                    session.sql(f"PUT file://{file_path} {stage_name} AUTO_COMPRESS=FALSE").collect()

                # Create table from staged files
                df = session.read.parquet(f"@~/{table}/")
                df.write.mode("overwrite").save_as_table(table)

                # Get row count
                count_result = session.sql(f"SELECT COUNT(*) FROM {table}").collect()
                row_count = count_result[0][0] if count_result else 0
                table_stats[table] = row_count
                logger.info(f"Loaded {row_count:,} rows into {table}")

            else:
                # For CSV/TBL files, use COPY INTO
                for file_path in table_files:
                    stage_name = f"@~/{table}"
                    session.sql(f"PUT file://{file_path} {stage_name}").collect()

                # Create file format and COPY INTO
                session.sql(
                    f"COPY INTO {table} FROM @~/{table}/ FILE_FORMAT = (TYPE = CSV FIELD_DELIMITER = '|')"
                ).collect()

                count_result = session.sql(f"SELECT COUNT(*) FROM {table}").collect()
                row_count = count_result[0][0] if count_result else 0
                table_stats[table] = row_count
                logger.info(f"Loaded {row_count:,} rows into {table}")

            per_table_timings[table] = elapsed_seconds(table_start)

        return table_stats, elapsed_seconds(start_time), per_table_timings

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
        """Execute a SQL query using Snowpark.

        Args:
            connection: Active Snowpark session.
            query: SQL query to execute.
            query_id: Query identifier.

        Returns:
            Standard query result dictionary.
        """
        session = connection or self._session
        if session is None:
            raise ConfigurationError("No active session. Call create_connection() first.")

        self._session = session
        start_time = mono_time()

        try:
            result = session.sql(query).collect()
            elapsed = elapsed_seconds(start_time)

            self._query_count += 1
            self._total_execution_time_seconds += elapsed

            rows = self._rows_to_dicts(result)
            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=elapsed,
                actual_row_count=len(rows),
                first_row=rows[0] if rows else None,
            )
            result_dict["stream_id"] = stream_id
            result_dict["results"] = rows
            result_dict["benchmark_type"] = benchmark_type
            result_dict["scale_factor"] = scale_factor
            result_dict["validation_enabled"] = validate_row_count
            return result_dict

        except SnowparkSQLException as e:
            elapsed = elapsed_seconds(start_time)
            return {
                "query_id": query_id,
                "stream_id": stream_id,
                "status": "FAILED",
                "execution_time_seconds": elapsed,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    @staticmethod
    def _rows_to_dicts(result: Any) -> list[dict[str, Any]]:
        """Convert Snowpark Row objects or tuple rows to dictionaries.

        Snowpark's collect() normally returns Row objects with ``asDict()``,
        which yields the expected ``{column_name: value}`` mapping. The tuple
        fallback (no ``asDict``) is only hit if a future Snowpark release or
        a stub returns plain sequences; in that case we have no column-name
        metadata, so positional integer keys are the safest non-empty form.
        """
        if not result:
            return []
        if hasattr(result[0], "asDict"):
            return [row.asDict() for row in result]
        return [dict(enumerate(row)) for row in result]

    @staticmethod
    def _resolve_table_names(benchmark: Any) -> list[str]:
        """Resolve table names from common BenchBox benchmark interfaces."""
        if hasattr(benchmark, "get_table_loading_order") and callable(benchmark.get_table_loading_order):
            return list(benchmark.get_table_loading_order())
        if hasattr(benchmark, "get_available_tables") and callable(benchmark.get_available_tables):
            return list(benchmark.get_available_tables())
        if hasattr(benchmark, "get_table_names") and callable(benchmark.get_table_names):
            return list(benchmark.get_table_names())
        tables = getattr(benchmark, "tables", None)
        if isinstance(tables, dict):
            return list(tables.keys())
        raise ConfigurationError("Benchmark does not expose table names for Snowpark data loading")

    def execute_dataframe(
        self,
        df_operation: Any,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Execute a Snowpark DataFrame operation.

        This method supports PySpark-style DataFrame operations that are
        translated to Snowflake SQL.

        Args:
            df_operation: Snowpark DataFrame with operations applied.
            **kwargs: Additional options.

        Returns:
            Query results as list of dicts.

        Note:
            Some Spark operations are not supported or are no-ops:
            - RDD operations: Not available
            - hint(): No-op (Snowflake uses its own optimizer)
            - repartition(): No-op (Snowflake handles partitioning)
        """
        if self._session is None:
            raise ConfigurationError("No active session. Call create_connection() first.")

        start_time = mono_time()

        try:
            result = df_operation.collect()
            elapsed = elapsed_seconds(start_time)

            self._query_count += 1
            self._total_execution_time_seconds += elapsed

            # Convert to list of dicts
            if result:
                return [row.asDict() if hasattr(row, "asDict") else dict(row) for row in result]

            return []

        except SnowparkSQLException as e:
            raise RuntimeError(f"DataFrame execution failed: {e}") from e

    def get_dataframe(self, table_name: str) -> Any:
        """Get a Snowpark DataFrame for a table.

        Args:
            table_name: Name of the table.

        Returns:
            Snowpark DataFrame.
        """
        if self._session is None:
            raise ConfigurationError("No active session. Call create_connection() first.")

        return self._session.table(table_name)

    def close(self) -> None:
        """Close the Snowpark session."""
        if self._session is not None:
            try:
                self._session.close()
                logger.info("Snowpark session closed")
            except Exception as e:
                logger.warning(f"Error closing session: {e}")
            finally:
                self._session = None

        logger.info(f"Executed {self._query_count} queries.")
        if self._total_execution_time_seconds > 0:
            logger.info(f"Total execution time: {self._total_execution_time_seconds:.1f}s")

    @staticmethod
    def add_cli_arguments(parser: Any) -> None:
        """Add Snowpark Connect-specific CLI arguments.

        WARNING — namespace collision risk: ``--account``, ``--user``,
        ``--password``, ``--database``, ``--schema``, ``--warehouse``, and
        ``--role`` are registered WITHOUT a ``--snowpark-`` prefix.  If this
        parser is shared with other adapters those names will conflict.

        These are legacy flags for the setup wizard (``benchbox platforms setup``).
        The ``benchbox run`` flow uses ``--platform-option key=val`` instead
        and does NOT call ``add_cli_arguments``.

        Args:
            parser: Argument parser to add arguments to.
        """
        group = parser.add_argument_group("Snowpark Connect Options")
        group.add_argument(
            "--account",
            help="Snowflake account identifier (e.g., xy12345.us-east-1)",
        )
        group.add_argument(
            "--user",
            help="Snowflake username",
        )
        group.add_argument(
            "--password",
            help="Snowflake password",
        )
        group.add_argument(
            "--warehouse",
            default="COMPUTE_WH",
            help="Virtual warehouse name (default: COMPUTE_WH)",
        )
        group.add_argument(
            "--database",
            default="BENCHBOX",
            help="Database name (default: BENCHBOX)",
        )
        group.add_argument(
            "--schema",
            default="PUBLIC",
            help="Schema name (default: PUBLIC)",
        )
        group.add_argument(
            "--role",
            help="Role to use for the session",
        )
        group.add_argument(
            "--warehouse-size",
            default="MEDIUM",
            help="Warehouse size (default: MEDIUM)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> SnowparkConnectAdapter:
        """Create adapter from configuration dict.

        Args:
            config: Configuration dictionary.

        Returns:
            Configured SnowparkConnectAdapter instance.
        """
        params = {
            "account": config.get("account"),
            "user": config.get("user"),
            "password": config.get("password"),
            "warehouse": config.get("warehouse", "COMPUTE_WH"),
            "database": config.get("database", "BENCHBOX"),
            "schema": config.get("schema", "PUBLIC"),
            "role": config.get("role"),
            "authenticator": config.get("authenticator"),
            "private_key_path": config.get("private_key_path"),
            "private_key_passphrase": config.get("private_key_passphrase"),
            "warehouse_size": config.get("warehouse_size", "MEDIUM"),
        }

        return cls(**params)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Configure adapter for specific benchmark.

        Args:
            connection: Session object.
            benchmark_type: Benchmark type (tpch, tpcds, ssb).
        """
        self._benchmark_type = benchmark_type.lower()
        logger.info(f"Configuring Snowpark Connect for {benchmark_type} benchmark")

        # Disable result cache for accurate benchmarking
        if self._session:
            self._session.sql("ALTER SESSION SET USE_CACHED_RESULT = FALSE").collect()
            logger.debug("Disabled result cache for benchmarking")

    # apply_primary_keys, apply_foreign_keys, apply_platform_optimizations,
    # and apply_constraint_configuration are inherited from SparkTuningMixin

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Snowpark Connect.

        Snowpark Connect uses Snowflake SQL.

        Returns:
            The dialect string "snowflake".
        """
        return "snowflake"
