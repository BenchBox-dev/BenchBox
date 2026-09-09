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


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "dev_loop_metrics"
REASONS = (
    "not_synchronize",
    "missing_event_sha",
    "not_exactly_two_parents",
    "chained_refresh",
    "prior_check_not_success",
    "prior_check_unbound",
    "prior_certification_not_full",
)


class _LifecycleClient:
    repo = "owner/repo"

    def __init__(
        self,
        commits: list[dict],
        runs_by_sha: dict[str, list[dict]],
        jobs_by_run: dict[int, list[dict]],
        checks_by_sha: dict[str, list[dict]],
        timeline: list[dict] | None = None,
    ) -> None:
        self.commits = commits
        self.runs_by_sha = runs_by_sha
        self.jobs_by_run = jobs_by_run
        self.checks_by_sha = checks_by_sha
        self.timeline = timeline or []

    def get_paginated(self, path: str, item_key: str | None = None) -> list[dict]:
        if "pulls/" in path and path.endswith("/commits"):
            return self.commits
        if "/timeline" in path:
            return self.timeline
        if "actions/runs?head_sha=" in path:
            return self.runs_by_sha.get(path.rsplit("head_sha=", 1)[1], [])
        if path.endswith("/jobs"):
            run_id = int(path.rsplit("/runs/", 1)[1].split("/jobs", 1)[0])
            return self.jobs_by_run.get(run_id, [])
        assert "check-runs" in path
        return self.checks_by_sha.get(path.rsplit("/commits/", 1)[1].split("/", 1)[0], [])


def _timed_job(minutes: float) -> dict:
    del minutes
    return {
        "conclusion": "success",
        "status": "completed",
        "started_at": "2026-08-14T00:00:00Z",
        "completed_at": "2026-08-14T00:06:00Z",
        "steps": [],
    }


def test_lifecycle_enumerates_superseded_heads_and_explicit_missing() -> None:
    heads = ["a" * 40, "b" * 40, "c" * 40]
    client = _LifecycleClient(
        commits=[{"sha": sha} for sha in heads],
        runs_by_sha={
            heads[0]: [{"id": 1, "run_attempt": 2, "name": "Develop PR"}],
            heads[2]: [{"id": 3, "name": "Develop PR"}],
        },
        jobs_by_run={1: [_timed_job(6.0)], 3: [_timed_job(6.0)]},
        checks_by_sha={},
    )
    pr = {"number": 7, "head": {"sha": heads[2]}, "merged_at": None}
    lifecycle = metrics.lifecycle_for_pr(client, pr)
    assert lifecycle["heads"] == heads
    assert set(lifecycle["per_head"]) == {heads[0], heads[2]}
    assert lifecycle["attempts"] == {heads[0]: 2, heads[2]: 1}
    assert [m["head_sha"] for m in lifecycle["missing"]] == [heads[1]]
    assert lifecycle["missing"][0]["status"] == "missing-artifact"
    assert lifecycle["totals"]["head_count"] == 3
    assert lifecycle["totals"]["total_attempts"] == 3
    assert lifecycle["totals"]["completed_runner_minutes"] == pytest.approx(12.0)


def _process_doc(version: str = "1.0.0") -> tuple[dict, str]:
    doc = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": version}
    import hashlib
    import json as _json

    return doc, hashlib.sha256(_json.dumps(doc).encode()).hexdigest()


def test_lifecycle_validator_accepts_consistent_report() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    process = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}
    assert metrics.validate_lifecycle_baseline(lifecycle, process, "digest-of-frozen-process-baseline") == []


def test_lifecycle_validator_rejects_tampered_totals() -> None:
    import copy
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_tampered_totals.json").read_text())
    process = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}
    errors = metrics.validate_lifecycle_baseline(lifecycle, process, "digest-of-frozen-process-baseline")
    assert any("totals.completed_runner_minutes" in e for e in errors)


def test_lifecycle_validator_rejects_omitted_superseded_head() -> None:
    import copy
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    lifecycle = copy.deepcopy(lifecycle)
    entry = lifecycle["prs"][0]
    dropped = entry["heads"][0]
    del entry["per_head"][dropped]
    del entry["attempts"][dropped]
    process = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}
    errors = metrics.validate_lifecycle_baseline(lifecycle, process, "digest-of-frozen-process-baseline")
    assert any("disagree" in e for e in errors)


def test_lifecycle_validator_rejects_changed_thresholds() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    changed = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.1.0"}
    errors = metrics.validate_lifecycle_baseline(lifecycle, changed, "digest-of-frozen-process-baseline")
    assert any("criteria changed" in e for e in errors)
    same_version = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}
    errors = metrics.validate_lifecycle_baseline(lifecycle, same_version, "different-digest")
    assert any("frozen digest" in e for e in errors)


