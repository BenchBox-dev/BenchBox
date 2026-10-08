# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import os
import socket
import sys
import time
from pathlib import Path
from typing import Any

import pytest


def skip_unless_docker_service(host: str, port: int, *, timeout: float = 2.0, platform: str = "") -> None:
    label = platform or f"{host}:{port}"
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
    except (ConnectionRefusedError, TimeoutError, OSError):
        pytest.skip(f"Skipping {label} Docker test: service not reachable at {host}:{port}")


def get_env_or_skip(var_name: str, platform_name: str) -> str:
    value = os.getenv(var_name)
    if not value:
        pytest.skip(f"Skipping {platform_name} live test: {var_name} not set")
    assert value is not None
    return value


def has_resolvable_s3_upload_credentials(source: dict[str, Any]) -> bool:
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
    timestamp = int(time.time())
    return f"benchbox_test_{timestamp}"


@pytest.fixture(scope="module")
def test_scale_factor() -> float:
    return float(os.getenv("BENCHBOX_TEST_SCALE_FACTOR", "0.01"))


@pytest.fixture(scope="module")
def test_output_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("live_test_output")


@pytest.fixture(scope="module")
def databricks_credentials() -> dict[str, str]:
    return {
        "server_hostname": get_env_or_skip("DATABRICKS_HOST", "Databricks"),
        "http_path": get_env_or_skip("DATABRICKS_HTTP_PATH", "Databricks"),
        "access_token": get_env_or_skip("DATABRICKS_TOKEN", "Databricks"),
        "catalog": os.getenv("DATABRICKS_CATALOG", "main"),
        "schema": os.getenv("DATABRICKS_SCHEMA", "default"),
    }


@pytest.fixture(scope="module")
def live_databricks_adapter(databricks_credentials):
    from benchbox.platforms.databricks import DatabricksAdapter

    adapter = DatabricksAdapter(**databricks_credentials)
    yield adapter


@pytest.fixture(scope="module")
def snowflake_credentials() -> dict[str, str | None]:
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
    from benchbox.platforms.snowflake import SnowflakeAdapter

    adapter = SnowflakeAdapter(**snowflake_credentials)
    yield adapter


@pytest.fixture(scope="module")
def bigquery_credentials() -> dict[str, str | None]:
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
    from benchbox.platforms.bigquery import BigQueryAdapter

    adapter = BigQueryAdapter(**bigquery_credentials)
    yield adapter


@pytest.fixture
def cleanup_test_schema(request):
    schemas_to_cleanup = []

    def register_cleanup(adapter, schema_name: str):
        schemas_to_cleanup.append((adapter, schema_name))

    yield register_cleanup

    for adapter, schema_name in schemas_to_cleanup:
        try:
            connection = adapter.create_connection()
            try:
                adapter.execute_sql(connection, f"DROP SCHEMA IF EXISTS {schema_name} CASCADE")
            except Exception as e:
                print(f"Warning: Failed to cleanup schema {schema_name}: {e}")
            finally:
                adapter.close_connection(connection)
        except Exception as e:
            print(f"Warning: Failed to connect for cleanup of schema {schema_name}: {e}")


def has_redshift_credentials() -> bool:
    if os.getenv("REDSHIFT_HOST"):
        return True
    try:
        from benchbox.security.credentials import CredentialManager

        creds = CredentialManager().get_platform_credentials("redshift")
        return bool(creds and creds.get("host"))
    except Exception:
        return False


def _get_redshift_credentials() -> dict[str, Any]:

    def _build_optional_redshift_config(source: dict[str, Any]) -> dict[str, Any]:
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
    return _get_redshift_credentials()


@pytest.fixture(scope="module")
def redshift_staging_credentials(redshift_credentials) -> dict[str, Any]:
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
    from benchbox.platforms.redshift import RedshiftAdapter

    adapter = RedshiftAdapter(**redshift_credentials)
    yield adapter


@pytest.fixture(scope="module")
def firebolt_credentials() -> dict[str, str]:
    return {
        "client_id": get_env_or_skip("FIREBOLT_CLIENT_ID", "Firebolt"),
        "client_secret": get_env_or_skip("FIREBOLT_CLIENT_SECRET", "Firebolt"),
        "account_name": get_env_or_skip("FIREBOLT_ACCOUNT_NAME", "Firebolt"),
        "engine_name": get_env_or_skip("FIREBOLT_ENGINE_NAME", "Firebolt"),
        "database": os.getenv("FIREBOLT_DATABASE", "benchbox"),
    }


@pytest.fixture(scope="module")
def live_firebolt_adapter(firebolt_credentials):
    from benchbox.platforms.firebolt import FireboltAdapter

    adapter = FireboltAdapter(**firebolt_credentials)
    yield adapter


@pytest.fixture(scope="module")
def live_firebolt_core_adapter():
    from benchbox.platforms.firebolt import FireboltAdapter

    host = os.getenv("FIREBOLT_CORE_HOST", "localhost")
    port = int(os.getenv("FIREBOLT_CORE_PORT", "3473"))
    skip_unless_docker_service(host, port, platform="Firebolt Core")
    adapter = FireboltAdapter(
        url=f"http://{host}:{port}",
        database=os.getenv("FIREBOLT_CORE_DATABASE", "firebolt"),
        deployment_mode="core",
    )
    yield adapter


@pytest.fixture(scope="module")
def starburst_credentials() -> dict[str, str | None]:
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
    from benchbox.platforms.trino import TrinoAdapter

    adapter = TrinoAdapter(**starburst_credentials)
    yield adapter


