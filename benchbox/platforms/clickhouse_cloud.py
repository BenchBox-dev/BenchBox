"""ClickHouse Cloud platform adapter for managed ClickHouse service.

ClickHouse Cloud is the managed cloud version of ClickHouse, providing
serverless and dedicated compute options with automatic scaling.
This adapter inherits from ClickHouseAdapter to reuse all shared logic
(mixins, client code) while implementing cloud-specific defaults.

Authentication:
- Uses environment variables or config file:
  - CLICKHOUSE_CLOUD_HOST: Hostname (e.g., abc123.us-east-2.aws.clickhouse.cloud)
  - CLICKHOUSE_CLOUD_PASSWORD: Password for authentication
  - CLICKHOUSE_CLOUD_USER: Username (default: "default")
  - CLICKHOUSE_CLOUD_OAUTH_TOKEN: OAuth/bearer token (alternative to password)

Connection:
- Uses clickhouse-connect for HTTPS-based communication (port 8443)
- Supports compression and secure connections by default

Data Loading:
- Default: Local INSERT via clickhouse-connect
- S3 staging: Upload to S3 then INSERT FROM s3() table function
- GCS staging: Upload to GCS then INSERT FROM gcs() table function

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.adapter import DriverIsolationCapability
from benchbox.platforms.clickhouse import ClickHouseAdapter
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn


class ClickHouseCloudAdapter(ClickHouseAdapter):
    """ClickHouse Cloud platform adapter - managed ClickHouse service.

    This adapter enables running benchmarks against ClickHouse Cloud,
    allowing direct comparison with self-hosted ClickHouse performance.

    Authentication:
        Set environment variables, or provide via platform options:
        - CLICKHOUSE_CLOUD_HOST: Cloud hostname
        - CLICKHOUSE_CLOUD_PASSWORD: Authentication password
        - CLICKHOUSE_CLOUD_USER: Username (default: "default")
        - CLICKHOUSE_CLOUD_OAUTH_TOKEN: OAuth/bearer token (alternative to password)

    Data Loading:
        By default, data is loaded via local INSERT statements. For large datasets,
        configure cloud storage staging:
        - S3: Set CLICKHOUSE_CLOUD_S3_STAGING_URL (e.g., s3://bucket/prefix/)
        - GCS: Set CLICKHOUSE_CLOUD_GCS_STAGING_URL (e.g., gs://bucket/prefix/)

    Example usage:
        benchbox run --platform clickhouse-cloud --benchmark tpch --scale 0.01

        # With explicit options
        benchbox run --platform clickhouse-cloud --benchmark tpch \\
            --platform-option host=abc123.us-east-2.aws.clickhouse.cloud \\
            --platform-option password=my-password

        # With OAuth token
        benchbox run --platform clickhouse-cloud --benchmark tpch \\
            --clickhouse-cloud-oauth-token=my-token

        # With S3 staging for data loading
        benchbox run --platform clickhouse-cloud --benchmark tpch --scale 1 \\
            --clickhouse-cloud-s3-staging-url=s3://my-bucket/benchbox-staging/
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY
    supports_external_tables = True

    def __init__(self, **config):
        """Initialize ClickHouse Cloud adapter.

        Forces deployment_mode to "cloud" and validates credentials upfront.

        Args:
            **config: Configuration options:
                - host: ClickHouse Cloud hostname (or use CLICKHOUSE_CLOUD_HOST env)
                - password: Authentication password (or use CLICKHOUSE_CLOUD_PASSWORD env)
                - oauth_token: OAuth/bearer token (or use CLICKHOUSE_CLOUD_OAUTH_TOKEN env)
                - username: Username (default: "default", or use CLICKHOUSE_CLOUD_USER env)
                - database: Database name (default: "default")
                - s3_staging_url: S3 URL for staging data (or use CLICKHOUSE_CLOUD_S3_STAGING_URL env)
                - s3_region: AWS region for S3 bucket (or use CLICKHOUSE_CLOUD_S3_REGION env)
                - gcs_staging_url: GCS URL for staging data (or use CLICKHOUSE_CLOUD_GCS_STAGING_URL env)
        """
        # Force cloud deployment mode - this is the key distinction
        config["deployment_mode"] = "cloud"
        # Internal flag to bypass the base adapter's cloud mode rejection
        # (cloud is only valid when called from this subclass)
        config["_is_cloud_subclass"] = True

        # Apply cloud-specific defaults from environment before parent init
        self._apply_cloud_defaults(config)

        # Call parent initialization (handles mixin composition)
        super().__init__(**config)

        # Remove internal flag from config to prevent leakage to other components
        config.pop("_is_cloud_subclass", None)

        logger.info(f"ClickHouse Cloud adapter initialized for host: {self.host}")

    def _apply_cloud_defaults(self, config: dict[str, Any]) -> None:
        """Apply cloud-specific defaults from environment variables.

        Environment variables follow the existing ClickHouse Cloud pattern:
        - CLICKHOUSE_CLOUD_HOST
        - CLICKHOUSE_CLOUD_PASSWORD
        - CLICKHOUSE_CLOUD_USER
        - CLICKHOUSE_CLOUD_OAUTH_TOKEN
        - CLICKHOUSE_CLOUD_S3_STAGING_URL
        - CLICKHOUSE_CLOUD_S3_REGION
        - CLICKHOUSE_CLOUD_GCS_STAGING_URL

        Args:
            config: Configuration dictionary to update with defaults
        """
        # Host from env if not provided
        if "host" not in config or not config["host"]:
            config["host"] = os.environ.get("CLICKHOUSE_CLOUD_HOST")

        # Password from env if not provided
        if "password" not in config or not config["password"]:
            config["password"] = os.environ.get("CLICKHOUSE_CLOUD_PASSWORD")

        # OAuth token from env if not provided
        if "oauth_token" not in config or not config["oauth_token"]:
            config["oauth_token"] = os.environ.get("CLICKHOUSE_CLOUD_OAUTH_TOKEN")

        # Username with default fallback
        if "username" not in config or not config["username"]:
            config["username"] = os.environ.get("CLICKHOUSE_CLOUD_USER", "default")

        # S3 staging from env if not provided
        if "s3_staging_url" not in config or not config["s3_staging_url"]:
            config["s3_staging_url"] = os.environ.get("CLICKHOUSE_CLOUD_S3_STAGING_URL")

        if "s3_region" not in config or not config["s3_region"]:
            config["s3_region"] = os.environ.get("CLICKHOUSE_CLOUD_S3_REGION")

        # GCS staging from env if not provided
        if "gcs_staging_url" not in config or not config["gcs_staging_url"]:
            config["gcs_staging_url"] = os.environ.get("CLICKHOUSE_CLOUD_GCS_STAGING_URL")

    @property
    def platform_name(self) -> str:
        """Return platform display name."""
        return "ClickHouse Cloud"

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | None:
        """Resolve sorted-ingestion support for ClickHouse Cloud.

        ClickHouse Cloud uses MergeTree ORDER BY at table creation, so post-load
        sorted-ingestion rewrites are intentionally unsupported.
        """
        try:
            mode, _method = self.resolve_sorted_ingestion_strategy()
        except ValueError as exc:
            raise ValueError(
                "ClickHouse Cloud does not support post-load sorted ingestion. "
                "Define table ORDER BY keys at CREATE TABLE time instead."
            ) from exc

        if mode == "off":
            return None
        raise ValueError(
            "ClickHouse Cloud does not support post-load sorted ingestion. "
            "Define table ORDER BY keys at CREATE TABLE time instead."
        )

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add ClickHouse Cloud-specific CLI arguments."""
        cloud_group = parser.add_argument_group("ClickHouse Cloud Arguments")
        cloud_group.add_argument(
            "--host",
            type=str,
            help="ClickHouse Cloud hostname (e.g., abc123.us-east-2.aws.clickhouse.cloud)",
        )
        cloud_group.add_argument(
            "--password",
            type=str,
            help="ClickHouse Cloud password (or use CLICKHOUSE_CLOUD_PASSWORD env)",
        )
        cloud_group.add_argument(
            "--clickhouse-cloud-oauth-token",
            type=str,
            help="OAuth/bearer token for authentication (or use CLICKHOUSE_CLOUD_OAUTH_TOKEN env). "
            "When provided, this is used instead of username/password.",
        )
        cloud_group.add_argument(
            "--username",
            type=str,
            default="default",
            help="Username (default: 'default')",
        )
        cloud_group.add_argument(
            "--database",
            type=str,
            default="default",
            help="Database name (default: 'default')",
        )

        # Cloud storage staging arguments for data loading
        staging_group = parser.add_argument_group("ClickHouse Cloud Storage Staging")
        staging_group.add_argument(
            "--clickhouse-cloud-s3-staging-url",
            type=str,
            help="S3 URL for staging data files during loading (e.g., s3://bucket/benchbox-staging/). "
            "Or use CLICKHOUSE_CLOUD_S3_STAGING_URL env var.",
        )
        staging_group.add_argument(
            "--clickhouse-cloud-s3-region",
            type=str,
            help="AWS region for the S3 staging bucket (e.g., us-east-1). Or use CLICKHOUSE_CLOUD_S3_REGION env var.",
        )
        staging_group.add_argument(
            "--clickhouse-cloud-gcs-staging-url",
            type=str,
            help="GCS URL for staging data files during loading (e.g., gs://bucket/benchbox-staging/). "
            "Or use CLICKHOUSE_CLOUD_GCS_STAGING_URL env var.",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create ClickHouse Cloud adapter from unified configuration.

        Maps CLI arguments and platform options to adapter configuration.

        Args:
            config: Unified configuration dictionary from CLI/orchestrator

        Returns:
            Configured ClickHouseCloudAdapter instance
        """
        adapter_config: dict[str, Any] = {}

        # Map cloud-specific parameters
        for key in ["host", "password", "username", "database", "oauth_token"]:
            if key in config and config[key] is not None:
                adapter_config[key] = config[key]

        # Map optional performance settings
        for key in [
            "max_memory_usage",
            "max_execution_time",
            "max_threads",
            "disable_result_cache",
            "compression",
        ]:
            if key in config and config[key] is not None:
                adapter_config[key] = config[key]

        # Map cloud storage staging settings
        for key in ["s3_staging_url", "s3_region", "gcs_staging_url"]:
            if key in config and config[key] is not None:
                adapter_config[key] = config[key]

        # Pass through benchmark context for potential use
        if "benchmark" in config:
            adapter_config["benchmark"] = config["benchmark"]

        return cls(**adapter_config)

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get ClickHouse Cloud platform information.

        Extends base ClickHouse platform info with cloud-specific details.

        Args:
            connection: Optional active connection

        Returns:
            Dictionary with platform metadata
        """
        info = super().get_platform_info(connection)
        info["platform_type"] = "clickhouse-cloud"
        info["platform_name"] = "ClickHouse Cloud"
        info["connection_mode"] = "cloud"
        info["configuration"]["deployment"] = "managed"

        # Include authentication mode indicator
        if getattr(self, "oauth_token", None):
            info["configuration"]["auth_method"] = "oauth"
        else:
            info["configuration"]["auth_method"] = "password"

        # Include cloud storage staging configuration if set
        if getattr(self, "s3_staging_url", None):
            info["configuration"]["s3_staging_url"] = self.s3_staging_url
        if getattr(self, "gcs_staging_url", None):
            info["configuration"]["gcs_staging_url"] = self.gcs_staging_url

        return info

    # -------------------------------------------------------------------------
    # Cloud Storage Staging for Data Loading
    # -------------------------------------------------------------------------

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data with cloud storage staging dispatch.

        Loading strategies (in priority order):
        1. **S3 staging** (if s3_staging_url is configured): Upload CSV to S3,
           then INSERT FROM s3() table function.
        2. **GCS staging** (if gcs_staging_url is configured): Upload CSV to GCS,
           then INSERT FROM gcs() table function.
        3. **Default INSERT** (fallback): Use inherited ClickHouse local INSERT path.

        Args:
            benchmark: Benchmark instance with table/data info
            connection: Active ClickHouse Cloud connection
            data_dir: Path to local data directory

        Returns:
            Tuple of (table_stats, total_time, loading_metadata)
        """
        if getattr(self, "s3_staging_url", None):
            return self._load_data_via_s3(benchmark, connection, data_dir)
        elif getattr(self, "gcs_staging_url", None):
            return self._load_data_via_gcs(benchmark, connection, data_dir)
        else:
            # Fall back to the inherited ClickHouse data loading (INSERT batching)
            return super().load_data(benchmark, connection, data_dir)

    def validate_external_table_requirements(self) -> None:
        """Validate cloud staging prerequisites for external table mode."""
        if not getattr(self, "s3_staging_url", None) and not getattr(self, "gcs_staging_url", None):
            raise ValueError(
                "ClickHouse Cloud external mode requires cloud staging URL. "
                "Set --platform-option s3_staging_url=s3://bucket/prefix/ or "
                "--platform-option gcs_staging_url=gs://bucket/prefix/."
            )

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Register external Parquet-backed views in ClickHouse Cloud."""
        self.validate_external_table_requirements()
        if getattr(self, "s3_staging_url", None):
            return self._create_external_tables_via_s3(benchmark, connection, data_dir)
        return self._create_external_tables_via_gcs(benchmark, connection, data_dir)

    @staticmethod
    def _normalize_external_file_inputs(file_paths: Any) -> tuple[list[Path], list[str]]:
        """Split file paths into local files and cloud URIs."""
        normalized_paths = file_paths if isinstance(file_paths, list) else [file_paths]
        local_paths: list[Path] = []
        cloud_uris: list[str] = []

        for file_path in normalized_paths:
            file_str = str(file_path)
            if file_str.startswith(("s3://", "gs://", "https://")):
                cloud_uris.append(file_str)
                continue

            path = Path(file_path)
            if path.exists() and (path.is_dir() or path.stat().st_size > 0):
                local_paths.append(path)

        return local_paths, cloud_uris

    def _create_external_tables_via_s3(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Create external views over S3-hosted Parquet data."""
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for ClickHouse Cloud external mode with S3 staging.\nInstall with: uv add boto3"
            ) from None

        start_time = mono_time()
        table_stats: dict[str, int] = {}
        data_files = self._resolve_cloud_data_files(benchmark, data_dir)
        s3_bucket, s3_prefix = self._parse_s3_url(self.s3_staging_url)

        s3_client_kwargs: dict[str, Any] = {}
        if getattr(self, "s3_region", None):
            s3_client_kwargs["region_name"] = self.s3_region
        s3_client = boto3.client("s3", **s3_client_kwargs)

        aws_key_id = os.environ.get("AWS_ACCESS_KEY_ID", "").replace("'", "''")
        aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "").replace("'", "''")
        if aws_key_id or aws_secret_key:
            self.logger.warning(
                "AWS credentials will be embedded in ClickHouse VIEW definitions and may "
                "appear in server query logs. Consider using a named S3 connection instead."
            )

        for table_name, file_paths in data_files.items():
            table_name_lower = table_name.lower()
            local_paths, cloud_uris = self._normalize_external_file_inputs(file_paths)
            iceberg_locals = [path for path in local_paths if path.is_dir() and (path / "metadata").is_dir()]
            parquet_locals = [path for path in local_paths if path.suffix.lower() == ".parquet"]
            parquet_cloud_uris = [
                uri for uri in cloud_uris if uri.lower().endswith(".parquet") and uri.startswith("s3://")
            ]
            iceberg_cloud_uris = [uri for uri in cloud_uris if uri.startswith("s3://") and "/metadata" in uri]

            if iceberg_locals:
                table_prefix = f"{s3_prefix}{table_name_lower}/external/"
                for local_path in iceberg_locals:
                    for source_file in local_path.rglob("*"):
                        if source_file.is_file():
                            relative = source_file.relative_to(local_path)
                            s3_client.upload_file(str(source_file), s3_bucket, f"{table_prefix}{relative.as_posix()}")
                source_expr = f"iceberg('s3://{s3_bucket}/{table_prefix}', '{aws_key_id}', '{aws_secret_key}')"
            elif iceberg_cloud_uris:
                root = iceberg_cloud_uris[0].split("/metadata", 1)[0] + "/"
                escaped_root = root.replace("'", "''")
                source_expr = f"iceberg('{escaped_root}', '{aws_key_id}', '{aws_secret_key}')"
            elif parquet_locals:
                table_prefix = f"{s3_prefix}{table_name_lower}/external/"
                for local_path in parquet_locals:
                    s3_client.upload_file(str(local_path), s3_bucket, f"{table_prefix}{local_path.name}")
                parquet_glob = f"s3://{s3_bucket}/{table_prefix}*.parquet"
                escaped_glob = parquet_glob.replace("'", "''")
                source_expr = f"s3('{escaped_glob}', '{aws_key_id}', '{aws_secret_key}', 'Parquet')"
            elif parquet_cloud_uris:
                # Derive a common prefix covering all cloud URIs for this table.
                dirs = {uri.rsplit("/", 1)[0] for uri in parquet_cloud_uris}
                if len(dirs) == 1:
                    parquet_glob = dirs.pop() + "/*.parquet"
                else:
                    # Multiple directories: find the longest common prefix
                    common = os.path.commonprefix(list(dirs)).rsplit("/", 1)[0]
                    parquet_glob = common + "/**/*.parquet"
                escaped_glob = parquet_glob.replace("'", "''")
                source_expr = f"s3('{escaped_glob}', '{aws_key_id}', '{aws_secret_key}', 'Parquet')"
            else:
                raise ValueError(
                    f"ClickHouse external mode requires Iceberg directories or Parquet files for table "
                    f"'{table_name_lower}'. No supported sources were found."
                )

            create_view_sql = f"CREATE OR REPLACE VIEW {table_name_lower} AS SELECT * FROM {source_expr}"
            connection.execute(create_view_sql)
            count_result = connection.execute(f"SELECT COUNT(*) FROM {table_name_lower}")
            table_stats[table_name_lower] = count_result[0][0] if count_result and count_result[0] else 0

        total_time = elapsed_seconds(start_time)
        metadata = {
            "loading_method": "s3_external_views",
            "s3_staging_url": self.s3_staging_url,
        }
        return table_stats, total_time, metadata

    def _create_external_tables_via_gcs(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Create external views over GCS-hosted Parquet data."""
        try:
            from google.cloud import storage as gcs_storage
        except ImportError:
            raise ImportError(
                "google-cloud-storage is required for ClickHouse Cloud external mode with GCS staging.\n"
                "Install with: uv add google-cloud-storage"
            ) from None

        start_time = mono_time()
        table_stats: dict[str, int] = {}
        data_files = self._resolve_cloud_data_files(benchmark, data_dir)
        gcs_bucket_name, gcs_prefix = self._parse_gcs_url(self.gcs_staging_url)

        gcs_client = gcs_storage.Client()
        gcs_bucket = gcs_client.bucket(gcs_bucket_name)

        gcs_hmac_key = os.environ.get("GCS_HMAC_ACCESS_KEY", "").replace("'", "''")
        gcs_hmac_secret = os.environ.get("GCS_HMAC_SECRET", "").replace("'", "''")
        if gcs_hmac_key or gcs_hmac_secret:
            self.logger.warning(
                "GCS HMAC credentials will be embedded in ClickHouse VIEW definitions and may "
                "appear in server query logs. Consider using a named GCS connection instead."
            )

        for table_name, file_paths in data_files.items():
            table_name_lower = table_name.lower()
            local_paths, cloud_uris = self._normalize_external_file_inputs(file_paths)
            iceberg_locals = [path for path in local_paths if path.is_dir() and (path / "metadata").is_dir()]
            parquet_locals = [path for path in local_paths if path.suffix.lower() == ".parquet"]
            parquet_cloud_uris = [
                uri for uri in cloud_uris if uri.lower().endswith(".parquet") and uri.startswith("gs://")
            ]
            iceberg_cloud_uris = [uri for uri in cloud_uris if uri.startswith("gs://") and "/metadata" in uri]

            if iceberg_locals:
                table_prefix = f"{gcs_prefix}{table_name_lower}/external/"
                for local_path in iceberg_locals:
                    for source_file in local_path.rglob("*"):
                        if source_file.is_file():
                            relative = source_file.relative_to(local_path)
                            blob = gcs_bucket.blob(f"{table_prefix}{relative.as_posix()}")
                            blob.upload_from_filename(str(source_file))
                root_url = f"https://storage.googleapis.com/{gcs_bucket_name}/{table_prefix}"
                escaped_root_url = root_url.replace("'", "''")
                source_expr = f"iceberg('{escaped_root_url}', '{gcs_hmac_key}', '{gcs_hmac_secret}')"
            elif iceberg_cloud_uris:
                root = iceberg_cloud_uris[0].split("/metadata", 1)[0] + "/"
                root_url = root.replace("gs://", "https://storage.googleapis.com/")
                escaped_root_url = root_url.replace("'", "''")
                source_expr = f"iceberg('{escaped_root_url}', '{gcs_hmac_key}', '{gcs_hmac_secret}')"
            elif parquet_locals:
                table_prefix = f"{gcs_prefix}{table_name_lower}/external/"
                for local_path in parquet_locals:
                    blob = gcs_bucket.blob(f"{table_prefix}{local_path.name}")
                    blob.upload_from_filename(str(local_path))
                parquet_glob = f"https://storage.googleapis.com/{gcs_bucket_name}/{table_prefix}*.parquet"
                escaped_glob = parquet_glob.replace("'", "''")
                source_expr = f"gcs('{escaped_glob}', '{gcs_hmac_key}', '{gcs_hmac_secret}', 'Parquet')"
            elif parquet_cloud_uris:
                # Derive a common prefix covering all cloud URIs for this table.
                dirs = {uri.rsplit("/", 1)[0] for uri in parquet_cloud_uris}
                if len(dirs) == 1:
                    cloud_prefix = dirs.pop()
                else:
                    cloud_prefix = os.path.commonprefix(list(dirs)).rsplit("/", 1)[0]
                parquet_glob = cloud_prefix.replace("gs://", "https://storage.googleapis.com/") + "/*.parquet"
                escaped_glob = parquet_glob.replace("'", "''")
                source_expr = f"gcs('{escaped_glob}', '{gcs_hmac_key}', '{gcs_hmac_secret}', 'Parquet')"
            else:
                raise ValueError(
                    f"ClickHouse external mode requires Iceberg directories or Parquet files for table "
                    f"'{table_name_lower}'. No supported sources were found."
                )

            create_view_sql = f"CREATE OR REPLACE VIEW {table_name_lower} AS SELECT * FROM {source_expr}"
            connection.execute(create_view_sql)
            count_result = connection.execute(f"SELECT COUNT(*) FROM {table_name_lower}")
            table_stats[table_name_lower] = count_result[0][0] if count_result and count_result[0] else 0

        total_time = elapsed_seconds(start_time)
        metadata = {
            "loading_method": "gcs_external_views",
            "gcs_staging_url": self.gcs_staging_url,
        }
        return table_stats, total_time, metadata

    def _resolve_cloud_data_files(self, benchmark, data_dir: Path) -> dict[str, list[Path]]:
        """Resolve data files for cloud staging upload.

        Returns:
            Mapping of table_name -> list of valid file paths.

        Raises:
            ValueError: If no data files are found.
        """
        import json

        from benchbox.platforms.base.data_loading import DataSourceResolver

        resolver = DataSourceResolver(
            platform_name=self.platform_name,
            table_mode=getattr(self, "table_mode", "native"),
            platform_config=getattr(self, "__dict__", None),
        )
        data_source = resolver.resolve(benchmark, data_dir)
        if data_source and data_source.tables:
            return {table: [Path(p) for p in paths] for table, paths in data_source.tables.items()}

        data_files = None
        try:
            manifest_path = Path(data_dir) / "_datagen_manifest.json"
            if manifest_path.exists():
                with open(manifest_path) as f:
                    manifest = json.load(f)
                tables = manifest.get("tables") or {}
                mapping = {}
                for table, entries in tables.items():
                    if entries:
                        chunk_paths = []
                        for entry in entries:
                            rel = entry.get("path")
                            if rel:
                                chunk_paths.append(Path(data_dir) / rel)
                        if chunk_paths:
                            mapping[table] = chunk_paths
                if mapping:
                    data_files = mapping
        except Exception as exc:
            self.logger.debug(f"Manifest fallback failed: {exc}")

        if not data_files:
            raise ValueError("No data files found. Ensure benchmark.generate_data() was called first.")
        return data_files

    def _load_data_via_s3(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data via S3 staging using ClickHouse's s3() table function.

        Workflow per table:
        1. Upload local CSV/TSV file(s) to S3 staging location
        2. Execute INSERT INTO ... SELECT * FROM s3(...) to ingest from S3
        3. Track row counts from COUNT(*)

        AWS credentials are resolved from:
        1. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY environment variables
        2. boto3 default credential chain (IAM role, ~/.aws/credentials, etc.)

        Requires boto3 to be installed (lazy import with helpful error message).
        """
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 staging data loading.\n"
                "Install with: uv add boto3\n"
                "Alternatively, remove --clickhouse-cloud-s3-staging-url to use INSERT batching."
            ) from None

        start_time = mono_time()
        table_stats: dict[str, int] = {}

        # Resolve AWS credentials for the ClickHouse s3() function
        aws_key_id = os.environ.get("AWS_ACCESS_KEY_ID", "")
        aws_secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY", "")

        # Create S3 client for file uploads
        s3_client_kwargs: dict[str, Any] = {}
        if getattr(self, "s3_region", None):
            s3_client_kwargs["region_name"] = self.s3_region
        s3_client = boto3.client("s3", **s3_client_kwargs)

        # Parse S3 staging URL into bucket and prefix
        s3_bucket, s3_prefix = self._parse_s3_url(self.s3_staging_url)

        try:
            data_files = self._resolve_cloud_data_files(benchmark, data_dir)

            for table_name, file_paths in data_files.items():
                if not isinstance(file_paths, list):
                    file_paths = [file_paths]

                # Filter valid files
                valid_files = [Path(fp) for fp in file_paths if Path(fp).exists() and Path(fp).stat().st_size > 0]

                if not valid_files:
                    self.logger.warning(f"Skipping {table_name} - no valid data files")
                    table_stats[table_name.lower()] = 0
                    continue

                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.log_verbose(f"Loading data for table (S3 staging): {table_name}{chunk_info}")

                try:
                    load_start = mono_time()
                    table_name_lower = table_name.lower()
                    total_rows_loaded = 0

                    for file_path in valid_files:
                        # Determine S3 key for this file
                        s3_key = f"{s3_prefix}{table_name_lower}/{file_path.name}"
                        s3_file_url = f"s3://{s3_bucket}/{s3_key}"

                        # Upload file to S3
                        upload_start = mono_time()
                        self.log_verbose(f"Uploading {file_path.name} to {s3_file_url}")
                        s3_client.upload_file(str(file_path), s3_bucket, s3_key)
                        upload_time = elapsed_seconds(upload_start)
                        self.log_verbose(f"Uploaded {file_path.name} in {upload_time:.2f}s")

                        # Build the INSERT INTO ... SELECT FROM s3() statement
                        # ClickHouse s3() function: s3(url, aws_key_id, aws_secret_key, format)
                        # Escape single quotes in credentials for SQL safety
                        safe_key_id = aws_key_id.replace("'", "''")
                        safe_secret = aws_secret_key.replace("'", "''")

                        ingest_sql = (
                            f"INSERT INTO {table_name_lower} "
                            f"SELECT * FROM s3("
                            f"'{s3_file_url}', "
                            f"'{safe_key_id}', "
                            f"'{safe_secret}', "
                            f"'CSVWithNames'"
                            f")"
                        )

                        ingest_start = mono_time()
                        connection.execute(ingest_sql)
                        ingest_time = elapsed_seconds(ingest_start)

                        # Get row count via COUNT(*)
                        count_result = connection.execute(f"SELECT COUNT(*) FROM {table_name_lower}")
                        rows_loaded = count_result[0][0] if count_result and count_result[0] else 0

                        total_rows_loaded = rows_loaded  # COUNT(*) gives total, not incremental
                        self.log_verbose(f"Ingested from {file_path.name} via S3 in {ingest_time:.2f}s")

                    table_stats[table_name_lower] = total_rows_loaded

                    effective_tuning = self.get_effective_tuning_configuration()
                    if effective_tuning is not None:
                        self.apply_ctas_sort(table_name_lower, effective_tuning, connection)

                    load_time = elapsed_seconds(load_start)
                    self.logger.info(
                        f"Loaded {total_rows_loaded:,} rows into {table_name_lower}{chunk_info} "
                        f"via S3 staging in {load_time:.2f}s"
                    )

                except Exception as e:
                    self.logger.error(f"Failed to load {table_name} via S3: {str(e)[:200]}...")
                    table_stats[table_name.lower()] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"Loaded {total_rows:,} total rows via S3 staging in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"S3 staging data loading failed: {e}")
            raise

        loading_metadata = {
            "loading_method": "s3_staging",
            "s3_staging_url": self.s3_staging_url,
            "s3_region": getattr(self, "s3_region", None),
        }

        return table_stats, total_time, loading_metadata

    def _load_data_via_gcs(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data via GCS staging using ClickHouse's gcs() table function.

        Workflow per table:
        1. Upload local CSV/TSV file(s) to GCS staging location
        2. Execute INSERT INTO ... SELECT * FROM gcs(...) to ingest from GCS
        3. Track row counts from COUNT(*)

        GCS credentials are resolved from:
        1. GOOGLE_APPLICATION_CREDENTIALS environment variable (service account JSON)
        2. google-cloud-storage default credential chain

        For the ClickHouse gcs() table function, HMAC keys are used:
        1. GCS_HMAC_ACCESS_KEY / GCS_HMAC_SECRET environment variables

        Requires google-cloud-storage to be installed (lazy import with helpful error message).
        """
        try:
            from google.cloud import storage as gcs_storage
        except ImportError:
            raise ImportError(
                "google-cloud-storage is required for GCS staging data loading.\n"
                "Install with: uv add google-cloud-storage\n"
                "Alternatively, remove --clickhouse-cloud-gcs-staging-url to use INSERT batching."
            ) from None

        start_time = mono_time()
        table_stats: dict[str, int] = {}

        # Resolve GCS HMAC credentials for the ClickHouse gcs() function
        gcs_hmac_key = os.environ.get("GCS_HMAC_ACCESS_KEY", "")
        gcs_hmac_secret = os.environ.get("GCS_HMAC_SECRET", "")

        # Create GCS client for file uploads (uses Application Default Credentials)
        gcs_client = gcs_storage.Client()

        # Parse GCS staging URL into bucket and prefix
        gcs_bucket_name, gcs_prefix = self._parse_gcs_url(self.gcs_staging_url)
        gcs_bucket = gcs_client.bucket(gcs_bucket_name)

        try:
            data_files = self._resolve_cloud_data_files(benchmark, data_dir)

            for table_name, file_paths in data_files.items():
                if not isinstance(file_paths, list):
                    file_paths = [file_paths]

                # Filter valid files
                valid_files = [Path(fp) for fp in file_paths if Path(fp).exists() and Path(fp).stat().st_size > 0]

                if not valid_files:
                    self.logger.warning(f"Skipping {table_name} - no valid data files")
                    table_stats[table_name.lower()] = 0
                    continue

                chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                self.log_verbose(f"Loading data for table (GCS staging): {table_name}{chunk_info}")

                try:
                    load_start = mono_time()
                    table_name_lower = table_name.lower()
                    total_rows_loaded = 0

                    for file_path in valid_files:
                        # Determine GCS blob name
                        blob_name = f"{gcs_prefix}{table_name_lower}/{file_path.name}"
                        gcs_file_url = f"gs://{gcs_bucket_name}/{blob_name}"

                        # Upload file to GCS
                        upload_start = mono_time()
                        self.log_verbose(f"Uploading {file_path.name} to {gcs_file_url}")
                        blob = gcs_bucket.blob(blob_name)
                        blob.upload_from_filename(str(file_path))
                        upload_time = elapsed_seconds(upload_start)
                        self.log_verbose(f"Uploaded {file_path.name} in {upload_time:.2f}s")

                        # Build the INSERT INTO ... SELECT FROM gcs() statement
                        # ClickHouse gcs() function: gcs(url, hmac_key, hmac_secret, format)
                        # Escape single quotes in credentials for SQL safety
                        safe_hmac_key = gcs_hmac_key.replace("'", "''")
                        safe_hmac_secret = gcs_hmac_secret.replace("'", "''")

                        # Use https:// URL format for ClickHouse gcs() function
                        gcs_https_url = f"https://storage.googleapis.com/{gcs_bucket_name}/{blob_name}"

                        ingest_sql = (
                            f"INSERT INTO {table_name_lower} "
                            f"SELECT * FROM gcs("
                            f"'{gcs_https_url}', "
                            f"'{safe_hmac_key}', "
                            f"'{safe_hmac_secret}', "
                            f"'CSVWithNames'"
                            f")"
                        )

                        ingest_start = mono_time()
                        connection.execute(ingest_sql)
                        ingest_time = elapsed_seconds(ingest_start)

                        # Get row count via COUNT(*)
                        count_result = connection.execute(f"SELECT COUNT(*) FROM {table_name_lower}")
                        rows_loaded = count_result[0][0] if count_result and count_result[0] else 0

                        total_rows_loaded = rows_loaded  # COUNT(*) gives total, not incremental
                        self.log_verbose(f"Ingested from {file_path.name} via GCS in {ingest_time:.2f}s")

                    table_stats[table_name_lower] = total_rows_loaded

                    effective_tuning = self.get_effective_tuning_configuration()
                    if effective_tuning is not None:
                        self.apply_ctas_sort(table_name_lower, effective_tuning, connection)

                    load_time = elapsed_seconds(load_start)
                    self.logger.info(
                        f"Loaded {total_rows_loaded:,} rows into {table_name_lower}{chunk_info} "
                        f"via GCS staging in {load_time:.2f}s"
                    )

                except Exception as e:
                    self.logger.error(f"Failed to load {table_name} via GCS: {str(e)[:200]}...")
                    table_stats[table_name.lower()] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"Loaded {total_rows:,} total rows via GCS staging in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"GCS staging data loading failed: {e}")
            raise

        loading_metadata = {
            "loading_method": "gcs_staging",
            "gcs_staging_url": self.gcs_staging_url,
        }

        return table_stats, total_time, loading_metadata

    @staticmethod
    def _parse_s3_url(s3_url: str) -> tuple[str, str]:
        """Parse an S3 URL into (bucket, prefix) components."""
        from benchbox.utils.cloud_urls import parse_s3_url

        return parse_s3_url(s3_url)

    @staticmethod
    def _parse_gcs_url(gcs_url: str) -> tuple[str, str]:
        """Parse a GCS URL into (bucket, prefix) components."""
        from benchbox.utils.cloud_urls import parse_gcs_url

        return parse_gcs_url(gcs_url)


def _build_clickhouse_cloud_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build ClickHouse Cloud database configuration with credential loading.

    Args:
        platform: Platform name (should be 'clickhouse-cloud')
        options: CLI platform options from --platform-option flags
        overrides: Runtime overrides from orchestrator
        info: Platform info from registry

    Returns:
        DatabaseConfig with credentials loaded
    """
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    # Load saved credentials
    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials("clickhouse-cloud") or {}

    # Build merged options: saved_creds < options < overrides
    merged_options = {}
    merged_options.update(saved_creds)
    merged_options.update(options)
    merged_options.update(overrides)

    name = info.display_name if info else "ClickHouse Cloud"
    driver_package = info.driver_package if info else "clickhouse-connect"

    config_dict = {
        "type": "clickhouse-cloud",
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
        # Platform-specific fields at top-level
        "host": merged_options.get("host"),
        "password": merged_options.get("password"),
        "username": merged_options.get("username"),
        "database": merged_options.get("database"),
        # OAuth token
        "oauth_token": merged_options.get("oauth_token"),
        # Cloud storage staging
        "s3_staging_url": merged_options.get("s3_staging_url"),
        "s3_region": merged_options.get("s3_region"),
        "gcs_staging_url": merged_options.get("gcs_staging_url"),
        # Optional settings
        "max_memory_usage": merged_options.get("max_memory_usage"),
        "max_execution_time": merged_options.get("max_execution_time"),
        "disable_result_cache": merged_options.get("disable_result_cache"),
        "compression": merged_options.get("compression"),
        # Benchmark context
        "benchmark": overrides.get("benchmark"),
        "scale_factor": overrides.get("scale_factor"),
        "tuning_config": overrides.get("tuning_config"),
    }

    return DatabaseConfig(**config_dict)


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("clickhouse-cloud", _build_clickhouse_cloud_config)
except ImportError:
    # Platform hooks may not be available in all contexts (e.g., minimal installs, testing)
    logger.debug("Platform hooks not available, skipping ClickHouse Cloud config builder registration")


__all__ = ["ClickHouseCloudAdapter"]
