"""Platform availability detection utilities for E2E tests.

Provides decorators and functions to detect platform availability
and skip tests when required dependencies or credentials are missing.
"""

from __future__ import annotations

import functools
import importlib
import os
import shutil
from typing import TYPE_CHECKING, Callable, TypeVar

import pytest

if TYPE_CHECKING:
    from collections.abc import Sequence

# Platform categories
LOCAL_PLATFORMS = frozenset({"duckdb", "sqlite", "datafusion", "postgresql", "timescaledb", "motherduck"})

CLOUD_PLATFORMS = frozenset(
    {
        "snowflake",
        "bigquery",
        "redshift",
        "athena",
        "databricks",
        "firebolt",
        "azure_synapse",
        "fabric_warehouse",
        "presto",
        "trino",
        "starburst",
        "clickhouse",
    }
)

DATAFRAME_PLATFORMS = frozenset(
    {
        "pandas-df",
        "polars-df",
        "dask-df",
        "pyspark-df",
        "modin-df",
        "cudf-df",
        "datafusion-df",
        "vaex-df",
        "ray-df",
    }
)

# Platform to module mapping for import checks
_PLATFORM_MODULES: dict[str, str | Sequence[str]] = {
    "duckdb": "duckdb",
    "sqlite": "sqlite3",
    "datafusion": "datafusion",
    "postgresql": "psycopg",
    "timescaledb": "psycopg",
    "motherduck": "duckdb",
    "snowflake": "snowflake.connector",
    "bigquery": "google.cloud.bigquery",
    "redshift": "redshift_connector",
    "athena": "pyathena",
    "databricks": "databricks.sql",
    "firebolt": "firebolt_db",
    "clickhouse": ("chdb", "clickhouse_driver"),
    "pandas-df": "pandas",
    "polars-df": "polars",
    "dask-df": "dask",
    "pyspark-df": "pyspark",
    "modin-df": "modin",
    "cudf-df": "cudf",
    "datafusion-df": "datafusion",
    "vaex-df": "vaex",
    "ray-df": "ray",
}

# Environment variables for cloud credentials
_CLOUD_CREDENTIAL_VARS: dict[str, Sequence[str]] = {
    "snowflake": ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER"),
    "bigquery": ("GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT"),
    "redshift": ("REDSHIFT_HOST", "REDSHIFT_USER"),
    "athena": ("AWS_ACCESS_KEY_ID", "AWS_REGION"),
    "databricks": ("DATABRICKS_HOST", "DATABRICKS_TOKEN"),
    "firebolt": ("FIREBOLT_CLIENT_ID", "FIREBOLT_CLIENT_SECRET"),
    "motherduck": ("MOTHERDUCK_TOKEN",),
    "starburst": ("STARBURST_HOST", "STARBURST_USER"),
}

F = TypeVar("F", bound=Callable[..., object])


def _check_module_available(module_name: str) -> bool:
    """Check if a Python module is importable."""
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def is_platform_available(platform: str) -> bool:
    """Check if a platform's dependencies are available.

    Args:
        platform: Platform name (e.g., 'duckdb', 'pandas-df')

    Returns:
        True if platform dependencies are importable
    """
    modules = _PLATFORM_MODULES.get(platform)
    if modules is None:
        return False

    if isinstance(modules, str):
        return _check_module_available(modules)

    # For platforms with multiple possible modules (e.g., clickhouse)
    return any(_check_module_available(m) for m in modules)


def is_dataframe_available(platform: str) -> bool:
    """Check if a DataFrame platform is available.

    Args:
        platform: DataFrame platform name (e.g., 'pandas-df', 'polars-df')

    Returns:
        True if DataFrame platform dependencies are importable
    """
    if platform not in DATAFRAME_PLATFORMS:
        return False
    if not is_platform_available(platform):
        return False
    # PySpark requires a working JVM to run; importing pyspark alone is not
    # sufficient. Guard against CI environments where pyspark is installed but
    # no Java is present (SparkSession would fail at startup).
    if platform == "pyspark-df" and shutil.which("java") is None:
        return False
    return True


def is_gpu_available() -> bool:
    """Check if CUDA GPU is available for cuDF tests.

    Returns:
        True if NVIDIA GPU with CUDA is detected
    """
    # Check for nvidia-smi
    if shutil.which("nvidia-smi") is None:
        return False

    # Try to import cudf
    try:
        import cudf  # noqa: F401

        return True
    except ImportError:
        return False


def has_cloud_credentials(platform: str) -> bool:
    """Check if required cloud credentials are configured.

    Checks ~/.benchbox/credentials.yaml first, then falls back to environment
    variables. The credentials file is the primary storage for cloud platform
    credentials (set via `benchbox platforms setup`).

    Args:
        platform: Cloud platform name (e.g., 'snowflake', 'bigquery')

    Returns:
        True if credentials are available from any source
    """
    # Check credentials file first
    try:
        from benchbox.security.credentials import CredentialManager

        creds = CredentialManager().get_platform_credentials(platform)
        metadata_keys = {"last_updated", "status", "error_message"}
        if creds and any(k not in metadata_keys for k in creds):
            return True
    except Exception:
        pass

    # Fall back to environment variables
    required_vars = _CLOUD_CREDENTIAL_VARS.get(platform)
    if required_vars is None:
        return False

    return all(os.environ.get(var) for var in required_vars)


def requires_platform(platform: str, reason: str | None = None) -> Callable[[F], F]:
    """Decorator to skip test if platform is not available.

    Args:
        platform: Platform name to check
        reason: Optional custom skip reason

    Returns:
        Decorator that skips test if platform unavailable
    """
    skip_reason = reason or f"Platform '{platform}' dependencies not available"

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            if not is_platform_available(platform):
                pytest.skip(skip_reason)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def requires_dataframe(platform: str, reason: str | None = None) -> Callable[[F], F]:
    """Decorator to skip test if DataFrame platform is not available.

    Args:
        platform: DataFrame platform name to check
        reason: Optional custom skip reason

    Returns:
        Decorator that skips test if DataFrame platform unavailable
    """
    skip_reason = reason or f"DataFrame platform '{platform}' not available"

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            if not is_dataframe_available(platform):
                pytest.skip(skip_reason)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def requires_gpu(reason: str | None = None) -> Callable[[F], F]:
    """Decorator to skip test if GPU is not available.

    Args:
        reason: Optional custom skip reason

    Returns:
        Decorator that skips test if GPU unavailable
    """
    skip_reason = reason or "NVIDIA GPU with CUDA not available"

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            if not is_gpu_available():
                pytest.skip(skip_reason)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


def requires_cloud_credentials(platform: str, reason: str | None = None) -> Callable[[F], F]:
    """Decorator to skip test if cloud credentials are not configured.

    Args:
        platform: Cloud platform name to check
        reason: Optional custom skip reason

    Returns:
        Decorator that skips test if credentials unavailable
    """
    skip_reason = reason or f"Cloud credentials for '{platform}' not configured"

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            if not has_cloud_credentials(platform):
                pytest.skip(skip_reason)
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator


# Pytest markers for platform categories
mark_e2e_local = pytest.mark.e2e_local
mark_e2e_cloud = pytest.mark.e2e_cloud
mark_e2e_dataframe = pytest.mark.e2e_dataframe
