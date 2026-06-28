"""Cloud storage path utilities for BenchBox.

This module provides minimal abstraction over cloud storage paths using cloudpathlib,
allowing benchmarks to work with cloud storage locations while maintaining simplicity.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Protocol, Union, runtime_checkable
from urllib.parse import urlparse

from benchbox.utils.dependencies import get_install_command, get_package_install_message

_UNLOADED_CLOUDPATHLIB = object()
CloudPath: Any = _UNLOADED_CLOUDPATHLIB
MissingCredentialsError: type[BaseException] = Exception


def _load_cloudpathlib() -> tuple[Any | None, type[BaseException]]:
    """Load cloudpathlib only when a cloud path operation actually needs it."""
    global CloudPath, MissingCredentialsError
    if CloudPath is _UNLOADED_CLOUDPATHLIB:
        try:
            from cloudpathlib import CloudPath as LoadedCloudPath
            from cloudpathlib.exceptions import MissingCredentialsError as LoadedMissingCredentialsError
        except ImportError:
            CloudPath = None
            MissingCredentialsError = Exception
        else:
            CloudPath = LoadedCloudPath
            MissingCredentialsError = LoadedMissingCredentialsError
    return CloudPath, MissingCredentialsError


logger = logging.getLogger(__name__)


class DatabricksPath:
    """Wrapper around a local path that stores Databricks UC Volume target.

    This class uses composition instead of inheritance to avoid Path subclassing
    issues. It wraps a local temporary directory path and stores the target
    dbfs:// path for later upload by the Databricks adapter.

    The class implements the os.PathLike protocol and delegates most operations
    to the underlying Path object.
    """

    def __init__(self, local_path: Union[str, Path], dbfs_target: str):
        """Create a new DatabricksPath instance.

        Args:
            local_path: Local filesystem path (usually a temp directory)
            dbfs_target: Target dbfs:// path for upload
        """
        self._path = Path(local_path) if not isinstance(local_path, Path) else local_path
        self._dbfs_target = dbfs_target

    def __fspath__(self) -> str:
        """Return the file system path (os.PathLike protocol)."""
        return str(self._path)

    def __str__(self) -> str:
        """String representation returns the local path."""
        return str(self._path)

    def __repr__(self) -> str:
        """Repr shows both local and target paths."""
        return f"DatabricksPath({self._path!r}, dbfs_target={self._dbfs_target!r})"

    def __truediv__(self, other: Union[str, Path]) -> Path:
        """Path joining operator - returns regular Path."""
        return self._path / other

    def __eq__(self, other: object) -> bool:
        """Equality comparison."""
        if isinstance(other, DatabricksPath):
            return self._path == other._path and self._dbfs_target == other._dbfs_target
        elif isinstance(other, (str, Path)):
            return self._path == Path(other)
        return False

    def __hash__(self) -> int:
        """Hash based on local path."""
        return hash(self._path)

    @property
    def dbfs_target(self) -> str:
        """Get the target dbfs:// path for this local directory."""
        return self._dbfs_target

    # Delegate common Path operations
    def exists(self) -> bool:
        """Check if the local path exists."""
        return self._path.exists()

    def mkdir(self, parents: bool = True, exist_ok: bool = True) -> None:
        """Create the local directory."""
        self._path.mkdir(parents=parents, exist_ok=exist_ok)

    def is_dir(self) -> bool:
        """Check if the local path is a directory."""
        return self._path.is_dir()

    def is_file(self) -> bool:
        """Check if the local path is a file."""
        return self._path.is_file()

    def iterdir(self):
        """Iterate over directory contents."""
        return self._path.iterdir()

    def glob(self, pattern: str):
        """Glob for files matching pattern."""
        return self._path.glob(pattern)

    @property
    def name(self) -> str:
        """Get the final path component."""
        return self._path.name

    @property
    def parent(self) -> Path:
        """Get the parent directory."""
        return self._path.parent

    @property
    def parts(self) -> tuple:
        """Get path components."""
        return self._path.parts

    def as_posix(self) -> str:
        """Return the path as a POSIX string."""
        return self._path.as_posix()

    def resolve(self, strict: bool = False) -> Path:
        """Resolve to absolute path."""
        return self._path.resolve(strict=strict)


