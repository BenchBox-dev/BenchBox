"""Shared fixtures for platform integration tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import socket
import time
from pathlib import Path
from typing import Any

import pytest


def skip_unless_docker_service(host: str, port: int, *, timeout: float = 2.0, platform: str = "") -> None:
    """Skip test if a Docker service is not reachable.

    Attempts a TCP connection to host:port. If the connection fails or times out,
    the test is skipped with a descriptive message.

    Args:
        host: Hostname or IP of the service
        port: TCP port to probe
        timeout: Connection timeout in seconds (default 2.0)
        platform: Platform name for the skip message (defaults to host:port)
    """
    label = platform or f"{host}:{port}"
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
    except (ConnectionRefusedError, TimeoutError, OSError):
        pytest.skip(f"Skipping {label} Docker test: service not reachable at {host}:{port}")


def get_env_or_skip(var_name: str, platform_name: str) -> str:
    """Get environment variable or skip test if not set.

    Args:
        var_name: Name of environment variable
        platform_name: Name of platform for error message

    Returns:
        Value of environment variable

    Raises:
        pytest.skip: If environment variable is not set
    """
    value = os.getenv(var_name)
    if not value:
        pytest.skip(f"Skipping {platform_name} live test: {var_name} not set")
    assert value is not None  # Type narrowing after skip
    return value


def has_resolvable_s3_upload_credentials(source: dict[str, Any]) -> bool:
    """Return whether boto3 can resolve AWS credentials for S3 uploads."""
    try:
        import boto3
    except ImportError:
        return False

    session = boto3.Session(
        aws_access_key_id=source.get("aws_access_key_id"),
        aws_secret_access_key=source.get("aws_secret_access_key"),
        aws_session_token=source.get("aws_session_token"),
        region_name=source.get("aws_region"),
    )
    return session.get_credentials() is not None


@pytest.fixture(scope="module")
def unique_test_schema() -> str:
    """Generate unique schema name for test isolation.

    Returns:
        Schema name with timestamp suffix
    """
    timestamp = int(time.time())
    return f"benchbox_test_{timestamp}"


@pytest.fixture(scope="module")
def test_scale_factor() -> float:
    """Get scale factor for live tests (defaults to 0.01 for minimal cost).

    Returns:
        Scale factor for benchmark data generation
    """
    return float(os.getenv("BENCHBOX_TEST_SCALE_FACTOR", "0.01"))


@pytest.fixture(scope="module")
def test_output_dir(tmp_path_factory) -> Path:
    """Create temporary output directory for live test data.

    Args:
        tmp_path_factory: pytest fixture for creating temp directories

    Returns:
        Path to temporary output directory
    """
    return tmp_path_factory.mktemp("live_test_output")


# ==============================================================================
# Databricks Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def databricks_credentials() -> dict[str, str]:
    """Get Databricks credentials from environment.

    Returns:
        Dictionary with Databricks connection parameters

    Raises:
        pytest.skip: If required credentials are not set
    """
    return {
        "server_hostname": get_env_or_skip("DATABRICKS_HOST", "Databricks"),
        "http_path": get_env_or_skip("DATABRICKS_HTTP_PATH", "Databricks"),
        "access_token": get_env_or_skip("DATABRICKS_TOKEN", "Databricks"),
        "catalog": os.getenv("DATABRICKS_CATALOG", "main"),
        "schema": os.getenv("DATABRICKS_SCHEMA", "default"),
    }


@pytest.fixture(scope="module")
def live_databricks_adapter(databricks_credentials):
    """Create Databricks adapter with live credentials.

    Args:
        databricks_credentials: Fixture providing credentials

    Yields:
        DatabricksAdapter instance connected to live workspace
    """
    from benchbox.platforms.databricks import DatabricksAdapter

    adapter = DatabricksAdapter(**databricks_credentials)
    yield adapter
    # No cleanup needed - adapter manages its own connections


# ==============================================================================
# Snowflake Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def snowflake_credentials() -> dict[str, str | None]:
    """Get Snowflake credentials from environment.

    Returns:
        Dictionary with Snowflake connection parameters

    Raises:
        pytest.skip: If required credentials are not set
    """
    return {
        "account": get_env_or_skip("SNOWFLAKE_ACCOUNT", "Snowflake"),
        "username": get_env_or_skip("SNOWFLAKE_USERNAME", "Snowflake"),
        "password": get_env_or_skip("SNOWFLAKE_PASSWORD", "Snowflake"),
        "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
        "database": os.getenv("SNOWFLAKE_DATABASE", "BENCHBOX"),
        "schema": os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC"),
        "role": os.getenv("SNOWFLAKE_ROLE"),
    }


@pytest.fixture(scope="module")
def live_snowflake_adapter(snowflake_credentials):
    """Create Snowflake adapter with live credentials.

    Args:
        snowflake_credentials: Fixture providing credentials

    Yields:
        SnowflakeAdapter instance connected to live account
    """
    from benchbox.platforms.snowflake import SnowflakeAdapter

    adapter = SnowflakeAdapter(**snowflake_credentials)
    yield adapter
    # No cleanup needed - adapter manages its own connections


# ==============================================================================
# BigQuery Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def bigquery_credentials() -> dict[str, str | None]:
    """Get BigQuery credentials from environment.

    Returns:
        Dictionary with BigQuery connection parameters

    Raises:
        pytest.skip: If required credentials are not set
    """
    # Check for service account credentials
    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        pytest.skip("Skipping BigQuery live test: GOOGLE_APPLICATION_CREDENTIALS not set")

    return {
        "project_id": get_env_or_skip("BIGQUERY_PROJECT", "BigQuery"),
        "dataset_id": os.getenv("BIGQUERY_DATASET", "benchbox_test"),
        "location": os.getenv("BIGQUERY_LOCATION", "US"),
        "storage_bucket": os.getenv("BIGQUERY_STORAGE_BUCKET"),
    }


@pytest.fixture(scope="module")
def live_bigquery_adapter(bigquery_credentials):
    """Create BigQuery adapter with live credentials.

    Args:
        bigquery_credentials: Fixture providing credentials

    Yields:
        BigQueryAdapter instance connected to live project
    """
    from benchbox.platforms.bigquery import BigQueryAdapter

    adapter = BigQueryAdapter(**bigquery_credentials)
    yield adapter
    # No cleanup needed - adapter manages its own connections


# ==============================================================================
# Common Cleanup Fixtures
# ==============================================================================


@pytest.fixture
def cleanup_test_schema(request):
    """Cleanup fixture to remove test schemas after tests complete.

    Usage:
        def test_something(live_adapter, cleanup_test_schema):
            schema_name = "test_schema"
            cleanup_test_schema(live_adapter, schema_name)
            # ... test code that creates schema ...

    Args:
        request: pytest request object

    Returns:
        Cleanup function that accepts (adapter, schema_name)
    """
    schemas_to_cleanup = []

    def register_cleanup(adapter, schema_name: str):
        """Register a schema for cleanup after test."""
        schemas_to_cleanup.append((adapter, schema_name))

    yield register_cleanup

    # Cleanup all registered schemas
    for adapter, schema_name in schemas_to_cleanup:
        try:
            connection = adapter.create_connection()
            try:
                # Try to drop the schema - implementation varies by platform
                adapter.execute_sql(connection, f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
            except Exception as e:
                # Log but don't fail - cleanup is best-effort
                print(f"Warning: Failed to cleanup schema {schema_name}: {e}")
            finally:
                adapter.close_connection(connection)
        except Exception as e:
            print(f"Warning: Failed to connect for cleanup of schema {schema_name}: {e}")


# ==============================================================================
# Redshift Fixtures
# ==============================================================================


def has_redshift_credentials() -> bool:
    """Return True if Redshift credentials are available from any source.

    Checks ~/.benchbox/credentials.yaml first, then falls back to env vars.
    Used for module-level skipif conditions.
    """
    if os.getenv("REDSHIFT_HOST"):
        return True
    try:
        from benchbox.security.credentials import CredentialManager

        creds = CredentialManager().get_platform_credentials("redshift")
        return bool(creds and creds.get("host"))
    except Exception:
        return False


def _get_redshift_credentials() -> dict[str, Any]:
    """Load Redshift credentials from credentials file or env vars.

    Returns:
        Dictionary of connection parameters for RedshiftAdapter

    Raises:
        pytest.skip: If no credentials are available from any source
    """

    def _build_optional_redshift_config(source: dict[str, Any]) -> dict[str, Any]:
        """Extract optional Redshift staging/auth settings from a credential source."""
        staging_root = source.get("staging_root")
        default_output_location = source.get("default_output_location")
        if (
            not staging_root
            and isinstance(default_output_location, str)
            and default_output_location.startswith("s3://")
        ):
            staging_root = default_output_location

        return {
            "schema": source.get("schema", "public"),
            "s3_bucket": source.get("s3_bucket"),
            "s3_prefix": source.get("s3_prefix"),
            "staging_root": staging_root,
            "iam_role": source.get("iam_role"),
            "aws_access_key_id": source.get("aws_access_key_id"),
            "aws_secret_access_key": source.get("aws_secret_access_key"),
            "aws_session_token": source.get("aws_session_token"),
            "aws_region": source.get("aws_region"),
        }

    # Try credentials file first
    try:
        from benchbox.security.credentials import CredentialManager

        creds = CredentialManager().get_platform_credentials("redshift")
        if creds and creds.get("host"):
            credentials = {
                "host": creds["host"],
                "port": int(creds.get("port", 5439)),
                "username": creds["username"],
                "password": creds["password"],
                "database": creds.get("database", "dev"),
            }
            credentials.update(_build_optional_redshift_config(creds))
            return credentials
    except Exception:
        pass

    # Fall back to env vars
    host = os.getenv("REDSHIFT_HOST")
    if not host:
        pytest.skip(
            "Skipping Redshift live test: no credentials in ~/.benchbox/credentials.yaml or REDSHIFT_HOST env var"
        )
    user = os.getenv("REDSHIFT_USER") or os.getenv("REDSHIFT_USERNAME")
    if not user:
        pytest.skip("Skipping Redshift live test: REDSHIFT_USER not set")
    password = os.getenv("REDSHIFT_PASSWORD")
    if not password:
        pytest.skip("Skipping Redshift live test: REDSHIFT_PASSWORD not set")
    credentials = {
        "host": host,
        "port": int(os.getenv("REDSHIFT_PORT", "5439")),
        "username": user,
        "password": password,
        "database": os.getenv("REDSHIFT_DATABASE", "dev"),
        "schema": os.getenv("REDSHIFT_SCHEMA", "public"),
        "s3_bucket": os.getenv("REDSHIFT_S3_BUCKET"),
        "iam_role": os.getenv("REDSHIFT_IAM_ROLE"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY"),
        "aws_session_token": os.getenv("AWS_SESSION_TOKEN"),
        "aws_region": os.getenv("AWS_DEFAULT_REGION") or os.getenv("AWS_REGION"),
    }
    return credentials


@pytest.fixture(scope="module")
def redshift_credentials() -> dict[str, Any]:
    """Get Redshift credentials from credentials file or environment.

    Returns:
        Dictionary with Redshift connection parameters

    Raises:
        pytest.skip: If required credentials are not available
    """
    return _get_redshift_credentials()


@pytest.fixture(scope="module")
def redshift_staging_credentials(redshift_credentials) -> dict[str, Any]:
    """Return Redshift credentials only when S3 staging is configured."""
    if not (redshift_credentials.get("staging_root") or redshift_credentials.get("s3_bucket")):
        pytest.skip(
            "Skipping Redshift live staging test: configure default_output_location in credentials "
            "or set REDSHIFT_S3_BUCKET"
        )
    if not has_resolvable_s3_upload_credentials(redshift_credentials):
        pytest.skip(
            "Skipping Redshift live staging test: configure AWS credentials for S3 uploads "
            "(env vars, AWS profile, or shared credentials file)"
        )
    return redshift_credentials


@pytest.fixture(scope="module")
def live_redshift_adapter(redshift_credentials):
    """Create Redshift adapter with live credentials.

    Args:
        redshift_credentials: Fixture providing credentials

    Yields:
        RedshiftAdapter instance connected to live cluster
    """
    from benchbox.platforms.redshift import RedshiftAdapter

    adapter = RedshiftAdapter(**redshift_credentials)
    yield adapter


# ==============================================================================
# Firebolt Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def firebolt_credentials() -> dict[str, str]:
    """Get Firebolt Cloud credentials from environment.

    Returns:
        Dictionary with Firebolt connection parameters

    Raises:
        pytest.skip: If required credentials are not set
    """
    return {
        "client_id": get_env_or_skip("FIREBOLT_CLIENT_ID", "Firebolt"),
        "client_secret": get_env_or_skip("FIREBOLT_CLIENT_SECRET", "Firebolt"),
        "account_name": get_env_or_skip("FIREBOLT_ACCOUNT_NAME", "Firebolt"),
        "engine_name": get_env_or_skip("FIREBOLT_ENGINE_NAME", "Firebolt"),
        "database": os.getenv("FIREBOLT_DATABASE", "benchbox"),
    }


@pytest.fixture(scope="module")
def live_firebolt_adapter(firebolt_credentials):
    """Create Firebolt adapter with live credentials.

    Yields:
        FireboltAdapter instance connected to live cloud engine
    """
    from benchbox.platforms.firebolt import FireboltAdapter

    adapter = FireboltAdapter(**firebolt_credentials)
    yield adapter


# ==============================================================================
# Starburst Galaxy (Trino) Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def starburst_credentials() -> dict[str, str | None]:
    """Get Starburst Galaxy credentials from environment.

    Returns:
        Dictionary with Starburst/Trino connection parameters

    Raises:
        pytest.skip: If required credentials are not set
    """
    return {
        "host": get_env_or_skip("STARBURST_HOST", "Starburst Galaxy"),
        "username": get_env_or_skip("STARBURST_USER", "Starburst Galaxy"),
        "password": get_env_or_skip("STARBURST_PASSWORD", "Starburst Galaxy"),
        "catalog": os.getenv("STARBURST_CATALOG", "tpch"),
        "schema": os.getenv("STARBURST_SCHEMA", "sf1"),
        "port": int(os.getenv("STARBURST_PORT", "443")),
    }


@pytest.fixture(scope="module")
def live_starburst_adapter(starburst_credentials):
    """Create Starburst Galaxy adapter with live credentials.

    Uses the Trino adapter since Starburst is Trino-compatible.

    Yields:
        TrinoAdapter instance connected to live Starburst Galaxy cluster
    """
    from benchbox.platforms.trino import TrinoAdapter

    adapter = TrinoAdapter(**starburst_credentials)
    yield adapter


# ==============================================================================
# MotherDuck Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def motherduck_credentials() -> dict[str, str]:
    """Get MotherDuck credentials from environment.

    Returns:
        Dictionary with MotherDuck connection parameters

    Raises:
        pytest.skip: If required credentials are not set
    """
    return {
        "token": get_env_or_skip("MOTHERDUCK_TOKEN", "MotherDuck"),
        "database": os.getenv("MOTHERDUCK_DATABASE", "benchbox_test"),
    }


@pytest.fixture(scope="module")
def live_motherduck_adapter(motherduck_credentials):
    """Create MotherDuck adapter with live credentials.

    Yields:
        MotherDuckAdapter instance connected to live cloud
    """
    from benchbox.platforms.motherduck import MotherDuckAdapter

    adapter = MotherDuckAdapter(**motherduck_credentials)
    yield adapter


# ==============================================================================
# pg_duckdb Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def live_pg_duckdb_adapter():
    """Create pg_duckdb adapter connected to a local Docker instance.

    Yields:
        PgDuckDBAdapter instance connected to PostgreSQL with pg_duckdb extension
    """
    from benchbox.platforms.pg_duckdb import PgDuckDBAdapter

    host = os.getenv("PG_DUCKDB_HOST", "localhost")
    port = int(os.getenv("PG_DUCKDB_PORT", "5432"))
    skip_unless_docker_service(host, port, platform="pg_duckdb")
    adapter = PgDuckDBAdapter(
        host=host,
        port=port,
        username=os.getenv("PG_DUCKDB_USER", "benchbox"),
        password=os.getenv("PG_DUCKDB_PASSWORD", "benchbox"),
        database=os.getenv("PG_DUCKDB_DATABASE", "benchbox_test"),
    )
    yield adapter


# ==============================================================================
# pg_mooncake Fixtures
# ==============================================================================


@pytest.fixture(scope="module")
def live_pg_mooncake_adapter():
    """Create pg_mooncake adapter connected to a local Docker instance.

    Yields:
        PgMooncakeAdapter instance connected to PostgreSQL with pg_mooncake extension
    """
    from benchbox.platforms.pg_mooncake import PgMooncakeAdapter

    host = os.getenv("PG_MOONCAKE_HOST", "localhost")
    port = int(os.getenv("PG_MOONCAKE_PORT", "5433"))
    skip_unless_docker_service(host, port, platform="pg_mooncake")
    adapter = PgMooncakeAdapter(
        host=host,
        port=port,
        username=os.getenv("PG_MOONCAKE_USER", "benchbox"),
        password=os.getenv("PG_MOONCAKE_PASSWORD", "benchbox"),
        database=os.getenv("PG_MOONCAKE_DATABASE", "benchbox_test"),
    )
    yield adapter
