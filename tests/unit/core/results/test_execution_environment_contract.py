"""Tests for the normalized execution-environment result contract."""

from __future__ import annotations

from datetime import datetime

import pytest

from benchbox.core.results.environment import (
    ContainerEnvironment,
    NormalizedExecutionEnvironment,
    PlatformCloudMetadata,
    PlatformComputeMetadata,
    PlatformDeploymentMetadata,
    PlatformRuntimeEnvironment,
    PlatformStorageMetadata,
)
from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.loader import reconstruct_benchmark_results
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.schema import build_result_payload

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _minimal_result(**overrides):
    defaults = {
        "benchmark_name": "TPC-H",
        "platform": "DuckDB",
        "scale_factor": 0.01,
        "execution_id": "env-contract-test",
        "timestamp": datetime(2026, 1, 1, 12, 0, 0),
        "duration_seconds": 1.2,
        "total_queries": 1,
        "successful_queries": 1,
        "failed_queries": 0,
        "query_results": [
            {
                "query_id": "Q1",
                "execution_time_seconds": 0.1,
                "rows_returned": 1,
                "status": "SUCCESS",
                "run_type": "measurement",
            }
        ],
    }
    defaults.update(overrides)
    return BenchmarkResults(**defaults)


def test_environment_block_keeps_legacy_host_keys_and_adds_normalized_client_host() -> None:
    result = _minimal_result(
        system_profile={
            "os_type": "Darwin",
            "os_release": "24.4.0",
            "architecture": "arm64",
            "cpu_count": 12,
            "memory_gb": 64,
            "python_version": "3.12.8",
            "machine_id": "machine-test",
        },
        platform_info={
            "platform_version": "1.0.0",
            "client_library_version": "1.0.0",
            "connection_mode": "in-memory",
            "configuration": {"threads": 4},
        },
    )

    payload = build_result_payload(result)

    assert payload["environment"]["os"] == "Darwin 24.4.0"
    assert payload["environment"]["arch"] == "arm64"
    assert payload["environment"]["client_host"] == {
        "os": "Darwin 24.4.0",
        "arch": "arm64",
        "cpu_count": 12,
        "memory_gb": 64,
        "python": "3.12.8",
        "machine_id": "machine-test",
    }
    assert payload["environment"]["platform_runtime"] == {
        "runtime_type": "unknown",
        "collection_status": "unavailable",
        "source": "unavailable",
    }
    assert payload["platform"]["config"]["threads"] == 4
    assert payload["platform"]["deployment"]["connection_mode"] == "in-memory"
    assert payload["platform"]["deployment"]["endpoint_class"] == "embedded_process"
    assert payload["platform"]["raw_config"]["threads"] == 4


def test_partial_explicit_client_host_merges_with_system_profile_for_legacy_compatibility() -> None:
    result = _minimal_result(
        system_profile={
            "os_type": "Darwin",
            "os_release": "24.4.0",
            "architecture": "arm64",
            "cpu_count": 12,
        },
        execution_environment=NormalizedExecutionEnvironment(client_host={"machine_id": "explicit-machine"}),
    )

    payload = build_result_payload(result)

    assert payload["environment"]["os"] == "Darwin 24.4.0"
    assert payload["environment"]["arch"] == "arm64"
    assert payload["environment"]["client_host"]["os"] == "Darwin 24.4.0"
    assert payload["environment"]["client_host"]["machine_id"] == "explicit-machine"


def test_url_form_localhost_endpoint_is_classified_as_localhost_port() -> None:
    result = _minimal_result(
        platform_info={
            "platform_version": "24.1",
            "client_library_version": "0.8",
            "configuration": {"endpoint": "http://localhost:8123"},
        },
    )

    payload = build_result_payload(result)

    assert payload["platform"]["deployment"]["endpoint_class"] == "localhost_port"
    assert payload["platform"]["deployment"]["collection_status"] == "partial"


