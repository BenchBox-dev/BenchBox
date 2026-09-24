"""Contract tests for the publication-corpus-cutover.yml workflow (A9 w4 + review follow-ups)."""

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


def _job(name: str) -> dict[str, Any]:
    return _workflow()["jobs"][name]


def _steps(job: str) -> list[dict[str, Any]]:
    return _job(job)["steps"]


def _run_text(job: str) -> str:
    return "\n".join(str(s.get("run", "")) for s in _steps(job))


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_workflow_is_valid_yaml() -> None:
    wf = _workflow()
    assert wf["name"] == "Publication - Corpus Cutover"
    assert "jobs" in wf


def test_workflow_has_workflow_dispatch_only() -> None:
    triggers = _workflow().get(True) or _workflow().get("on") or {}
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


def test_all_jobs_have_no_job_level_permissions() -> None:
    for job_name, job in _workflow()["jobs"].items():
        assert "permissions" not in job, f"job {job_name} must not override permissions"


def test_workflow_concurrency_is_serialized() -> None:
    conc = _workflow().get("concurrency", {})
    assert conc.get("group") == "corpus-cutover"
    assert conc.get("cancel-in-progress") is False


def test_workflow_has_required_jobs() -> None:
    jobs = _workflow()["jobs"]
    assert {"build", "assemble", "verify", "rollback"} <= set(jobs)


def test_workflow_job_dependency_ordering() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["assemble"]["needs"] == "build"
    assert jobs["verify"]["needs"] == "assemble"
    assert jobs["rollback"]["needs"] == ["build", "assemble", "verify"]


# ---------------------------------------------------------------------------
# build job
# ---------------------------------------------------------------------------


def test_build_verifies_lane_isolation() -> None:
    assert "Verify corpus lane isolation" in [s.get("name") for s in _steps("build")]
    assert "scripts/publication/verify_lane_isolation.py --lane corpus" in _run_text("build")


def test_build_corpus_archive_materializes_accepted_union() -> None:
    """Archive must materialize the ledger-seed union (incl. published_only), never develop-only cp."""
    build_run = _run_text("build")
    assert "cp -r results-data/bundles/. lane_artifacts/corpus_archive/" not in build_run
    assert "--materialize-dest lane_artifacts/corpus_archive" in build_run
    assert "git fetch --no-tags origin published-results" in build_run
    assert "2>/dev/null || true" not in build_run
    assert 'CORPUS_COUNT" -eq 0' in build_run
    assert 'CORPUS_COUNT" -ne "$EXPECTED' in build_run


