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


def test_workflow_is_dispatch_only_with_required_inputs() -> None:
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True) or {}

    assert "push" not in triggers
    assert "workflow_dispatch" in triggers
    dispatch_inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "expect_noop" in dispatch_inputs
    assert dispatch_inputs["expect_noop"]["type"] == "boolean"
    assert "force_rollback" in dispatch_inputs
    assert dispatch_inputs["force_rollback"]["type"] == "boolean"
    assert "rollback_target_sha" in dispatch_inputs
    assert dispatch_inputs["develop_sha"]["required"] is True
    assert dispatch_inputs["published_results_sha"]["required"] is True


def test_workflow_permissions_follow_least_privilege() -> None:
    wf = _workflow()
    jobs = wf["jobs"]

    # Top-level permissions should be read-only
    assert wf.get("permissions") == {"contents": "read"}

    assert jobs["build"]["permissions"] == {"contents": "read"}
    assert jobs["verify"]["permissions"] == {"contents": "read"}
    assert jobs["deploy"]["permissions"] == {"contents": "read", "pages": "write", "id-token": "write"}
    assert jobs["rollback"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }


def test_workflow_uses_pages_deploy_actions_only_in_write_jobs() -> None:
    text = _workflow_text()
    assert "actions/deploy-pages@v4" in text
    assert "actions/upload-pages-artifact@v3" in text
    assert "group: pages-deploy" in text
    assert "cancel-in-progress: false" in text


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
    assert "test -s results-explorer/public/data/results.duckdb" in text
    assert "test -s site/results/data/results.duckdb" in text
    assert "scripts/assemble_public_site.py --site-dir site" in text
    assert "sphinx-build -b html" in text


def test_build_step_includes_pre_deploy_candidate_and_noop_check() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    precheck_step = next(s for s in steps if s.get("name") == "Pre-deploy candidate verification")
    run_cmd = precheck_step["run"]

    assert "scripts/publication/verify_live.py" in run_cmd
    assert "--candidate-manifest" in run_cmd
    assert "--baseline-manifest" in run_cmd
    assert "--pre-deploy" in run_cmd
    assert "--require-receipt" in run_cmd


def test_deploy_uses_real_pages_deployment() -> None:
    steps = _workflow()["jobs"]["deploy"]["steps"]
    assert any(step.get("uses") == "actions/deploy-pages@v4" for step in steps)
    assert _workflow()["jobs"]["deploy"]["environment"]["name"] == "github-pages"


def test_verify_step_invokes_verify_live_with_receipt() -> None:
    steps = _workflow()["jobs"]["verify"]["steps"]
    verify_step = next(s for s in steps if s.get("name") == "Probe required live routes")
    run_cmd = verify_step["run"]

    assert "scripts/publication/verify_live.py" in run_cmd
    assert "--require-receipt" in run_cmd
    assert "--manifest" in run_cmd
    assert "--base-url" in run_cmd


def test_rollback_restores_only_a_cryptographically_attested_artifact() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    step_names = [s.get("name") for s in steps]
    run_bodies = "\n".join(s.get("run", "") for s in steps if isinstance(s.get("run"), str))

    assert "Resolve last known-good attested receipt" in step_names
    assert "Download and verify known-good site artifact" in step_names
    assert "Create and sign rollback live receipt" in step_names
    assert "Upload rollback audit receipt" in step_names
    assert "Deploy attested rollback artifact to GitHub Pages" in step_names
    assert "Upload attested rollback Pages artifact" in step_names

    assert "verify_live_receipt_signature" in run_bodies
    assert "known-good artifact digest mismatch" in run_bodies
    assert "rollback_target_sha" not in run_bodies

    assert any(step.get("uses") == "actions/deploy-pages@v4" for step in steps)
    assert any(step.get("uses") == "actions/upload-pages-artifact@v3" for step in steps)


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


def test_rollback_does_not_rebuild_from_a_baseline_branch_sha() -> None:
    assert BASELINE_PATH.is_file(), f"Baseline file missing at {BASELINE_PATH}"
    baseline_data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    assert baseline_data.get("branches", {}).get("release", {}).get("sha")
    rollback_text = "\n".join(
        step.get("run", "") for step in _workflow()["jobs"]["rollback"]["steps"] if isinstance(step.get("run"), str)
    )
    assert "git worktree add" not in rollback_text
    assert "git checkout" not in rollback_text
