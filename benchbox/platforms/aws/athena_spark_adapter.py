"""Amazon Athena for Apache Spark platform adapter.

Athena for Apache Spark is AWS's interactive Spark service with sub-second
startup times. Unlike EMR Serverless or Glue, it uses a notebook-style
execution model with persistent sessions.

Key Features:
- Sub-second startup: Pre-provisioned Spark capacity
- Interactive: Notebook-style session execution
- Serverless: No cluster management required
- S3 integration: Native S3 and Glue Data Catalog support
- Cost-effective: Pay per DPU-hour during session

Usage:
    from benchbox.platforms.aws import AthenaSparkAdapter

    adapter = AthenaSparkAdapter(
        workgroup="spark-workgroup",
        s3_staging_dir="s3://my-bucket/benchbox-data",
    )

    # Run TPC-H benchmark
    adapter.create_schema("tpch_sf1")
    adapter.load_data(["lineitem", "orders", ...], source_dir)
    result = adapter.execute_query("SELECT * FROM lineitem LIMIT 10")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    pass

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.cloud_spark import (
    CloudSparkConfigMixin,
    CloudSparkStaging,
    SparkTuningMixin,
)
from benchbox.platforms.base.cloud_spark.config import CloudPlatform
from benchbox.platforms.base.phase_tracking import _resolve_benchmark_table_names
from benchbox.utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)

try:
    import boto3
    from botocore.exceptions import ClientError

    BOTO3_AVAILABLE = True
except ImportError:
    boto3 = None
    ClientError = Exception
    BOTO3_AVAILABLE = False

logger = logging.getLogger(__name__)


class AthenaSparkSessionState:
    """Athena Spark session state constants.

    Reference: https://docs.aws.amazon.com/athena/latest/APIReference/API_SessionStatus.html
    """

    CREATING = "CREATING"
    CREATED = "CREATED"
    IDLE = "IDLE"
    BUSY = "BUSY"
    TERMINATING = "TERMINATING"
    TERMINATED = "TERMINATED"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"

    # States where session is usable
    READY_STATES = {IDLE, CREATED}

    # Terminal states
    TERMINAL_STATES = {TERMINATED, FAILED}


class AthenaSparkCalculationState:
    """Athena Spark calculation (query) state constants.

    Reference: https://docs.aws.amazon.com/athena/latest/APIReference/API_CalculationStatus.html
    """

    CREATING = "CREATING"
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    CANCELING = "CANCELING"
    CANCELED = "CANCELED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    # Terminal states
    TERMINAL_STATES = {COMPLETED, FAILED, CANCELED}

    # Success states
    SUCCESS_STATES = {COMPLETED}


class AthenaSparkAdapter(CloudSparkConfigMixin, SparkTuningMixin, PlatformAdapter):
    """Amazon Athena for Apache Spark platform adapter.

    Athena Spark provides interactive Spark execution with sub-second startup.
    It uses a session-based model where you start a session, run calculations
    (queries), and terminate the session when done.

    Execution Model:
    - Start a session in a Spark-enabled workgroup
    - Submit calculations (SQL or PySpark code)
    - Results are written to S3 automatically
    - Terminate session when complete

    Key Features:
    - Sub-second startup with pre-provisioned capacity
    - Interactive session-based execution
    - Native Glue Data Catalog integration
    - S3 integration for data and results

    Billing:
    - DPU-hour: ~$0.35/hour per DPU
    - Minimum: 1 DPU
    - Billed per session duration
    """

    plan_capture_phase_eligible = True

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    # CloudSparkConfigMixin: Uses EMR config as base for Athena Spark
    cloud_platform = CloudPlatform.EMR

    def __init__(
        self,
        workgroup: str | None = None,
        s3_staging_dir: str | None = None,
        region: str = "us-east-1",
        database: str | None = None,
        engine_version: str = "PySpark engine version 3",
        session_idle_timeout_minutes: int = 15,
        coordinator_dpu_size: int = 1,
        max_concurrent_dpus: int = 20,
        default_executor_dpu_size: int = 1,
        timeout_minutes: int = 60,
        notebook_version: str | None = None,
        table_format: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Athena Spark adapter.

        Args:
            workgroup: Athena workgroup name (must be Spark-enabled).
            s3_staging_dir: S3 path for data staging (required, e.g., s3://bucket/path).
            region: AWS region (default: us-east-1).
            database: Glue Data Catalog database name (default: benchbox).
            engine_version: Spark engine version (default: PySpark engine version 3).
            session_idle_timeout_minutes: Session idle timeout (default: 15).
            coordinator_dpu_size: Coordinator DPU size (default: 1).
            max_concurrent_dpus: Maximum concurrent DPUs (default: 20).
            default_executor_dpu_size: Default executor DPU size (default: 1).
            timeout_minutes: Calculation timeout in minutes (default: 60).
            notebook_version: Jupyter notebook version (optional).
            **kwargs: Additional platform options.
        """
        if not BOTO3_AVAILABLE:
            deps_satisfied, missing = check_platform_dependencies("athena-spark")
            if not deps_satisfied:
                raise ConfigurationError(get_dependency_error_message("athena-spark", missing))

        if not workgroup:
            raise ConfigurationError("workgroup is required for Athena Spark. Must be a Spark-enabled workgroup.")

        if not s3_staging_dir:
            raise ConfigurationError("s3_staging_dir is required (e.g., s3://bucket/path)")

        if not s3_staging_dir.startswith("s3://"):
            raise ConfigurationError(f"Invalid S3 path: {s3_staging_dir}. Must start with s3://")

        # Parse S3 path
        s3_parts = s3_staging_dir[5:].split("/", 1)
        self.s3_bucket = s3_parts[0]
        self.s3_prefix = s3_parts[1] if len(s3_parts) > 1 else ""

        self.workgroup = workgroup
        self.s3_staging_dir = s3_staging_dir.rstrip("/")
        self.region = region
        self.database = database or "benchbox"
        self.engine_version = engine_version
        self.session_idle_timeout_minutes = session_idle_timeout_minutes
        self.coordinator_dpu_size = coordinator_dpu_size
        self.max_concurrent_dpus = max_concurrent_dpus
        self.default_executor_dpu_size = default_executor_dpu_size
        self.timeout_minutes = timeout_minutes
        self.notebook_version = notebook_version
        self.table_format = table_format or "parquet"

        # Initialize staging using cloud-spark shared infrastructure
        self._staging: CloudSparkStaging | None = None
        try:
            self._staging = CloudSparkStaging.from_uri(self.s3_staging_dir)
        except Exception as e:
            logger.warning(f"Failed to initialize S3 staging: {e}")

        # Clients (lazy initialization)
        self._athena_client: Any = None
        self._glue_client: Any = None
        self._s3_client: Any = None

        # Session management
        self._session_id: str | None = None

        # Metrics tracking
        self._query_count = 0
        self._total_execution_time_seconds = 0.0
        self._total_dpu_hours = 0.0

        # Benchmark configuration (set via configure_for_benchmark)
        self._benchmark_type: str | None = None
        self._scale_factor: float = 1.0
        self._spark_config: dict[str, str] = {}

        super().__init__(**kwargs)

    def _get_athena_client(self) -> Any:
        """Get or create Athena client."""
        if self._athena_client is None:
            self._athena_client = boto3.client("athena", region_name=self.region)
        return self._athena_client

    def _get_glue_client(self) -> Any:
        """Get or create Glue client."""
        if self._glue_client is None:
            self._glue_client = boto3.client("glue", region_name=self.region)
        return self._glue_client

    def _get_s3_client(self) -> Any:
        """Get or create S3 client."""
        if self._s3_client is None:
            self._s3_client = boto3.client("s3", region_name=self.region)
        return self._s3_client

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Return platform metadata.

        Args:
            connection: Not used (Athena Spark manages sessions internally).

        Returns:
            Dict with platform information including name, version, and capabilities.
        """
        return {
            "platform": "athena-spark",
            "display_name": "Amazon Athena for Apache Spark",
            "vendor": "AWS",
            "type": "interactive_spark",
            "region": self.region,
            "workgroup": self.workgroup,
            "engine_version": self.engine_version,
            "engine_version_source": "config",
            "supports_sql": True,
            "supports_dataframe": True,
            "billing_model": "DPU-hour",
            "session_id": self._session_id,
        }

    def create_connection(self, **kwargs: Any) -> Any:
        """Start an Athena Spark session.

        Returns:
            Dict with session status and ID.

        Raises:
            ConfigurationError: If session creation fails.
        """
        client = self._get_athena_client()

        try:
            # Check if we already have an active session
            if self._session_id:
                session_status = self._get_session_status()
                if session_status in AthenaSparkSessionState.READY_STATES:
                    logger.info(f"Using existing session: {self._session_id}")
                    return {
                        "status": "connected",
                        "session_id": self._session_id,
                        "session_state": session_status,
                    }

            # Start a new session
            logger.info(f"Starting Athena Spark session in workgroup: {self.workgroup}")

            session_config = {
                "CoordinatorDpuSize": self.coordinator_dpu_size,
                "MaxConcurrentDpus": self.max_concurrent_dpus,
                "DefaultExecutorDpuSize": self.default_executor_dpu_size,
            }

            if self.notebook_version:
                session_config["NotebookVersion"] = self.notebook_version

            response = client.start_session(
                WorkGroup=self.workgroup,
                EngineConfiguration=session_config,
                SessionIdleTimeoutInMinutes=self.session_idle_timeout_minutes,
            )

            self._session_id = response["SessionId"]
            session_state = response["State"]

            # Wait for session to become ready
            self._wait_for_session_ready()

            logger.info(f"Athena Spark session started: {self._session_id}")
            return {
                "status": "connected",
                "session_id": self._session_id,
                "session_state": session_state,
                "workgroup": self.workgroup,
            }

        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            error_message = e.response.get("Error", {}).get("Message", str(e))

            if error_code == "InvalidRequestException":
                raise ConfigurationError(
                    f"Invalid Athena Spark configuration: {error_message}. "
                    f"Ensure workgroup '{self.workgroup}' is Spark-enabled."
                ) from e
            raise ConfigurationError(f"Failed to start Athena Spark session: {error_message}") from e

    def _get_session_status(self) -> str:
        """Get current session status."""
        if not self._session_id:
            return AthenaSparkSessionState.TERMINATED

        client = self._get_athena_client()

        try:
            response = client.get_session_status(SessionId=self._session_id)
            return response["Status"]["State"]
        except Exception:
            return AthenaSparkSessionState.TERMINATED

    def _wait_for_session_ready(self, timeout_seconds: int = 300) -> None:
        """Wait for session to become ready.

        Args:
            timeout_seconds: Maximum time to wait.

        Raises:
            ConfigurationError: If session fails or times out.
        """
        client = self._get_athena_client()
        start_time = mono_time()

        while elapsed_seconds(start_time) < timeout_seconds:
            response = client.get_session_status(SessionId=self._session_id)
            state = response["Status"]["State"]

            if state in AthenaSparkSessionState.READY_STATES:
                return

            if state in AthenaSparkSessionState.TERMINAL_STATES:
                reason = response["Status"].get("StateChangeReason", "Unknown")
                raise ConfigurationError(f"Session failed: {state} - {reason}")

            time.sleep(2)

        raise ConfigurationError(f"Session startup timed out after {timeout_seconds}s")

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create Glue database if it doesn't exist.

        Args:
            benchmark: Benchmark instance.
            connection: Active connection/session metadata; not used by Athena Spark.
        """
        start_time = mono_time()
        database = self.database
        glue_client = self._get_glue_client()

        try:
            glue_client.get_database(Name=database)
            logger.info(f"Database '{database}' already exists")
        except glue_client.exceptions.EntityNotFoundException:
            # Create database
            location_uri = f"{self.s3_staging_dir}/databases/{database}/"
            glue_client.create_database(
                DatabaseInput={
                    "Name": database,
                    "Description": "BenchBox benchmark database",
                    "LocationUri": location_uri,
                }
            )
            logger.info(f"Created database '{database}'")
        return elapsed_seconds(start_time)

    def _submit_calculation(
        self,
        code: str,
        code_type: str = "SQL",
        wait_for_completion: bool = True,
    ) -> tuple[str, str]:
        """Submit a calculation to the Athena Spark session.

        Args:
            code: SQL or Python code to execute.
            code_type: Type of code ("SQL" or "PYTHON").
            wait_for_completion: Whether to wait for completion.

        Returns:
            Tuple of (calculation_id, final_state).
        """
        if not self._session_id:
            raise ConfigurationError("No active session. Call create_connection() first.")

        client = self._get_athena_client()

        # For SQL, wrap in spark.sql() for proper execution
        if code_type == "SQL":
            # Ensure we're using the correct database
            execution_code = f"""
spark.sql("USE {self.database}")
result = spark.sql('''{code}''')
result.show(100, truncate=False)
"""
        else:
            execution_code = code

        response = client.start_calculation_execution(
            SessionId=self._session_id,
            CodeBlock=execution_code,
        )

        calculation_id = response["CalculationExecutionId"]
        state = response["State"]

        if wait_for_completion:
            state = self._wait_for_calculation_complete(calculation_id)

        return calculation_id, state

    def _wait_for_calculation_complete(
        self,
        calculation_id: str,
        timeout_seconds: int | None = None,
    ) -> str:
        """Wait for calculation to complete.

        Args:
            calculation_id: The calculation execution ID.
            timeout_seconds: Maximum time to wait.

        Returns:
            Final calculation state.
        """
        client = self._get_athena_client()
        timeout = timeout_seconds or self.timeout_minutes * 60
        start_time = mono_time()

        while elapsed_seconds(start_time) < timeout:
            response = client.get_calculation_execution_status(CalculationExecutionId=calculation_id)
            state = response["Status"]["State"]

            if state in AthenaSparkCalculationState.TERMINAL_STATES:
                return state

            time.sleep(2)

        raise RuntimeError(f"Calculation timed out after {timeout}s")

    def _get_calculation_result(self, calculation_id: str) -> list[dict[str, Any]]:
        """Get calculation results.

        Args:
            calculation_id: The calculation execution ID.

        Returns:
            List of result rows as dicts.
        """
        client = self._get_athena_client()

        try:
            response = client.get_calculation_execution(CalculationExecutionId=calculation_id)

            # Results are in the Result field
            result = response.get("Result", {})
            result_s3_uri = result.get("ResultS3Uri")

            if result_s3_uri:
                # Fetch results from S3
                return self._fetch_results_from_s3(result_s3_uri)

            # Try to get stdout if no S3 results
            stdout = result.get("StdOutS3Uri")
            if stdout:
                return self._fetch_results_from_s3(stdout)

            return []

        except Exception as e:
            logger.warning(f"Could not get calculation results: {e}")
            return []

    def _fetch_results_from_s3(self, s3_uri: str) -> list[dict[str, Any]]:
        """Fetch results from S3.

        Args:
            s3_uri: S3 URI of the results.

        Returns:
            List of result rows as dicts.
        """
        s3_client = self._get_s3_client()

        # Parse S3 URI
        if s3_uri.startswith("s3://"):
            s3_uri = s3_uri[5:]
        bucket, key = s3_uri.split("/", 1)

        try:
            response = s3_client.get_object(Bucket=bucket, Key=key)
            content = response["Body"].read().decode("utf-8")

            # Parse based on content type
            results = []
            for line in content.strip().split("\n"):
                if line:
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        # Plain text result
                        results.append({"output": line})
            return results

        except Exception as e:
            logger.debug(f"Could not fetch results from {s3_uri}: {e}")
            return []

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Upload benchmark data to S3 and create Hive tables.

        Args:
            benchmark: Benchmark instance.
            connection: Active connection/session metadata; not used by Athena Spark.
            data_dir: Local directory containing table data files.

        Returns:
            Tuple of table row-count placeholders, elapsed seconds, and table URI metadata.
        """
        start_time = mono_time()
        source_path = Path(data_dir)
        tables = _resolve_benchmark_table_names(benchmark)
        file_format = self.requested_table_format or self.table_format
        if not source_path.exists():
            raise ConfigurationError(f"Source directory not found: {data_dir}")

        # Check if tables already exist in S3
        if self._staging and self._staging.tables_exist(tables):
            logger.info("Tables already exist in S3 staging, skipping upload")
            table_uris = {table: self._staging.get_table_uri(table) for table in tables}
            return dict.fromkeys(tables, 0), elapsed_seconds(start_time), {"table_uris": table_uris}

        # Upload using cloud-spark staging infrastructure
        if self._staging:
            logger.info(f"Uploading {len(tables)} tables to S3 staging")
            self._staging.upload_tables(
                tables=tables,
                source_dir=source_path,
                file_format=file_format,
            )

        # Create Hive external tables via Spark SQL
        table_uris = {}
        for table in tables:
            table_uri = f"{self.s3_staging_dir}/tables/{table}"
            table_uris[table] = table_uri

            create_table_sql = f"""
                CREATE EXTERNAL TABLE IF NOT EXISTS {self.database}.{table}
                USING {self.table_format.upper()}
                LOCATION '{table_uri}'
            """
            self._submit_calculation(create_table_sql, code_type="SQL", wait_for_completion=True)
            logger.info(f"Created table {self.database}.{table}")

        return dict.fromkeys(tables, 0), elapsed_seconds(start_time), {"table_uris": table_uris}

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
        """Execute a SQL query on Athena Spark.

        Args:
            connection: Active connection/session metadata; not used by Athena Spark.
            query: SQL query to execute.
            query_id: Query identifier.

        Returns:
            Standard query result dictionary.
        """
        start_time = mono_time()
        try:
            calculation_id, state = self._submit_calculation(query, code_type="SQL", wait_for_completion=True)
            elapsed = elapsed_seconds(start_time)
            self._query_count += 1
            self._total_execution_time_seconds += elapsed
            if state not in AthenaSparkCalculationState.SUCCESS_STATES:
                raise RuntimeError(f"Athena Spark calculation failed with state: {state}")
            results = self._get_calculation_result(calculation_id)
            return {
                "query_id": query_id,
                "stream_id": stream_id,
                "status": "SUCCESS",
                "execution_time_seconds": elapsed,
                "rows_returned": len(results),
                "results": results,
                "error": None,
            }
        except Exception as e:
            return {
                "query_id": query_id,
                "stream_id": stream_id,
                "status": "FAILED",
                "execution_time_seconds": elapsed_seconds(start_time),
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }

    def close(self) -> None:
        """Terminate the Athena Spark session."""
        if self._session_id:
            try:
                client = self._get_athena_client()
                client.terminate_session(SessionId=self._session_id)
                logger.info(f"Terminated session: {self._session_id}")
            except Exception as e:
                logger.warning(f"Failed to terminate session: {e}")
            finally:
                self._session_id = None

        logger.info(f"Athena Spark session closed. Executed {self._query_count} calculations.")
        if self._total_execution_time_seconds > 0:
            logger.info(f"Total execution time: {self._total_execution_time_seconds:.1f}s")

    @staticmethod
    def add_cli_arguments(parser: Any) -> None:
        """Add Athena Spark-specific CLI arguments.

        Args:
            parser: Argument parser to add arguments to.
        """
        group = parser.add_argument_group("Athena Spark Options")
        group.add_argument(
            "--workgroup",
            help="Spark-enabled Athena workgroup name",
        )
        group.add_argument(
            "--s3-staging-dir",
            help="S3 path for data staging (e.g., s3://bucket/path)",
        )
        group.add_argument(
            "--region",
            default="us-east-1",
            help="AWS region (default: us-east-1)",
        )
        group.add_argument(
            "--database",
            default="benchbox",
            help="Glue Data Catalog database (default: benchbox)",
        )
        group.add_argument(
            "--coordinator-dpu-size",
            type=int,
            default=1,
            help="Coordinator DPU size (default: 1)",
        )
        group.add_argument(
            "--max-concurrent-dpus",
            type=int,
            default=20,
            help="Maximum concurrent DPUs (default: 20)",
        )
        group.add_argument(
            "--session-idle-timeout",
            type=int,
            default=15,
            help="Session idle timeout in minutes (default: 15)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AthenaSparkAdapter:
        """Create adapter from configuration dict.

        Args:
            config: Configuration dictionary.

        Returns:
            Configured AthenaSparkAdapter instance.
        """
        params = {
            "workgroup": config.get("workgroup"),
            "s3_staging_dir": config.get("s3_staging_dir"),
            "region": config.get("region", "us-east-1"),
            "database": config.get("database", "benchbox"),
            "engine_version": config.get("engine_version", "PySpark engine version 3"),
            "session_idle_timeout_minutes": config.get("session_idle_timeout_minutes", 15),
            "coordinator_dpu_size": config.get("coordinator_dpu_size", 1),
            "max_concurrent_dpus": config.get("max_concurrent_dpus", 20),
            "default_executor_dpu_size": config.get("default_executor_dpu_size", 1),
            "timeout_minutes": config.get("timeout_minutes", 60),
            "table_format": config.get("table_format"),
        }

        return cls(**params)

    # configure_for_benchmark is inherited from CloudSparkConfigMixin

    # apply_primary_keys, apply_foreign_keys, apply_platform_optimizations,
    # and apply_constraint_configuration are inherited from SparkTuningMixin

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Athena Spark.

        Athena Spark uses Spark SQL for query execution.

        Returns:
            The dialect string "spark".
        """
        return "spark"
