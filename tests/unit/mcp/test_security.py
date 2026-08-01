"""Unit coverage for remote MCP security policy and durable coordination."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent

from benchbox.mcp.security import (
    AdmissionLimits,
    DurableSecurityStore,
    Principal,
    RemoteSecurityMiddleware,
    TenantWorkspaceProvider,
    load_remote_security_config,
)
from tests.integration.mcp._security import write_security_config

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_auth_config_contains_only_digests_and_verifies_identity(tmp_path: Path) -> None:
    token = "unit-secret-token"
    path = write_security_config(tmp_path, tokens={token: ("tenant-a", ("benchbox:read",))})
    assert token not in path.read_text(encoding="utf-8")
    config = load_remote_security_config(path)

    async def exercise() -> None:
        from benchbox.mcp.security import DigestTokenVerifier

        verifier = DigestTokenVerifier(config)
        access = await verifier.verify_token(token)
        assert access is not None
        assert access.subject == "tenant-a"
        assert await verifier.verify_token("wrong") is None

    anyio.run(exercise)


def test_tenant_workspace_is_server_owned_and_distinct(tmp_path: Path) -> None:
    provider = TenantWorkspaceProvider(tmp_path / "owned")
    first = Principal("a" * 32, "client", "issuer", "a", frozenset())
    second = Principal("b" * 32, "client", "issuer", "b", frozenset())
    first_paths = provider.paths_for(first)
    second_paths = provider.paths_for(second)
    assert first_paths.results_dir != second_paths.results_dir
    assert first_paths.results_dir.is_relative_to(tmp_path / "owned")
    assert second_paths.charts_dir.is_relative_to(tmp_path / "owned")


def test_authorization_rejects_platform_benchmark_and_scale_outside_policy(tmp_path: Path) -> None:
    path = write_security_config(
        tmp_path,
        tokens={"token": ("tenant-a", ("benchbox:read", "benchbox:execute"))},
    )
    config = load_remote_security_config(path)
    middleware = RemoteSecurityMiddleware(config, DurableSecurityStore(config.state_db, config.admission))
    principal = Principal("a" * 32, "client", "issuer", "a", frozenset({"benchbox:execute"}))
    middleware._authorize(principal, "run_benchmark", {"platform": "duckdb", "benchmark": "tpch", "scale_factor": 1})
    with pytest.raises(MCPError, match="Platform"):
        middleware._authorize(
            principal, "run_benchmark", {"platform": "snowflake", "benchmark": "tpch", "scale_factor": 1}
        )
    with pytest.raises(MCPError, match="Benchmark"):
        middleware._authorize(
            principal, "run_benchmark", {"platform": "duckdb", "benchmark": "tpcds", "scale_factor": 1}
        )
    with pytest.raises(MCPError, match="scale"):
        middleware._authorize(
            principal, "run_benchmark", {"platform": "duckdb", "benchmark": "tpch", "scale_factor": 2}
        )
    with pytest.raises(MCPError, match="finite"):
        middleware._authorize(
            principal, "run_benchmark", {"platform": "duckdb", "benchmark": "tpch", "scale_factor": "nan"}
        )


def test_durable_admission_is_shared_between_store_instances(tmp_path: Path) -> None:
    limits = AdmissionLimits(global_concurrency=1, principal_concurrency=1, queue_limit=0)
    first = DurableSecurityStore(tmp_path / "state.sqlite3", limits)
    second = DurableSecurityStore(tmp_path / "state.sqlite3", limits)

    async def exercise() -> None:
        lease = await first.admit("principal-a")
        with pytest.raises(MCPError, match="queue"):
            await second.admit("principal-b")
        first.release(lease)
        second_lease = await second.admit("principal-b")
        second.release(second_lease)

    anyio.run(exercise)


def test_audit_schema_excludes_secrets_arguments_and_database_urls(tmp_path: Path) -> None:
    store = DurableSecurityStore(tmp_path / "state.sqlite3", AdmissionLimits())
    store.audit(
        principal_id="opaque-principal",
        tool_name="run_benchmark",
        decision="allowed",
        execution_id="execution-1",
        artifact_ref="/server/owned/result.json",
    )
    serialized = repr(store.audit_events())
    assert "opaque-principal" in serialized
    assert "result.json" in serialized
    assert "server/owned" not in serialized
    assert "token" not in serialized.lower()


def test_audit_reference_extraction_is_bounded_to_execution_and_basename() -> None:
    result = CallToolResult(
        content=[
            TextContent(
                type="text",
                text='{"mcp_metadata":{"execution_id":"execution-1","result_file":"/owned/result.json"}}',
            )
        ]
    )
    assert RemoteSecurityMiddleware._result_refs(result) == ("execution-1", "/owned/result.json")