@pytest.fixture(scope="module")
def motherduck_credentials() -> dict[str, str]:
    return {
        "token": get_env_or_skip("MOTHERDUCK_TOKEN", "MotherDuck"),
        "database": os.getenv("MOTHERDUCK_DATABASE", "benchbox_test"),
    }


@pytest.fixture(scope="module")
def live_motherduck_adapter(motherduck_credentials):
    from benchbox.platforms.motherduck import MotherDuckAdapter

    adapter = MotherDuckAdapter(**motherduck_credentials)
    yield adapter


@pytest.fixture(scope="module")
def live_pg_duckdb_adapter():
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


@pytest.fixture(scope="module")
def live_pg_mooncake_adapter():
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


@pytest.fixture(scope="module")
def live_cedardb_adapter():
    from benchbox.platforms.cedardb import CedarDBAdapter

    host = os.getenv("CEDARDB_HOST", "localhost")
    port = int(os.getenv("CEDARDB_PORT", "5435"))
    skip_unless_docker_service(host, port, platform="CedarDB")
    adapter = CedarDBAdapter(
        host=host,
        port=port,
        username=os.getenv("CEDARDB_USER", "benchbox"),
        password=os.getenv("CEDARDB_PASSWORD", "Benchbox1!"),
        database=os.getenv("CEDARDB_DATABASE", "benchbox_test"),
    )
    yield adapter


# ==============================================================================
# Stub-installer leak guard
# ==============================================================================

#: Adapter (and adapter-adjacent) modules that platform stub installers patch.
#: Every installer in ``common.py`` patches these only through ``monkeypatch``,
#: so a test whose net effect changes any attribute is leaking stub state into
#: other tests. This complements the unit-tier ``tests.utilities.leak_detector``
#: (owned elsewhere; intentionally not modified) with integration-tier coverage.
STUB_PATCHED_MODULES: tuple[str, ...] = (
    "benchbox.platforms.databricks.adapter",
    "benchbox.platforms.bigquery",
    "benchbox.platforms.redshift",
    "benchbox.platforms.snowflake",
    "benchbox.platforms.athena",
    "benchbox.platforms.clickhouse._dependencies",
    "benchbox.platforms.clickhouse.setup",
    "benchbox.platforms.trino",
    "benchbox.platforms.presto",
    "benchbox.platforms.postgresql",
    "benchbox.platforms.influxdb",
    "benchbox.platforms.influxdb._dependencies",
    "benchbox.platforms.influxdb.adapter",
    "benchbox.platforms.influxdb.client",
    "benchbox.platforms.starrocks._dependencies",
    "benchbox.platforms.starrocks.setup",
    "benchbox.platforms.databend.adapter",
    "benchbox.platforms.doris",
    "benchbox.platforms.lakesail",
    "benchbox.platforms.aws.athena_spark_adapter",
    "benchbox.platforms.aws.emr_serverless_adapter",
    "benchbox.platforms.gcp.dataproc_adapter",
    "benchbox.platforms.gcp.dataproc_serverless_adapter",
    "benchbox.utils.dependencies",
)

_STUB_BASELINE_KEY = pytest.StashKey[dict[str, dict[str, Any]]]()


def import_stub_patched_modules() -> None:
    """Import every watched module that is importable, for pre-test baselines.

    Helpers read ``sys.modules`` without importing (mirroring the unit-tier leak
    detector), so modules first imported inside a test body would otherwise have
    no baseline to compare against.
    """
    import importlib

    for name in STUB_PATCHED_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            continue


def snapshot_stub_adapter_attrs() -> dict[str, dict[str, Any]]:
    """Snapshot watched adapter-module attributes without importing anything."""
    snapshot: dict[str, dict[str, Any]] = {}
    for name in STUB_PATCHED_MODULES:
        module = sys.modules.get(name)
        if module is not None:
            snapshot[name] = dict(vars(module))
    return snapshot


def find_stub_adapter_attr_leaks(before: dict[str, dict[str, Any]]) -> list[str]:
    """Return ``module.attr`` names whose identity changed since ``before``."""
    problems: list[str] = []
    for name, old_attrs in before.items():
        module = sys.modules.get(name)
        if module is None:  # pragma: no cover - defensive
            problems.append(f"{name} (module removed)")
            continue
        current = vars(module)
        for attr, old_value in old_attrs.items():
            if attr not in current or current[attr] is not old_value:
                problems.append(f"{name}.{attr}")
        for attr in current:
            if attr not in old_attrs:
                problems.append(f"{name}.{attr}")
    return problems


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    """Capture the adapter-module baseline before any fixture is set up.

    This must run before function-scoped fixtures: the session-wide
    ``mock_platform_dependency_checks`` fixture legitimately patches some of
    these same attributes with mocks and restores them at teardown (net zero),
    so a baseline taken after fixture setup would mistake the restore for a
    leak. A yield-fixture check would have the symmetric problem at teardown,
    running before ``monkeypatch`` undo.
    """
    item.stash[_STUB_BASELINE_KEY] = snapshot_stub_adapter_attrs()
    yield


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item):
    """Fail a test whose net effect changed stub-installer-patched attributes.

    This runs after all function-scoped fixture finalizers, so ``monkeypatch``
    has already undone legitimate stub installs. Anything still changed was
    assigned directly and would leak into other tests.
    """
    yield
    baseline = item.stash.get(_STUB_BASELINE_KEY, None)
    if baseline is None:
        return None
    problems = find_stub_adapter_attr_leaks(baseline)
    if problems:
        pytest.fail(
            "test leaked stub-installer state on adapter modules "
            "(patch via monkeypatch so it is restored): " + ", ".join(sorted(problems)),
            pytrace=False,
        )
    return None
