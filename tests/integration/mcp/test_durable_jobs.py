"""Multi-worker, restart, and tenant acceptance tests for durable MCP jobs."""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import pytest
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent

from benchbox.mcp.jobs import DurableJobRepository, DurableJobWorker
from benchbox.mcp.security import JobLimits, TenantWorkspaceProvider
from tests.integration.mcp._security import authenticated_http_client, write_security_config

pytestmark = [pytest.mark.integration, pytest.mark.fast]


def _request() -> dict[str, object]:
    return {"platform": "duckdb", "benchmark": "tpch", "scale_factor": 0.01}


def _executor(job, staging: Path) -> dict[str, object]:
    result = staging / "benchmark.json"
    result.write_text(json.dumps({"execution_id": job.execution_id}), encoding="utf-8")
    return {"mcp_metadata": {"execution_id": job.execution_id, "result_file": str(result)}}


def test_two_worker_submission_observation_and_completion(tmp_path: Path) -> None:
    limits = JobLimits()
    first_repository = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    second_repository = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    workspaces = TenantWorkspaceProvider(tmp_path / "workspaces")
    second_worker = DurableJobWorker(second_repository, workspaces, executor=_executor, worker_id="worker-b")
    submitted, _ = first_repository.submit("tenant-a", _request())

    claimed = second_repository.claim(second_worker.worker_id)
    assert claimed is not None
    anyio.run(second_worker._run_job, claimed)

    observed = first_repository.get_owned(submitted.execution_id, "tenant-a")
    assert observed is not None and observed.state == "completed"
    assert observed.artifact_path is not None and Path(observed.artifact_path).is_file()


def test_restart_recovers_expired_worker_lease(tmp_path: Path) -> None:
    limits = JobLimits(lease_seconds=0.05, poll_seconds=0.01, max_attempts=2)
    first_repository = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    submitted, _ = first_repository.submit("tenant-a", _request())
    assert first_repository.claim("terminated-worker") is not None

    anyio.run(anyio.sleep, 0.06)
    restarted_repository = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    restarted_worker = DurableJobWorker(
        restarted_repository,
        TenantWorkspaceProvider(tmp_path / "workspaces"),
        executor=_executor,
        worker_id="restarted-worker",
    )
    restarted_worker.recover_expired()
    claimed = restarted_repository.claim(restarted_worker.worker_id)
    assert claimed is not None
    anyio.run(restarted_worker._run_job, claimed)

    completed = first_repository.get(submitted.execution_id)
    assert completed is not None and completed.state == "completed"
    assert completed.attempts == 2


def test_tenant_cannot_observe_or_cancel_another_job(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits())
    submitted, _ = repository.submit("tenant-a", _request())

    assert repository.get_owned(submitted.execution_id, "tenant-b") is None
    assert repository.cancel(submitted.execution_id, "tenant-b") is None
    assert repository.get_owned(submitted.execution_id, "tenant-a") is not None


def test_tenant_job_tools_are_remote_only_and_cross_tenant_fail_closed(tmp_path: Path, monkeypatch) -> None:
    token_a = "tenant-a-job-token"
    token_b = "tenant-b-job-token"
    config = write_security_config(
        tmp_path,
        tokens={
            token_a: ("tenant-a", ("benchbox:read", "benchbox:execute")),
            token_b: ("tenant-b", ("benchbox:read", "benchbox:execute")),
        },
    )
    monkeypatch.setattr(DurableJobWorker, "_execute_benchmark", staticmethod(_executor))

    async def exercise() -> None:
        async with authenticated_http_client(config, token_a) as (client_a, _):
            tools = await client_a.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {"start_benchmark", "get_benchmark_status", "get_benchmark_result", "cancel_benchmark"} <= names
            started = await client_a.call_tool(
                "start_benchmark",
                {
                    "platform": "duckdb",
                    "benchmark": "tpch",
                    "scale_factor": 0.01,
                    "idempotency_key": "acceptance-1",
                },
            )
            assert not started.is_error
            assert isinstance(started.content[0], TextContent)
            execution_id = json.loads(started.content[0].text)["execution_id"]

            for _ in range(100):
                current = await client_a.call_tool("get_benchmark_status", {"execution_id": execution_id})
                assert isinstance(current.content[0], TextContent)
                if json.loads(current.content[0].text)["status"] == "completed":
                    break
                await anyio.sleep(0.01)
            else:
                pytest.fail("durable benchmark did not complete")
            result = await client_a.call_tool("get_benchmark_result", {"execution_id": execution_id})
            assert not result.is_error
            assert execution_id in result.content[0].text
            synchronous = await client_a.call_tool(
                "run_benchmark", {"platform": "duckdb", "benchmark": "tpch", "scale_factor": 0.01}
            )
            assert "requires start_benchmark" in synchronous.content[0].text

        async with authenticated_http_client(config, token_b) as (client_b, _):
            for tool_name in ("get_benchmark_status", "cancel_benchmark", "get_benchmark_result"):
                with pytest.raises(MCPError, match="not found"):
                    await client_b.call_tool(tool_name, {"execution_id": execution_id})

    anyio.run(exercise)
