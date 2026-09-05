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
DEPLOY_PAGES_ACTION = "actions/deploy-pages@d6db90164ac5ed86f2b6aed7e0febac5b3c0c03e"
UPLOAD_PAGES_ACTION = "actions/upload-pages-artifact@56afc609e74202658d3ffba0e8f6dda462b719fa"


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
    assert dispatch_inputs["generation"]["required"] is True
    assert "approved_manifest_digest" in dispatch_inputs


def test_workflow_permissions_follow_least_privilege() -> None:
    wf = _workflow()
    jobs = wf["jobs"]

    # Top-level permissions should be read-only
    assert wf.get("permissions") == {"contents": "read"}

    assert jobs["build"]["permissions"] == {"actions": "read", "contents": "read"}
    assert jobs["verify"]["permissions"] == {"contents": "read"}
    assert jobs["deploy"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    assert jobs["rollback"]["permissions"] == {
        "actions": "read",
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    assert jobs["verify"]["environment"] == {"name": "publication-attestation"}
    assert jobs["rollback"]["environment"]["name"] == "github-pages"


def test_workflow_uses_pages_deploy_actions_only_in_write_jobs() -> None:
    text = _workflow_text()
    assert DEPLOY_PAGES_ACTION in text
    assert UPLOAD_PAGES_ACTION in text
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
    workflow = _workflow()
    steps = workflow["jobs"]["deploy"]["steps"]
    deployment = next(step for step in steps if step.get("uses") == DEPLOY_PAGES_ACTION)
    assert deployment["with"]["artifact_name"] == "publication-pages-${{ needs.build.outputs.generation }}"
    assert workflow["jobs"]["deploy"]["environment"]["name"] == "github-pages"


def test_receipts_use_measured_provenance_and_valid_json_newlines() -> None:
    text = _workflow_text()

    assert '"target": "benchbox.dev"' in text
    assert 'd("lock")' not in text
    assert 'd("corpus")' not in text
    assert 'd("read-model")' not in text
    assert '"bundle_count": 0' not in text
    assert '"size": 0' not in text
    assert "LOCKFILE_DIGEST=$(sha256sum uv.lock" in text
    assert "CORPUS_DIGEST=$(sha256sum receipt-dist/corpus-file-digests.txt" in text
    assert 'tree_size("site")' in text
    assert " + '\\\\n'" not in text
    assert '"artifact_name": os.environ["PAGES_ARTIFACT"]' in text
    assert '"rollback_artifact_name": os.environ["SITE_ARTIFACT"]' in text


def test_build_receipt_enforces_attested_cas_lineage() -> None:
    text = _workflow_text()

    assert "generation 1 cannot replace current live receipt" in text
    assert "requires prior_live_receipt_id" in text
    assert "verify_live_receipt_signature" in text
    assert "prior_live_receipt_id is stale; current live head is" in text
    assert 'gh api --paginate "repos/${{ github.repository }}/actions/artifacts?per_page=100"' in text
    assert '"\\(.created_at) \\(.id) \\(.workflow_run.id)"' in text
    assert "Revalidate authoritative live head" in text
    assert "publication live head changed after build" in text
    assert '"parent_sha": os.environ.get("PARENT_SHA") or None' in text
    assert "validate_manifest_dict(manifest)" in text


def test_production_requires_an_independently_approved_manifest() -> None:
    text = _workflow_text()

    assert "production deployment requires an independently reviewed approved_manifest_digest" in text
    assert 'approved != manifest["manifest_digest"]' in text
    assert 'open("receipt-dist/desired-manifest.json", "w")' in text
    assert 'open("receipt-dist/assembly-receipt.json", "w")' in text
    assert "--baseline-manifest receipt-dist/desired-manifest.json" in text
    assert "WORKFLOW_SHA: ${{ github.sha }}" in text
    assert '"workflow_sha": os.environ["WORKFLOW_SHA"]' in text


def test_verify_step_invokes_verify_live_with_receipt() -> None:
    steps = _workflow()["jobs"]["verify"]["steps"]
    verify_step = next(s for s in steps if s.get("name") == "Probe required live routes")
    run_cmd = verify_step["run"]

    assert "scripts/publication/verify_live.py" in run_cmd
    assert "--require-receipt" in run_cmd
    assert "--manifest" in run_cmd
    assert "--base-url" in run_cmd


def test_live_receipt_binds_html_endpoints_and_acknowledges_before_probing() -> None:
    workflow = _workflow()
    text = _workflow_text()
    steps = workflow["jobs"]["verify"]["steps"]
    names = [step.get("name") for step in steps]

    assert '"/": os.environ["ROOT_ENDPOINT_DIGEST"]' in text
    assert '"/docs/": os.environ["DOCS_ENDPOINT_DIGEST"]' in text
    assert '"/results/": os.environ["EXPLORER_ENDPOINT_DIGEST"]' in text
    assert names.index("Upload provider deployment acknowledgement") < names.index("Probe required live routes")


def test_rollback_restores_only_a_cryptographically_attested_artifact() -> None:
    steps = _workflow()["jobs"]["rollback"]["steps"]
    step_names = [s.get("name") for s in steps]
    run_bodies = "\n".join(s.get("run", "") for s in steps if isinstance(s.get("run"), str))

    assert "Resolve last known-good attested receipt" in step_names
    assert "Download and verify known-good site artifact" in step_names
    assert "Create and sign rollback live receipt" in step_names
    assert "Publish rollback as the new attested live head" in step_names
    assert "Retain restored site artifact for the new rollback head" in step_names
    assert "Upload rollback audit receipt" in step_names
    assert "Deploy attested rollback artifact to GitHub Pages" in step_names
    assert "Upload attested rollback Pages artifact" in step_names

    assert "verify_live_receipt_signature" in run_bodies
    assert "known-good artifact digest mismatch" in run_bodies
    assert "rollback_target_sha" not in run_bodies
    assert ".workflow_run.name" not in run_bodies
    assert "actions/runs/$RUN_ID" in run_bodies
    assert "['artifacts']['pages_assembly']['digest']" in run_bodies
    assert "'generation': int(os.environ['BUILD_GENERATION'])" in run_bodies
    assert "successor-live-receipt/live-receipt.json" in run_bodies
    assert "'artifact_name': os.environ['PAGES_ARTIFACT']" in run_bodies
    assert "'artifact_run_id': os.environ['GITHUB_RUN_ID']" in run_bodies
    assert "'rollback_artifact_name': os.environ['SITE_ARTIFACT']" in run_bodies
    assert "['rollback_artifact_name']" in run_bodies

    assert any(step.get("uses") == DEPLOY_PAGES_ACTION for step in steps)
    assert any(step.get("uses") == UPLOAD_PAGES_ACTION for step in steps)


def test_retained_site_artifact_includes_hidden_files() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    retained = next(
        step for step in steps if step.get("name") == "Retain immutable site artifact for attested rollback"
    )

    assert retained["with"]["include-hidden-files"] is True


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