class CloudStagingPath:
    """Universal wrapper for persistent local staging + cloud target pattern.

    This class provides a consistent approach for all cloud storage providers
    (GCS, S3, Azure, etc.) by maintaining:
    - local_path: Persistent local directory for data generation and caching
    - cloud_target: Target cloud URI for upload (gs://, s3://, etc.)

    The class implements the os.PathLike protocol and delegates filesystem
    operations to the local path, allowing generators to work with local files
    while the platform adapter handles uploads to the cloud target.

    This eliminates the need for temporary directories and enables data caching
    between runs, significantly improving performance.
    """

    def __init__(self, local_path: Union[str, Path], cloud_target: str):
        """Create a new CloudStagingPath instance.

        Args:
            local_path: Persistent local filesystem path for staging/caching
            cloud_target: Target cloud URI (gs://, s3://, etc.) for upload
        """
        self._path = Path(local_path) if not isinstance(local_path, Path) else local_path
        self._cloud_target = cloud_target

    def __fspath__(self) -> str:
        """Return the file system path (os.PathLike protocol)."""
        return str(self._path)

    def __str__(self) -> str:
        """String representation returns the local path."""
        return str(self._path)

    def __repr__(self) -> str:
        """Repr shows both local and cloud paths."""
        return f"CloudStagingPath({self._path!r}, cloud_target={self._cloud_target!r})"

    def __truediv__(self, other: Union[str, Path]) -> Path:
        """Path joining operator - returns regular Path."""
        return self._path / other

    def __eq__(self, other: object) -> bool:
        """Equality comparison."""
        if isinstance(other, CloudStagingPath):
            return self._path == other._path and self._cloud_target == other._cloud_target
        elif isinstance(other, (str, Path)):
            return self._path == Path(other)
        return False

    def __hash__(self) -> int:
        """Hash based on local path."""
        return hash(self._path)

    @property
    def cloud_target(self) -> str:
        """Get the target cloud URI for this staging directory."""
        return self._cloud_target

    # Delegate common Path operations to local path
    def exists(self) -> bool:
        """Check if the local path exists."""
        return self._path.exists()

    def mkdir(self, parents: bool = True, exist_ok: bool = True) -> None:
        """Create the local directory."""
        self._path.mkdir(parents=parents, exist_ok=exist_ok)

    def is_dir(self) -> bool:
        """Check if the local path is a directory."""
        return self._path.is_dir()

    def is_file(self) -> bool:
        """Check if the local path is a file."""
        return self._path.is_file()

    def iterdir(self):
        """Iterate over directory contents."""
        return self._path.iterdir()

    def glob(self, pattern: str):
        """Glob for files matching pattern."""
        return self._path.glob(pattern)

    @property
    def name(self) -> str:
        """Get the final path component."""
        return self._path.name

    @property
    def parent(self) -> Path:
        """Get the parent directory."""
        return self._path.parent

    @property
    def parts(self) -> tuple:
        """Get path components."""
        return self._path.parts

    def as_posix(self) -> str:
        """Return the path as a POSIX string."""
        return self._path.as_posix()

    def resolve(self, strict: bool = False) -> Path:
        """Resolve to absolute path."""
        return self._path.resolve(strict=strict)


@runtime_checkable
class RemoteFileSystemAdapter(Protocol):
    """Minimal adapter interface for remote file operations used by validation.

    Implementations should operate on absolute remote paths, including scheme
    (e.g., dbfs:/Volumes/.../file). Paths are treated as opaque strings.
    """

    def file_exists(self, remote_path: str) -> bool:  # pragma: no cover - interface
        ...

    def read_file(self, remote_path: str) -> bytes:  # pragma: no cover - interface
        ...

    def write_file(self, remote_path: str, content: bytes) -> None:  # pragma: no cover - interface
        ...

    def list_files(self, remote_path: str, pattern: str = "*") -> list[str]:  # pragma: no cover - interface
        ...


