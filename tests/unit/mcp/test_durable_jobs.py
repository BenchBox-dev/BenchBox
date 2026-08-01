"""Unit coverage for durable remote benchmark job coordination."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import anyio
import pytest
from mcp.shared.exceptions import MCPError

from benchbox.mcp.jobs import DurableJobRepository, DurableJobWorker
from benchbox.mcp.security import JobLimits, TenantWorkspaceProvider

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _request(scale: float = 0.01) -> dict[str, object]:
    return {"platform": "duckdb", "benchmark": "tpch", "scale_factor": scale}


def test_job_submission_is_tenant_owned_and_idempotent(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits())
    first, created = repository.submit("tenant-a", _request(), idempotency_key="request-1")
    duplicate, duplicate_created = repository.submit("tenant-a", _request(), idempotency_key="request-1")

    assert created is True
    assert duplicate_created is False
    assert duplicate.execution_id == first.execution_id
    assert repository.get_owned(first.execution_id, "tenant-a") == first
    assert repository.get_owned(first.execution_id, "tenant-b") is None
    with pytest.raises(MCPError, match="different request"):
        repository.submit("tenant-a", _request(0.1), idempotency_key="request-1")


def test_job_queue_is_bounded_across_repository_instances(tmp_path: Path) -> None:
    limits = JobLimits(queue_limit=1)
    first = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    second = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    first.submit("tenant-a", _request())

    with pytest.raises(MCPError, match="queue"):
        second.submit("tenant-b", _request())


def test_job_claim_lease_retry_and_terminal_failure(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits(max_attempts=2))
    submitted, _ = repository.submit("tenant-a", _request())

    first = repository.claim("worker-a")
    assert first is not None
    assert first.state == "running"
    assert first.attempts == 1
    assert repository.claim("worker-b") is None
    assert repository.renew(first.execution_id, "worker-b") is False
    assert repository.fail_attempt(first.execution_id, "worker-a", "transient") == "queued"

    second = repository.claim("worker-b")
    assert second is not None
    assert second.execution_id == submitted.execution_id
    assert second.attempts == 2
    assert repository.fail_attempt(second.execution_id, "worker-b", "transient") == "failed"


def test_cancel_is_idempotent_and_fences_running_publication(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits())
    queued, _ = repository.submit("tenant-a", _request())
    cancelled = repository.cancel(queued.execution_id, "tenant-a")
    repeated = repository.cancel(queued.execution_id, "tenant-a")
    assert cancelled is not None and cancelled.state == "cancelled"
    assert repeated is not None and repeated.state == "cancelled"

    running, _ = repository.submit("tenant-a", _request())
    claimed = repository.claim("worker-a")
    assert claimed is not None and claimed.execution_id == running.execution_id
    requested = repository.cancel(running.execution_id, "tenant-a")
    assert requested is not None and requested.cancel_requested
    assert repository.begin_publication(running.execution_id, "worker-a") is False
    assert repository.fail_attempt(running.execution_id, "worker-a", "cancelled") == "cancelled"


def test_cancel_after_publication_commit_point_does_not_revoke_result(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits())
    submitted, _ = repository.submit("tenant-a", _request())
    claimed = repository.claim("worker-a")
    assert claimed is not None
    assert repository.begin_publication(submitted.execution_id, "worker-a")

    unchanged = repository.cancel(submitted.execution_id, "tenant-a")
    assert unchanged is not None and unchanged.state == "publishing"
    assert unchanged.cancel_requested is False
    artifact = tmp_path / "response.json"
    artifact.write_text("{}", encoding="utf-8")
    assert repository.complete(submitted.execution_id, "worker-a", artifact)


def test_completed_job_is_recorded_only_after_atomic_artifact_publication(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits())
    workspaces = TenantWorkspaceProvider(tmp_path / "workspaces")

    def executor(job, staging: Path):
        result = staging / "benchmark.json"
        result.write_text('{"ok": true}', encoding="utf-8")
        return {"mcp_metadata": {"execution_id": job.execution_id, "result_file": str(result)}}

    worker = DurableJobWorker(repository, workspaces, executor=executor, worker_id="worker-a")
    submitted, _ = repository.submit("tenant-a", _request())
    claimed = repository.claim(worker.worker_id)
    assert claimed is not None

    anyio.run(worker._run_job, claimed)

    completed = repository.get(submitted.execution_id)
    assert completed is not None and completed.state == "completed"
    assert completed.artifact_path is not None
    response_path = Path(completed.artifact_path)
    assert response_path.is_file()
    payload = json.loads(response_path.read_text(encoding="utf-8"))
    result_file = Path(payload["mcp_metadata"]["result_file"])
    assert result_file.is_file()
    assert ".staging" not in str(result_file)


def test_data_only_artifact_path_is_rewritten_into_final_tenant_job(tmp_path: Path) -> None:
    staging = tmp_path / ".staging" / "attempt"
    final_dir = tmp_path / "job"
    response = {"data_generation": {"data_path": str(staging / "generated_data")}}

    rewritten = DurableJobWorker._rewrite_result_paths(response, staging, final_dir)

    assert rewritten["data_generation"]["data_path"] == str(final_dir / "generated_data")


def test_expired_lease_recovery_requeues_without_duplicate_publication(tmp_path: Path) -> None:
    limits = JobLimits(lease_seconds=0.05, poll_seconds=0.01, max_attempts=2)
    repository = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    workspaces = TenantWorkspaceProvider(tmp_path / "workspaces")
    worker = DurableJobWorker(repository, workspaces, worker_id="worker-b")
    submitted, _ = repository.submit("tenant-a", _request())
    claimed = repository.claim("lost-worker")
    assert claimed is not None

    anyio.run(anyio.sleep, 0.06)
    worker.recover_expired()
    recovered = repository.get(submitted.execution_id)
    assert recovered is not None and recovered.state == "queued"
    replacement = repository.claim("worker-b")
    assert replacement is not None
    assert repository.begin_publication(submitted.execution_id, "lost-worker") is False
    assert repository.complete(submitted.execution_id, "lost-worker", tmp_path / "stale.json") is False


def test_unexpected_worker_failure_retries_then_can_complete(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits(max_attempts=2))
    workspaces = TenantWorkspaceProvider(tmp_path / "workspaces")

    def failing_executor(_job, _staging: Path):
        raise RuntimeError("opaque failure")

    submitted, _ = repository.submit("tenant-a", _request())
    first_worker = DurableJobWorker(repository, workspaces, executor=failing_executor, worker_id="worker-a")
    first_claim = repository.claim(first_worker.worker_id)
    assert first_claim is not None
    anyio.run(first_worker._run_job, first_claim)
    retried = repository.get(submitted.execution_id)
    assert retried is not None and retried.state == "queued"
    assert retried.error_code == "RuntimeError"

    second_worker = DurableJobWorker(
        repository,
        workspaces,
        executor=lambda job, _staging: {"mcp_metadata": {"execution_id": job.execution_id}},
        worker_id="worker-b",
    )
    second_claim = repository.claim(second_worker.worker_id)
    assert second_claim is not None
    anyio.run(second_worker._run_job, second_claim)
    completed = repository.get(submitted.execution_id)
    assert completed is not None and completed.state == "completed"


def test_publishing_recovery_completes_existing_durable_artifact(tmp_path: Path) -> None:
    limits = JobLimits(lease_seconds=0.05, poll_seconds=0.01)
    repository = DurableJobRepository(tmp_path / "state.sqlite3", limits)
    workspaces = TenantWorkspaceProvider(tmp_path / "workspaces")
    worker = DurableJobWorker(repository, workspaces, worker_id="recovery-worker")
    submitted, _ = repository.submit("tenant-a", _request())
    claimed = repository.claim("lost-worker")
    assert claimed is not None
    assert repository.begin_publication(claimed.execution_id, "lost-worker")
    _, final_dir, response_path = worker._job_paths(claimed)
    final_dir.mkdir(parents=True)
    response_path.write_text('{"mcp_metadata": {"execution_id": "recovered"}}', encoding="utf-8")
    (final_dir / ".published").write_text(claimed.execution_id, encoding="ascii")

    anyio.run(anyio.sleep, 0.06)
    worker.recover_expired()
    recovered = repository.get(submitted.execution_id)
    assert recovered is not None and recovered.state == "completed"
    assert recovered.artifact_path == str(response_path)


def test_retention_removes_artifact_before_terminal_metadata(tmp_path: Path) -> None:
    repository = DurableJobRepository(tmp_path / "state.sqlite3", JobLimits(retention_seconds=60))
    worker = DurableJobWorker(repository, TenantWorkspaceProvider(tmp_path / "workspaces"))
    submitted, _ = repository.submit("tenant-a", _request())
    repository.cancel(submitted.execution_id, "tenant-a")
    with sqlite3.connect(repository.path) as connection:
        connection.execute(
            "UPDATE mcp_benchmark_jobs SET completed_at = '2020-01-01T00:00:00+00:00' WHERE execution_id = ?",
            (submitted.execution_id,),
        )

    assert [job.execution_id for job in repository.expired_terminal()] == [submitted.execution_id]
    worker.purge_expired()
    assert repository.get(submitted.execution_id) is None