def test_refresh_audit_recompute_accepts_consistent_block() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    audit = (FIXTURES / "refresh_audit_sample.md").read_text()
    assert metrics.validate_refresh_audit(audit, lifecycle, REASONS) == []


def test_refresh_audit_rejects_duplicate_identity() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    audit = (FIXTURES / "refresh_audit_sample.md").read_text()
    block_text = audit.replace(
        '"head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",\n      "run_id": 12,',
        '"head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",\n      "run_id": 11,',
    )
    errors = metrics.validate_refresh_audit(block_text, lifecycle, REASONS)
    assert any("duplicate" in e for e in errors)


def test_refresh_audit_rejects_conflated_timing_and_identity() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    audit = (FIXTURES / "refresh_audit_sample.md").read_text()
    merged = audit.replace('"prior_check_unbound": 0,\n    ', "")
    errors = metrics.validate_refresh_audit(merged, lifecycle, REASONS)
    assert any("prior_check_unbound" in e for e in errors)


def test_refresh_audit_rejects_unknown_denominator_and_changed_window() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    audit = (FIXTURES / "refresh_audit_sample.md").read_text()
    errors = metrics.validate_refresh_audit(audit.replace("[101, 102]", "[101, 999]"), lifecycle, REASONS)
    assert any("outside the frozen baseline" in e for e in errors)
    errors = metrics.validate_refresh_audit(audit.replace("[101, 102]", "[101]"), lifecycle, REASONS)
    assert any("omits frozen baseline PRs" in e for e in errors)
    errors = metrics.validate_refresh_audit(
        audit.replace("2026-08-11T00:00:00+00:00", "2026-08-01T00:00:00+00:00"), lifecycle, REASONS
    )
    assert any("window_start" in e for e in errors)


def test_refresh_reason_codes_come_from_classifier() -> None:
    codes = metrics.load_refresh_reason_codes()
    assert metrics.REFRESH_REASON_TIMING in codes
    assert metrics.REFRESH_REASON_IDENTITY in codes


class _SearchClient:
    repo = "owner/repo"

    def __init__(self, total: int, items: list[dict]) -> None:
        self.total = total
        self.items = items

    def get(self, _path: str) -> dict:
        return {"total_count": self.total, "items": self.items[:1]}

    def get_paginated(self, _path: str, item_key: str | None = None) -> list[dict]:
        assert item_key == "items"
        return self.items


def test_cohort_enumeration_is_complete_against_total_count() -> None:
    client = _SearchClient(3, [{"number": 7}, {"number": 8}, {"number": 9}])
    assert metrics.fetch_cohort_pr_numbers(client, "2026-08-11T00:00:00+00:00", "2026-09-08T00:00:00+00:00") == [
        7,
        8,
        9,
    ]


def test_cohort_enumeration_fails_closed_on_short_page() -> None:
    client = _SearchClient(3, [{"number": 7}])
    with pytest.raises(metrics.ApiFailure, match="truncated"):
        metrics.fetch_cohort_pr_numbers(client, "2026-08-11T00:00:00+00:00", "2026-09-08T00:00:00+00:00")


def _acceptance_doc(**overrides: object) -> dict:
    doc: dict = {
        "schema": "pr_process_acceptance_v1",
        "process_binding": {"criteria_version": "1.0.0", "process_digest": "digest"},
        "registration": {"commit": "abc123", "time": "2026-09-08T12:33:43Z"},
        "incident_replays": [{"scenario": "s1", "status": "pass"}],
        "cohort": {
            "required": {"window_start": "W0", "window_end": "W1", "min_prs": 10, "min_days": 7, "strata": ["product"]},
            "observed": {
                "window_start": "W0",
                "window_end": "W1",
                "prs": 10,
                "days": 7,
                "strata": ["product"],
                "batch_deliveries": [],
            },
        },
        "efficiency": {
            "baseline_avoidable_actions": 65,
            "observed_avoidable_actions": 20,
            "added_required_lane_failure": False,
            "p95_regression_attributable": False,
        },
    }
    doc.update(overrides)
    return doc


def _process_doc() -> dict:
    return {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}


def test_acceptance_validator_rejects_changed_criteria_and_cohort() -> None:
    acceptance = _acceptance_doc()
    errors = metrics.validate_process_acceptance(acceptance, {"criteria_version": "2.0.0"}, "digest")
    assert any("criteria" in e for e in errors)
    errors = metrics.validate_process_acceptance(acceptance, _process_doc(), "other-digest")
    assert any("bound digest" in e for e in errors)
    moved = _acceptance_doc()
    moved["cohort"]["observed"]["window_end"] = "W2"
    errors = metrics.validate_process_acceptance(moved, _process_doc(), "digest")
    assert any("unreported cohort change" in e for e in errors)