class DatabricksVolumeAdapter:
    """RemoteFileSystemAdapter implementation for Databricks UC Volumes (dbfs:/Volumes/...)."""

    def __init__(self, workspace_client: Any | None = None, *, host: str | None = None, token: str | None = None):
        try:
            from databricks.sdk import WorkspaceClient  # type: ignore
        except Exception as e:  # pragma: no cover - optional dependency
            raise ImportError(
                get_package_install_message("databricks-sdk", "databricks-sdk required for DatabricksVolumeAdapter.")
            ) from e

        if workspace_client is not None:
            self._ws = workspace_client
        else:
            # Let SDK auto-configure if host/token are None
            self._ws = WorkspaceClient(host=(f"https://{host}" if host else None), token=token)

    def _to_ws_path(self, remote_path: str) -> str:
        # Convert dbfs:/Volumes/... to /Volumes/...
        return remote_path.replace("dbfs:", "")

    def file_exists(self, remote_path: str) -> bool:
        path = self._to_ws_path(remote_path)
        try:
            info = self._ws.files.get(path)  # type: ignore[attr-defined]
            return bool(info)
        except Exception:
            # get() may raise if not found
            return False

    def read_file(self, remote_path: str) -> bytes:
        path = self._to_ws_path(remote_path)
        try:
            data = self._ws.files.download(path)  # type: ignore[attr-defined]
            # Some SDKs return bytes directly, others return a stream-like object
            if hasattr(data, "read"):
                return data.read()
            return bytes(data)
        except Exception as e:  # pragma: no cover - provider specific
            raise RuntimeError(f"Failed to read remote file: {remote_path}: {e}") from e

    def write_file(self, remote_path: str, content: bytes) -> None:
        path = self._to_ws_path(remote_path)
        try:
            from io import BytesIO

            self._ws.files.upload(path, BytesIO(content), overwrite=True)  # type: ignore[attr-defined]
        except Exception as e:  # pragma: no cover - provider specific
            raise RuntimeError(f"Failed to write remote file: {remote_path}: {e}") from e

    def list_files(self, remote_path: str, pattern: str = "*") -> list[str]:
        path = self._to_ws_path(remote_path)
        try:
            items = self._ws.files.list(path)  # type: ignore[attr-defined]
            names: List[str] = []
            for it in items or []:
                # Item may be dict or object; extract path/name best-effort
                p = getattr(it, "path", None) or getattr(it, "file_path", None) or str(it)
                names.append(p)
            # Best-effort pattern filter (suffix/prefix wildcard only)
            import fnmatch

            return [n for n in names if fnmatch.fnmatch(n.split("/")[-1], pattern)]
        except Exception:  # pragma: no cover - provider specific
            return []


def is_cloud_path(path: Union[str, Path]) -> bool:
    """Check if a path is a cloud storage path.

    Includes dbfs:// paths (Databricks File System / Unity Catalog Volumes)
    which require special handling via Databricks Files API.

    Args:
        path: Path to check

    Returns:
        True if path is a cloud storage path (s3://, gs://, abfss://, dbfs://, etc.)
    """
    # Convert Path objects (including CloudPath from cloudpathlib) to strings
    if not isinstance(path, str):
        path = str(path)

    parsed = urlparse(path)
    return parsed.scheme in ["s3", "gs", "gcs", "az", "abfss", "azure", "dbfs"]


def is_databricks_path(path: Union[str, Path]) -> bool:
    """Check if a path is a Databricks DBFS or UC Volume path.

    Databricks paths use the dbfs:// scheme but are NOT supported by
    cloudpathlib. They require special handling via Databricks Files API.

    Args:
        path: Path to check

    Returns:
        True if path is a dbfs:// path
    """
    if isinstance(path, Path):
        path = str(path)

    if not isinstance(path, str):
        return False

    parsed = urlparse(path)
    return parsed.scheme == "dbfs"


