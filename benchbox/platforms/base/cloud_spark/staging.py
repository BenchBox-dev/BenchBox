"""Cloud Spark staging infrastructure for unified cloud storage uploads.

Provides a unified API for uploading benchmark data to cloud storage
across all major cloud providers:
- AWS S3 (s3://)
- Google Cloud Storage (gs://)
- Azure Blob Storage (abfss://, wasbs://)
- Databricks Unity Catalog Volumes (dbfs:/Volumes/)
- Local filesystem (file://) for testing

Usage:
    from benchbox.platforms.base.cloud_spark import CloudSparkStaging

    # Auto-detect provider from URI scheme
    staging = CloudSparkStaging.from_uri("s3://my-bucket/benchbox/data")

    # Upload all TPC-H tables
    staging.upload_tables(
        tables=["lineitem", "orders", "customer", ...],
        source_dir=Path("./generated_data"),
        format="parquet",
    )

    # Check if data already exists
    if staging.tables_exist(tables):
        emit("Data already staged, skipping upload")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from benchbox.utils.dependencies import get_package_install_message

logger = logging.getLogger(__name__)


class CloudProvider(Enum):
    """Supported cloud storage providers."""

    AWS_S3 = "s3"
    GCS = "gs"
    AZURE_BLOB = "azure"
    AZURE_ADLS = "abfss"
    DBFS = "dbfs"
    LOCAL = "file"


@dataclass
class UploadProgress:
    """Progress information for file uploads."""

    table_name: str
    file_name: str
    bytes_uploaded: int
    total_bytes: int
    files_completed: int
    total_files: int

    @property
    def percent_complete(self) -> float:
        """Calculate percentage complete."""
        if self.total_bytes == 0:
            return 100.0
        return (self.bytes_uploaded / self.total_bytes) * 100


@dataclass
class StagingConfig:
    """Configuration for cloud staging."""

    uri: str
    provider: CloudProvider
    bucket: str
    prefix: str
    region: str | None = None
    credentials: dict[str, Any] | None = None
    compression: str | None = None  # zstd, gzip, none
    parallel_uploads: int = 4
    chunk_size: int = 8 * 1024 * 1024  # 8MB default


class CloudSparkStaging(ABC):
    """Abstract base class for cloud storage staging.

    Provides a unified API for uploading benchmark data to any cloud
    storage provider. Subclasses implement provider-specific upload logic.
    """

    def __init__(self, config: StagingConfig) -> None:
        """Initialize staging with configuration.

        Args:
            config: Staging configuration including URI and credentials
        """
        self.config = config
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @classmethod
    def from_uri(
        cls,
        uri: str,
        credentials: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> CloudSparkStaging:
        """Create staging instance from URI with auto-detected provider.

        Args:
            uri: Cloud storage URI (s3://, gs://, abfss://, dbfs://)
            credentials: Optional credentials dict
            **kwargs: Additional configuration options

        Returns:
            CloudSparkStaging instance for the detected provider

        Raises:
            ValueError: If URI scheme is not supported

        Examples:
            >>> staging = CloudSparkStaging.from_uri("s3://my-bucket/data")
            >>> staging = CloudSparkStaging.from_uri("gs://my-bucket/data")
            >>> staging = CloudSparkStaging.from_uri("abfss://container@account.dfs.core.windows.net/data")
        """
        parsed = urlparse(uri)
        scheme = parsed.scheme.lower()

        # Detect provider from scheme
        provider_map = {
            "s3": CloudProvider.AWS_S3,
            "s3a": CloudProvider.AWS_S3,
            "gs": CloudProvider.GCS,
            "gcs": CloudProvider.GCS,
            "abfss": CloudProvider.AZURE_ADLS,
            "wasbs": CloudProvider.AZURE_BLOB,
            "az": CloudProvider.AZURE_BLOB,
            "dbfs": CloudProvider.DBFS,
            "file": CloudProvider.LOCAL,
            "": CloudProvider.LOCAL,  # No scheme = local path
        }

        if scheme not in provider_map:
            raise ValueError(f"Unsupported URI scheme: {scheme}. Supported: {', '.join(provider_map.keys())}")

        provider = provider_map[scheme]

        # Parse bucket and prefix
        bucket, prefix = cls._parse_uri(uri, provider)

        config = StagingConfig(
            uri=uri,
            provider=provider,
            bucket=bucket,
            prefix=prefix,
            credentials=credentials,
            **kwargs,
        )

        # Return provider-specific implementation
        return cls._create_for_provider(config)

    @staticmethod
    def _parse_uri(uri: str, provider: CloudProvider) -> tuple[str, str]:
        """Parse URI into bucket and prefix components.

        Args:
            uri: Cloud storage URI
            provider: Detected cloud provider

        Returns:
            Tuple of (bucket, prefix)
        """
        parsed = urlparse(uri)

        if provider == CloudProvider.LOCAL:
            return "", parsed.path

        if provider == CloudProvider.AZURE_ADLS:
            # abfss://container@account.dfs.core.windows.net/path
            # netloc = container@account.dfs.core.windows.net
            bucket = parsed.netloc  # Full container@account string
            prefix = parsed.path.lstrip("/")
        elif provider == CloudProvider.DBFS:
            # dbfs:/Volumes/catalog/schema/volume/path
            bucket = ""  # DBFS doesn't have traditional buckets
            prefix = parsed.path.lstrip("/")
        else:
            # s3://bucket/prefix or gs://bucket/prefix
            bucket = parsed.netloc
            prefix = parsed.path.lstrip("/")

        return bucket, prefix

    @classmethod
    def _create_for_provider(cls, config: StagingConfig) -> CloudSparkStaging:
        """Create provider-specific staging implementation.

        Args:
            config: Staging configuration

        Returns:
            Provider-specific CloudSparkStaging instance
        """
        provider_classes: dict[CloudProvider, type[CloudSparkStaging]] = {
            CloudProvider.AWS_S3: S3Staging,
            CloudProvider.GCS: GCSStaging,
            CloudProvider.AZURE_ADLS: AzureADLSStaging,
            CloudProvider.AZURE_BLOB: AzureBlobStaging,
            CloudProvider.DBFS: DBFSStaging,
            CloudProvider.LOCAL: LocalStaging,
        }

        staging_class = provider_classes.get(config.provider)
        if staging_class is None:
            raise ValueError(f"No staging implementation for provider: {config.provider}")

        return staging_class(config)

    @abstractmethod
    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Upload a single file to cloud storage.

        Args:
            local_path: Local file path
            remote_path: Remote path (relative to staging prefix)
            progress_callback: Optional callback for progress updates

        Returns:
            Full URI of uploaded file
        """

    @abstractmethod
    def file_exists(self, remote_path: str) -> bool:
        """Check if a remote file exists.

        Args:
            remote_path: Remote path (relative to staging prefix)

        Returns:
            True if file exists
        """

    @abstractmethod
    def list_files(self, remote_prefix: str) -> list[str]:
        """List files under a remote prefix.

        Args:
            remote_prefix: Remote prefix to list (relative to staging prefix)

        Returns:
            List of file paths
        """

    @abstractmethod
    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete a remote file or directory.

        Args:
            remote_path: Remote path to delete
            recursive: If True, delete directory contents recursively
        """

    @staticmethod
    def _normalize_data_files(
        data_files: Mapping[str, str | Path | Sequence[str | Path] | None],
    ) -> dict[str, list[Path]]:
        """Normalize per-table file mappings to concrete local paths.

        Raises TypeError if any table's value is None - callers should filter
        placeholder metadata (e.g. via ``_has_explicit_data_files``) before
        invoking this method.
        """
        normalized: dict[str, list[Path]] = {}
        for table_name, table_files in data_files.items():
            if table_files is None:
                raise TypeError(f"Explicit data files for table '{table_name}' cannot be None")
            if isinstance(table_files, (str, Path)):
                candidates = [table_files]
            else:
                candidates = list(table_files)

            paths = [Path(path) for path in candidates]
            if paths:
                normalized[table_name] = paths
        return normalized

    @staticmethod
    def _expand_explicit_table_files(table_name: str, table_files: list[Path]) -> list[tuple[Path, str]]:
        """Expand explicit files/directories to upload entries with stable relative paths."""
        standalone_files: list[Path] = []
        expanded: list[tuple[Path, str]] = []

        for candidate in table_files:
            if candidate.is_dir():
                for nested_file in sorted(path for path in candidate.rglob("*") if path.is_file()):
                    expanded.append((nested_file, nested_file.relative_to(candidate).as_posix()))
            else:
                standalone_files.append(candidate)

        if standalone_files:
            if len(standalone_files) == 1:
                expanded.append((standalone_files[0], standalone_files[0].name))
            else:
                try:
                    common_root = Path(os.path.commonpath([str(path.parent) for path in standalone_files]))
                except ValueError as exc:
                    raise ValueError(f"Cannot determine common root for table '{table_name}' files: {exc}") from exc
                for file_path in standalone_files:
                    expanded.append((file_path, file_path.relative_to(common_root).as_posix()))

        seen_targets: set[str] = set()
        for _file_path, relative_target in expanded:
            if relative_target in seen_targets:
                raise ValueError(
                    f"Explicit data files for table '{table_name}' would overwrite staged path '{relative_target}'"
                )
            seen_targets.add(relative_target)

        return expanded

    def upload_data_files(
        self,
        data_files: Mapping[str, str | Path | Sequence[str | Path]],
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> dict[str, str]:
        """Upload explicit per-table file mappings to cloud storage.

        Callers that already know the exact data files should use this API
        instead of relying on table-name globbing via ``upload_tables()``.
        """
        normalized = self._normalize_data_files(data_files)
        uploaded: dict[str, str] = {}
        upload_entries = {
            table_name: self._expand_explicit_table_files(table_name, table_files)
            for table_name, table_files in normalized.items()
        }
        total_files = sum(len(entries) for entries in upload_entries.values())
        files_completed = 0

        for table_name, table_entries in upload_entries.items():
            if not table_entries:
                self._logger.warning(f"No files found for table {table_name}")
                continue

            for file_path, relative_target in table_entries:
                remote_path = f"{table_name}/{relative_target}"
                self.upload_file(file_path, remote_path, progress_callback)
                files_completed += 1

                if progress_callback:
                    file_size = file_path.stat().st_size
                    progress = UploadProgress(
                        table_name=table_name,
                        file_name=file_path.name,
                        bytes_uploaded=file_size,
                        total_bytes=file_size,
                        files_completed=files_completed,
                        total_files=total_files,
                    )
                    progress_callback(progress)

            uploaded[table_name] = self.get_table_uri(table_name)
            self._logger.info(f"Uploaded table {table_name} ({len(table_entries)} files)")

        return uploaded

    def upload_tables(
        self,
        tables: list[str],
        source_dir: Path,
        file_format: str = "parquet",
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> dict[str, str]:
        """Upload multiple tables to cloud storage.

        Args:
            tables: List of table names to upload
            source_dir: Local directory containing table data
            file_format: File format (parquet, csv, etc.)
            progress_callback: Optional callback for progress updates

        Returns:
            Dict mapping table names to their remote URIs
        """
        data_files: dict[str, list[Path]] = {}

        for table_name in tables:
            # Find table files
            pattern = f"{table_name}*.{file_format}"
            table_files = list(source_dir.glob(pattern))

            if not table_files:
                # Try without extension for formats like .tbl
                pattern = f"{table_name}*"
                table_files = list(source_dir.glob(pattern))

            if not table_files:
                self._logger.warning(f"No files found for table {table_name}")
                continue

            data_files[table_name] = table_files

        return self.upload_data_files(data_files, progress_callback)

    def tables_exist(self, tables: list[str], file_format: str = "parquet") -> bool:
        """Check if all tables already exist in staging.

        Args:
            tables: List of table names to check
            file_format: Expected file format

        Returns:
            True if all tables have at least one file
        """
        for table_name in tables:
            files = self.list_files(f"{table_name}/")
            if not files:
                return False
        return True

    def get_table_uri(self, table_name: str) -> str:
        """Get the full URI for a table's data.

        Args:
            table_name: Name of the table

        Returns:
            Full URI to table data directory
        """
        return f"{self.config.uri.rstrip('/')}/{table_name}/"


class S3Staging(CloudSparkStaging):
    """AWS S3 staging implementation."""

    def __init__(self, config: StagingConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create S3 client."""
        if self._client is None:
            try:
                import boto3
            except ImportError as e:
                raise ImportError(get_package_install_message("boto3", "boto3 required for S3 staging.")) from e

            session_kwargs = {}
            if self.config.credentials:
                session_kwargs.update(self.config.credentials)
            if self.config.region:
                session_kwargs["region_name"] = self.config.region

            session = boto3.Session(**session_kwargs)
            self._client = session.client("s3")

        return self._client

    def _full_key(self, remote_path: str) -> str:
        """Get full S3 key including prefix."""
        if self.config.prefix:
            return f"{self.config.prefix.rstrip('/')}/{remote_path}"
        return remote_path

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Upload file to S3."""
        client = self._get_client()
        key = self._full_key(remote_path)

        extra_args = {}
        if self.config.compression == "gzip":
            extra_args["ContentEncoding"] = "gzip"

        client.upload_file(str(local_path), self.config.bucket, key, ExtraArgs=extra_args or None)

        return f"s3://{self.config.bucket}/{key}"

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists in S3."""
        client = self._get_client()
        key = self._full_key(remote_path)

        try:
            client.head_object(Bucket=self.config.bucket, Key=key)
            return True
        except client.exceptions.ClientError:
            return False

    def list_files(self, remote_prefix: str) -> list[str]:
        """List files in S3 under prefix."""
        client = self._get_client()
        prefix = self._full_key(remote_prefix)

        files = []
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.config.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                files.append(obj["Key"])

        return files

    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete file or directory from S3."""
        client = self._get_client()

        if recursive:
            files = self.list_files(remote_path)
            if files:
                objects = [{"Key": key} for key in files]
                client.delete_objects(
                    Bucket=self.config.bucket,
                    Delete={"Objects": objects},
                )
        else:
            key = self._full_key(remote_path)
            client.delete_object(Bucket=self.config.bucket, Key=key)


class GCSStaging(CloudSparkStaging):
    """Google Cloud Storage staging implementation."""

    def __init__(self, config: StagingConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create GCS client."""
        if self._client is None:
            try:
                from google.cloud import storage
            except ImportError as e:
                raise ImportError(
                    get_package_install_message(
                        "google-cloud-storage", "google-cloud-storage required for GCS staging."
                    )
                ) from e

            self._client = storage.Client()

        return self._client

    def _full_path(self, remote_path: str) -> str:
        """Get full GCS path including prefix."""
        if self.config.prefix:
            return f"{self.config.prefix.rstrip('/')}/{remote_path}"
        return remote_path

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Upload file to GCS."""
        client = self._get_client()
        bucket = client.bucket(self.config.bucket)
        blob_path = self._full_path(remote_path)
        blob = bucket.blob(blob_path)

        blob.upload_from_filename(str(local_path))

        return f"gs://{self.config.bucket}/{blob_path}"

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists in GCS."""
        client = self._get_client()
        bucket = client.bucket(self.config.bucket)
        blob_path = self._full_path(remote_path)
        blob = bucket.blob(blob_path)

        return blob.exists()

    def list_files(self, remote_prefix: str) -> list[str]:
        """List files in GCS under prefix."""
        client = self._get_client()
        bucket = client.bucket(self.config.bucket)
        prefix = self._full_path(remote_prefix)

        blobs = bucket.list_blobs(prefix=prefix)
        return [blob.name for blob in blobs]

    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete file or directory from GCS."""
        client = self._get_client()
        bucket = client.bucket(self.config.bucket)

        if recursive:
            blobs = bucket.list_blobs(prefix=self._full_path(remote_path))
            for blob in blobs:
                blob.delete()
        else:
            blob_path = self._full_path(remote_path)
            blob = bucket.blob(blob_path)
            blob.delete()


class AzureADLSStaging(CloudSparkStaging):
    """Azure Data Lake Storage Gen2 staging implementation."""

    def __init__(self, config: StagingConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create ADLS client."""
        if self._client is None:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.storage.filedatalake import DataLakeServiceClient
            except ImportError as e:
                raise ImportError(
                    get_package_install_message(
                        "azure-storage-file-datalake azure-identity",
                        "azure-storage-file-datalake required for Azure ADLS staging.",
                    )
                ) from e

            # Parse account from container@account.dfs.core.windows.net
            netloc = self.config.bucket
            if "@" not in netloc:
                raise ValueError(f"Invalid ADLS URI format: {self.config.uri}")
            container, account_host = netloc.split("@", 1)

            account_url = f"https://{account_host}"
            credential = DefaultAzureCredential()

            service_client = DataLakeServiceClient(account_url, credential=credential)
            self._client = service_client.get_file_system_client(container)
            self._container = container

        return self._client

    def _full_path(self, remote_path: str) -> str:
        """Get full ADLS path including prefix."""
        if self.config.prefix:
            return f"{self.config.prefix.rstrip('/')}/{remote_path}"
        return remote_path

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Upload file to Azure ADLS."""
        client = self._get_client()
        file_path = self._full_path(remote_path)

        file_client = client.get_file_client(file_path)
        with open(local_path, "rb") as f:
            file_client.upload_data(f, overwrite=True)

        return f"{self.config.uri.rstrip('/')}/{remote_path}"

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists in ADLS."""
        client = self._get_client()
        file_path = self._full_path(remote_path)
        file_client = client.get_file_client(file_path)

        try:
            file_client.get_file_properties()
            return True
        except Exception:
            return False

    def list_files(self, remote_prefix: str) -> list[str]:
        """List files in ADLS under prefix."""
        client = self._get_client()
        prefix = self._full_path(remote_prefix)

        paths = client.get_paths(path=prefix)
        return [path.name for path in paths if not path.is_directory]

    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete file or directory from ADLS."""
        client = self._get_client()
        file_path = self._full_path(remote_path)

        if recursive:
            dir_client = client.get_directory_client(file_path)
            dir_client.delete_directory()
        else:
            file_client = client.get_file_client(file_path)
            file_client.delete_file()


class AzureBlobStaging(CloudSparkStaging):
    """Azure Blob Storage staging implementation."""

    def __init__(self, config: StagingConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create Blob client."""
        if self._client is None:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.storage.blob import ContainerClient
            except ImportError as e:
                raise ImportError(
                    get_package_install_message(
                        "azure-storage-blob azure-identity",
                        "azure-storage-blob required for Azure Blob staging.",
                    )
                ) from e

            credential = DefaultAzureCredential()
            # Parse container URL from config
            self._client = ContainerClient(
                account_url=f"https://{self.config.bucket.split('@')[1] if '@' in self.config.bucket else self.config.bucket}",
                container_name=self.config.bucket.split("@")[0] if "@" in self.config.bucket else self.config.bucket,
                credential=credential,
            )

        return self._client

    def _full_path(self, remote_path: str) -> str:
        """Get full blob path including prefix."""
        if self.config.prefix:
            return f"{self.config.prefix.rstrip('/')}/{remote_path}"
        return remote_path

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Upload file to Azure Blob."""
        client = self._get_client()
        blob_path = self._full_path(remote_path)

        blob_client = client.get_blob_client(blob_path)
        with open(local_path, "rb") as f:
            blob_client.upload_blob(f, overwrite=True)

        return f"{self.config.uri.rstrip('/')}/{remote_path}"

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists in Azure Blob."""
        client = self._get_client()
        blob_path = self._full_path(remote_path)
        blob_client = client.get_blob_client(blob_path)

        return blob_client.exists()

    def list_files(self, remote_prefix: str) -> list[str]:
        """List files in Azure Blob under prefix."""
        client = self._get_client()
        prefix = self._full_path(remote_prefix)

        blobs = client.list_blobs(name_starts_with=prefix)
        return [blob.name for blob in blobs]

    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete file or directory from Azure Blob."""
        client = self._get_client()

        if recursive:
            blobs = client.list_blobs(name_starts_with=self._full_path(remote_path))
            for blob in blobs:
                client.delete_blob(blob.name)
        else:
            blob_path = self._full_path(remote_path)
            client.delete_blob(blob_path)


class DBFSStaging(CloudSparkStaging):
    """Databricks DBFS/Unity Catalog Volumes staging implementation."""

    def __init__(self, config: StagingConfig) -> None:
        super().__init__(config)
        self._client: Any = None

    def _get_client(self) -> Any:
        """Get or create DBFS client via Databricks SDK."""
        if self._client is None:
            try:
                from databricks.sdk import WorkspaceClient
            except ImportError as e:
                raise ImportError(
                    get_package_install_message("databricks-sdk", "databricks-sdk required for DBFS staging.")
                ) from e

            self._client = WorkspaceClient()

        return self._client

    def _full_path(self, remote_path: str) -> str:
        """Get full DBFS path including prefix."""
        if self.config.prefix:
            return f"/{self.config.prefix.strip('/')}/{remote_path}"
        return f"/{remote_path}"

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Upload file to DBFS."""
        client = self._get_client()
        dbfs_path = self._full_path(remote_path)

        with open(local_path, "rb") as f:
            client.dbfs.upload(dbfs_path, f, overwrite=True)

        return f"dbfs:{dbfs_path}"

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists in DBFS."""
        client = self._get_client()
        dbfs_path = self._full_path(remote_path)

        try:
            client.dbfs.get_status(dbfs_path)
            return True
        except Exception:
            return False

    def list_files(self, remote_prefix: str) -> list[str]:
        """List files in DBFS under prefix."""
        client = self._get_client()
        dbfs_path = self._full_path(remote_prefix)

        try:
            files = client.dbfs.list(dbfs_path)
            return [f.path for f in files if not f.is_dir]
        except Exception:
            return []

    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete file or directory from DBFS."""
        client = self._get_client()
        dbfs_path = self._full_path(remote_path)
        client.dbfs.delete(dbfs_path, recursive=recursive)


class LocalStaging(CloudSparkStaging):
    """Local filesystem staging for testing."""

    def __init__(self, config: StagingConfig) -> None:
        super().__init__(config)
        self._base_path = Path(config.prefix or config.uri.replace("file://", ""))

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        progress_callback: Callable[[UploadProgress], None] | None = None,
    ) -> str:
        """Copy file to local staging directory."""
        import shutil

        dest = self._base_path / remote_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(local_path, dest)

        return f"file://{dest}"

    def file_exists(self, remote_path: str) -> bool:
        """Check if file exists locally."""
        return (self._base_path / remote_path).exists()

    def list_files(self, remote_prefix: str) -> list[str]:
        """List files under local prefix."""
        prefix_path = self._base_path / remote_prefix
        if not prefix_path.exists():
            return []
        return [str(p.relative_to(self._base_path)) for p in prefix_path.rglob("*") if p.is_file()]

    def delete_path(self, remote_path: str, recursive: bool = False) -> None:
        """Delete local file or directory."""
        import shutil

        path = self._base_path / remote_path
        if path.is_dir() and recursive:
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()