def test_explicit_runtime_container_and_platform_facets_serialize_to_canonical_blocks() -> None:
    result = _minimal_result(
        platform="ClickHouse Server",
        execution_environment=NormalizedExecutionEnvironment(
            platform_runtime=PlatformRuntimeEnvironment(
                runtime_type="docker_container",
                collection_status="available",
                source="observed",
                os="Linux",
                arch="amd64",
                engine_host="container:clickhouse",
            ),
            container=ContainerEnvironment(
                collection_status="available",
                source="observed",
                docker_engine_version="26.1.0",
                image="clickhouse/clickhouse-server:24.1",
                image_digest="sha256:abc123",
                container_id="container-123",
                container_name="benchbox-clickhouse",
                os="linux",
                arch="amd64",
                requested_platform="linux/amd64",
                cpu_limit=4,
                memory_limit="8g",
                port_mappings={"8123/tcp": [{"host_ip": "127.0.0.1", "host_port": "8123"}]},
                bind_mounts=[{"source": "/tmp/data", "destination": "/var/lib/clickhouse"}],
            ),
        ),
        platform_deployment=PlatformDeploymentMetadata(
            deployment_type="self_hosted",
            connection_mode="localhost",
            endpoint_class="localhost_port",
            metadata_source="observed",
            collection_status="available",
        ),
        platform_cloud=PlatformCloudMetadata(
            provider="aws",
            region="us-east-1",
            account="account-hash",
            source="requested",
            collection_status="partial",
        ),
        platform_compute=PlatformComputeMetadata(
            node_type="c6i.2xlarge",
            node_count=1,
            cache_enabled=False,
            source="observed",
            collection_status="available",
        ),
        platform_storage=PlatformStorageMetadata(
            table_format="native",
            compression="zstd",
            cleanup_policy="drop",
            source="requested",
            collection_status="partial",
        ),
        platform_raw_config={"host": "localhost", "port": 8123},
        platform_raw_metadata={"server_version": "24.1"},
    )

    payload = build_result_payload(result)

    assert payload["environment"]["platform_runtime"]["runtime_type"] == "docker_container"
    assert payload["environment"]["platform_runtime"]["os"] == "Linux"
    assert payload["environment"]["container"]["image"] == "clickhouse/clickhouse-server:24.1"
    assert payload["environment"]["container"]["port_mappings"]["8123/tcp"][0]["host_port"] == "8123"
    assert payload["platform"]["deployment"]["endpoint_class"] == "localhost_port"
    assert payload["platform"]["cloud"]["region"] == "us-east-1"
    assert payload["platform"]["compute"]["node_type"] == "c6i.2xlarge"
    assert payload["platform"]["compute"]["cache_enabled"] is False
    assert payload["platform"]["storage"]["compression"] == "zstd"
    assert payload["platform"]["raw_config"] == {"host": "localhost", "port": 8123}
    assert payload["platform"]["raw_metadata"] == {"server_version": "24.1"}


def test_loader_preserves_normalized_environment_metadata_for_round_trip() -> None:
    payload = build_result_payload(
        _minimal_result(
            system_profile={"os_type": "Linux", "os_release": "6.8", "architecture": "x86_64"},
            execution_environment=NormalizedExecutionEnvironment(
                platform_runtime=PlatformRuntimeEnvironment(
                    runtime_type="remote_server",
                    collection_status="partial",
                    source="inferred",
                    engine_host="db.internal",
                )
            ),
            platform_deployment=PlatformDeploymentMetadata(
                deployment_type="self_hosted",
                endpoint_class="remote_host",
                metadata_source="inferred",
                collection_status="partial",
            ),
        )
    )

    reconstructed = reconstruct_benchmark_results(payload)
    round_trip = build_result_payload(reconstructed)

    assert reconstructed.system_profile["os_type"] == "Linux"
    assert reconstructed.execution_environment["platform_runtime"]["runtime_type"] == "remote_server"
    assert reconstructed.platform_deployment["endpoint_class"] == "remote_host"
    assert round_trip["environment"]["client_host"]["os"] == "Linux 6.8"
    assert round_trip["environment"]["platform_runtime"]["engine_host"] == "db.internal"
    assert round_trip["platform"]["deployment"]["endpoint_class"] == "remote_host"


def test_loader_uses_legacy_flat_host_fields_when_client_host_is_partial() -> None:
    payload = build_result_payload(
        _minimal_result(system_profile={"os_type": "Linux", "os_release": "6.8", "architecture": "x86_64"})
    )
    payload["environment"]["client_host"] = {"machine_id": "nested-machine"}

    reconstructed = reconstruct_benchmark_results(payload)

    assert reconstructed.system_profile["os_type"] == "Linux"
    assert reconstructed.system_profile["architecture"] == "x86_64"
    assert reconstructed.system_profile["machine_id"] == "nested-machine"


def test_anonymized_export_replaces_machine_id_in_flat_and_normalized_client_host(tmp_path) -> None:
    payload = build_result_payload(
        _minimal_result(
            system_profile={
                "os_type": "Linux",
                "architecture": "x86_64",
                "machine_id": "raw-machine-id",
            }
        )
    )

    ResultExporter(output_dir=tmp_path, anonymize=True)._apply_anonymization(payload)

    assert payload["environment"]["machine_id"].startswith("machine_")
    assert payload["environment"]["machine_id"] != "raw-machine-id"
    assert payload["environment"]["client_host"]["machine_id"] == payload["environment"]["machine_id"]