def validate_cloud_path_support() -> bool:
    """Validate that cloud path support is available.

    Returns:
        True if cloudpathlib is available, False otherwise
    """
    cloud_path, _ = _load_cloudpathlib()
    return cloud_path is not None


def create_path_handler(path: Union[str, Path]) -> Union[Path, CloudPath, DatabricksPath]:
    """Create appropriate path handler for local or cloud paths.

    Note: dbfs:// paths (Databricks UC Volumes) cannot be handled directly by
    cloudpathlib. For these paths, we create a local temporary directory for
    data generation and store the target dbfs:// path as an attribute. The actual
    upload is handled by DatabricksAdapter during the load phase.

    Args:
        path: Local or cloud storage path (or already-created DatabricksPath/CloudPath)

    Returns:
        Path object for local paths, CloudPath for cloud paths,
        DatabricksPath for dbfs:// paths (either created or passed through)

    Raises:
        ImportError: If cloud path is provided but cloudpathlib not installed
        ValueError: If cloud path format is invalid
    """
    # If already a DatabricksPath instance, return as-is (avoids double-wrapping)
    if isinstance(path, DatabricksPath):
        return path

    # If already a CloudPath instance, return as-is (avoids double-wrapping)
    # Check if CloudPath is actually a class type, not None or a mock
    cloud_path_cls = CloudPath if CloudPath is not _UNLOADED_CLOUDPATHLIB else None
    if cloud_path_cls is not None and hasattr(cloud_path_cls, "__mro__") and isinstance(path, cloud_path_cls):
        return path

    # Handle Databricks paths specially - they require local generation + upload
    if is_databricks_path(path):
        path_str = str(path)

        # Validate dbfs:// path format for UC Volumes
        if not path_str.startswith("dbfs:/Volumes/"):
            raise ValueError(
                f"Invalid dbfs:// path: {path_str}. "
                f"Unity Catalog Volumes must use format: dbfs:/Volumes/catalog/schema/volume"
            )

        # Create temporary directory for local data generation
        import tempfile

        temp_dir_str = tempfile.mkdtemp(prefix="benchbox_dbfs_")

        # Create DatabricksPath that wraps the temp directory and stores the target
        databricks_path = DatabricksPath(temp_dir_str, path_str)

        logger.info(f"Created temporary directory for dbfs:// path: {databricks_path}")
        logger.debug(f"Target UC Volume: {path_str}")

        return databricks_path

    if not is_cloud_path(path):
        return Path(path)

    cloud_path_cls, _ = _load_cloudpathlib()
    if cloud_path_cls is None:
        raise ImportError(f"cloudpathlib is required for cloud storage paths. {get_install_command('cloudstorage')}")

    try:
        return cloud_path_cls(str(path))
    except Exception as e:
        raise ValueError(f"Invalid cloud path format '{path}': {e}") from e


def get_remote_fs_adapter(remote_path: str) -> RemoteFileSystemAdapter:
    """Create a RemoteFileSystemAdapter for a remote path.

    Currently supports Databricks UC Volumes via dbfs:/ scheme. For other
    providers, placeholder implementations can be added in the future.
    """
    if is_databricks_path(remote_path):
        # Lazy import to avoid enforcing dependency when unused
        try:
            from databricks.sdk import WorkspaceClient  # type: ignore

            ws = WorkspaceClient()
            return DatabricksVolumeAdapter(ws)
        except ImportError as e:
            raise ImportError(
                get_package_install_message(
                    "databricks-sdk", "databricks-sdk required for Databricks UC Volume operations."
                )
            ) from e
        except Exception as e:
            raise RuntimeError(
                f"Failed to initialize Databricks workspace client: {e}. "
                "Ensure DATABRICKS_HOST and DATABRICKS_TOKEN are set correctly."
            ) from e

    # Placeholder adapters for future S3/GCS/Azure implementations could go here
    raise ValueError(f"No RemoteFileSystemAdapter available for path: {remote_path}")


