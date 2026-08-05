"""Every registered adapter must honor the result credential boundary.

This is intentionally an integration-shaped unit test: it constructs each
registered adapter without opening a connection, carries its configured
options through the result payload boundary, and rejects any credential
sentinel that survives either the platform config or raw-config compatibility
block.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for
details.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.results.database import ResultDatabase
from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload

pytestmark = [pytest.mark.unit, pytest.mark.medium]


_CREDENTIAL_SENTINELS = (
    "EGRESS_PASSWORD_SENTINEL",
    "EGRESS_TOKEN_SENTINEL",
    "EGRESS_API_KEY_SENTINEL",
    "EGRESS_ACCESS_KEY_SENTINEL",
    "EGRESS_SECRET_KEY_SENTINEL",
    "EGRESS_ACCESS_TOKEN_SENTINEL",
    "EGRESS_DSN_PASSWORD_SENTINEL",
)


def _sentinel_config(tmp_path: Path) -> dict[str, object]:
    """Return a connection-free config broad enough for the adapter family."""
    return {
        "database_path": ":memory:",
        "database": "benchbox",
        "db_name": "benchbox",
        "db_path": ":memory:",
        "host": "localhost",
        "port": 5432,
        "username": "EGRESS_USERNAME_SENTINEL",
        "user": "EGRESS_USERNAME_SENTINEL",
        "password": _CREDENTIAL_SENTINELS[0],
        "token": _CREDENTIAL_SENTINELS[1],
        "api_key": _CREDENTIAL_SENTINELS[2],
        "access_key": _CREDENTIAL_SENTINELS[3],
        "secret_key": _CREDENTIAL_SENTINELS[4],
        "access_token": _CREDENTIAL_SENTINELS[5],
        "account": "EGRESS_ACCOUNT_SENTINEL",
        "project_id": "EGRESS_PROJECT_SENTINEL",
        "project": "EGRESS_PROJECT_SENTINEL",
        "region": "us-east-1",
        "warehouse": "EGRESS_WAREHOUSE_SENTINEL",
        "schema": "public",
        "catalog": "duckdb",
        "storage_container": "EGRESS_CONTAINER_SENTINEL",
        "container": "EGRESS_CONTAINER_SENTINEL",
        "bucket": "EGRESS_BUCKET_SENTINEL",
        "output_location": "s3://egress-bucket-sentinel/path/",
        "gcs_staging_dir": "gs://egress-bucket-sentinel/path/",
        "s3_staging_dir": "s3://egress-bucket-sentinel/path/",
        "access_key_id": "EGRESS_ACCESS_KEY_ID_SENTINEL",
        "secret_access_key": "EGRESS_SECRET_ACCESS_KEY_SENTINEL",
        "connection_string": "postgresql://user:EGRESS_DSN_PASSWORD_SENTINEL@localhost/benchbox",
        "endpoint": "http://localhost:8080",
        "server": "localhost",
        "driver": "SQLite3",
        "spark_config": {},
        "spark_conf": {},
        "storage_options": {},
        "catalog_name": "benchbox",
        "mode": "core",
        "deployment": "local",
        "deployment_mode": "local",
        "auth_method": "password",
        "benchmark": "tpch",
        "scale_factor": 0.01,
        "output_dir": str(tmp_path),
        "working_dir": str(tmp_path),
        "workgroup": "EGRESS_WORKGROUP_SENTINEL",
        "workspace_id": "EGRESS_WORKSPACE_ID_SENTINEL",
        "workspace_name": "EGRESS_WORKSPACE_SENTINEL",
        "lakehouse_id": "EGRESS_LAKEHOUSE_ID_SENTINEL",
        "execution_role_arn": "arn:aws:iam::123456789012:role/EGRESS_ROLE_SENTINEL",
        "job_role": "arn:aws:iam::123456789012:role/EGRESS_ROLE_SENTINEL",
        "server_hostname": "EGRESS_HOSTNAME_SENTINEL.azuredatabricks.net",
        "http_path": "/sql/EGRESS_HTTP_PATH_SENTINEL",
        "gcs_bucket": "EGRESS_BUCKET_SENTINEL",
        "gcs_path": "EGRESS_PATH_SENTINEL",
        "aws_region": "us-east-1",
        "storage_account_name": "EGRESS_STORAGE_SENTINEL",
        "storage_account": "EGRESS_STORAGE_SENTINEL",
        "application_id": "EGRESS_APPLICATION_SENTINEL",
        "create_application": True,
        "spark_pool_name": "EGRESS_SPARK_POOL_SENTINEL",
    }


def _registered_platform_names() -> tuple[str, ...]:
    PlatformRegistry._ensure_registered()
    return tuple(sorted(PlatformRegistry._adapters))


@pytest.mark.parametrize("platform_name", _registered_platform_names())
def test_registered_adapter_result_payload_redacts_credential_sentinels(platform_name: str, tmp_path: Path) -> None:
    config = _sentinel_config(tmp_path)
    if platform_name == "clickhouse":
        config["deployment"] = "local"
        config["deployment_mode"] = "local"
    elif platform_name == "ducklake":
        config["catalog"] = "duckdb"
    elif platform_name in {"pg-duckdb", "timescaledb"}:
        config["deployment_mode"] = "self-hosted"
    elif platform_name == "firebolt":
        config["deployment_mode"] = "core"
    elif platform_name == "snowpark-connect":
        config["user"] = "EGRESS_USERNAME_SENTINEL"

    adapter_class = PlatformRegistry.get_adapter_class(platform_name)
    try:
        adapter = adapter_class(**config)
    except (ImportError, ConfigurationError) as exc:
        # Adapters are inconsistent about which exception carries a missing
        # optional dependency: most raise ImportError, but the Spark-family
        # adapters (dataproc, dataproc-serverless, fabric-spark,
        # snowpark-connect, synapse-spark) raise ConfigurationError with the
        # same get_dependency_error_message() text. `uv sync --group dev` -- the
        # environment the required medium-test job builds -- installs neither
        # extra, so keying the skip on ImportError alone errored those five
        # adapters out before they reached any assertion. Gate on the shared
        # message so a genuine ConfigurationError (a real misconfiguration this
        # test should catch) still fails loudly.
        if "Missing dependencies" in str(exc):
            pytest.skip(f"optional adapter dependency is not installed: {exc}")
        raise

    result = BenchmarkResults(
        benchmark_name="tpch",
        platform=platform_name,
        scale_factor=0.01,
        execution_id=f"sentinel-{platform_name}",
        timestamp=datetime.now(),
        duration_seconds=1.0,
        total_queries=0,
        successful_queries=0,
        failed_queries=0,
        platform_info={"configuration": dict(adapter.platform_config)},
        platform_raw_config=dict(adapter.platform_config),
    )

    payload = build_result_payload(result, sanitize_platform_secrets=False)
    serialized = json.dumps(payload, default=str, sort_keys=True)
    for sentinel in _CREDENTIAL_SENTINELS:
        assert sentinel not in serialized, f"{platform_name} leaked {sentinel}"

    exported = ResultExporter(output_dir=tmp_path / "export", anonymize=False).export_result(result, formats=["json"])
    exported_json = exported["json"].read_text(encoding="utf-8")
    for sentinel in _CREDENTIAL_SENTINELS:
        assert sentinel not in exported_json, f"{platform_name} JSON export leaked {sentinel}"

    database = ResultDatabase(db_path=tmp_path / "results.db")
    database.store_result(result)
    database_bytes = (tmp_path / "results.db").read_bytes()
    for sentinel in _CREDENTIAL_SENTINELS:
        assert sentinel.encode() not in database_bytes, f"{platform_name} results.db leaked {sentinel}"


def test_platform_metadata_blocks_never_egress_distinct_sentinels(tmp_path: Path) -> None:
    """raw_config, raw_metadata, and normalized mapping blocks share one boundary.

    Distinct sentinels per source ensure a partial fix cannot silence the gate.
    """
    gates = {
        "raw_config": "RAW_CONFIG_GATE",
        "raw_metadata": "RAW_METADATA_GATE",
        "deployment": "DEPLOYMENT_GATE",
        "cloud": "CLOUD_GATE",
        "compute": "COMPUTE_GATE",
        "storage": "STORAGE_GATE",
    }
    result = BenchmarkResults(
        benchmark_name="synthetic",
        platform="synthetic",
        scale_factor=1.0,
        execution_id="metadata-blocks-gate",
        timestamp=datetime.now(),
        duration_seconds=0.1,
        total_queries=0,
        successful_queries=0,
        failed_queries=0,
        platform_info={"sort_key": "o_orderkey", "threads": 4},
        platform_raw_config={"password": gates["raw_config"], "threads": 4},
        platform_raw_metadata={"password": gates["raw_metadata"], "partition_key": "l_orderkey"},
        platform_deployment={"token": gates["deployment"], "connection_mode": "embedded"},
        platform_cloud={"access_key": gates["cloud"], "region": "us-east-1"},
        platform_compute={"connection_string": gates["compute"], "warehouse": "BENCH_WH"},
        platform_storage={"secret": gates["storage"], "bucket": "bench-bucket"},
    )

    public = json.dumps(build_result_payload(result), default=str)
    private = (
        ResultExporter(output_dir=tmp_path / "export", anonymize=False)
        .export_result(result, formats=["json"])["json"]
        .read_text(encoding="utf-8")
    )
    db_path = tmp_path / "results.db"
    ResultDatabase(db_path=db_path).store_result(result)
    database_bytes = db_path.read_bytes()

    for source, sentinel in gates.items():
        assert sentinel not in public, f"public payload leaked {source}={sentinel}"
        assert sentinel not in private, f"private export leaked {source}={sentinel}"
        assert sentinel.encode() not in database_bytes, f"results.db leaked {source}={sentinel}"

    # Non-secret tuning must still be available to analysis consumers.
    assert "o_orderkey" in public
    assert "BENCH_WH" in private
    assert b"bench-bucket" in database_bytes
