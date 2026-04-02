"""AWS Athena platform adapter for serverless query-on-S3 benchmarking.

Athena is AWS's serverless interactive query service that makes it easy to
analyze data directly in S3 using standard SQL. It is essentially managed
Trino, optimized for ad-hoc querying of data lakes.

Key Features:
- Serverless: No infrastructure to manage
- Pay-per-query pricing based on data scanned
- Native integration with AWS Glue Data Catalog
- Support for Parquet, ORC, JSON, CSV formats
- Partition projection for efficient queries

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
        TuningColumn,
        UnifiedTuningConfiguration,
    )

from ..core.exceptions import ConfigurationError
from ..utils.dependencies import (
    check_platform_dependencies,
    get_dependency_error_message,
)
from .base import DriverIsolationCapability, PlatformAdapter
from .base.data_loading import DataSourceResolver, FileFormatRegistry

try:
    import boto3
    from pyathena import connect as athena_connect
except ImportError:
    boto3 = None
    athena_connect = None


class AthenaAdapter(PlatformAdapter):
    """AWS Athena platform adapter for serverless query execution.

    Athena is a serverless query service that runs Trino under the hood.
    It queries data directly from S3 without requiring data movement.

    Key Features:
    - Serverless: scales automatically, no infrastructure to manage
    - Pay-per-query: charged based on data scanned (currently $5 per TB)
    - Native S3 integration with optimized data formats
    - AWS Glue Data Catalog for metadata management
    - Workgroup-based resource management and cost controls
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True

    def __init__(self, **config):
        super().__init__(**config)

        # Check dependencies
        if not boto3 or not athena_connect:
            available, missing = check_platform_dependencies("athena")
            if not available:
                error_msg = get_dependency_error_message("athena", missing)
                raise ImportError(error_msg)

        self._dialect = "trino"  # Athena uses Trino SQL syntax

        # AWS configuration
        self.region = config.get("region") or config.get("aws_region") or "us-east-1"
        self.aws_access_key_id = config.get("aws_access_key_id")
        self.aws_secret_access_key = config.get("aws_secret_access_key")
        self.aws_profile = config.get("aws_profile")

        # Athena configuration
        self.workgroup = config.get("workgroup") or "primary"
        self.database = config.get("database") or "default"
        self.catalog = config.get("catalog") or "AwsDataCatalog"

        # S3 configuration for query results and data staging
        self.s3_output_location = config.get("s3_output_location")
        self.s3_staging_dir = config.get("s3_staging_dir") or config.get("staging_root")

        # Extract bucket and prefix from staging_root
        if self.s3_staging_dir and self.s3_staging_dir.startswith("s3://"):
            parts = self.s3_staging_dir[5:].split("/", 1)
            self.s3_bucket = parts[0]
            # Strip trailing slashes to avoid double-slash in path construction
            self.s3_prefix = parts[1].rstrip("/") if len(parts) > 1 else "benchbox-data"
        else:
            self.s3_bucket = config.get("s3_bucket")
            # Strip trailing slashes from user-provided prefix
            prefix = config.get("s3_prefix") or "benchbox-data"
            self.s3_prefix = prefix.rstrip("/") if prefix else "benchbox-data"

        # If no output location specified, use staging dir
        if not self.s3_output_location and self.s3_bucket:
            self.s3_output_location = f"s3://{self.s3_bucket}/athena-results/"

        # Query settings
        self.query_timeout = config.get("query_timeout") if config.get("query_timeout") is not None else 0
        self.encryption = config.get("encryption")  # SSE-S3, SSE-KMS

        # Data format preferences (for table creation)
        # data_format controls the final table format:
        #   - "parquet" (default): Upload text to staging, CTAS convert to Parquet (fast queries)
        #   - "text": Direct text tables (slower queries, useful for debugging)
        self.data_format = (config.get("data_format") or "parquet").lower()
        self.default_format = config.get("default_format") or "PARQUET"
        self.compression = config.get("compression") or "SNAPPY"
        self.cleanup_staging = config.get("cleanup_staging", True)  # Cleanup staging after CTAS

        # Cost tracking
        self._total_data_scanned_bytes = 0
        self._query_count = 0

        # S3 client for data operations
        self._s3_client = None

        # Validate configuration
        self._validate_configuration()

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Build opt-in sorted-ingestion SQL for Athena."""
        mode, method = self.resolve_sorted_ingestion_strategy()
        if mode == "off":
            return None

        if method != "ctas":
            raise ValueError(f"Sorted ingestion method '{method}' is not supported for Athena.")

        order_by = ", ".join(column.name for column in sort_columns)
        return f"CREATE TABLE {table_name} AS SELECT * FROM {table_name} ORDER BY {order_by}"

    def _validate_configuration(self) -> None:
        """Validate Athena configuration and provide actionable error messages.

        Validates:
        - S3 output/staging location format
        - AWS credentials presence (environment or profile)
        - Workgroup format
        """
        import os
        import re

        errors = []

        # Validate S3 paths
        s3_path_pattern = re.compile(r"^s3://[a-z0-9][a-z0-9.-]{1,61}[a-z0-9](?:/.*)?$")

        if self.s3_output_location and not s3_path_pattern.match(self.s3_output_location):
            errors.append(
                f"Invalid S3 output location format: '{self.s3_output_location}'\n"
                "  Expected format: s3://bucket-name/optional/path/\n"
                "  Example: s3://my-athena-results/benchbox/"
            )

        if self.s3_staging_dir and not s3_path_pattern.match(self.s3_staging_dir):
            errors.append(
                f"Invalid S3 staging directory format: '{self.s3_staging_dir}'\n"
                "  Expected format: s3://bucket-name/optional/path/\n"
                "  Example: s3://my-data-bucket/benchbox-staging/"
            )

        # Check for missing S3 configuration (required for data operations)
        if not self.s3_bucket and not self.s3_staging_dir:
            errors.append(
                "No S3 location configured. Athena requires S3 for data storage.\n"
                "  Configure via one of:\n"
                "    --platform-option s3_staging_dir=s3://bucket/path/\n"
                "    --platform-option s3_bucket=bucket-name\n"
                "    Environment: ATHENA_S3_STAGING_DIR=s3://bucket/path/"
            )

        # Check for AWS credentials
        has_explicit_creds = bool(self.aws_access_key_id and self.aws_secret_access_key)
        has_profile = bool(self.aws_profile)
        has_env_creds = bool(os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"))
        has_default_profile = os.path.exists(os.path.expanduser("~/.aws/credentials"))
        has_instance_role = self._check_instance_metadata_available()

        if not any([has_explicit_creds, has_profile, has_env_creds, has_default_profile, has_instance_role]):
            errors.append(
                "No AWS credentials found. Athena requires AWS authentication.\n"
                "  Configure via one of:\n"
                "    1. AWS CLI: aws configure\n"
                "    2. Environment variables: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY\n"
                "    3. Profile: --platform-option aws_profile=your-profile\n"
                "    4. IAM role (when running on AWS EC2/ECS/Lambda)"
            )

        # Validate workgroup format
        if self.workgroup:
            workgroup_pattern = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,127}$")
            if not workgroup_pattern.match(self.workgroup):
                errors.append(
                    f"Invalid workgroup name: '{self.workgroup}'\n"
                    "  Workgroup must start with a letter, contain only letters, numbers,\n"
                    "  underscores, and hyphens, and be 1-128 characters.\n"
                    "  Example: primary, analytics-team, prod_benchmarks"
                )

        # Validate region format
        if self.region:
            region_pattern = re.compile(r"^[a-z]{2}-[a-z]+-\d$")
            if not region_pattern.match(self.region):
                errors.append(
                    f"Invalid AWS region format: '{self.region}'\n"
                    "  Expected format: xx-xxxx-N (e.g., us-east-1, eu-west-2)\n"
                    "  Common regions: us-east-1, us-west-2, eu-west-1, ap-southeast-1"
                )

        if errors:
            error_message = "Athena configuration validation failed:\n\n" + "\n\n".join(errors)
            raise ConfigurationError(
                error_message,
                details={
                    "platform": "athena",
                    "region": self.region,
                    "workgroup": self.workgroup,
                    "s3_bucket": self.s3_bucket,
                    "validation_errors": len(errors),
                },
            )

    def _check_instance_metadata_available(self) -> bool:
        """Check if running on AWS with instance metadata (IAM role).

        This is a quick non-blocking check to see if we might be running
        on an EC2 instance or ECS task with an IAM role.
        """
        import socket

        try:
            # Quick check for instance metadata endpoint
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.1)  # Very short timeout
            result = sock.connect_ex(("169.254.169.254", 80))
            sock.close()
            return result == 0
        except Exception:
            return False

    @property
    def platform_name(self) -> str:
        return "Athena"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Athena-specific CLI arguments."""
        athena_group = parser.add_argument_group("Athena Arguments")
        athena_group.add_argument("--region", type=str, default="us-east-1", help="AWS region for Athena")
        athena_group.add_argument("--workgroup", type=str, default="primary", help="Athena workgroup")
        athena_group.add_argument("--database", type=str, default="default", help="Athena database/schema")
        athena_group.add_argument("--s3-output-location", type=str, help="S3 location for query results")
        athena_group.add_argument("--s3-staging-dir", type=str, help="S3 location for data staging")
        athena_group.add_argument("--aws-profile", type=str, help="AWS profile name for credentials")

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Athena adapter from unified configuration."""
        from benchbox.utils.database_naming import generate_database_name

        adapter_config: dict[str, Any] = {}

        # Generate database name using benchmark characteristics
        if "database" in config and config["database"]:
            adapter_config["database"] = config["database"]
        else:
            database_name = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform="athena",
                tuning_config=config.get("tuning_config"),
            )
            adapter_config["database"] = database_name

        # AWS configuration
        for key in ["region", "aws_region", "aws_access_key_id", "aws_secret_access_key", "aws_profile"]:
            if key in config:
                adapter_config[key] = config[key]

        # Athena-specific configuration
        for key in [
            "workgroup",
            "catalog",
            "s3_output_location",
            "s3_staging_dir",
            "staging_root",
            "s3_bucket",
            "s3_prefix",
            "query_timeout",
            "encryption",
            "data_format",
            "default_format",
            "compression",
            "cleanup_staging",
        ]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def _get_s3_client(self):
        """Get or create S3 client."""
        if self._s3_client is None:
            session_kwargs = {}
            if self.aws_profile:
                session_kwargs["profile_name"] = self.aws_profile
            if self.region:
                session_kwargs["region_name"] = self.region

            session = boto3.Session(**session_kwargs)

            client_kwargs = {}
            if self.aws_access_key_id and self.aws_secret_access_key:
                client_kwargs["aws_access_key_id"] = self.aws_access_key_id
                client_kwargs["aws_secret_access_key"] = self.aws_secret_access_key

            self._s3_client = session.client("s3", **client_kwargs)

        return self._s3_client

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Athena platform information."""
        platform_info = {
            "platform_type": "athena",
            "platform_name": "AWS Athena",
            "connection_mode": "serverless",
            "configuration": {
                "region": self.region,
                "workgroup": self.workgroup,
                "database": self.database,
                "catalog": self.catalog,
                "s3_output_location": self.s3_output_location,
                "data_format": self.data_format,
                "compression": self.compression,
                "cleanup_staging": self.cleanup_staging,
            },
        }

        # Try to get Athena version from workgroup settings
        if connection:
            try:
                cursor = connection.cursor()
                cursor.execute("SELECT version()")
                result = cursor.fetchone()
                if result:
                    platform_info["platform_version"] = result[0]
                cursor.close()
            except Exception as e:
                self.logger.debug(f"Could not get Athena version: {e}")
                platform_info["platform_version"] = "Athena (version unknown)"
        else:
            platform_info["platform_version"] = None

        # Get pyathena version
        try:
            import pyathena

            platform_info["client_library_version"] = pyathena.__version__
        except Exception:
            platform_info["client_library_version"] = None

        return platform_info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Athena."""
        return "trino"  # Athena uses Trino SQL syntax

    def check_server_database_exists(self, **connection_config) -> bool:
        """Check if database exists in Athena/Glue catalog."""
        try:
            database = connection_config.get("database", self.database)

            # Use Glue client to check database
            session_kwargs = {}
            if self.aws_profile:
                session_kwargs["profile_name"] = self.aws_profile
            if self.region:
                session_kwargs["region_name"] = self.region

            session = boto3.Session(**session_kwargs)
            glue_client = session.client("glue")

            try:
                glue_client.get_database(Name=database)
                return True
            except glue_client.exceptions.EntityNotFoundException:
                return False

        except Exception as e:
            self.logger.debug(f"Error checking database existence: {e}")
            return False

    def drop_database(self, **connection_config) -> None:
        """Drop database from Athena/Glue catalog."""
        database = connection_config.get("database", self.database)

        if not self.check_server_database_exists(database=database):
            self.log_verbose(f"Database {database} does not exist - nothing to drop")
            return

        try:
            session_kwargs = {}
            if self.aws_profile:
                session_kwargs["profile_name"] = self.aws_profile
            if self.region:
                session_kwargs["region_name"] = self.region

            session = boto3.Session(**session_kwargs)
            glue_client = session.client("glue")

            # Get and delete all tables first
            paginator = glue_client.get_paginator("get_tables")
            for page in paginator.paginate(DatabaseName=database):
                for table in page.get("TableList", []):
                    table_name = table["Name"]
                    self.logger.debug(f"Deleting table {database}.{table_name}")
                    glue_client.delete_table(DatabaseName=database, Name=table_name)

            # Delete the database
            glue_client.delete_database(Name=database)
            self.logger.info(f"Dropped database {database}")

        except Exception as e:
            raise RuntimeError(f"Failed to drop Athena database {database}: {e}") from e

    def create_connection(self, **connection_config) -> Any:
        """Create Athena connection via pyathena."""
        self.log_operation_start("Athena connection")

        # Handle existing database
        self.handle_existing_database(**connection_config)

        # Build connection parameters
        connect_kwargs: dict[str, Any] = {
            "s3_staging_dir": self.s3_output_location,
            "region_name": self.region,
            "work_group": self.workgroup,
            "catalog_name": self.catalog,
            "schema_name": connection_config.get("database", self.database),
        }

        # AWS credentials
        if self.aws_access_key_id and self.aws_secret_access_key:
            connect_kwargs["aws_access_key_id"] = self.aws_access_key_id
            connect_kwargs["aws_secret_access_key"] = self.aws_secret_access_key
        elif self.aws_profile:
            connect_kwargs["profile_name"] = self.aws_profile

        target_database = connect_kwargs["schema_name"]

        # Create database if needed
        if not self.database_was_reused and not self.check_server_database_exists(database=target_database):
            self.log_verbose(f"Creating database: {target_database}")
            self._create_database(target_database)

        try:
            connection = athena_connect(**connect_kwargs)

            # Test connection
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()

            self.logger.info(f"Connected to Athena in {self.region}")
            self.log_operation_complete("Athena connection", details=f"Database: {target_database}")

            return connection

        except Exception as e:
            self.logger.error(f"Failed to connect to Athena: {e}")
            raise

    def _create_database(self, database_name: str) -> None:
        """Create database in Glue Data Catalog."""
        try:
            session_kwargs = {}
            if self.aws_profile:
                session_kwargs["profile_name"] = self.aws_profile
            if self.region:
                session_kwargs["region_name"] = self.region

            session = boto3.Session(**session_kwargs)
            glue_client = session.client("glue")

            # Set location for database
            location_uri = f"s3://{self.s3_bucket}/{self.s3_prefix}/databases/{database_name}/"

            glue_client.create_database(
                DatabaseInput={
                    "Name": database_name,
                    "Description": "BenchBox benchmark database",
                    "LocationUri": location_uri,
                }
            )
            self.logger.info(f"Created database {database_name}")

        except Exception as e:
            if "AlreadyExistsException" in str(type(e).__name__):
                self.logger.debug(f"Database {database_name} already exists")
            else:
                raise RuntimeError(f"Failed to create database {database_name}: {e}") from e

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using Athena external table definitions.

        In parquet mode (default):
        - Creates staging tables with _staging suffix for text file upload
        - Final parquet tables are created via CTAS in load_data()

        In text mode:
        - Creates tables directly pointing to text file locations
        """
        start_time = mono_time()
        cursor = connection.cursor()

        try:
            # Get schema SQL using common helper with Trino dialect
            schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")

            # Split and execute statements
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                if not statement:
                    continue

                # Normalize to lowercase table names
                statement = self._normalize_table_name_in_sql(statement)

                if self.data_format == "parquet":
                    # In parquet mode, create staging tables for text file upload
                    # Final parquet tables will be created via CTAS after data load
                    staging_statement = self._convert_to_external_table(statement, is_staging=True)
                    try:
                        cursor.execute(staging_statement)
                        self.logger.debug(f"Created staging table: {staging_statement[:100]}...")
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            table_name = self._extract_table_name(staging_statement)
                            if table_name:
                                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                                cursor.execute(staging_statement)
                        else:
                            raise
                else:
                    # In text mode, create tables directly pointing to text files
                    statement = self._convert_to_external_table(statement, is_staging=False)
                    try:
                        cursor.execute(statement)
                        self.logger.debug(f"Executed: {statement[:100]}...")
                    except Exception as e:
                        if "already exists" in str(e).lower():
                            table_name = self._extract_table_name(statement)
                            if table_name:
                                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")
                                cursor.execute(statement)
                        else:
                            raise

            mode_desc = "staging tables (parquet mode)" if self.data_format == "parquet" else "text tables"
            self.logger.info(f"Schema created ({mode_desc})")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise
        finally:
            cursor.close()

        return elapsed_seconds(start_time)

    def _convert_to_external_table(self, statement: str, is_staging: bool = False) -> str:
        """Convert CREATE TABLE to CREATE EXTERNAL TABLE for Athena.

        Athena external tables require:
        1. CREATE EXTERNAL TABLE syntax (Hive DDL)
        2. ROW FORMAT specification for delimited files (CSV, TBL)
        3. STORED AS clause for file format
        4. LOCATION pointing to S3 path
        5. No NOT NULL constraints (Hive DDL doesn't support them)
        6. Hive-compatible types (VARCHAR without length -> STRING)

        For TPC-H/TPC-DS pipe-delimited files (.tbl), we use LazySimpleSerDe
        with the pipe character as field delimiter.

        Args:
            statement: The CREATE TABLE SQL statement
            is_staging: If True, creates a staging table for text files (used in parquet mode)
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        import re

        # Convert types to Hive DDL compatible types
        # Hive DDL for external tables doesn't support VARCHAR(n) - use STRING instead
        statement = re.sub(r"VARCHAR\s*\(\s*\d+\s*\)", "STRING", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\bVARCHAR\b", "STRING", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\bCHAR\s*\(\s*\d+\s*\)", "STRING", statement, flags=re.IGNORECASE)

        # Extract table name
        table_match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)", statement, re.IGNORECASE)
        if not table_match:
            return statement

        table_name = table_match.group(1).lower()

        # For parquet mode, staging tables get _staging suffix
        if is_staging:
            staging_table_name = f"{table_name}_staging"
            statement = re.sub(
                r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
                f"CREATE EXTERNAL TABLE IF NOT EXISTS {staging_table_name}",
                statement,
                count=1,
                flags=re.IGNORECASE,
            )
            # Staging tables always point to staging location with text files
            location = f"s3://{self.s3_bucket}/{self.s3_prefix}/{self.database}_staging/{table_name}/"
            storage_clause = (
                f"\nROW FORMAT DELIMITED"
                f"\n  FIELDS TERMINATED BY '|'"
                f"\n  LINES TERMINATED BY '\\n'"
                f"\nSTORED AS TEXTFILE"
                f"\nLOCATION '{location}'"
            )
        else:
            # Convert to EXTERNAL TABLE
            statement = re.sub(
                r"CREATE\s+TABLE",
                "CREATE EXTERNAL TABLE",
                statement,
                count=1,
                flags=re.IGNORECASE,
            )

            # Ensure IF NOT EXISTS is present
            if "IF NOT EXISTS" not in statement.upper():
                statement = statement.replace("EXTERNAL TABLE", "EXTERNAL TABLE IF NOT EXISTS", 1)

            # Build storage clause based on format
            location = f"s3://{self.s3_bucket}/{self.s3_prefix}/{self.database}/{table_name}/"

            if self.data_format == "parquet" or self.default_format.upper() == "PARQUET":
                storage_clause = f"\nSTORED AS PARQUET\nLOCATION '{location}'"
            elif self.default_format.upper() in ("CSV", "TEXTFILE"):
                # For CSV files, use LazySimpleSerDe with comma delimiter
                storage_clause = (
                    f"\nROW FORMAT DELIMITED"
                    f"\n  FIELDS TERMINATED BY ','"
                    f"\n  LINES TERMINATED BY '\\n'"
                    f"\nSTORED AS TEXTFILE"
                    f"\nLOCATION '{location}'"
                )
            else:
                # Default: TBL/DAT files (TPC-H/TPC-DS) use pipe delimiter
                storage_clause = (
                    f"\nROW FORMAT DELIMITED"
                    f"\n  FIELDS TERMINATED BY '|'"
                    f"\n  LINES TERMINATED BY '\\n'"
                    f"\nSTORED AS TEXTFILE"
                    f"\nLOCATION '{location}'"
                    f"\nTBLPROPERTIES ('skip.header.line.count'='0')"
                )

        # Remove NOT NULL constraints - Athena/Hive DDL doesn't support them for external tables
        statement = re.sub(r"\s+NOT\s+NULL", "", statement, flags=re.IGNORECASE)

        # Remove any existing WITH clause
        statement = re.sub(r"\s+WITH\s*\([^)]*\)", "", statement, flags=re.IGNORECASE)

        # Append storage clause after column definitions
        if statement.rstrip().endswith(")"):
            statement = statement.rstrip() + storage_clause
        else:
            statement = statement + storage_clause

        return statement

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data to S3 and optionally convert to Parquet via CTAS.

        In parquet mode (default):
        1. Upload text files to S3 staging location
        2. Use CTAS to convert staging tables to Parquet (100x less data scanned)
        3. Optionally cleanup staging tables and S3 data

        In text mode:
        1. Upload data files to S3 at the table's LOCATION
        2. Run MSCK REPAIR TABLE to discover new partitions
        3. Verify row counts via SELECT COUNT(*)
        """
        start_time = mono_time()
        table_stats = {}
        total_time = 0.0

        # Validate S3 bucket is configured
        if not self.s3_bucket:
            raise ValueError(
                "S3 bucket not configured. Athena requires S3 for data storage.\n"
                "Configure via: --platform-option s3_bucket=your-bucket\n"
                "Or set staging_root: s3://your-bucket/path"
            )

        s3_client = self._get_s3_client()
        cursor = connection.cursor()

        try:
            data_files = self._resolve_data_files(benchmark, data_dir)

            # Determine S3 path based on mode
            # In parquet mode, upload to staging location; otherwise, upload to final location
            is_parquet_mode = self.data_format == "parquet"

            # Track tables for CTAS conversion
            tables_to_convert = []
            effective_tuning = self.get_effective_tuning_configuration()

            # Upload data to S3 for each table
            for table_name, file_paths in data_files.items():
                table_name_lower = table_name.lower()
                uploaded_rows, file_count = self._upload_files_to_s3(
                    s3_client=s3_client,
                    table_name=table_name,
                    table_name_lower=table_name_lower,
                    file_paths=file_paths,
                    is_parquet_mode=is_parquet_mode,
                )
                chunk_info = f" from {file_count} file(s)" if file_count > 1 else ""
                self.log_verbose(f"Uploading data for table: {table_name}{chunk_info}")

                if is_parquet_mode:
                    # Track for CTAS conversion
                    tables_to_convert.append((table_name_lower, uploaded_rows))
                    self.logger.info(f"📤 Uploaded {uploaded_rows:,} rows to staging for {table_name_lower}")
                else:
                    row_count, count_verified = self._load_text_mode_table(
                        cursor=cursor,
                        table_name_lower=table_name_lower,
                        uploaded_rows=uploaded_rows,
                    )
                    table_stats[table_name_lower] = row_count
                    if count_verified and effective_tuning is not None:
                        self.apply_ctas_sort(table_name_lower, effective_tuning, connection)

                    self.logger.info(
                        f"✅ Loaded {table_stats[table_name_lower]:,} rows into {table_name_lower}{chunk_info}"
                    )

            # In parquet mode, convert staging tables to Parquet using CTAS
            if is_parquet_mode and tables_to_convert:
                self.logger.info("🔄 Converting staging tables to Parquet format...")
                table_stats = self._convert_staging_to_parquet(cursor, tables_to_convert, s3_client)
                if effective_tuning is not None:
                    for table_name_lower in table_stats:
                        self.apply_ctas_sort(table_name_lower, effective_tuning, connection)

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            mode_desc = "Parquet" if is_parquet_mode else "text"
            self.logger.info(f"✅ Loaded {total_rows:,} total rows ({mode_desc} format) in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"Data loading failed: {e}")
            raise
        finally:
            cursor.close()

        return table_stats, total_time, None

    def validate_external_table_requirements(self) -> None:
        """Validate required S3 configuration for external table mode."""
        if not self.s3_bucket:
            raise ValueError(
                "Athena external mode requires S3 bucket configuration. "
                "Set --platform-option s3_bucket=your-bucket or "
                "--platform-option staging_root=s3://your-bucket/path."
            )

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Upload Parquet files and register Athena external tables without CTAS conversion."""
        self.validate_external_table_requirements()
        start_time = mono_time()
        table_stats: dict[str, int] = {}

        s3_client = self._get_s3_client()
        cursor = connection.cursor()
        try:
            data_files = self._resolve_data_files(benchmark, data_dir)
            external_table_sql = self._build_external_table_statements(benchmark)

            for table_name, file_paths in data_files.items():
                table_name_lower = table_name.lower()
                parquet_files = self._normalize_parquet_files(file_paths)
                if not parquet_files:
                    raise ValueError(
                        f"Athena external mode requires Parquet source files for table '{table_name_lower}'. "
                        "Generate or convert data to Parquet before using --table-mode external."
                    )

                self._upload_external_parquet_files_to_s3(s3_client, table_name_lower, parquet_files)

                create_table_sql = external_table_sql.get(table_name_lower)
                if not create_table_sql:
                    raise ValueError(f"No CREATE TABLE statement found for table '{table_name_lower}'")

                try:
                    cursor.execute(create_table_sql)
                except Exception as exc:
                    if "already exists" in str(exc).lower():
                        cursor.execute(f"DROP TABLE IF EXISTS {table_name_lower}")
                        cursor.execute(create_table_sql)
                    else:
                        raise

                cursor.execute(f"SELECT COUNT(*) FROM {table_name_lower}")
                result = cursor.fetchone()
                table_stats[table_name_lower] = int(result[0]) if result else 0

        finally:
            cursor.close()

        total_time = elapsed_seconds(start_time)
        return table_stats, total_time, None

    def _normalize_parquet_files(self, file_paths: Any) -> list[Path]:
        """Normalize file inputs to existing local Parquet files."""
        valid_files = self._normalize_existing_files(file_paths)
        return [path for path in valid_files if path.suffix.lower() == ".parquet"]

    def _upload_external_parquet_files_to_s3(
        self,
        s3_client: Any,
        table_name_lower: str,
        parquet_files: list[Path],
    ) -> None:
        """Upload Parquet files to the external table S3 prefix."""
        s3_table_path = f"{self.s3_prefix}/{self.database}/{table_name_lower}/"
        for file_path in parquet_files:
            s3_key = f"{s3_table_path}{file_path.name}"
            try:
                s3_client.upload_file(str(file_path), self.s3_bucket, s3_key)
                self.logger.debug(f"Uploaded {file_path.name} to s3://{self.s3_bucket}/{s3_key}")
            except Exception as exc:
                self.logger.error(f"Failed to upload {file_path}: {exc}")
                raise

    def _build_external_table_statements(self, benchmark: Any) -> dict[str, str]:
        """Build CREATE EXTERNAL TABLE SQL statements keyed by normalized table name."""
        schema_sql = self._create_schema_with_tuning(benchmark, source_dialect="duckdb")
        statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
        table_sql: dict[str, str] = {}

        for statement in statements:
            normalized = self._normalize_table_name_in_sql(statement)
            table_name = self._extract_table_name(normalized)
            if not table_name:
                continue
            table_sql[table_name.lower()] = self._convert_to_external_table(normalized, is_staging=False)

        return table_sql

    def _resolve_data_files(self, benchmark: Any, data_dir: Path) -> dict[str, Any]:
        """Resolve benchmark data files from benchmark tables or manifest."""
        resolver = DataSourceResolver()
        data_source = resolver.resolve(benchmark, data_dir)
        if not data_source or not data_source.tables:
            raise ValueError("No data files found")
        return data_source.tables

    @staticmethod
    def _normalize_existing_files(file_paths: Any) -> list[Path]:
        """Normalize file inputs to existing, non-empty local paths."""
        normalized_paths = file_paths if isinstance(file_paths, list) else [file_paths]
        valid_files: list[Path] = []
        for file_path in normalized_paths:
            path = Path(file_path)
            if path.exists() and path.stat().st_size > 0:
                valid_files.append(path)
        return valid_files

    def _build_s3_table_path(self, table_name_lower: str, is_parquet_mode: bool) -> str:
        """Build the destination S3 prefix for a table load."""
        if is_parquet_mode:
            return f"{self.s3_prefix}/{self.database}_staging/{table_name_lower}/"
        return f"{self.s3_prefix}/{self.database}/{table_name_lower}/"

    def _upload_files_to_s3(
        self,
        s3_client: Any,
        table_name: str,
        table_name_lower: str,
        file_paths: Any,
        is_parquet_mode: bool,
    ) -> tuple[int, int]:
        """Upload table files to S3 and return (uploaded_rows, file_count)."""
        valid_files = self._normalize_existing_files(file_paths)
        file_count = len(valid_files)
        s3_table_path = self._build_s3_table_path(table_name_lower, is_parquet_mode)
        uploaded_rows = 0

        for file_path in valid_files:
            s3_key = f"{s3_table_path}{file_path.name}"
            try:
                s3_client.upload_file(str(file_path), self.s3_bucket, s3_key)

                compression_handler = FileFormatRegistry.get_compression_handler(file_path)
                with compression_handler.open(file_path) as file_handle:
                    uploaded_rows += sum(1 for line in file_handle if line.strip())

                self.logger.debug(f"Uploaded {file_path.name} to s3://{self.s3_bucket}/{s3_key}")
            except Exception as e:
                self.logger.error(f"Failed to upload {file_path}: {e}")
                raise

        return uploaded_rows, file_count

    def _load_text_mode_table(self, cursor: Any, table_name_lower: str, uploaded_rows: int) -> tuple[int, bool]:
        """Load one table in text mode and return (row_count, count_verified).

        The second element indicates whether SELECT COUNT(*) succeeded,
        which determines whether post-load operations like CTAS sort
        should proceed.
        """
        try:
            cursor.execute(f"MSCK REPAIR TABLE {table_name_lower}")
            self.logger.debug(f"Repaired table {table_name_lower}")
        except Exception as e:
            self.logger.debug(f"MSCK REPAIR for {table_name_lower}: {e}")

        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table_name_lower}")
            result = cursor.fetchone()
            actual_row_count = result[0] if result else 0
            if actual_row_count != uploaded_rows:
                self.logger.warning(
                    f"Row count mismatch for {table_name_lower}: "
                    f"uploaded {uploaded_rows:,}, table has {actual_row_count:,}"
                )
            return actual_row_count, True
        except Exception as e:
            self.logger.warning(f"Could not verify row count for {table_name_lower}: {e}")
            return uploaded_rows, False

    def _convert_staging_to_parquet(
        self,
        cursor: Any,
        tables_to_convert: list[tuple[str, int]],
        s3_client: Any,
    ) -> dict[str, int]:
        """Convert staging text tables to Parquet using CTAS.

        This provides ~100x reduction in data scanned for analytical queries.

        Args:
            cursor: Active database cursor
            tables_to_convert: List of (table_name, expected_rows) tuples
            s3_client: S3 client for cleanup operations

        Returns:
            Dict mapping table names to row counts
        """
        table_stats = {}

        for table_name, expected_rows in tables_to_convert:
            staging_table = f"{table_name}_staging"
            parquet_location = f"s3://{self.s3_bucket}/{self.s3_prefix}/{self.database}/{table_name}/"

            try:
                # Drop existing parquet table if exists
                cursor.execute(f"DROP TABLE IF EXISTS {table_name}")

                # CTAS to convert staging table to Parquet
                # Athena CTAS defaults to Parquet format, with SNAPPY compression
                ctas_sql = f"""
                CREATE TABLE {table_name}
                WITH (
                    format = 'PARQUET',
                    external_location = '{parquet_location}',
                    parquet_compression = '{self.compression}'
                )
                AS SELECT * FROM {staging_table}
                """
                self.logger.debug(f"Executing CTAS for {table_name}")
                cursor.execute(ctas_sql)

                # Verify row count
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                result = cursor.fetchone()
                actual_row_count = result[0] if result else 0
                table_stats[table_name] = actual_row_count

                if actual_row_count != expected_rows:
                    self.logger.warning(
                        f"Row count mismatch for {table_name}: expected {expected_rows:,}, got {actual_row_count:,}"
                    )

                self.logger.info(f"✅ Converted {table_name} to Parquet ({actual_row_count:,} rows)")

                # Cleanup staging table and S3 data if configured
                if self.cleanup_staging:
                    self._cleanup_staging(cursor, s3_client, table_name, staging_table)

            except Exception as e:
                self.logger.error(f"Failed to convert {table_name} to Parquet: {e}")
                # Fall back to staging table row count
                table_stats[table_name] = expected_rows
                raise

        return table_stats

    def _cleanup_staging(
        self,
        cursor: Any,
        s3_client: Any,
        table_name: str,
        staging_table: str,
    ) -> None:
        """Clean up staging table and S3 data after CTAS conversion.

        Args:
            cursor: Active database cursor
            s3_client: S3 client for S3 cleanup
            table_name: Original table name
            staging_table: Staging table name to drop
        """
        try:
            # Drop staging table from Glue catalog
            cursor.execute(f"DROP TABLE IF EXISTS {staging_table}")
            self.logger.debug(f"Dropped staging table {staging_table}")

            # Delete staging S3 data
            staging_prefix = f"{self.s3_prefix}/{self.database}_staging/{table_name}/"
            paginator = s3_client.get_paginator("list_objects_v2")

            objects_to_delete = []
            for page in paginator.paginate(Bucket=self.s3_bucket, Prefix=staging_prefix):
                for obj in page.get("Contents", []):
                    objects_to_delete.append({"Key": obj["Key"]})

            if objects_to_delete:
                # Delete in batches of 1000 (S3 limit)
                for i in range(0, len(objects_to_delete), 1000):
                    batch = objects_to_delete[i : i + 1000]
                    s3_client.delete_objects(Bucket=self.s3_bucket, Delete={"Objects": batch})
                self.logger.debug(f"Deleted {len(objects_to_delete)} staging files for {table_name}")

        except Exception as e:
            self.logger.warning(f"Failed to cleanup staging for {table_name}: {e}")

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        """Configure Athena for benchmark execution."""
        # Athena is serverless - configuration is per-query via workgroup settings
        self.log_verbose(f"Configuring Athena for {benchmark_type} benchmark")

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
        """Execute query with cost tracking."""
        start_time = mono_time()
        cursor = connection.cursor()

        try:
            cursor.execute(query)
            result = cursor.fetchall()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

            # Track data scanned for cost calculation
            data_scanned_bytes = 0
            query_execution_id = None

            if hasattr(cursor, "query_id"):
                query_execution_id = cursor.query_id

            if hasattr(cursor, "data_scanned_in_bytes"):
                data_scanned_bytes = cursor.data_scanned_in_bytes or 0
                self._total_data_scanned_bytes += data_scanned_bytes

            self._query_count += 1

            # Validate row count
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

            # Calculate query cost (Athena charges $5 per TB scanned)
            cost_per_tb = 5.0
            cost = (data_scanned_bytes / (1024**4)) * cost_per_tb

            # Build result dict
            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=result[0] if result else None,
                validation_result=validation_result,
            )

            # Add Athena-specific fields
            result_dict["data_scanned_bytes"] = data_scanned_bytes
            result_dict["cost"] = cost
            result_dict["query_execution_id"] = query_execution_id
            result_dict["resource_usage"] = {
                "data_scanned_bytes": data_scanned_bytes,
                "cost_usd": cost,
            }

            return result_dict

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            cursor.close()

    def get_cost_summary(self) -> dict[str, Any]:
        """Get cost summary for the benchmark run."""
        cost_per_tb = 5.0
        total_cost = (self._total_data_scanned_bytes / (1024**4)) * cost_per_tb

        return {
            "total_data_scanned_bytes": self._total_data_scanned_bytes,
            "total_data_scanned_tb": self._total_data_scanned_bytes / (1024**4),
            "query_count": self._query_count,
            "cost_per_tb_usd": cost_per_tb,
            "total_cost_usd": total_cost,
            "average_cost_per_query_usd": total_cost / max(self._query_count, 1),
        }

    def _extract_table_name(self, statement: str) -> str | None:
        """Extract table name from CREATE TABLE statement."""
        import re

        match = re.search(
            r"CREATE\s+(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)",
            statement,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip().lower()
        return None

    def _normalize_table_name_in_sql(self, sql: str) -> str:
        """Normalize table names to lowercase in CREATE TABLE statements."""
        return normalize_table_name_in_sql(sql)

    def get_query_plan(self, connection: Any, query: str) -> str:
        """Get query execution plan."""
        from benchbox.platforms.base.sql_execution import get_query_plan_from_cursor

        return get_query_plan_from_cursor(connection, query)

    def close_connection(self, connection: Any) -> None:
        """Close Athena connection."""
        try:
            if connection and hasattr(connection, "close"):
                connection.close()
        except Exception as e:
            self.logger.warning(f"Error closing connection: {e}")

    def test_connection(self) -> bool:
        """Test connection to Athena.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            connect_kwargs: dict[str, Any] = {
                "s3_staging_dir": self.s3_output_location,
                "region_name": self.region,
                "work_group": self.workgroup,
                "catalog_name": self.catalog,
                "schema_name": "default",  # Use default for test
            }

            # AWS credentials
            if self.aws_access_key_id and self.aws_secret_access_key:
                connect_kwargs["aws_access_key_id"] = self.aws_access_key_id
                connect_kwargs["aws_secret_access_key"] = self.aws_secret_access_key
            elif self.aws_profile:
                connect_kwargs["profile_name"] = self.aws_profile

            conn = athena_connect(**connect_kwargs)
            cursor = conn.cursor()

            try:
                cursor.execute("SELECT 1")
                cursor.fetchone()
                return True
            finally:
                cursor.close()
                conn.close()
        except Exception as e:
            self.logger.debug(f"Connection test failed: {e}")
            return False

    def supports_tuning_type(self, tuning_type) -> bool:
        """Check if Athena supports a specific tuning type."""
        try:
            from benchbox.core.tuning.interface import TuningType

            return tuning_type in {
                TuningType.PARTITIONING,
            }
        except ImportError:
            return False

    def generate_tuning_clause(self, table_tuning) -> str:
        """Generate Athena-specific tuning clauses."""
        if not table_tuning or not table_tuning.has_any_tuning():
            return ""

        clauses = []

        try:
            from benchbox.core.tuning.interface import TuningType

            partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
            if partition_columns:
                sorted_cols = sorted(partition_columns, key=lambda col: col.order)
                column_names = [col.name.lower() for col in sorted_cols]
                clauses.append(f"PARTITIONED BY ({', '.join(column_names)})")

        except ImportError:
            pass

        return " ".join(clauses)

    def apply_table_tunings(self, table_tuning, connection: Any) -> None:
        """Apply tuning configurations to Athena table."""
        if not table_tuning or not table_tuning.has_any_tuning():
            return

        table_name = table_tuning.table_name.lower()
        self.logger.info(f"Athena tunings for {table_name} applied at table creation time")

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        """Apply unified tuning configuration."""
        if not unified_config:
            return

        for _table_name, table_tuning in unified_config.table_tunings.items():
            self.apply_table_tunings(table_tuning, connection)

    def apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None:
        """Apply Athena-specific optimizations."""
        if not platform_config:
            return
        self.logger.info("Athena optimizations applied via workgroup settings")

    def apply_constraint_configuration(
        self,
        primary_key_config: PrimaryKeyConfiguration,
        foreign_key_config: ForeignKeyConfiguration,
        connection: Any,
    ) -> None:
        """Apply constraint configurations (informational only in Athena)."""
        if primary_key_config and primary_key_config.enabled:
            self.logger.info("Primary key constraints noted (Athena does not enforce constraints)")

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Get list of existing tables."""
        cursor = connection.cursor()
        try:
            cursor.execute("SHOW TABLES")
            return [row[0].lower() for row in cursor.fetchall()]
        except Exception:
            return []
        finally:
            cursor.close()

    def analyze_table(self, connection: Any, table_name: str) -> None:
        """Run ANALYZE on table (not needed for Athena - stats auto-collected)."""
        self.logger.debug(f"ANALYZE not needed for Athena - statistics are auto-collected for {table_name}")


def _build_athena_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build Athena database configuration with credential loading."""
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    # Load saved credentials
    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("athena") or {}

    # Build merged options: saved_creds < options < overrides
    merged_options = {}
    merged_options.update(saved_creds)
    merged_options.update(options)
    merged_options.update(overrides)

    name = info.display_name if info else "AWS Athena"
    driver_package = info.driver_package if info else "pyathena"

    config_dict = {
        "type": "athena",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Platform-specific fields
        "region": merged_options.get("region") or merged_options.get("aws_region"),
        "workgroup": merged_options.get("workgroup"),
        "database": merged_options.get("database"),
        "catalog": merged_options.get("catalog"),
        "s3_output_location": merged_options.get("s3_output_location"),
        "s3_staging_dir": merged_options.get("s3_staging_dir"),
        "staging_root": merged_options.get("staging_root"),
        "s3_bucket": merged_options.get("s3_bucket"),
        "s3_prefix": merged_options.get("s3_prefix"),
        "aws_profile": merged_options.get("aws_profile"),
        "aws_access_key_id": merged_options.get("aws_access_key_id"),
        "aws_secret_access_key": merged_options.get("aws_secret_access_key"),
        # Data format options
        "data_format": merged_options.get("data_format"),
        "compression": merged_options.get("compression"),
        "cleanup_staging": merged_options.get("cleanup_staging"),
        # Benchmark context
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    return DatabaseConfig(**config_dict)


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("athena", _build_athena_config)
except ImportError:
    pass