def validate_cloud_credentials(path: Union[str, Path]) -> dict[str, Any]:
    """Validate cloud credentials for the given path.

    Args:
        path: Cloud storage path to validate

    Returns:
        Dictionary with validation results:
        - valid: bool indicating if credentials are valid
        - provider: string cloud provider (s3, gcs, azure, dbfs)
        - error: error message if validation failed
        - env_vars: list of environment variables checked
    """
    # Databricks paths use Databricks access tokens, validated separately by the adapter
    if is_databricks_path(path):
        return {
            "valid": True,  # Assume valid - will be checked by Databricks adapter
            "provider": "dbfs",
            "error": None,
            "env_vars": ["DATABRICKS_HOST", "DATABRICKS_HTTP_PATH", "DATABRICKS_TOKEN"],
        }

    if not is_cloud_path(path):
        return {"valid": True, "provider": "local", "error": None, "env_vars": []}

    cloud_path_cls, missing_credentials_error = _load_cloudpathlib()
    if cloud_path_cls is None:
        return {
            "valid": False,
            "provider": "unknown",
            "error": "cloudpathlib not installed",
            "env_vars": [],
        }

    parsed = urlparse(str(path))
    provider = parsed.scheme

    # Define expected environment variables for each provider
    env_checks = {
        "s3": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"],
        "gs": ["GOOGLE_APPLICATION_CREDENTIALS"],
        "gcs": ["GOOGLE_APPLICATION_CREDENTIALS"],
        "abfss": ["AZURE_STORAGE_ACCOUNT_NAME", "AZURE_STORAGE_ACCOUNT_KEY"],
        "azure": ["AZURE_STORAGE_ACCOUNT_NAME", "AZURE_STORAGE_ACCOUNT_KEY"],
    }
    expected_vars = env_checks.get(provider, [])

    # For S3, check multiple credential sources (not just env vars)
    if provider == "s3":
        # Check environment variables
        has_env_creds = bool(os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"))

        # Check AWS profile
        has_profile = bool(os.getenv("AWS_PROFILE"))

        # Check credentials file
        credentials_file = Path(os.path.expanduser("~/.aws/credentials"))
        has_credentials_file = credentials_file.exists()

        # Check config file with default profile
        config_file = Path(os.path.expanduser("~/.aws/config"))
        has_config_file = config_file.exists()

        if not any([has_env_creds, has_profile, has_credentials_file, has_config_file]):
            return {
                "valid": False,
                "provider": provider,
                "error": (
                    "No AWS credentials found. Configure via:\n"
                    "  - aws configure (creates ~/.aws/credentials)\n"
                    "  - AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY env vars\n"
                    "  - AWS_PROFILE env var with named profile"
                ),
                "env_vars": expected_vars,
            }
    else:
        # For other providers, check environment variables
        missing_vars = [var for var in expected_vars if not os.getenv(var)]

        if missing_vars:
            return {
                "valid": False,
                "provider": provider,
                "error": f"Missing environment variables: {', '.join(missing_vars)}",
                "env_vars": expected_vars,
            }

    # Try to create a cloud path to test credentials
    try:
        cloud_path = cloud_path_cls(str(path))
        # Test basic operations
        _ = cloud_path.exists()
        return {
            "valid": True,
            "provider": provider,
            "error": None,
            "env_vars": expected_vars,
        }
    except missing_credentials_error as e:
        return {
            "valid": False,
            "provider": provider,
            "error": f"Credential validation failed: {e}",
            "env_vars": expected_vars,
        }
    except Exception as e:
        return {
            "valid": False,
            "provider": provider,
            "error": f"Cloud path validation failed: {e}",
            "env_vars": expected_vars,
        }


def ensure_cloud_directory(
    path: Union[str, Path, CloudPath],
) -> Union[Path, CloudPath, DatabricksPath]:
    """Ensure cloud or local directory exists.

    Args:
        path: Directory path to create

    Returns:
        Path object (local or cloud)

    Raises:
        Exception: If directory creation fails
    """
    path_handler = create_path_handler(path) if isinstance(path, (str, Path)) else path

    try:
        if hasattr(path_handler, "mkdir"):
            # Local Path or CloudPath with mkdir
            path_handler.mkdir(parents=True, exist_ok=True)  # type: ignore
        elif hasattr(path_handler, "exists"):
            # CloudPath - some providers auto-create directories
            # Just check if we can access the path
            if not path_handler.exists():  # type: ignore
                # For cloud paths, we might need to create a marker file
                logger.info(f"Cloud directory will be created on first file write: {path_handler}")
    except Exception as e:
        logger.error(f"Failed to ensure directory exists: {path_handler} - {e}")
        raise

    return path_handler


def get_cloud_path_info(path: Union[str, Path]) -> dict[str, Any]:
    """Get information about a cloud path.

    Args:
        path: Path to analyze

    Returns:
        Dictionary with path information:
        - is_cloud: bool
        - provider: string provider name
        - bucket: bucket/container name (or None for dbfs)
        - path: path within bucket
        - credentials_valid: bool
        - volume_info: dict with catalog/schema/volume (for dbfs only)
    """
    # Handle Databricks paths specially - extract UC Volume components
    if is_databricks_path(path):
        parsed = urlparse(str(path))
        # For dbfs:/Volumes/catalog/schema/volume, extract components
        path_parts = parsed.path.lstrip("/").split("/")
        volume_info = {}
        if len(path_parts) >= 4 and path_parts[0] == "Volumes":
            volume_info = {
                "catalog": path_parts[1] if len(path_parts) > 1 else None,
                "schema": path_parts[2] if len(path_parts) > 2 else None,
                "volume": path_parts[3] if len(path_parts) > 3 else None,
            }

        return {
            "is_cloud": True,
            "provider": "dbfs",
            "bucket": None,  # Not applicable for DBFS
            "path": parsed.path,
            "credentials_valid": True,  # Checked by Databricks adapter
            "volume_info": volume_info,
        }

    if not is_cloud_path(path):
        return {
            "is_cloud": False,
            "provider": "local",
            "bucket": None,
            "path": str(path),
            "credentials_valid": True,
        }

    parsed = urlparse(str(path))
    scheme = parsed.scheme
    bucket = parsed.netloc
    cloud_path = parsed.path.lstrip("/")

    # Use scheme directly so provider identity matches the URI protocol.
    provider = scheme

    credential_check = validate_cloud_credentials(path)

    return {
        "is_cloud": True,
        "provider": provider,
        "bucket": bucket,
        "path": cloud_path,
        "credentials_valid": credential_check["valid"],
    }


class CloudPathAdapter:
    """Adapter to provide unified interface for local and cloud paths."""

    def __init__(self, path: Union[str, Path]):
        """Initialize path adapter.

        Args:
            path: Local or cloud storage path
        """
        self.original_path = str(path)
        self.is_cloud = is_cloud_path(path)
        self.path_handler = create_path_handler(path)

        if self.is_cloud:
            self.path_info = get_cloud_path_info(path)
        else:
            self.path_info = {"is_cloud": False, "provider": "local"}

    def exists(self) -> bool:
        """Check if path exists."""
        try:
            return self.path_handler.exists()  # type: ignore
        except Exception:
            return False

    def mkdir(self, parents: bool = True, exist_ok: bool = True) -> None:
        """Create directory."""
        if hasattr(self.path_handler, "mkdir"):
            self.path_handler.mkdir(parents=parents, exist_ok=exist_ok)  # type: ignore

    def __str__(self) -> str:
        """String representation."""
        return str(self.path_handler)

    def __truediv__(self, other: str) -> CloudPathAdapter:
        """Path joining operator."""
        if self.is_cloud:
            new_path = str(self.path_handler / other)  # type: ignore
        else:
            new_path = str(self.path_handler / other)
        return CloudPathAdapter(new_path)

    @property
    def name(self) -> str:
        """Get the name of the path."""
        return self.path_handler.name  # type: ignore

    @property
    def parent(self) -> CloudPathAdapter:
        """Get the parent directory."""
        return CloudPathAdapter(str(self.path_handler.parent))  # type: ignore


def format_cloud_usage_guide(provider: str) -> str:
    """Format usage guide for cloud storage provider.

    Args:
        provider: Cloud provider (s3, gs, azure, dbfs)

    Returns:
        Formatted usage guide string
    """
    guides = {
        "dbfs": """
Databricks DBFS / Unity Catalog Volumes Setup:
1. Set environment variables:
   export DATABRICKS_HOST=adb-123456789.azuredatabricks.net
   export DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123
   export DATABRICKS_TOKEN=your_personal_access_token

2. Create UC Volume (Unity Catalog):
   CREATE VOLUME IF NOT EXISTS workspace.benchbox.data;

3. Install databricks-sdk:
   uv add databricks-sdk

4. Usage example:
   benchbox run --platform databricks --benchmark tpch --scale 0.01 \\
                 --output dbfs:/Volumes/workspace/benchbox/data

Note: Data is generated locally, then uploaded to UC Volume during load phase.
      Schema and volume are created automatically if they don't exist.
""",
        "s3": """
AWS S3 Setup:
1. Set environment variables:
   export AWS_ACCESS_KEY_ID=your_access_key
   export AWS_SECRET_ACCESS_KEY=your_secret_key
   export AWS_DEFAULT_REGION=us-west-2

2. Usage example:
   benchbox run --platform duckdb --benchmark tpch --scale 0.01 \\
                 --output s3://your-bucket/benchbox/results
""",
        "gs": """
Google Cloud Storage Setup:
1. Set up authentication:
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

2. Usage example:
   benchbox run --platform duckdb --benchmark tpch --scale 0.01 \\
                 --output gs://your-bucket/benchbox/results
""",
        "azure": """
Azure Blob Storage Setup:
1. Set environment variables:
   export AZURE_STORAGE_ACCOUNT_NAME=your_account
   export AZURE_STORAGE_ACCOUNT_KEY=your_key

2. Usage example:
   benchbox run --platform duckdb --benchmark tpch --scale 0.01 \\
                 --output abfss://container@account.dfs.core.windows.net/benchbox/results
""",
    }

    return guides.get(provider, f"No setup guide available for provider: {provider}")


class CloudStorageGeneratorMixin:
    """Mixin class to add cloud storage upload functionality to data generators.

    This mixin provides a standardized way for all data generators to handle cloud storage
    uploads without duplicating code. Generators should inherit from this mixin and call
    the cloud upload methods when needed.
    """

    def _is_cloud_output(self, output_dir) -> bool:
        """Check if output directory is a cloud path."""
        return is_cloud_path(str(output_dir))

    def _handle_cloud_or_local_generation(self, output_dir, local_generate_func, verbose: bool = False):
        """Handle both cloud and local generation paths.

        With CloudStagingPath and DatabricksPath, both cloud and local paths now work the same way:
        - CloudStagingPath/DatabricksPath expose their local cache path via __fspath__()
        - Generators see the local path and work normally (validation, generation, caching)
        - Platform adapters access the cloud_target property for uploads

        This eliminates the need for temporary directories and enables persistent caching.

        Args:
            output_dir: Output directory (local path, CloudStagingPath, or DatabricksPath)
            local_generate_func: Function to generate data locally
            verbose: Whether to print verbose output

        Returns:
            Dictionary mapping table names to file paths
        """
        # Both local and cloud paths now use the same code path!
        # CloudStagingPath/DatabricksPath implement __fspath__() to return local path
        return local_generate_func(output_dir)
