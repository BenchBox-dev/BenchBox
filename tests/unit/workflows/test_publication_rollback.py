"""Contract and simulation tests for publication deployment and automated rollback mechanism."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "publication-deploy.yml"
BASELINE_PATH = ROOT / "docs" / "operations" / "publication-baseline-2026-08-31.json"


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), f"Workflow file missing at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_workflow_has_required_triggers() -> None:
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True) or {}

    # push trigger on release branch
    assert "push" in triggers
    push = triggers["push"]
    assert "release" in push.get("branches", [])
    assert any("results-data/**" in p for p in push.get("paths", []))
    assert any("scripts/publication/**" in p for p in push.get("paths", []))

    # workflow_dispatch with required drill inputs
    assert "workflow_dispatch" in triggers
    dispatch_inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "expect_noop" in dispatch_inputs
    assert dispatch_inputs["expect_noop"]["type"] == "boolean"
    assert "force_rollback" in dispatch_inputs
    assert dispatch_inputs["force_rollback"]["type"] == "boolean"
    assert "rollback_target_sha" in dispatch_inputs


def test_workflow_permissions_follow_least_privilege() -> None:
    wf = _workflow()
    jobs = wf["jobs"]

    # Top-level permissions should be read-only
    assert wf.get("permissions") == {"contents": "read"}

    # Freeze G3: every job is contents: read only (docs.yml is sole Pages deployer)
    for job_name in ("build", "deploy", "verify", "rollback"):
        assert jobs[job_name]["permissions"] == {"contents": "read"}, job_name
        perms = jobs[job_name]["permissions"]
        assert perms.get("pages") != "write", job_name
        assert perms.get("id-token") != "write", job_name


def test_workflow_has_no_pages_deploy_actions() -> None:
    text = _workflow_text()
    assert "actions/deploy-pages" not in text
    assert "actions/upload-pages-artifact" not in text
    assert "pages: write" not in text
    assert "id-token: write" not in text


def test_workflow_job_dependencies_and_ordering() -> None:
    jobs = _workflow()["jobs"]

    assert "build" in jobs
    assert "deploy" in jobs
    assert "verify" in jobs
    assert "rollback" in jobs

    assert jobs["deploy"]["needs"] == "build"
    assert jobs["verify"]["needs"] == ["build", "deploy"]
    assert jobs["rollback"]["needs"] == ["build", "deploy", "verify"]


def test_build_uses_correct_cli_flags() -> None:
    text = _workflow_text()
    assert "--data-dir results-data" in text
    assert "--data-dir results-data/bundles" not in text
    assert "--output results-explorer/public/data" in text
    assert "--bundles-dir" not in text
    assert "--output-dir" not in text
    assert "results_explorer_snapshot_invariants.py" in text
    assert "results-explorer/public/data/results.duckdb" in text
    assert "--data-dir results-explorer/public/data" not in text
    assert "2>/dev/null || true" not in text
    assert 'if [ -f "results-explorer/public/data/results.duckdb" ]' not in text
    assert 'if [ ! -f "results-explorer/public/data/results.duckdb" ]' in text


def test_build_step_includes_pre_deploy_candidate_and_noop_check() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    precheck_step = next(s for s in steps if s.get("name") == "Pre-deploy candidate verification and no-op check")
    run_cmd = precheck_step["run"]

    assert "scripts/publication/verify_live.py" in run_cmd
    assert "--candidate-manifest" in run_cmd
    assert "--baseline-manifest" in run_cmd
    assert "--pre-deploy" in run_cmd
    assert "--require-receipt" in run_cmd


def test_deploy_is_rehearsal_noop() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    assert len(steps) >= 1
    run_bodies = "\n".join(s.get("run", "") for s in steps if isinstance(s.get("run"), str))
    assert "docs.yml as the sole production Pages deployer" in run_bodies
    assert "do not deploy" in run_bodies.lower()
    for step in steps:
        uses = step.get("uses", "")
        assert "deploy-pages" not in uses
        assert "upload-pages-artifact" not in uses


def test_verify_step_invokes_verify_live_with_receipt() -> None:
    steps = _workflow()["jobs"]["verify"]["steps"]
    verify_step = next(s for s in steps if s.get("name") == "Run live verification probe")
    run_cmd = verify_step["run"]

    assert "scripts/publication/verify_live.py" in run_cmd
    assert "--require-receipt" in run_cmd
    assert "--manifest" in run_cmd
    assert "--base-url" in run_cmd


def test_rollback_writes_facts_only_receipt_without_pages_deploy() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    step_names = [s.get("name") for s in steps]
    run_bodies = "\n".join(s.get("run", "") for s in steps if isinstance(s.get("run"), str))

    assert "Write facts-only rollback receipt" in step_names
    assert "Upload rollback audit receipt" in step_names
    assert "Deploy attested rollback artifact to GitHub Pages" not in step_names
    assert "Upload immutable rollback Pages artifact" not in step_names

    assert "<html" not in run_bodies.lower()
    assert "index.html" not in run_bodies
    assert "pinned_baseline_release_sha" in run_bodies
    assert "freeze_still_blocked" in run_bodies
    assert "pages_deploy_attempted" in run_bodies

    for step in steps:
        uses = step.get("uses", "")
        assert "deploy-pages" not in uses
        assert "upload-pages-artifact" not in uses


def test_rollback_condition_covers_all_failure_modes_and_drills() -> None:
    rollback_job = _workflow()["jobs"]["rollback"]
    if_cond = rollback_job.get("if", "")

    assert "always()" in if_cond
    assert "needs.deploy.result == 'failure'" in if_cond
    assert "needs.verify.result == 'failure'" in if_cond
    assert "force_rollback == true" in if_cond


@pytest.mark.parametrize(
    ("deploy_result", "verify_result", "force_rollback", "expected_rollback"),
    [
        ("success", "success", False, False),  # Normal successful deployment -> no rollback
        ("failure", "skipped", False, True),  # Deploy failed -> rollback
        ("success", "failure", False, True),  # Healthcheck/checksum verification failed -> rollback
        ("success", "success", True, True),  # Forced drill -> rollback
        ("failure", "failure", True, True),  # Multiple failures + force -> rollback
    ],
)
def test_simulated_rollback_trigger_logic(
    deploy_result: str,
    verify_result: str,
    force_rollback: bool,
    expected_rollback: bool,
) -> None:
    """Simulate GitHub Actions expression evaluation for the rollback conditional."""
    deploy_failed = deploy_result == "failure"
    verify_failed = verify_result == "failure"
    should_rollback = deploy_failed or verify_failed or force_rollback

    assert should_rollback is expected_rollback


def test_rollback_resolves_baseline_target_sha() -> None:
    assert BASELINE_PATH.is_file(), f"Baseline file missing at {BASELINE_PATH}"
    baseline_data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    release_sha = baseline_data.get("branches", {}).get("release", {}).get("sha")

    assert release_sha, "Baseline must contain pinned release SHA"
    assert len(release_sha) == 40
    assert all(c in "0123456789abcdef" for c in release_sha.lower())
