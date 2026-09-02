"""Contract tests for the publication-corpus-cutover.yml workflow (A9 w4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "publication-corpus-cutover.yml"


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), f"workflow file missing: {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_workflow_is_valid_yaml() -> None:
    wf = _workflow()
    assert wf["name"] == "Publication - Corpus Cutover"
    assert "jobs" in wf


def test_workflow_has_workflow_dispatch_only() -> None:
    wf = _workflow()
    triggers = wf.get(True) or wf.get("on") or {}
    assert "workflow_dispatch" in triggers
    assert "push" not in triggers
    assert "pull_request" not in triggers


def test_workflow_permissions_are_least_privilege() -> None:
    wf = _workflow()
    assert wf.get("permissions") == {"contents": "read"}
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pages: write" not in raw
    assert "id-token: write" not in raw
    assert "actions: write" not in raw


def test_workflow_concurrency_is_serialized() -> None:
    wf = _workflow()
    conc = wf.get("concurrency", {})
    assert conc.get("group") == "corpus-cutover"
    assert conc.get("cancel-in-progress") is False


def test_workflow_has_required_jobs() -> None:
    wf = _workflow()
    jobs = wf["jobs"]
    assert "build" in jobs
    assert "assemble" in jobs
    assert "verify" in jobs
    assert "rollback" in jobs


def test_workflow_job_dependency_ordering() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["assemble"]["needs"] == "build"
    assert jobs["verify"]["needs"] == "assemble"
    assert jobs["rollback"]["needs"] == ["build", "assemble", "verify"]


def test_workflow_permissions_contents_read_only() -> None:
    wf = _workflow()
    perms = wf.get("permissions")
    assert perms == {"contents": "read"}
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pages: write" not in raw
    assert "id-token: write" not in raw
    assert "actions: write" not in raw


def test_build_verifies_lane_isolation() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    step_names = [s.get("name") for s in steps]
    assert "Verify corpus lane isolation" in step_names


def test_build_references_verify_lane_isolation_script() -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "scripts/publication/verify_lane_isolation.py --lane corpus" in raw


def test_assemble_references_check_corpus_bijection() -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "scripts/publication/check_corpus_bijection.py" in raw


def test_rollback_condition_triggers_on_failure() -> None:
    rollback_job = _workflow()["jobs"]["rollback"]
    if_cond = rollback_job.get("if", "")
    assert "always()" in if_cond
    assert "needs.assemble.result == 'failure'" in if_cond or "needs.verify.result == 'failure'" in if_cond


def test_rollback_records_promotion_failed() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    step_names = [s.get("name") for s in steps]
    assert "Freeze promotions and record promotion_failed" in step_names


def test_rollback_restores_last_known_good() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    step_names = [s.get("name") for s in steps]
    assert "Restore last-known-good full-site deployment" in step_names


def test_rollback_does_not_modify_package_prose_explorer() -> None:
    """Rollback must NOT touch package, prose, API docs, or Explorer app artifacts."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    rollback_section = raw.split("rollback:")[1] if "rollback:" in raw else ""
    assert "benchbox/" not in rollback_section
    assert "results-explorer/" not in rollback_section
    assert "docs/" not in rollback_section
    assert "_blog/" not in rollback_section
    assert "landing/" not in rollback_section


def test_rollback_does_not_branch_backward() -> None:
    """Rollback must roll forward to retained safe artifact, never move branch backward."""
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    rollback_section = raw.split("rollback:")[1] if "rollback:" in raw else ""
    assert "git checkout" not in rollback_section.lower()
    assert "git reset" not in rollback_section.lower()
    assert "git revert" not in rollback_section.lower()
    assert "roll-forward" in rollback_section.lower() or "last-known-good" in rollback_section.lower()


def test_force_failure_drill_input() -> None:
    wf = _workflow()
    triggers = wf.get(True) or wf.get("on") or {}
    dispatch = triggers.get("workflow_dispatch", {})
    inputs = dispatch.get("inputs", {})
    assert "force_failure_drill" in inputs
    assert inputs["force_failure_drill"]["type"] == "boolean"
    assert inputs["force_failure_drill"]["default"] is False


def test_build_uploads_corpus_artifacts() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    uploads = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {u["with"]["name"] for u in uploads}
    assert "corpus_archive" in uploaded_names
    assert "accepted_bundles" in uploaded_names


def test_rollback_uploads_promotion_failed_receipt() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    uploads = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {u["with"]["name"] for u in uploads}
    assert "promotion_failed" in uploaded_names


def test_rollback_no_job_level_permission_escalation() -> None:
    wf = _workflow()
    rollback_job = wf["jobs"]["rollback"]
    assert "permissions" not in rollback_job, "rollback job must not override top-level permissions"


def test_all_jobs_have_no_job_level_permissions() -> None:
    """No job should escalate beyond top-level contents: read."""
    wf = _workflow()
    for job_name, job in wf["jobs"].items():
        assert "permissions" not in job, f"job {job_name} must not override permissions"