def test_acceptance_validator_holds_incomplete_cohort_and_replays() -> None:
    acceptance = _acceptance_doc()
    acceptance["cohort"]["observed"]["prs"] = 4
    acceptance["incident_replays"] = [{"scenario": "s1", "status": "pending"}]
    acceptance["efficiency"]["observed_avoidable_actions"] = None
    errors = metrics.validate_process_acceptance(acceptance, _process_doc(), "digest")
    assert any("prs" in e for e in errors)
    assert any("not passing" in e for e in errors)
    assert any("unmeasured" in e for e in errors)


def test_acceptance_validator_accepts_complete_record() -> None:
    """The validator can pass: guards against a firewall that never opens."""
    import hashlib
    import json as _json2
    import subprocess

    repo_root = Path(metrics.__file__).resolve().parents[2]
    process_path = repo_root / "_project" / "analysis" / "pr-process-acceptance-baseline.json"
    process_raw = process_path.read_bytes()
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    process = _json2.loads(process_raw.decode("utf-8"))
    frozen = process["prospective_cohort"]
    acceptance = _acceptance_doc()
    acceptance["process_binding"] = {
        "criteria_version": process["criteria_version"],
        "process_digest": hashlib.sha256(process_raw).hexdigest(),
    }
    acceptance["registration"] = {"commit": head, "time": "2026-09-08T12:33:43Z"}
    acceptance["incident_replays"] = [{"scenario": name, "status": "pass"} for name in process["incident_scenarios"]]
    acceptance["cohort"]["required"]["min_prs"] = frozen["min_prs"]
    acceptance["cohort"]["required"]["min_days"] = frozen["min_days"]
    acceptance["cohort"]["required"]["strata"] = list(frozen["strata"])
    acceptance["cohort"]["observed"]["prs"] = frozen["min_prs"]
    acceptance["cohort"]["observed"]["days"] = frozen["min_days"]
    acceptance["cohort"]["observed"]["strata"] = list(frozen["strata"])
    acceptance["cohort"]["observed"]["human_hold"] = True
    acceptance["cohort"]["observed"]["batch_deliveries"] = [
        {"members": ["a", "b"]},
        {"members": ["c", "d"]},
    ]
    acceptance["efficiency"]["observed_avoidable_actions"] = 20
    errors = metrics.validate_process_acceptance(acceptance, process, hashlib.sha256(process_raw).hexdigest())
    assert errors == []


def test_acceptance_validator_rejects_weakened_frozen_requirements() -> None:
    import hashlib
    import json as _json2

    repo_root = Path(metrics.__file__).resolve().parents[2]
    process_path = repo_root / "_project" / "analysis" / "pr-process-acceptance-baseline.json"
    process_raw = process_path.read_bytes()
    process = _json2.loads(process_raw.decode("utf-8"))
    digest = hashlib.sha256(process_raw).hexdigest()
    frozen = process["prospective_cohort"]

    def conforming() -> dict:
        acceptance = _acceptance_doc()
        acceptance["process_binding"] = {
            "criteria_version": process["criteria_version"],
            "process_digest": digest,
        }
        acceptance["incident_replays"] = [
            {"scenario": name, "status": "pass"} for name in process["incident_scenarios"]
        ]
        acceptance["cohort"]["required"]["min_prs"] = frozen["min_prs"]
        acceptance["cohort"]["required"]["min_days"] = frozen["min_days"]
        acceptance["cohort"]["required"]["strata"] = list(frozen["strata"])
        acceptance["cohort"]["observed"]["prs"] = frozen["min_prs"]
        acceptance["cohort"]["observed"]["days"] = frozen["min_days"]
        acceptance["cohort"]["observed"]["strata"] = list(frozen["strata"])
        acceptance["cohort"]["observed"]["human_hold"] = True
        acceptance["cohort"]["observed"]["batch_deliveries"] = [
            {"members": ["a", "b"]},
            {"members": ["c", "d"]},
        ]
        return acceptance

    weakened = conforming()
    weakened["cohort"]["required"]["min_prs"] = frozen["min_prs"] - 1
    errors = metrics.validate_process_acceptance(weakened, process, digest)
    assert any("weakens the frozen floor" in e for e in errors)

    dropped = conforming()
    dropped["incident_replays"] = dropped["incident_replays"][:-1]
    errors = metrics.validate_process_acceptance(dropped, process, digest)
    assert any("replay scenario set" in e for e in errors)

    invented = conforming()
    invented["incident_replays"].append({"scenario": "invented-easy", "status": "pass"})
    errors = metrics.validate_process_acceptance(invented, process, digest)
    assert any("replay scenario set" in e for e in errors)

    few = conforming()
    few["cohort"]["observed"]["batch_deliveries"] = [{"members": ["a", "b"]}]
    errors = metrics.validate_process_acceptance(few, process, digest)
    assert any("batch deliveries insufficient" in e for e in errors)

    no_hold = conforming()
    del no_hold["cohort"]["observed"]["human_hold"]
    errors = metrics.validate_process_acceptance(no_hold, process, digest)
    assert any("human hold" in e for e in errors)

    weak_days = conforming()
    weak_days["cohort"]["required"]["min_days"] = frozen["min_days"] - 1
    errors = metrics.validate_process_acceptance(weak_days, process, digest)
    assert any("weakens the frozen floor" in e for e in errors)

    changed_strata = conforming()
    changed_strata["cohort"]["required"]["strata"] = list(frozen["strata"]) + ["invented"]
    errors = metrics.validate_process_acceptance(changed_strata, process, digest)
    assert any("frozen strata" in e for e in errors)

    weak_reduction = conforming()
    weak_reduction["efficiency"]["observed_avoidable_actions"] = 60
    errors = metrics.validate_process_acceptance(weak_reduction, process, digest)
    assert any("below frozen 50%" in e for e in errors)


