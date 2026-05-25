"""GCP Dataproc Serverless platform adapter.

Dataproc Serverless is Google Cloud's fully managed, auto-scaling Spark service.
Unlike traditional Dataproc clusters, Serverless eliminates cluster management
entirely - you submit batches and GCP handles all infrastructure automatically.

Key Features:
- No cluster management: Submit batches, GCP provisions resources automatically
- Auto-scaling: Resources scale based on workload demands
- Fast startup: Sub-minute batch startup vs minutes for clusters
- Cost-effective: Pay only for actual compute time, no idle cluster costs
- GCS integration: Native Google Cloud Storage support

Usage:
    from benchbox.platforms.gcp import DataprocServerlessAdapter

    adapter = DataprocServerlessAdapter(
        project_id="my-project",
        region="us-central1",
        gcs_staging_dir="gs://my-bucket/benchbox-data",
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
import uuid
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
from benchbox.platforms.gcp._gcs_path import parse_gcs_staging_dir
from benchbox.utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)

try:
    from google.cloud import dataproc_v1, storage

    GOOGLE_CLOUD_AVAILABLE = True
except ImportError:
    dataproc_v1 = None
    storage = None
    GOOGLE_CLOUD_AVAILABLE = False

logger = logging.getLogger(__name__)


class DataprocBatchState:
    """Dataproc Serverless batch state constants.

    Reference: https://cloud.google.com/dataproc-serverless/docs/reference/rpc/google.cloud.dataproc.v1#google.cloud.dataproc.v1.Batch.State
    """

    STATE_UNSPECIFIED = "STATE_UNSPECIFIED"
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    CANCELLED = "CANCELLED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"

    # Terminal states
    TERMINAL_STATES = {SUCCEEDED, FAILED, CANCELLED}

    # Success state
    SUCCESS_STATES = {SUCCEEDED}


class DataprocServerlessAdapter(CloudSparkConfigMixin, SparkTuningMixin, PlatformAdapter):
    """GCP Dataproc Serverless platform adapter.

    Dataproc Serverless is Google Cloud's fully managed Spark service that
    eliminates cluster management. Batches are submitted and GCP automatically
    provisions and scales the required resources.

    Execution Model:
    - Batches are submitted via the Batch Controller API
    - GCP provisions Spark resources automatically
    - Results are written to GCS and retrieved after batch completion
    - No cluster to manage, start, or stop

    Key Features:
    - Zero cluster management
    - Sub-minute batch startup
    - Automatic resource scaling
    - Integration with GCS, BigQuery, and Bigtable
    - Spark 3.x with Delta Lake support

    Billing:
    - Per-second billing for actual compute time
    - No idle costs (unlike persistent clusters)
    - Pricing: ~$0.06/vCPU-hour, ~$0.0065/GB-hour
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    # CloudSparkConfigMixin: Uses Dataproc Serverless-optimized config
    cloud_platform = CloudPlatform.DATAPROC_SERVERLESS

    def __init__(
        self,
        project_id: str | None = None,
        region: str = "us-central1",
        gcs_staging_dir: str | None = None,
        database: str | None = None,
        runtime_version: str = "2.1",
        service_account: str | None = None,
        network_uri: str | None = None,
        subnetwork_uri: str | None = None,
        timeout_minutes: int = 60,
        spark_config: dict[str, str] | None = None,
        table_format: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Dataproc Serverless adapter.

        Args:
            project_id: GCP project ID (required).
            region: GCP region for batch execution (default: us-central1).
            gcs_staging_dir: GCS path for data staging (required, e.g., gs://bucket/path).
            database: Hive database name (default: benchbox).
            runtime_version: Dataproc Serverless runtime version (default: 2.1).
            service_account: Service account email for batch execution.
            network_uri: VPC network URI (optional, uses default if not provided).
            subnetwork_uri: Subnetwork URI (optional).
            timeout_minutes: Batch timeout in minutes (default: 60).
            spark_config: Additional Spark configuration properties.
            **kwargs: Additional platform options.
        """
        if not GOOGLE_CLOUD_AVAILABLE:
            deps_satisfied, missing = check_platform_dependencies("dataproc-serverless")
            if not deps_satisfied:
                raise ConfigurationError(get_dependency_error_message("dataproc-serverless", missing))

        if not project_id:
            raise ConfigurationError("project_id is required for Dataproc Serverless adapter")

        parsed = parse_gcs_staging_dir(gcs_staging_dir)
        self.gcs_bucket = parsed.bucket
        self.gcs_prefix = parsed.prefix

        self.project_id = project_id
        self.region = region
        self.gcs_staging_dir = parsed.uri
        self.database = database or "benchbox"
        self.runtime_version = runtime_version
        self.service_account = service_account
        self.network_uri = network_uri
        self.subnetwork_uri = subnetwork_uri
        self.timeout_minutes = timeout_minutes
        self.table_format = table_format or "parquet"

        # Initialize staging using cloud-spark shared infrastructure
        self._staging: CloudSparkStaging | None = None
        try:
            self._staging = CloudSparkStaging.from_uri(self.gcs_staging_dir)
        except Exception as e:
            logger.warning(f"Failed to initialize GCS staging: {e}")

        # Clients (lazy initialization)
        self._batch_client: Any = None
        self._storage_client: Any = None

        # Metrics tracking
        self._query_count = 0
        self._total_batch_time_seconds = 0.0

        # Benchmark configuration (set via configure_for_benchmark)
        self._benchmark_type: str | None = None
        self._scale_factor: float = 1.0
        self._spark_config: dict[str, str] = spark_config or {}

        super().__init__(**kwargs)

    def _get_batch_client(self) -> Any:
        """Get or create Dataproc Batch Controller client."""
        if self._batch_client is None:
            self._batch_client = dataproc_v1.BatchControllerClient(
                client_options={"api_endpoint": f"{self.region}-dataproc.googleapis.com:443"}
            )
        return self._batch_client

    def _get_storage_client(self) -> Any:
        """Get or create GCS storage client."""
        if self._storage_client is None:
            self._storage_client = storage.Client(project=self.project_id)
        return self._storage_client

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Return platform metadata.

        Args:
            connection: Not used (Dataproc Serverless manages sessions internally).

        Returns:
            Dict with platform information including name, version, and capabilities.
        """
        return {
            "platform": "dataproc-serverless",
            "display_name": "Google Cloud Dataproc Serverless",
            "vendor": "Google Cloud",
            "type": "serverless_spark",
            "project_id": self.project_id,
            "region": self.region,
            "runtime_version": self.runtime_version,
            "supports_sql": True,
            "supports_dataframe": True,
            "billing_model": "per-second compute time",
            "cluster_management": False,
        }

    def create_connection(self, **kwargs: Any) -> Any:
        """Verify GCP connectivity and permissions.

        Returns:
            Dict with connection status and project info.

        Raises:
            ConfigurationError: If GCP connection fails.
        """
        try:
            # Verify batch API access by listing batches (will fail if no permissions)
            client = self._get_batch_client()

            # List batches to verify permissions (empty result is fine)
            parent = f"projects/{self.project_id}/locations/{self.region}"
            request = dataproc_v1.ListBatchesRequest(parent=parent, page_size=1)
            client.list_batches(request=request)

            logger.info(f"Connected to Dataproc Serverless in {self.region}")
            return {
                "status": "connected",
                "project_id": self.project_id,
                "region": self.region,
                "message": "Ready to submit Serverless Spark batches",
            }
        except Exception as e:
            raise ConfigurationError(f"Failed to connect to Dataproc Serverless: {e}") from e

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create Hive database if it doesn't exist.

        Args:
            benchmark: Benchmark instance.
            connection: Active connection metadata; not used by Dataproc Serverless.
        """
        start_time = mono_time()
        database = self.database

        # Create database via a Spark SQL batch
        create_db_query = f"CREATE DATABASE IF NOT EXISTS {database}"
        self._submit_spark_sql_batch(create_db_query, wait_for_completion=True)
        logger.info(f"Database '{database}' created or already exists")
        return elapsed_seconds(start_time)

    def _submit_spark_sql_batch(
        self,
        query: str,
        wait_for_completion: bool = True,
    ) -> tuple[str, str]:
        """Submit a Spark SQL batch to Dataproc Serverless.

        Args:
            query: SQL query to execute.
            wait_for_completion: Whether to wait for batch completion.

        Returns:
            Tuple of (batch_id, final_state).
        """
        client = self._get_batch_client()

        batch_id = f"benchbox-{uuid.uuid4().hex[:12]}"
        results_path = f"{self.gcs_staging_dir}/results/{batch_id}"

        # Create PySpark script that runs the query and saves results
        job_script = f'''
from pyspark.sql import SparkSession

spark = SparkSession.builder \\
    .appName("BenchBox Query") \\
    .enableHiveSupport() \\
    .getOrCreate()

spark.sql("USE {self.database}")

result = spark.sql("""{query}""")
result.write.mode("overwrite").json("{results_path}")

spark.stop()
'''

        # Upload script to GCS
        script_path = f"{self.gcs_staging_dir}/scripts/{batch_id}.py"
        self._upload_to_gcs(script_path, job_script)

        # Build batch configuration
        batch = {
            "pyspark_batch": {
                "main_python_file_uri": script_path,
            },
            "runtime_config": {
                "version": self.runtime_version,
                "properties": self._spark_config,
            },
        }

        # Add service account if specified
        if self.service_account:
            batch["environment_config"] = {
                "execution_config": {
                    "service_account": self.service_account,
                }
            }

        # Add network configuration if specified
        if self.network_uri or self.subnetwork_uri:
            if "environment_config" not in batch:
                batch["environment_config"] = {"execution_config": {}}
            if self.network_uri:
                batch["environment_config"]["execution_config"]["network_uri"] = self.network_uri
            if self.subnetwork_uri:
                batch["environment_config"]["execution_config"]["subnetwork_uri"] = self.subnetwork_uri

        parent = f"projects/{self.project_id}/locations/{self.region}"

        logger.debug(f"Submitting batch {batch_id}")
        operation = client.create_batch(
            request={
                "parent": parent,
                "batch": batch,
                "batch_id": batch_id,
            }
        )

        if wait_for_completion:
            result = operation.result(timeout=self.timeout_minutes * 60)
            return batch_id, result.state.name
        else:
            return batch_id, DataprocBatchState.PENDING

    def _upload_to_gcs(self, gcs_path: str, content: str) -> None:
        """Upload content to GCS.

        Args:
            gcs_path: Full GCS path (gs://bucket/path).
            content: Content to upload.
        """
        client = self._get_storage_client()

        # Parse GCS path
        if gcs_path.startswith("gs://"):
            gcs_path = gcs_path[5:]
        bucket_name, blob_name = gcs_path.split("/", 1)

        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(content)

    def _retrieve_results(self, batch_id: str) -> list[dict[str, Any]]:
        """Retrieve batch results from GCS.

        Args:
            batch_id: The batch ID.

        Returns:
            List of result rows as dicts.
        """
        client = self._get_storage_client()
        results_prefix = f"{self.gcs_prefix}/results/{batch_id}/"

        bucket = client.bucket(self.gcs_bucket)
        blobs = bucket.list_blobs(prefix=results_prefix)

        results = []
        for blob in blobs:
            if blob.name.endswith(".json"):
                content = blob.download_as_string()
                # Spark JSON output is newline-delimited JSON
                for line in content.decode().strip().split("\n"):
                    if line:
                        results.append(json.loads(line))

        return results

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Upload benchmark data to GCS and create Hive tables.

        Args:
            benchmark: Benchmark instance.
            connection: Active connection metadata; not used by Dataproc Serverless.
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

        # Check if tables already exist in GCS
        if self._staging and self._staging.tables_exist(tables):
            logger.info("Tables already exist in GCS staging, skipping upload")
            table_uris = {table: self._staging.get_table_uri(table) for table in tables}
            return dict.fromkeys(tables, 0), elapsed_seconds(start_time), {"table_uris": table_uris}

        # Upload using cloud-spark staging infrastructure
        if self._staging:
            logger.info(f"Uploading {len(tables)} tables to GCS staging")
            self._staging.upload_tables(
                tables=tables,
                source_dir=source_path,
                file_format=file_format,
            )

        # Create Hive external tables via Serverless batches
        table_uris = {}
        for table in tables:
            table_uri = f"{self.gcs_staging_dir}/tables/{table}"
            table_uris[table] = table_uri

            create_table_query = f"""
                CREATE EXTERNAL TABLE IF NOT EXISTS {self.database}.{table}
                USING {self.table_format.upper()}
                LOCATION '{table_uri}'
            """
            self._submit_spark_sql_batch(create_table_query, wait_for_completion=True)
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
        """Execute a SQL query on Dataproc Serverless.

        Args:
            connection: Active connection metadata; not used by Dataproc Serverless.
            query: SQL query to execute.
            query_id: Query identifier.

        Returns:
            Standard query result dictionary.
        """
        start_time = mono_time()
        try:
            batch_id, state = self._submit_spark_sql_batch(query, wait_for_completion=True)
            elapsed = elapsed_seconds(start_time)
            self._query_count += 1
            self._total_batch_time_seconds += elapsed
            if state not in DataprocBatchState.SUCCESS_STATES:
                raise RuntimeError(f"Dataproc Serverless batch failed with state: {state}")
            results = self._retrieve_results(batch_id)
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
        """Clean up resources."""
        logger.info(f"Dataproc Serverless session closed. Executed {self._query_count} batches.")
        if self._total_batch_time_seconds > 0:
            logger.info(f"Total batch time: {self._total_batch_time_seconds:.1f}s")

    @staticmethod
    def add_cli_arguments(parser: Any) -> None:
        """Add Dataproc Serverless-specific CLI arguments.

        Args:
            parser: Argument parser to add arguments to.
        """
        group = parser.add_argument_group("Dataproc Serverless Options")
        group.add_argument(
            "--project-id",
            help="GCP project ID",
        )
        group.add_argument(
            "--region",
            default="us-central1",
            help="GCP region (default: us-central1)",
        )
        group.add_argument(
            "--gcs-staging-dir",
            help="GCS path for data staging (e.g., gs://bucket/path)",
        )
        group.add_argument(
            "--database",
            default="benchbox",
            help="Hive database name (default: benchbox)",
        )
        group.add_argument(
            "--runtime-version",
            default="2.1",
            help="Dataproc Serverless runtime version (default: 2.1)",
        )
        group.add_argument(
            "--service-account",
            help="Service account email for batch execution",
        )
        group.add_argument(
            "--network-uri",
            help="VPC network URI",
        )
        group.add_argument(
            "--subnetwork-uri",
            help="Subnetwork URI",
        )
        group.add_argument(
            "--timeout-minutes",
            type=int,
            default=60,
            help="Batch timeout in minutes (default: 60)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> DataprocServerlessAdapter:
        """Create adapter from configuration dict.

        Args:
            config: Configuration dictionary.

        Returns:
            Configured DataprocServerlessAdapter instance.
        """
        params = {
            "project_id": config.get("project_id"),
            "region": config.get("region", "us-central1"),
            "gcs_staging_dir": config.get("gcs_staging_dir"),
            "database": config.get("database", "benchbox"),
            "runtime_version": config.get("runtime_version", "2.1"),
            "service_account": config.get("service_account"),
            "network_uri": config.get("network_uri"),
            "subnetwork_uri": config.get("subnetwork_uri"),
            "timeout_minutes": config.get("timeout_minutes", 60),
            "table_format": config.get("table_format"),
        }

        return cls(**params)

    # configure_for_benchmark is inherited from CloudSparkConfigMixin

    # apply_primary_keys, apply_foreign_keys, apply_platform_optimizations,
    # and apply_constraint_configuration are inherited from SparkTuningMixin

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Dataproc Serverless.

        Dataproc Serverless uses Spark SQL for query execution.

        Returns:
            The dialect string "spark".
        """
        return "spark"
