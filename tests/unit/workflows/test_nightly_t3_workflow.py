"""Contract tests for the nightly T3 workflow.

The workflow splits Tier 3 validation into independent domain jobs and keeps one
issue per domain label. These tests pin the properties that make that safe:
triggers without branch filters, one job per domain, the cloud opt-in variable,
issue-write permission held by the reporting job only, and SHA-pinned actions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS_DIR / "nightly-v2.yml"

# Job id -> issue label.
DOMAIN_JOBS = {
    "docker": "t3:docker",
    "cloud": "t3:cloud",
    "perf": "t3:perf",
    "matrix": "t3:matrix",
    "browser": "t3:browser",
    "extension": "t3:extension",
    "install": "t3:install",
    "drift": "t3:drift",
    "quarantine": "t3:quarantine",
    "durations-refresh": "t3:durations",
}

_PINNED_ACTION = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")


def _load(path: Path = WORKFLOW) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    # PyYAML parses the bare `on` key as boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "workflow has no `on:` mapping"
    return triggers


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    return job.get("steps", [])


def _run_text(job: dict[str, Any]) -> str:
    return "\n".join(str(step.get("run", "")) for step in _steps(job))


def test_triggers_are_schedule_and_dispatch_without_branch_filters() -> None:
    triggers = _triggers(_load())
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert not any("branches" in (value or {}) for value in triggers.values() if isinstance(value, dict))


def test_schedule_does_not_collide_with_other_workflows() -> None:
    crons = _triggers(_load())["schedule"]
    assert len(crons) == 1
    mine = crons[0]["cron"]
    others: dict[str, str] = {}
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        if path == WORKFLOW:
            continue
        document = _load(path)
        triggers = document.get("on", document.get(True)) if isinstance(document, dict) else None
        if not isinstance(triggers, dict):
            continue
        for entry in triggers.get("schedule") or []:
            others[entry["cron"]] = path.name
    assert mine not in others, f"cron {mine!r} already used by {others.get(mine)}"


def test_every_domain_has_a_job() -> None:
    jobs = _load()["jobs"]
    missing = sorted(set(DOMAIN_JOBS) - set(jobs))
    assert not missing, f"missing domain jobs: {missing}"


def test_docker_covers_all_three_services() -> None:
    docker = _load()["jobs"]["docker"]
    services = {entry["service"] for entry in docker["strategy"]["matrix"]["include"]}
    assert services == {"postgres", "clickhouse", "trino"}
    assert docker["strategy"]["fail-fast"] is False


def test_wheel_matrix_covers_python_versions_and_operating_systems() -> None:
    job = _load()["jobs"]["matrix"]
    matrix = job["strategy"]["matrix"]
    assert matrix["python-version"] == ["3.11", "3.12", "3.13", "3.14"]
    assert set(matrix["os"]) == {"ubuntu-latest", "macos-latest", "windows-latest"}
    text = _run_text(job)
    assert "generate_data" in text and "TPCH" in text and "TPCDS" in text, "dbgen and dsdgen must run per OS"


def test_browser_covers_firefox_and_webkit() -> None:
    assert _load()["jobs"]["browser"]["strategy"]["matrix"]["browser"] == ["firefox", "webkit"]


def test_cloud_job_is_gated_by_repository_variable() -> None:
    condition = str(_load()["jobs"]["cloud"]["if"])
    assert "vars.BENCHBOX_T3_CLOUD_ENABLED == 'true'" in condition
    # The gate must be the whole condition: no `|| true` style escape hatches.
    assert "||" not in condition


def test_drift_job_is_weekly_gated_and_covers_all_checks() -> None:
    jobs = _load()["jobs"]
    assert jobs["drift"]["needs"] == ["drift-gate"]
    assert "needs.drift-gate.outputs.run == 'true'" in str(jobs["drift"]["if"])
    gate_text = _run_text(jobs["drift-gate"])
    assert "date -u +%u" in gate_text and "workflow_dispatch" in gate_text
    text = _run_text(jobs["drift"])
    for needle in (
        "results-data/bundles",
        "find_public_path_leaks",
        "check_submission_validator_sync.py",
        "cross_surface_baseline_autodetect.py",
        "generate_pricing_data.py --refresh",
    ):
        assert needle in text, f"drift job is missing {needle!r}"


def test_quarantine_job_tolerates_unregistered_marker() -> None:
    text = _run_text(_load()["jobs"]["quarantine"])
    assert "-m quarantine" in text
    assert "pytest.mark.quarantine" in text, "job must check marker registration before selecting it"


def test_durations_job_emits_pytest_durations_artifact() -> None:
    job = _load()["jobs"]["durations-refresh"]
    assert "--durations=0" in _run_text(job)
    uploads = [step for step in _steps(job) if str(step.get("uses", "")).startswith("actions/upload-artifact@")]
    assert uploads and uploads[-1]["with"]["name"] == "t3-durations"


def test_every_domain_job_uploads_artifacts() -> None:
    jobs = _load()["jobs"]
    without = [
        name
        for name in DOMAIN_JOBS
        if not any(str(step.get("uses", "")).startswith("actions/upload-artifact@") for step in _steps(jobs[name]))
    ]
    assert not without, f"domain jobs without an artifact upload: {without}"


def test_default_permissions_are_read_only() -> None:
    assert _load()["permissions"] == {"contents": "read"}


def test_only_report_job_holds_issue_write() -> None:
    jobs = _load()["jobs"]
    writers = {
        name for name, job in jobs.items() if "write" in {str(v) for v in (job.get("permissions") or {}).values()}
    }
    assert writers == {"report"}
    assert jobs["report"]["permissions"] == {"contents": "read", "issues": "write"}


def test_report_job_covers_every_domain_and_label() -> None:
    report = _load()["jobs"]["report"]
    assert set(report["needs"]) == set(DOMAIN_JOBS)
    assert "always()" in str(report["if"])
    text = _run_text(report)
    for job in DOMAIN_JOBS:
        assert re.search(rf"\b{re.escape(job)}\b", text), f"report loop omits {job}"
    # Labels are derived as t3:<domain>; the durations job maps to t3:durations.
    assert 'label="t3:${domain}"' in text
    assert "durations-refresh) domain=durations" in text
    assert "gh issue create" in text and "gh issue close" in text and "gh issue comment" in text


def test_actions_are_pinned_by_sha() -> None:
    unpinned: list[str] = []
    for name, job in _load()["jobs"].items():
        for step in _steps(job):
            uses = step.get("uses")
            if uses and not _PINNED_ACTION.match(str(uses)):
                unpinned.append(f"{name}: {uses}")
    assert not unpinned, f"actions must be pinned to a full commit SHA: {unpinned}"
