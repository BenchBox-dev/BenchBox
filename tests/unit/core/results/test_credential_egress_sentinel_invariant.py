"""Permanent credential-egress sentinel sweep across all export chokepoints.

This is intentionally an integration-shaped unit test: it constructs each
registered adapter without opening a connection, carries configured options
through the public payload / private JSON export / results.db boundaries, and
rejects any credential or identifier sentinel that survives.

Coverage layers (R8 permanent invariant + expansion):

* 47-adapter platform_config / raw_config construct-and-export sweep with
  explicit optional-dependency skip accounting (45-pass / 2-ODBC-skip when
  only pyodbc is missing under --all-extras).
* raw_metadata + normalized deployment/cloud/compute/storage blocks.
* URI query/fragment credentials through platform-options sanitization and
  result export chokepoints.
* MCP error scrubbing for assignment-form secrets.
* Nested tuning companion identifiers (list-of-dicts FK tables) through the
  public anonymizer and anonymized .tuning.json companion.

Do not reduce this to a key-name grep: construct adapters/results and inspect
serialized outputs. Do not introduce SecretStr or a four-layer architecture.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for
details.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.results.anonymization import AnonymizationManager
from benchbox.core.results.database import ResultDatabase
from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.platform_options import sanitize_platform_options
from benchbox.core.results.schema import build_result_payload
from benchbox.mcp.errors import make_execution_error

pytestmark = [pytest.mark.unit, pytest.mark.medium]

# Reviewed adapter corpus size. Drift means a platform was added/removed without
# updating the permanent egress invariant.
EXPECTED_REGISTERED_PLATFORM_COUNT = 47

# Optional ODBC-backed adapters that remain skippable even under
# ``uv run --all-extras`` when the host lacks pyodbc (system driver). Any other
# missing-dependency skip must still record the exact reason so a disappearing
# adapter cannot make the sweep vacuous.
OPTIONAL_ODBC_ADAPTER_DEPENDENCIES: dict[str, str] = {
    "fabric-lakehouse": "pyodbc",
    "synapse": "pyodbc",
}

_CREDENTIAL_SENTINELS = (
    "EGRESS_PASSWORD_SENTINEL",
    "EGRESS_TOKEN_SENTINEL",
    "EGRESS_API_KEY_SENTINEL",
    "EGRESS_ACCESS_KEY_SENTINEL",
    "EGRESS_SECRET_KEY_SENTINEL",
    "EGRESS_ACCESS_TOKEN_SENTINEL",
    "EGRESS_DSN_PASSWORD_SENTINEL",
)

# Cross-layer expansion gates (distinct so a partial fix cannot silence all).
_SWEEP_URI_GATE = "SWEEP_URI_GATE"
_SWEEP_MCP_GATE = "SWEEP_MCP_GATE"
_SWEEP_TABLE_GATE = "SWEEP_TABLE_GATE"
_SWEEP_COLUMN_GATE = "SWEEP_COLUMN_GATE"


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
    PlatformRegistry.clear_cache()
    return tuple(sorted(PlatformRegistry.get_available_platforms()))


def _prepare_config_for_platform(platform_name: str, tmp_path: Path) -> dict[str, object]:
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
    return config


def _construct_adapter_or_skip_reason(platform_name: str, tmp_path: Path) -> Any | str:
    """Return a constructed adapter, or a skip-reason string (never empty).

    Adapters are inconsistent about which exception carries a missing optional
    dependency: most raise ImportError, but the Spark-family adapters raise
    ConfigurationError with the same get_dependency_error_message() text. Gate
    on the shared message so a genuine ConfigurationError still fails loudly.
    """
    config = _prepare_config_for_platform(platform_name, tmp_path)
    adapter_class = PlatformRegistry.get_adapter_class(platform_name)
    try:
        return adapter_class(**config)
    except (ImportError, ConfigurationError) as exc:
        message = str(exc)
        if "Missing dependencies" not in message:
            raise
        required = OPTIONAL_ODBC_ADAPTER_DEPENDENCIES.get(platform_name)
        if required is not None and required not in message.lower():
            raise AssertionError(
                f"{platform_name} optional skip must cite missing dependency {required!r}; got: {message}"
            ) from exc
        return f"skip:optional-dependency:{platform_name}:{message}"


def _assert_no_sentinels_in_text(text: str, sentinels: tuple[str, ...] | list[str], *, context: str) -> None:
    for sentinel in sentinels:
        assert sentinel not in text, f"{context} leaked {sentinel}"


def _assert_no_sentinels_in_bytes(data: bytes, sentinels: tuple[str, ...] | list[str], *, context: str) -> None:
    for sentinel in sentinels:
        assert sentinel.encode() not in data, f"{context} leaked {sentinel}"


def _export_chokepoints(result: BenchmarkResults, tmp_path: Path) -> tuple[str, str, bytes]:
    """Drive public payload, private JSON export, and results.db bytes."""
    public = json.dumps(build_result_payload(result, sanitize_platform_secrets=False), default=str, sort_keys=True)
    private = (
        ResultExporter(output_dir=tmp_path / "export", anonymize=False)
        .export_result(result, formats=["json"])["json"]
        .read_text(encoding="utf-8")
    )
    db_path = tmp_path / "results.db"
    ResultDatabase(db_path=db_path).store_result(result)
    return public, private, db_path.read_bytes()


def test_registered_platform_count_is_forty_seven() -> None:
    """Registry size is an explicit invariant of the permanent sweep corpus."""
    PlatformRegistry.clear_cache()
    platforms = PlatformRegistry.get_available_platforms()
    assert len(platforms) == EXPECTED_REGISTERED_PLATFORM_COUNT, (
        f"expected {EXPECTED_REGISTERED_PLATFORM_COUNT} registered platforms, got {len(platforms)}: {sorted(platforms)}"
    )


def test_adapter_construct_coverage_accounting(tmp_path: Path) -> None:
    """Every registered adapter must construct or record an explicit skip reason.

    Under ``uv run --all-extras`` on a host without pyodbc the partition is the
    reviewed 45-pass / 2-optional-ODBC-skip accounting. When other optional
    extras are also absent, each skip still carries the Missing dependencies
    text so the sweep cannot silently shrink.
    """
    names = _registered_platform_names()
    assert len(names) == EXPECTED_REGISTERED_PLATFORM_COUNT

    constructed: list[str] = []
    skipped: dict[str, str] = {}
    for platform_name in names:
        outcome = _construct_adapter_or_skip_reason(platform_name, tmp_path / platform_name)
        if isinstance(outcome, str):
            assert outcome.startswith("skip:optional-dependency:"), outcome
            assert "Missing dependencies" in outcome
            skipped[platform_name] = outcome
            continue
        constructed.append(platform_name)

    assert len(constructed) + len(skipped) == EXPECTED_REGISTERED_PLATFORM_COUNT
    assert not (set(constructed) & set(skipped))

    odbc_skips = {name: reason for name, reason in skipped.items() if name in OPTIONAL_ODBC_ADAPTER_DEPENDENCIES}
    non_odbc_skips = {
        name: reason for name, reason in skipped.items() if name not in OPTIONAL_ODBC_ADAPTER_DEPENDENCIES
    }

    for name, reason in odbc_skips.items():
        required = OPTIONAL_ODBC_ADAPTER_DEPENDENCIES[name]
        assert required in reason.lower(), f"{name} ODBC skip must cite {required}: {reason}"

    # Full-extras environment (only ODBC host packages missing): pin 45/2.
    if not non_odbc_skips:
        assert set(odbc_skips).issubset(OPTIONAL_ODBC_ADAPTER_DEPENDENCIES)
        assert len(constructed) == EXPECTED_REGISTERED_PLATFORM_COUNT - len(odbc_skips)
        assert len(constructed) >= EXPECTED_REGISTERED_PLATFORM_COUNT - len(OPTIONAL_ODBC_ADAPTER_DEPENDENCIES)
        # When both ODBC adapters skip, the reviewed accounting is exactly 45/2.
        if set(odbc_skips) == set(OPTIONAL_ODBC_ADAPTER_DEPENDENCIES):
            assert len(constructed) == 45
            assert len(skipped) == 2


@pytest.mark.parametrize("platform_name", _registered_platform_names())
def test_registered_adapter_result_payload_redacts_credential_sentinels(platform_name: str, tmp_path: Path) -> None:
    outcome = _construct_adapter_or_skip_reason(platform_name, tmp_path)
    if isinstance(outcome, str):
        pytest.skip(outcome.removeprefix("skip:optional-dependency:").split(":", 1)[-1])

    adapter = outcome
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

    public, private, database_bytes = _export_chokepoints(result, tmp_path)
    _assert_no_sentinels_in_text(public, _CREDENTIAL_SENTINELS, context=f"{platform_name} public payload")
    _assert_no_sentinels_in_text(private, _CREDENTIAL_SENTINELS, context=f"{platform_name} private JSON export")
    _assert_no_sentinels_in_bytes(database_bytes, _CREDENTIAL_SENTINELS, context=f"{platform_name} results.db")


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

    public, private, database_bytes = _export_chokepoints(result, tmp_path)
    # Public path always sanitizes; re-check the sanitized public payload too.
    public_sanitized = json.dumps(build_result_payload(result), default=str)

    for source, sentinel in gates.items():
        assert sentinel not in public, f"public payload leaked {source}={sentinel}"
        assert sentinel not in public_sanitized, f"sanitized public payload leaked {source}={sentinel}"
        assert sentinel not in private, f"private export leaked {source}={sentinel}"
        assert sentinel.encode() not in database_bytes, f"results.db leaked {source}={sentinel}"

    # Non-secret tuning must still be available to analysis consumers.
    assert "o_orderkey" in public
    assert "BENCH_WH" in private
    assert b"bench-bucket" in database_bytes


def test_uri_query_credentials_never_egress_through_options_or_result_chokepoints(tmp_path: Path) -> None:
    """URI query/fragment credential params must not survive sanitize or export.

    Option keys need not themselves be secret-named: the credential lives only
    in the URI component (export URLs, sslpassword, OAuth-style fragments).
    """
    values = {
        "url": f"https://example.invalid/x?password={_SWEEP_URI_GATE}",
        "endpoint": f"https://example.invalid/export?access_token={_SWEEP_URI_GATE}&x=1",
        "ssl": f"postgresql://host.example/db?sslpassword={_SWEEP_URI_GATE}&application_name=bb",
        "fragment": f"https://example.invalid/export#access_token={_SWEEP_URI_GATE}&section=results",
        "combined": f"postgresql://u:URI_USERINFO_GATE@example.invalid/db?sslpassword={_SWEEP_URI_GATE}",
    }
    uri_sentinels = (_SWEEP_URI_GATE, "URI_USERINFO_GATE")
    sanitized = sanitize_platform_options(values)
    sanitized_blob = json.dumps(sanitized)
    _assert_no_sentinels_in_text(sanitized_blob, uri_sentinels, context="sanitize_platform_options")
    assert sanitized["url"] == "https://example.invalid/x?password=****"
    assert "application_name=bb" in sanitized["ssl"]
    assert "x=1" in sanitized["endpoint"]

    result = BenchmarkResults(
        benchmark_name="synthetic",
        platform="synthetic",
        scale_factor=1.0,
        execution_id="uri-query-gate",
        timestamp=datetime.now(),
        duration_seconds=0.1,
        total_queries=0,
        successful_queries=0,
        failed_queries=0,
        platform_info={"configuration": dict(values)},
        platform_raw_config=dict(values),
        platform_raw_metadata={"connection_uri": values["ssl"]},
        platform_compute={"jdbc_url": values["url"], "warehouse": "BENCH_WH"},
    )
    public, private, database_bytes = _export_chokepoints(result, tmp_path)
    public_sanitized = json.dumps(build_result_payload(result), default=str)
    for blob, label in (
        (public, "public"),
        (public_sanitized, "sanitized public"),
        (private, "private"),
    ):
        _assert_no_sentinels_in_text(blob, uri_sentinels, context=f"{label} export")
    _assert_no_sentinels_in_bytes(database_bytes, uri_sentinels, context="results.db")
    assert "BENCH_WH" in private


def test_mcp_error_scrub_never_egress_credential_sentinels() -> None:
    """MCP error responses must scrub assignment-form credential material."""
    cases = (
        f"dsn={_SWEEP_MCP_GATE}",
        f"password={_SWEEP_MCP_GATE}",
        f"connection_string={_SWEEP_MCP_GATE}",
        f"private_key={_SWEEP_MCP_GATE}",
        f"motherduck_token={_SWEEP_MCP_GATE}",
        f'dsn="{_SWEEP_MCP_GATE}"',
        f"sas={_SWEEP_MCP_GATE}",
        f"pat={_SWEEP_MCP_GATE}",
    )
    for text in cases:
        result = make_execution_error(text, exception=Exception(text))
        blob = json.dumps(result)
        assert _SWEEP_MCP_GATE not in blob, f"MCP error leaked sentinel for {text!r}: {blob}"
        assert _SWEEP_MCP_GATE not in result["message"]
        assert _SWEEP_MCP_GATE not in result["details"]["exception_message"]
        assert "****" in result["message"]

    # Benign diagnostic prose must remain readable (prose-precision contract).
    benign = "password field is missing; token expired while connecting"
    clean = make_execution_error(benign, exception=Exception(benign))
    assert clean["details"]["exception_message"] == benign


def test_nested_tuning_companion_identifiers_never_egress(tmp_path: Path) -> None:
    """List-of-dicts FK companion shapes must not leak table/column identifiers.

    The public anonymizer and the anonymized .tuning.json companion are the
    durable chokepoints; private (anonymize=False) may retain identifiers for
    local analysis, matching the exporter contract.
    """
    companion_payload = {
        "requested": {
            "constraints": {
                "foreign_keys": {
                    "enabled": True,
                    "tables": [
                        {
                            "table": _SWEEP_TABLE_GATE,
                            "columns": [_SWEEP_COLUMN_GATE],
                            "referenced_table": _SWEEP_TABLE_GATE,
                            "referenced_columns": [_SWEEP_COLUMN_GATE],
                        }
                    ],
                },
                "local_table": f"{_SWEEP_TABLE_GATE}/{_SWEEP_COLUMN_GATE}",
                "references_table": _SWEEP_TABLE_GATE,
                "references_column": _SWEEP_COLUMN_GATE,
            }
        }
    }
    anonymized = AnonymizationManager().anonymize_tuning_payload(companion_payload)
    anonymized_blob = json.dumps(anonymized)
    for gate in (_SWEEP_TABLE_GATE, _SWEEP_COLUMN_GATE):
        assert gate not in anonymized_blob, f"anonymize_tuning_payload leaked {gate}"

    constraints = anonymized["requested"]["constraints"]
    entry = constraints["foreign_keys"]["tables"][0]
    assert entry["table"].startswith("table_")
    assert entry["columns"][0].startswith("column_")
    assert constraints["foreign_keys"]["enabled"] is True
    assert constraints["local_table"].startswith("table_")
    assert constraints["references_table"].startswith("table_")
    assert constraints["references_column"].startswith("column_")

    # Public export path: anonymized .tuning.json companion.
    result = BenchmarkResults(
        benchmark_name="synthetic",
        platform="synthetic",
        scale_factor=1.0,
        execution_id="tuning-companion-gate",
        timestamp=datetime.now(),
        duration_seconds=0.1,
        total_queries=0,
        successful_queries=0,
        failed_queries=0,
        tunings_applied={
            "constraints": companion_payload["requested"]["constraints"],
        },
        tuning_source="wizard",
        tuning_source_file="examples/tunings/custom.yaml:0123456789abcdef",
    )
    exported = ResultExporter(output_dir=tmp_path / "export", anonymize=True).export_result(result, formats=["json"])
    tuning_path = tmp_path / "export" / f"{exported['json'].stem}.tuning.json"
    assert tuning_path.is_file(), "anonymized export must emit .tuning.json when tunings_applied is set"
    tuning_raw = tuning_path.read_text(encoding="utf-8")
    primary_raw = exported["json"].read_text(encoding="utf-8")
    for gate in (_SWEEP_TABLE_GATE, _SWEEP_COLUMN_GATE):
        assert gate not in tuning_raw, f"anonymized .tuning.json leaked {gate}"
        assert gate not in primary_raw, f"anonymized primary JSON leaked {gate}"


def test_cross_layer_sentinel_gate_is_green() -> None:
    """Compact multi-layer gate matching the tracker verification command.

    URI options, MCP errors, and nested tuning companions must all redact the
    distinct sweep sentinels in a single assertion surface.
    """
    uri = json.dumps(sanitize_platform_options({"url": f"https://example.invalid/x?password={_SWEEP_URI_GATE}"}))
    mcp = json.dumps(make_execution_error(f"dsn={_SWEEP_MCP_GATE}", exception=Exception(f"dsn={_SWEEP_MCP_GATE}")))
    payload = {
        "requested": {
            "constraints": {
                "foreign_keys": {
                    "tables": [{"table": _SWEEP_TABLE_GATE, "columns": [_SWEEP_COLUMN_GATE]}],
                }
            }
        }
    }
    tuning = json.dumps(AnonymizationManager().anonymize_tuning_payload(payload))
    combined = uri + mcp + tuning
    for gate in (_SWEEP_URI_GATE, _SWEEP_MCP_GATE, _SWEEP_TABLE_GATE, _SWEEP_COLUMN_GATE):
        assert gate not in combined, f"cross-layer gate leaked {gate}"
