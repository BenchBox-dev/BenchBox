"""Regression tests for develop PR metric collection and timeout alignment."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "_project" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("dev_loop_pr_metrics", SCRIPTS / "dev_loop_pr_metrics.py")
assert spec is not None and spec.loader is not None
metrics = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = metrics
spec.loader.exec_module(metrics)


class _NoRunsClient:
    repo = "owner/repo"

    def get_paginated(self, *_args, **_kwargs):
        return []


class _FakeClient:
    repo = "joeharris76/BenchBox"

    def __init__(self, runs: list[dict], jobs: list[dict] | None = None, checks: list[dict] | None = None) -> None:
        self.runs = runs
        self.jobs = jobs or []
        self.checks = checks or []

    def get_paginated(self, path: str, *, item_key: str) -> list[dict]:
        if item_key == "workflow_runs":
            return self.runs
        if item_key == "jobs":
            return self.jobs
        assert item_key == "check_runs"
        return self.checks


def test_gh_api_retries_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_run(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls < 3:
            return SimpleNamespace(returncode=1, stdout="", stderr="temporary failure")
        return SimpleNamespace(returncode=0, stdout='{"ok": true}', stderr="")

    monkeypatch.setattr(metrics.subprocess, "run", fake_run)
    monkeypatch.setattr(metrics.time, "sleep", lambda _seconds: None)

    assert metrics._gh_api("/repos/example/project") == {"ok": True}
    assert calls == 3


def test_empty_first_pass_run_returns_all_metric_slots() -> None:
    assert metrics.first_pass_green_and_job_seconds(_NoRunsClient(), "branch") == (None, None, None)


def test_runtime_metrics_only_include_successful_jobs() -> None:
    runs = [
        {
            "id": 42,
            "name": "Develop PR",
            "created_at": "2026-07-27T10:00:00+00:00",
            "conclusion": "success",
        }
    ]
    jobs = [
        {
            "name": metrics.FAST_TEST_JOB_NAME,
            "conclusion": "cancelled",
            "started_at": "2026-07-27T10:01:00+00:00",
            "completed_at": "2026-07-27T10:09:00+00:00",
        },
        {
            "name": metrics.FAST_TEST_JOB_NAME,
            "conclusion": "success",
            "started_at": "2026-07-27T10:10:00+00:00",
            "completed_at": "2026-07-27T10:10:20+00:00",
        },
        {
            "name": metrics.MEDIUM_TEST_JOB_NAME,
            "conclusion": "failure",
            "started_at": "2026-07-27T10:11:00+00:00",
            "completed_at": "2026-07-27T10:11:30+00:00",
        },
        {
            "name": metrics.MEDIUM_TEST_JOB_NAME,
            "conclusion": "success",
            "started_at": "2026-07-27T10:12:00+00:00",
            "completed_at": "2026-07-27T10:12:45+00:00",
        },
    ]

    result = metrics.first_pass_green_and_job_seconds(_FakeClient(runs, jobs), "feature/metrics")

    assert result == (True, 20.0, 45.0)


def test_event_fanout_for_pr_fetches_same_head_runs_jobs_and_checks() -> None:
    checks = [
        _check("ci-required-result", started="2026-07-27T10:00:00Z", completed="2026-07-27T10:05:00Z"),
        _check("Results Explorer browser gate", started="2026-07-27T10:00:00Z", completed="2026-07-27T10:01:00Z"),
        _check("ruleset-drift", started="2026-07-27T10:00:00Z", completed="2026-07-27T10:02:00Z"),
    ]
    runs = [
        {
            "id": 7,
            "name": "Develop PR",
            "head_sha": "abc",
            "run_started_at": "2026-07-27T10:00:00Z",
            "updated_at": "2026-07-27T10:05:00Z",
            "status": "completed",
        }
    ]
    jobs = [
        {
            "name": "Install results-explorer dependencies",
            "conclusion": "success",
            "status": "completed",
            "started_at": "2026-07-27T10:00:00Z",
            "completed_at": "2026-07-27T10:01:00Z",
            "steps": [],
        }
    ]
    fanout = metrics.event_fanout_for_pr(
        _FakeClient(runs, jobs, checks),
        {"head": {"sha": "abc"}, "merged_at": "2026-07-27T10:06:00Z"},
    )
    assert fanout["required_gate_seconds"] == 300.0
    assert fanout["all_workflow_seconds"] == 300.0
    assert fanout["queue_delay_seconds"] == 60.0
    assert fanout["workflow_run_counts"] == {"Develop PR": 1}


def test_medium_budget_reads_workflow_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    workflow = tmp_path / "pr.yml"
    workflow.write_text("jobs:\n  medium-test:\n    timeout-minutes: 55\n", encoding="utf-8")
    monkeypatch.setattr(metrics, "MEDIUM_TEST_WORKFLOW_PATH", workflow)

    warning = metrics._medium_budget_warning(55 * 60)

    assert warning is not None
    assert "55 min timeout" in warning


def _check(
    name: str,
    *,
    conclusion: str = "success",
    started: str,
    completed: str,
) -> dict:
    return {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": started,
        "completed_at": completed,
    }


def test_required_gate_uses_latest_rerun_and_ignores_stale_failure() -> None:
    checks = [
        _check(
            "ci-required-result", conclusion="failure", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:10:00Z"
        ),
        _check("ci-required-result", started="2026-08-14T00:12:00Z", completed="2026-08-14T00:20:00Z"),
        _check("Results Explorer browser gate", started="2026-08-14T00:12:00Z", completed="2026-08-14T00:13:00Z"),
        _check("ruleset-drift", started="2026-08-14T00:12:00Z", completed="2026-08-14T00:12:30Z"),
    ]
    assert metrics.required_gate_seconds(checks) == 8 * 60.0
    assert metrics.merge_unblock_seconds(checks) == 8 * 60.0


def test_missing_required_context_yields_no_merge_unblock() -> None:
    checks = [
        _check("ci-required-result", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:05:00Z"),
        _check("Results Explorer browser gate", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:01:00Z"),
    ]
    assert metrics.required_gate_seconds(checks) is None
    assert metrics.merge_unblock_seconds(checks) is None


def test_required_context_rename_is_a_missing_check() -> None:
    checks = [
        _check("ci-required-result", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:05:00Z"),
        _check("Results Explorer browser gate", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:01:00Z"),
        _check("ruleset-drift-old-name", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:01:00Z"),
    ]
    assert metrics.required_gate_seconds(checks) is None


def test_all_workflow_seconds_span_multiple_synchronize_workflows() -> None:
    runs = [
        {
            "name": "Develop PR",
            "head_sha": "abc",
            "run_started_at": "2026-08-14T00:00:00Z",
            "updated_at": "2026-08-14T00:30:00Z",
            "status": "completed",
        },
        {
            "name": "Documentation",
            "head_sha": "abc",
            "run_started_at": "2026-08-14T00:00:05Z",
            "updated_at": "2026-08-14T00:07:00Z",
            "status": "completed",
        },
        {
            "name": "Results Explorer browser tests",
            "head_sha": "abc",
            "run_started_at": "2026-08-14T00:00:02Z",
            "updated_at": "2026-08-14T00:00:40Z",
            "status": "completed",
        },
    ]
    assert metrics.all_workflow_seconds(runs) == 30 * 60.0
    grouped = metrics.correlate_runs_by_head(runs)
    assert list(grouped) == ["abc"]
    assert len(grouped["abc"]) == 3


def test_in_progress_workflow_does_not_close_all_workflow_window() -> None:
    runs = [
        {
            "name": "Develop PR",
            "run_started_at": "2026-08-14T00:00:00Z",
            "updated_at": "2026-08-14T00:10:00Z",
            "status": "in_progress",
        },
    ]
    assert metrics.all_workflow_seconds(runs) is None


def test_cancelled_jobs_are_excluded_from_completed_runner_minutes() -> None:
    jobs = [
        {
            "name": "lint",
            "conclusion": "success",
            "status": "completed",
            "started_at": "2026-08-14T00:00:00Z",
            "completed_at": "2026-08-14T00:05:00Z",
            "steps": [
                {"name": "Checkout code", "started_at": "2026-08-14T00:00:00Z", "completed_at": "2026-08-14T00:00:30Z"},
                {"name": "Install uv", "started_at": "2026-08-14T00:00:30Z", "completed_at": "2026-08-14T00:01:00Z"},
                {
                    "name": "Lint and format check with ruff",
                    "started_at": "2026-08-14T00:01:00Z",
                    "completed_at": "2026-08-14T00:05:00Z",
                },
            ],
        },
        {
            "name": "medium-test",
            "conclusion": "cancelled",
            "status": "completed",
            "started_at": "2026-08-14T00:00:00Z",
            "completed_at": "2026-08-14T00:20:00Z",
        },
    ]
    setup, execution, total = metrics.job_setup_execution_seconds(jobs[0])
    assert setup == 60.0
    assert execution == 240.0
    assert total == 300.0
    report = metrics.runner_minute_report(jobs)
    assert report["completed_runner_minutes"] == 5.0
    assert report["cancelled_runner_minutes"] == 20.0
    assert report["cancelled_job_count"] == 1
    assert report["public_standard_runner_usd"] == 0.0
    assert metrics.job_setup_execution_seconds(jobs[1]) == (None, None, None)


def test_event_fanout_separates_required_gate_from_documentation() -> None:
    checks = [
        _check("ci-required-result", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:10:00Z"),
        _check("Results Explorer browser gate", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:00:20Z"),
        _check("ruleset-drift", started="2026-08-14T00:00:00Z", completed="2026-08-14T00:00:30Z"),
    ]
    runs = [
        {
            "name": "Develop PR",
            "run_started_at": "2026-08-14T00:00:00Z",
            "updated_at": "2026-08-14T00:10:00Z",
            "status": "completed",
        },
        {
            "name": "Documentation",
            "run_started_at": "2026-08-14T00:00:00Z",
            "updated_at": "2026-08-14T00:07:00Z",
            "status": "completed",
        },
    ]
    jobs = [
        {
            "name": "build",
            "conclusion": "success",
            "status": "completed",
            "started_at": "2026-08-14T00:00:00Z",
            "completed_at": "2026-08-14T00:06:00Z",
        }
    ]
    fanout = metrics.event_fanout_metrics(
        runs=runs,
        jobs=jobs,
        check_runs=checks,
        merged_at="2026-08-14T00:12:00Z",
    )
    assert fanout["schema"] == metrics.EVENT_FANOUT_SCHEMA
    assert fanout["required_gate_seconds"] == 600.0
    assert fanout["merge_unblock_seconds"] == 600.0
    assert fanout["all_workflow_seconds"] == 600.0
    assert fanout["queue_delay_seconds"] == 120.0
    assert fanout["workflow_run_counts"]["Documentation"] == 1


def test_event_fanout_schema_is_versioned_and_help_documents_flag() -> None:
    assert metrics.EVENT_FANOUT_SCHEMA == "event_fanout_v1"
    with pytest.raises(SystemExit) as exc:
        metrics.main(["--help"])
    assert exc.value.code == 0