def test_lifecycle_validator_rejects_unbound_attempts() -> None:
    import copy
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text(encoding="utf-8"))
    lifecycle = copy.deepcopy(lifecycle)
    lifecycle["prs"][0]["attempts"]["dddddddddddddddddddddddddddddddddddddddd"] = 1
    process = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}
    errors = metrics.validate_lifecycle_baseline(lifecycle, process, "digest-of-frozen-process-baseline")
    assert any("unobserved head" in e for e in errors)


def test_refresh_audit_rejects_non_list_denominator() -> None:
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text())
    audit = (
        (FIXTURES / "refresh_audit_sample.md")
        .read_text()
        .replace('"denominator_prs": [101, 102]', '"denominator_prs": 101')
    )
    errors = metrics.validate_refresh_audit(audit, lifecycle, REASONS)
    assert any("must be a list" in e for e in errors)


def _failed_job() -> dict:
    return {
        "conclusion": "failure",
        "status": "completed",
        "started_at": "2026-08-14T00:00:00Z",
        "completed_at": "2026-08-14T00:04:00Z",
        "steps": [],
    }


def test_lifecycle_nontip_split_and_failed_bucket() -> None:
    tip, mid, root = "a" * 40, "b" * 40, "c" * 40
    commits = [
        {"sha": root, "parents": []},
        {"sha": mid, "parents": [{"sha": root}]},
        {"sha": tip, "parents": [{"sha": mid}]},
    ]
    client = _LifecycleClient(
        commits=commits,
        runs_by_sha={tip: [{"id": 1, "run_attempt": 1, "name": "Develop PR"}]},
        jobs_by_run={1: [_timed_job(6.0), _failed_job()]},
        checks_by_sha={},
    )
    pr = {"number": 7, "head": {"sha": tip}, "merged_at": None}
    lifecycle = metrics.lifecycle_for_pr(client, pr)
    assert lifecycle["heads"] == [root, mid, tip]
    assert set(lifecycle["per_head"]) == {tip}
    statuses = {m["head_sha"]: m["status"] for m in lifecycle["missing"]}
    assert statuses == {root: "non-tip-commit", mid: "non-tip-commit"}
    assert lifecycle["totals"]["missing_head_count"] == 0
    assert lifecycle["totals"]["non_tip_head_count"] == 2
    assert lifecycle["totals"]["failed_runner_minutes"] == pytest.approx(4.0)
    assert lifecycle["totals"]["completed_runner_minutes"] == pytest.approx(6.0)


def test_lifecycle_rejects_observed_head_without_retrieval_ids() -> None:
    import copy
    import json as _json

    lifecycle = _json.loads((FIXTURES / "lifecycle_sample.json").read_text(encoding="utf-8"))
    lifecycle = copy.deepcopy(lifecycle)
    first = lifecycle["prs"][0]
    sha = next(iter(first["per_head"]))
    del first["per_head"][sha]["retrieval_ids"]
    process = {"schema": "pr_process_acceptance_baseline_v1", "criteria_version": "1.0.0"}
    errors = metrics.validate_lifecycle_baseline(lifecycle, process, "digest-of-frozen-process-baseline")
    assert any("no run retrieval IDs" in e for e in errors)
