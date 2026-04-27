"""AWS Glue managed Spark platform adapter.

AWS Glue is a fully managed ETL (extract, transform, and load) service
that makes it easy to prepare and load data for analytics. Under the
hood, Glue uses Apache Spark for distributed data processing.

Key Features:
- Serverless: No infrastructure to manage, scales automatically
- Pay-per-use: Charged per DPU-hour (~$0.44/DPU-hour)
- Integrated: Native AWS Glue Data Catalog for metadata management
- Flexible: Supports Python shell, Spark, and Ray job types

Usage:
    from benchbox.platforms.aws import AWSGlueAdapter

    adapter = AWSGlueAdapter(
        region="us-east-1",
        s3_staging_dir="s3://my-bucket/benchbox-data",
        job_role="arn:aws:iam::123456789:role/GlueBenchmarkRole",
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
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        UnifiedTuningConfiguration,
    )

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.platforms.base.cloud_spark import (
    CloudSparkStaging,
    SparkConfigOptimizer,
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


class GlueJobStatus:
    """AWS Glue job run status constants."""

    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"
    WAITING = "WAITING"


class AWSGlueAdapter(SparkTuningMixin, PlatformAdapter):
    """AWS Glue managed Spark platform adapter.

    Glue is AWS's serverless ETL service that runs Apache Spark jobs.
    It integrates with the Glue Data Catalog for metadata management
    and S3 for data storage.

    Execution Model:
    - Unlike interactive query services, Glue executes jobs as batch processes
    - Each benchmark query is submitted as a Glue job run
    - Results are written to S3 and retrieved after job completion

    Key Features:
    - Serverless: Scales automatically based on workload
    - Pay-per-use: ~$0.44 per DPU-hour
    - Native AWS integration (S3, Data Catalog, CloudWatch)
    - Supports both SQL and DataFrame execution modes
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    def __init__(self, **config: Any) -> None:
        """Initialize AWS Glue adapter.

        Args:
            **config: Configuration options:
                - region: AWS region (default: us-east-1)
                - s3_staging_dir: S3 path for data staging (required)
                - job_role: IAM role ARN for Glue jobs (required)
                - database: Glue Data Catalog database (default: benchbox)
                - worker_type: Glue worker type (default: G.1X)
                - number_of_workers: Number of Glue workers (default: 2)
                - glue_version: Glue version (default: 4.0)
                - job_timeout: Job timeout in minutes (default: 60)
                - extra_py_files: Additional Python files for jobs
                - extra_jars: Additional JAR files for jobs
                - spark_conf: Additional Spark configuration
        """
        super().__init__(**config)

        # Check dependencies
        if not BOTO3_AVAILABLE:
            available, missing = check_platform_dependencies("glue")
            if not available:
                error_msg = get_dependency_error_message("glue", missing)
                raise ImportError(error_msg)

        self._dialect = "spark"  # Glue uses Spark SQL

        # AWS configuration
        self.region = config.get("region") or config.get("aws_region") or "us-east-1"
        self.aws_access_key_id = config.get("aws_access_key_id")
        self.aws_secret_access_key = config.get("aws_secret_access_key")
        self.aws_profile = config.get("aws_profile")

        # S3 staging configuration (required)
        self.s3_staging_dir = config.get("s3_staging_dir") or config.get("staging_root")
        if not self.s3_staging_dir:
            raise ConfigurationError(
                "AWS Glue requires s3_staging_dir for data and results.\n"
                "Example: s3://my-bucket/benchbox-data\n\n"
                "Provide via:\n"
                "  --staging-root s3://my-bucket/benchbox-data\n"
                "  or: BENCHBOX_S3_STAGING_DIR environment variable"
            )

        # Parse S3 staging path
        if self.s3_staging_dir.startswith("s3://"):
            parts = self.s3_staging_dir[5:].split("/", 1)
            self.s3_bucket = parts[0]
            self.s3_prefix = parts[1].rstrip("/") if len(parts) > 1 else "benchbox-data"
        else:
            raise ConfigurationError(
                f"Invalid S3 staging path: {self.s3_staging_dir}\nMust start with s3:// (e.g., s3://my-bucket/path)"
            )

        # IAM role for Glue jobs (required)
        self.job_role = config.get("job_role") or config.get("iam_role")
        if not self.job_role:
            raise ConfigurationError(
                "AWS Glue requires job_role (IAM role ARN) for job execution.\n"
                "Example: arn:aws:iam::123456789012:role/GlueServiceRole\n\n"
                "The role needs:\n"
                "  - AWSGlueServiceRole policy\n"
                "  - S3 read/write access to staging bucket\n"
                "  - Glue Data Catalog access"
            )

        # Glue Data Catalog configuration
        self.database = config.get("database") or "benchbox"
        self.catalog_id = config.get("catalog_id")  # AWS account ID, defaults to caller

        # Glue job configuration
        self.worker_type = config.get("worker_type") or "G.1X"
        self.number_of_workers = config.get("number_of_workers") or 2
        self.glue_version = config.get("glue_version") or "4.0"
        self.job_timeout = config.get("job_timeout") or 60  # minutes
        self.max_concurrent_runs = config.get("max_concurrent_runs") or 1

        # Additional job resources
        self.extra_py_files = config.get("extra_py_files") or []
        self.extra_jars = config.get("extra_jars") or []

        # Spark configuration (merged with optimizer recommendations)
        self.spark_conf = config.get("spark_conf") or {}

        # Execution mode
        self.execution_mode = config.get("execution_mode") or "sql"

        # Job tracking
        self._job_name: str | None = None
        self._job_runs: list[str] = []

        # Cost tracking
        self._total_dpu_hours = 0.0
        self._query_count = 0

        # AWS clients (lazy initialization)
        self._glue_client = None
        self._s3_client = None
        self._staging: CloudSparkStaging | None = None

        # Initialize staging using shared infrastructure
        self._init_staging()

    def _init_staging(self) -> None:
        """Initialize cloud staging using shared infrastructure."""
        self._staging = CloudSparkStaging.from_uri(self.s3_staging_dir)

    def _get_glue_client(self) -> Any:
        """Get or create Glue client."""
        if self._glue_client is None:
            session = self._get_boto_session()
            self._glue_client = session.client("glue")
        return self._glue_client

    def _get_s3_client(self) -> Any:
        """Get or create S3 client."""
        if self._s3_client is None:
            session = self._get_boto_session()
            self._s3_client = session.client("s3")
        return self._s3_client

    def _get_boto_session(self) -> Any:
        """Create boto3 session with configured credentials."""
        if self.aws_profile:
            return boto3.Session(profile_name=self.aws_profile, region_name=self.region)
        elif self.aws_access_key_id and self.aws_secret_access_key:
            return boto3.Session(
                aws_access_key_id=self.aws_access_key_id,
                aws_secret_access_key=self.aws_secret_access_key,
                region_name=self.region,
            )
        else:
            # Use default credential chain (env vars, instance profile, etc.)
            return boto3.Session(region_name=self.region)

    # -------------------------------------------------------------------------
    # PlatformAdapter Interface
    # -------------------------------------------------------------------------

    def create_connection(self) -> Any:
        """Verify AWS credentials and Glue access.

        Returns:
            Glue client for subsequent operations.

        Raises:
            ConfigurationError: If AWS credentials are invalid or Glue access denied.
        """
        try:
            client = self._get_glue_client()
            # Verify access by listing databases
            client.get_databases(MaxResults=1)
            logger.info(f"Connected to AWS Glue in {self.region}")
            return client
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "Unknown")
            if error_code == "AccessDeniedException":
                raise ConfigurationError(
                    f"Access denied to AWS Glue in {self.region}.\nCheck IAM permissions for Glue service access."
                ) from e
            raise ConfigurationError(f"Failed to connect to AWS Glue: {e}") from e

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create Glue Data Catalog database if it doesn't exist.

        Args:
            benchmark: Benchmark instance.
            connection: Active connection metadata; not used by Glue.
        """
        start_time = mono_time()
        database = self.database
        client = self._get_glue_client()

        try:
            client.get_database(Name=database)
            logger.info(f"Database '{database}' already exists")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "EntityNotFoundException":
                logger.info(f"Creating database '{database}'")
                client.create_database(
                    DatabaseInput={
                        "Name": database,
                        "Description": "BenchBox benchmark database",
                    }
                )
            else:
                raise
        return elapsed_seconds(start_time)

    def load_data(
        self,
        benchmark,
        connection: Any,
        data_dir: Path,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Upload benchmark data to S3 and create Glue tables.

        Args:
            benchmark: Benchmark instance.
            connection: Active connection metadata; not used by Glue.
            data_dir: Local directory containing table data files.

        Returns:
            Tuple of table row-count placeholders, elapsed seconds, and table URI metadata.
        """
        start_time = mono_time()
        source_path = Path(data_dir)
        tables = _resolve_benchmark_table_names(benchmark)
        file_format = self.requested_table_format or "parquet"
        if not source_path.exists():
            raise ConfigurationError(f"Source directory not found: {data_dir}")

        # Check if tables already exist in S3
        if self._staging and self._staging.tables_exist(tables):
            logger.info("Tables already exist in S3 staging, skipping upload")
            table_uris = {table: self._staging.get_table_uri(table) for table in tables}
            return dict.fromkeys(tables, 0), elapsed_seconds(start_time), {"table_uris": table_uris}

        # Upload tables using shared staging infrastructure
        logger.info(f"Uploading {len(tables)} tables to S3")
        if self._staging:
            uploaded = self._staging.upload_tables(
                tables=tables,
                source_dir=source_path,
                file_format=file_format,
            )
        else:
            uploaded = {}

        # Create Glue Data Catalog tables
        for table in tables:
            self._create_catalog_table(table, file_format, uploaded.get(table, ""))

        return dict.fromkeys(tables, 0), elapsed_seconds(start_time), {"table_uris": uploaded}

    def _create_catalog_table(
        self,
        table_name: str,
        file_format: str,
        s3_location: str,
    ) -> None:
        """Create a table in Glue Data Catalog.

        Args:
            table_name: Name of the table.
            file_format: Data format (parquet, csv, etc.).
            s3_location: S3 path to table data.
        """
        client = self._get_glue_client()

        # Determine SerDe and input format based on file format
        if file_format.lower() == "parquet":
            input_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
            output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
            serde = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
        elif file_format.lower() == "csv":
            input_format = "org.apache.hadoop.mapred.TextInputFormat"
            output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"
            serde = "org.apache.hadoop.hive.serde2.OpenCSVSerde"
        else:
            # Default to Parquet
            input_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat"
            output_format = "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat"
            serde = "org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"

        table_input = {
            "Name": table_name,
            "Description": f"BenchBox {table_name} table",
            "TableType": "EXTERNAL_TABLE",
            "StorageDescriptor": {
                "Columns": [],  # Schema inference from data
                "Location": s3_location,
                "InputFormat": input_format,
                "OutputFormat": output_format,
                "SerdeInfo": {"SerializationLibrary": serde},
                "Compressed": True,
            },
            "Parameters": {
                "classification": file_format.lower(),
                "benchbox_managed": "true",
            },
        }

        try:
            client.create_table(DatabaseName=self.database, TableInput=table_input)
            logger.info(f"Created table '{self.database}.{table_name}'")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "AlreadyExistsException":
                logger.debug(f"Table '{table_name}' already exists, skipping")
            else:
                raise

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
        """Execute SQL query via Glue job.

        Args:
            connection: Active connection metadata; not used by Glue.
            query: SQL query to execute.
            query_id: Query identifier.

        Returns:
            Standard query result dictionary.
        """
        start_time = mono_time()
        try:
            self._ensure_job_exists()
            run_id = self._submit_job_run(query)
            status = self._wait_for_job(run_id)
            if status != GlueJobStatus.SUCCEEDED:
                raise RuntimeError(f"Glue job failed with status: {status}")
            results = self._retrieve_results(run_id)
            elapsed = elapsed_seconds(start_time)
            self._query_count += 1
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

    def _ensure_job_exists(self) -> str:
        """Ensure Glue job exists for benchmark execution.

        Returns:
            Job name.
        """
        if self._job_name:
            return self._job_name

        job_name = f"benchbox-{self.database}-{uuid.uuid4().hex[:8]}"
        client = self._get_glue_client()

        # Get optimized Spark config
        spark_config = SparkConfigOptimizer.for_tpch(
            scale_factor=1.0,
            platform=CloudPlatform.GLUE,
        )

        # Merge with user-provided config
        merged_config = {**spark_config.to_dict(), **self.spark_conf}

        # Build job script
        script_location = self._upload_job_script()

        default_arguments = {
            "--enable-metrics": "true",
            "--enable-spark-ui": "true",
            "--enable-continuous-cloudwatch-log": "true",
            "--enable-glue-datacatalog": "true",
            "--job-bookmark-option": "job-bookmark-disable",
            "--TempDir": f"s3://{self.s3_bucket}/{self.s3_prefix}/temp/",
            "--database": self.database,
            "--output_path": f"s3://{self.s3_bucket}/{self.s3_prefix}/results/",
        }

        # Add Spark configuration
        for key, value in merged_config.items():
            default_arguments["--conf"] = f"{key}={value}"

        try:
            client.create_job(
                Name=job_name,
                Role=self.job_role,
                Command={
                    "Name": "glueetl",
                    "ScriptLocation": script_location,
                    "PythonVersion": "3",
                },
                DefaultArguments=default_arguments,
                GlueVersion=self.glue_version,
                WorkerType=self.worker_type,
                NumberOfWorkers=self.number_of_workers,
                Timeout=self.job_timeout,
                MaxConcurrentRuns=self.max_concurrent_runs,
                ExecutionProperty={"MaxConcurrentRuns": self.max_concurrent_runs},
            )
            logger.info(f"Created Glue job: {job_name}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "AlreadyExistsException":
                logger.debug(f"Job '{job_name}' already exists")
            else:
                raise

        self._job_name = job_name
        return job_name

    def _upload_job_script(self) -> str:
        """Upload Glue job script to S3.

        Returns:
            S3 path to script.
        """
        script_content = """
import sys
from awsglue.transforms import *
from awsglue.utils import getResolvedOptions
from pyspark.context import SparkContext
from awsglue.context import GlueContext
from awsglue.job import Job
import json

args = getResolvedOptions(sys.argv, ['JOB_NAME', 'database', 'output_path', 'query'])

sc = SparkContext()
glueContext = GlueContext(sc)
spark = glueContext.spark_session
job = Job(glueContext)
job.init(args['JOB_NAME'], args)

# Execute the query
query = args['query']
database = args['database']

# Set database
spark.sql(f"USE {database}")

# Execute query and write results
result_df = spark.sql(query)

# Write results to S3 as JSON
output_path = args['output_path'] + args['JOB_RUN_ID'] + "/"
result_df.write.mode("overwrite").json(output_path)

# Also write row count for validation
row_count = result_df.count()
glueContext.get_logger().info(f"Query returned {row_count} rows")

job.commit()
"""

        script_key = f"{self.s3_prefix}/scripts/benchbox_query_runner.py"
        s3_client = self._get_s3_client()

        s3_client.put_object(
            Bucket=self.s3_bucket,
            Key=script_key,
            Body=script_content.encode("utf-8"),
            ContentType="text/x-python",
        )

        return f"s3://{self.s3_bucket}/{script_key}"

    def _submit_job_run(self, query: str) -> str:
        """Submit a Glue job run.

        Args:
            query: SQL query to execute.

        Returns:
            Job run ID.
        """
        client = self._get_glue_client()

        response = client.start_job_run(
            JobName=self._job_name,
            Arguments={
                "--query": query,
            },
        )

        run_id = response["JobRunId"]
        self._job_runs.append(run_id)
        logger.info(f"Started job run: {run_id}")

        return run_id

    def _wait_for_job(self, run_id: str, poll_interval: int = 10) -> str:
        """Wait for Glue job to complete.

        Args:
            run_id: Job run ID.
            poll_interval: Seconds between status checks.

        Returns:
            Final job status.
        """
        client = self._get_glue_client()
        terminal_states = {
            GlueJobStatus.SUCCEEDED,
            GlueJobStatus.FAILED,
            GlueJobStatus.STOPPED,
            GlueJobStatus.TIMEOUT,
            GlueJobStatus.ERROR,
        }

        while True:
            response = client.get_job_run(JobName=self._job_name, RunId=run_id)
            status = response["JobRun"]["JobRunState"]

            if status in terminal_states:
                # Track DPU usage
                execution_time = response["JobRun"].get("ExecutionTime", 0)
                dpu_hours = (execution_time / 3600) * self.number_of_workers
                self._total_dpu_hours += dpu_hours

                return status

            logger.debug(f"Job {run_id} status: {status}")
            time.sleep(poll_interval)

    def _retrieve_results(self, run_id: str) -> list[dict[str, Any]]:
        """Retrieve query results from S3.

        Args:
            run_id: Job run ID.

        Returns:
            Query results as list of dicts.
        """
        s3_client = self._get_s3_client()
        result_prefix = f"{self.s3_prefix}/results/{run_id}/"

        # List result files
        response = s3_client.list_objects_v2(
            Bucket=self.s3_bucket,
            Prefix=result_prefix,
        )

        results: list[dict[str, Any]] = []

        for obj in response.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".json") and not key.endswith("_SUCCESS"):
                # Read JSON result file
                data = s3_client.get_object(Bucket=self.s3_bucket, Key=key)
                content = data["Body"].read().decode("utf-8")

                # Parse JSON lines format
                for line in content.strip().split("\n"):
                    if line:
                        results.append(json.loads(line))

        return results

    def close(self) -> None:
        """Clean up Glue resources."""
        # Note: We don't delete the job by default to allow result inspection
        logger.info(f"AWS Glue adapter closed. Total DPU-hours: {self._total_dpu_hours:.2f}")

    # -------------------------------------------------------------------------
    # CLI and Configuration Interface
    # -------------------------------------------------------------------------

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add AWS Glue-specific CLI arguments."""
        glue_group = parser.add_argument_group("AWS Glue Arguments")
        glue_group.add_argument("--region", type=str, default="us-east-1", help="AWS region for Glue")
        glue_group.add_argument(
            "--s3-staging-dir",
            type=str,
            help="S3 location for data staging (e.g., s3://bucket/path)",
        )
        glue_group.add_argument(
            "--job-role",
            type=str,
            help="IAM role ARN for Glue job execution",
        )
        glue_group.add_argument("--database", type=str, default="benchbox", help="Glue Data Catalog database")
        glue_group.add_argument(
            "--worker-type",
            type=str,
            default="G.1X",
            choices=["G.025X", "G.1X", "G.2X", "G.4X", "G.8X", "Z.2X"],
            help="Glue worker type",
        )
        glue_group.add_argument(
            "--number-of-workers",
            type=int,
            default=2,
            help="Number of Glue workers",
        )
        glue_group.add_argument(
            "--glue-version",
            type=str,
            default="4.0",
            choices=["3.0", "4.0"],
            help="Glue version",
        )
        glue_group.add_argument("--aws-profile", type=str, help="AWS profile name for credentials")

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> AWSGlueAdapter:
        """Create AWS Glue adapter from unified configuration.

        Args:
            config: Unified configuration dictionary.

        Returns:
            Configured AWSGlueAdapter instance.
        """
        from benchbox.utils.database_naming import generate_database_name

        adapter_config: dict[str, Any] = {}

        # Generate database name using benchmark characteristics
        if "database" in config and config["database"]:
            adapter_config["database"] = config["database"]
        else:
            database_name = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="glue",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database"] = database_name

        # AWS configuration
        for key in ["region", "aws_region", "aws_access_key_id", "aws_secret_access_key", "aws_profile"]:
            if key in config:
                adapter_config[key] = config[key]

        # Glue-specific configuration
        for key in [
            "s3_staging_dir",
            "staging_root",
            "job_role",
            "iam_role",
            "worker_type",
            "number_of_workers",
            "glue_version",
            "job_timeout",
            "execution_mode",
            "spark_conf",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Configure Glue for benchmark execution.

        Args:
            connection: Not used (Glue is job-based, not session-based).
            benchmark_type: Type of benchmark being executed.
        """
        # Glue configuration is applied at job creation time via Spark config
        logger.debug(f"Configuring Glue for {benchmark_type} benchmark")

    # -------------------------------------------------------------------------
    # Platform Information
    # -------------------------------------------------------------------------

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get AWS Glue platform information.

        Args:
            connection: Not used (Glue manages sessions internally).
        """
        return {
            "platform": "aws_glue",
            "display_name": "AWS Glue",
            "dialect": self._dialect,
            "region": self.region,
            "worker_type": self.worker_type,
            "number_of_workers": self.number_of_workers,
            "glue_version": self.glue_version,
            "database": self.database,
            "s3_staging": self.s3_staging_dir,
            "execution_mode": self.execution_mode,
            "supports_sql": True,
            "supports_dataframe": True,
        }

    def get_dialect(self) -> str:
        """Get SQL dialect."""
        return self._dialect

    # -------------------------------------------------------------------------
    # Tuning Interface (Minimal Implementation)
    # -------------------------------------------------------------------------

    # apply_primary_keys, apply_foreign_keys, apply_platform_optimizations,
    # and apply_constraint_configuration are inherited from SparkTuningMixin

    def apply_tuning(self, config: UnifiedTuningConfiguration) -> dict[str, Any]:
        """Apply unified tuning configuration."""
        results: dict[str, Any] = {
            "platform_optimizations": [],
            "primary_keys": [],
            "foreign_keys": [],
        }

        if config.platform:
            results["platform_optimizations"] = self.apply_platform_optimizations(config.platform)

        return results

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for AWS Glue.

        Glue uses Spark SQL for query execution, so we use the Spark dialect.

        Returns:
            The dialect string "spark".
        """
        return "spark"
