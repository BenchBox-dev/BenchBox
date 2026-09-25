"""docs.yml skipped-deploy marker contract pins.

When the independent-publication receipt gates off the legacy release deploy,
a follow-on job must mark exactly this run's pre-created github-pages record
`inactive` so deployment history does not read the skip as `success`. Two
past defects shape these pins: posting without `auto_inactive=false` marks
every prior successful github-pages deployment inactive (including the live
independent-publication deployment), and a bare newest-first lookup by SHA can
select the wrong record because duplicate github-pages records per SHA exist
(reruns, concurrent queued runs).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_PATH = REPO_ROOT / ".github" / "workflows" / "docs.yml"


def _load() -> dict:
    return yaml.safe_load(DOCS_PATH.read_text(encoding="utf-8"))


def _deploy_job(data: dict) -> dict:
    return data["jobs"]["deploy"]


def _record_job(data: dict) -> dict:
    return data["jobs"]["record-skipped-deployment"]


def _steps(job: dict) -> list:
    return job["steps"]


def _step_by_name(job: dict, name: str) -> dict:
    for step in _steps(job):
        if step.get("name") == name:
            return step
    raise AssertionError(f"step {name!r} not found")


def test_skip_marker_exposes_bound_deployment_id() -> None:
    deploy = _deploy_job(_load())
    outputs = deploy.get("outputs") or {}
    assert outputs.get("skipped_deployment_id"), (
        "deploy must expose the bound record id so the follow-on marks exactly this run's record"
    )
    capture = _step_by_name(deploy, "Capture this run's skipped deployment record")
    assert capture["id"] == "capture-deployment"
    run = capture["run"]
    assert 'select(.ref == "release")' in run
    assert "pushed_at" in run


def test_skip_marker_posts_inactive_without_side_effects() -> None:
    data = _load()
    record = _record_job(data)
    assert (record.get("permissions") or {}).get("deployments") == "write"
    assert "environment" not in record, (
        "follow-on must not set environment: so no new deployment record is pre-created for the marker itself"
    )
    assert "skipped_deployment_id" in record["if"]
    step = _steps(record)[0]
    run = step["run"]
    assert "-f auto_inactive=false" in run
    assert '-f state="inactive"' in run
    assert "deployments/$DEPLOYMENT_ID/statuses" in run


def test_skip_marker_only_runs_on_skipped_release_push() -> None:
    record = _record_job(_load())
    condition = record["if"]
    assert "refs/heads/release" in condition
    assert "skipped" in condition
    assert "skipped_deployment_id" in condition


def test_deploy_still_gates_pages_write_on_receipt() -> None:
    deploy = _deploy_job(_load())
    steps = _steps(deploy)
    deploy_step = next(step for step in steps if str(step.get("uses", "")).startswith("actions/deploy-pages@"))
    assert deploy_step["if"] == "steps.independent.outputs.active != 'true'"