def test_build_uploads_corpus_artifacts() -> None:
    uploads = [s for s in _steps("build") if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    names = {u["with"]["name"] for u in uploads}
    assert {"corpus_archive", "accepted_bundles"} <= names


def test_build_diffs_committed_ledger_seed() -> None:
    assert "create_ledger_seed.py" in _run_text("build")


# ---------------------------------------------------------------------------
# assemble job — B1
# ---------------------------------------------------------------------------


def test_assemble_invokes_real_site_assembler() -> None:
    """B1: the assemble job must build index.html + the DuckDB read model."""
    run = _run_text("assemble")
    assert "_project/scripts/explorer_publish.py build" in run
    assert "npm run build --prefix results-explorer" in run
    assert "scripts/publication/assembler.py" in run
    assert "assembled-site/index.html" in run
    assert "assembled-site/results/data/results.duckdb" in run


def test_assemble_verifies_shadow_site() -> None:
    assert "verify_shadow_site.py assembled-site/" in _run_text("assemble")


def test_assemble_scans_privacy() -> None:
    run = _run_text("assemble")
    assert "check_artifact_privacy.py assembled-site/" in run
    assert "|| true" not in run


def test_assemble_bijection_requires_real_artifact() -> None:
    """B2: bijection runs against the assembled DuckDB with --require-artifact, no `|| true`."""
    run = _run_text("assemble")
    assert "check_corpus_bijection.py" in run
    assert "--artifact assembled-site/results/data/results.duckdb" in run
    assert "--require-artifact" in run
    assert "|| true" not in run


def test_assemble_uploads_full_site() -> None:
    uploads = [s for s in _steps("assemble") if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    assert "full_site_deployment" in {u["with"]["name"] for u in uploads}


# ---------------------------------------------------------------------------
# verify job — B2, M4
# ---------------------------------------------------------------------------


def test_verify_bijection_does_not_swallow_failure() -> None:
    """B2: the verify-job bijection check must not append `|| true`."""
    run = _run_text("verify")
    assert "check_corpus_bijection.py" in run
    assert "--artifact deployed-site/results/data/results.duckdb" in run
    assert "--require-artifact" in run
    assert "|| true" not in run


def test_verify_force_failure_drill_actually_fails() -> None:
    """M4: force_failure_drill must make the verify job exit 1."""
    drill = [s for s in _steps("verify") if s.get("name") == "Force failure drill"]
    assert drill, "verify job needs a 'Force failure drill' step"
    step = drill[0]
    assert "force_failure_drill == true" in step["if"]
    assert "exit 1" in step["run"]


# ---------------------------------------------------------------------------
# rollback job — B3, M5
# ---------------------------------------------------------------------------


def test_rollback_triggers_on_any_non_success() -> None:
    """M5: failure OR cancellation of assemble/verify triggers recovery."""
    if_cond = " ".join(_job("rollback")["if"].split())
    assert "always()" in if_cond
    assert "needs.assemble.result != 'success'" in if_cond
    assert "needs.verify.result != 'success'" in if_cond
    assert "inputs.force_failure_drill == true" in if_cond


def test_rollback_excludes_build_failure_from_freeze() -> None:
    """M5: a build failure means nothing was assembled/deployed — no freeze."""
    if_cond = " ".join(_job("rollback")["if"].split())
    assert "needs.build.result == 'success'" in if_cond


def test_rollback_rebuilds_from_pinned_known_good_sha() -> None:
    """B3: roll-forward must materialise a real known-good tree, not fabricate a file."""
    run = _run_text("rollback")
    assert "rollback_target_sha" in run or "rollback_target_sha" in WORKFLOW_PATH.read_text()
    assert "git worktree add ../known-good" in run
    assert "_project/scripts/explorer_publish.py build" in run
    assert "npm run build --prefix results-explorer" in run
    assert "restored-site/index.html" in run
    assert "restored-site/results/data/results.duckdb" in run


def test_rollback_verifies_restored_site() -> None:
    run = _run_text("rollback")
    assert "verify_shadow_site.py restored-site/" in run
    assert "check_corpus_bijection.py" in run
    assert "--require-artifact" in run


def test_rollback_runs_live_probe() -> None:
    """B3: a live probe must actually run and its result be recorded (non-fatal)."""
    probe = [s for s in _steps("rollback") if s.get("name", "").startswith("Probe live production")]
    assert probe, "rollback needs a live-probe step"
    assert "verify_live.py" in probe[0]["run"]
    assert "exit_code" in probe[0]["run"]


def test_rollback_receipt_only_records_established_facts() -> None:
    """B3: the receipt must reference verified outputs, not a hard-coded 'restored.' string."""
    receipt = [s for s in _steps("rollback") if s.get("name", "").startswith("Write roll-forward receipt")]
    assert receipt, "rollback needs a receipt-writing step"
    body = receipt[0]["run"]
    assert "restored_tree_sha256" in body
    assert "steps.probe.outputs.exit_code" in body
    assert "steps.verify_restore.outputs" in body
    # The fabricated attestation string from the original implementation is gone.
    assert "Last-known-good full-site deployment restored." not in _run_text("rollback")


def test_rollback_uploads_restored_site_and_receipt() -> None:
    uploads = [s for s in _steps("rollback") if str(s.get("uses", "")).startswith("actions/upload-artifact")]
    names = {u["with"]["name"] for u in uploads}
    assert {"restored_full_site", "promotion_failed"} <= names


def test_rollback_does_not_move_any_branch_backward() -> None:
    """Roll FORWARD only: never rewrite history or move a ref backward."""
    run = _run_text("rollback").lower()
    for forbidden in ("git checkout ", "git reset", "git revert", "git rebase", "git branch -f", "git push"):
        assert forbidden not in run, f"rollback must not run `{forbidden.strip()}`"


def test_rollback_does_not_commit_to_source_trees() -> None:
    """Rollback rebuilds read-only from a side worktree; it must never commit."""
    run = _run_text("rollback").lower()
    assert "git commit" not in run
    assert "git add" not in run


def test_rollback_no_job_level_permission_escalation() -> None:
    assert "permissions" not in _job("rollback")


# ---------------------------------------------------------------------------
# inputs
# ---------------------------------------------------------------------------


def test_force_failure_drill_input() -> None:
    triggers = _workflow().get(True) or _workflow().get("on") or {}
    inputs = triggers.get("workflow_dispatch", {}).get("inputs", {})
    assert inputs["force_failure_drill"]["type"] == "boolean"
    assert inputs["force_failure_drill"]["default"] is False


def test_rollback_target_sha_input() -> None:
    triggers = _workflow().get(True) or _workflow().get("on") or {}
    inputs = triggers.get("workflow_dispatch", {}).get("inputs", {})
    assert "rollback_target_sha" in inputs
    assert inputs["rollback_target_sha"]["type"] == "string"
