"""Contract and architecture tests for publication transactions workflow."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
TX_WORKFLOW_PATH = WORKFLOWS_DIR / "publication-transaction.yml"
PREVIEW_DEPLOY_PATH = WORKFLOWS_DIR / "publication-preview-deploy.yml"
PREVIEW_SOAK_PATH = WORKFLOWS_DIR / "publication-preview-soak.yml"
DOCS_PATH = WORKFLOWS_DIR / "docs.yml"
DEPLOY_PATH = WORKFLOWS_DIR / "publication-deploy.yml"


def _load_yaml(path: Path) -> dict[str, Any]:
    assert path.is_file(), f"Workflow file missing at {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_transaction_workflow_is_dispatch_only_with_required_inputs() -> None:
    wf = _load_yaml(TX_WORKFLOW_PATH)
    triggers = wf.get("on") or wf.get(True) or {}

    assert "push" not in triggers
    assert "pull_request" not in triggers
    assert "workflow_dispatch" in triggers

    inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "kind" in inputs
    assert inputs["kind"]["type"] == "choice"
    assert set(inputs["kind"]["options"]) == {"promotion", "rollback"}
    assert inputs["develop_sha"]["required"] is True
    assert inputs["published_results_sha"]["required"] is True
    assert "candidate_manifest_digest" in inputs
    assert "restore_transaction_id" in inputs
    assert "barrier_evidence" in inputs


def test_transaction_workflow_permissions_follow_least_privilege() -> None:
    wf = _load_yaml(TX_WORKFLOW_PATH)
    jobs = wf["jobs"]

    # Top-level is read-only
    assert wf.get("permissions") == {"contents": "read"}

    # prepare: read-only
    assert jobs["prepare"]["permissions"] == {"contents": "read", "actions": "read"}

    # deploy: contents: write (for journal CAS), pages: write, id-token: write, actions: read
    assert jobs["deploy"]["permissions"] == {
        "contents": "write",
        "pages": "write",
        "id-token": "write",
        "actions": "read",
    }
    assert jobs["deploy"]["environment"]["name"] == "github-pages"

    # verify: contents: write (for journal CAS)
    assert jobs["verify"]["permissions"] == {"contents": "write"}
    assert jobs["verify"]["environment"]["name"] == "publication-attestation"

    # finalize: contents: write (for journal CAS)
    assert jobs["finalize"]["permissions"] == {"contents": "write"}


def test_transaction_workflow_concurrency_scoped_to_deploy_job() -> None:
    wf = _load_yaml(TX_WORKFLOW_PATH)

    # Top-level workflow must NOT lock pages-deploy across candidate preparation
    assert "concurrency" not in wf

    # prepare job must NOT lock pages-deploy
    assert "concurrency" not in wf["jobs"]["prepare"]

    # deploy job alone holds the pages-deploy lock
    assert wf["jobs"]["deploy"]["concurrency"] == {
        "group": "pages-deploy",
        "cancel-in-progress": False,
    }


def test_transaction_workflow_job_dependencies() -> None:
    jobs = _load_yaml(TX_WORKFLOW_PATH)["jobs"]

    assert jobs["deploy"]["needs"] == "prepare"
    assert jobs["verify"]["needs"] == ["prepare", "deploy"]
    assert jobs["finalize"]["needs"] == ["prepare", "deploy", "verify"]


def test_transaction_workflow_pins_all_actions() -> None:
    text = TX_WORKFLOW_PATH.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+([^\s#]+)", text)

    for ref in action_refs:
        assert "@" in ref, f"Action reference '{ref}' is missing version tag or commit SHA"
        name, sha = ref.split("@", 1)
        assert re.fullmatch(r"[0-9a-f]{40}", sha), (
            f"Action '{name}' in publication-transaction.yml must be pinned by a 40-character commit SHA, got: {sha}"
        )


def test_five_write_paths_inventory_and_disabled_or_journaled_invariant() -> None:
    """Inventory all five write paths (promotion, rollback, legacy release, legacy recovery, preview).

    Assert the invariant: every Pages write path is either:
    1. A journaled transaction in publication-transaction.yml (promotion, rollback)
    2. An approved legacy path with admission control (docs.yml, publication-deploy.yml)
    3. Explicitly disabled in code (publication-preview-deploy.yml)
    """
    deploy_pages_workflows: list[Path] = []
    for path in WORKFLOWS_DIR.glob("*.yml"):
        content = path.read_text(encoding="utf-8")
        if "deploy-pages" in content or "pages.cjs" in content:
            deploy_pages_workflows.append(path)

    workflow_names = {p.name for p in deploy_pages_workflows}
    expected_workflow_names = {
        "publication-transaction.yml",  # Path 1 (promotion) & Path 2 (rollback)
        "docs.yml",  # Path 3 (legacy release)
        "publication-deploy.yml",  # Path 4 (legacy recovery)
        "publication-preview-deploy.yml",  # Path 5 (preview, disabled in code)
    }

    assert workflow_names == expected_workflow_names, (
        f"Unexpected Pages deployment workflows found. Expected only {expected_workflow_names}, got {workflow_names}"
    )

    # Verify Path 5 (preview deploy) is disabled in code
    preview_wf = _load_yaml(PREVIEW_DEPLOY_PATH)
    deploy_job = preview_wf["jobs"]["deploy"]
    assert deploy_job.get("if") is False, "Preview deploy job must be disabled in code with 'if: false'"
    deploy_steps = deploy_job.get("steps", [])
    first_step = deploy_steps[0] if deploy_steps else {}
    assert "permanently disabled in code" in first_step.get("run", ""), (
        "Preview deploy job must contain an explicit code guard asserting permanent disablement"
    )

    # Verify Path 3 (docs.yml legacy release) has admission guard
    docs_wf = _load_yaml(DOCS_PATH)
    docs_deploy_steps = docs_wf["jobs"]["deploy"]["steps"]
    guard_step = next(
        (s for s in docs_deploy_steps if s.get("name") == "Check for independent publication ownership"), None
    )
    assert guard_step is not None, "docs.yml must retain independent publication admission guard"
    assert "Publication Transactions" in guard_step.get("run", "")

    # Verify Path 4 (publication-deploy.yml legacy recovery) has scoped concurrency and attested restore
    deploy_wf = _load_yaml(DEPLOY_PATH)
    assert "concurrency" not in deploy_wf, "publication-deploy.yml must not lock concurrency at workflow level"
    assert deploy_wf["jobs"]["deploy"]["concurrency"]["group"] == "pages-deploy"
    assert deploy_wf["jobs"]["rollback"]["concurrency"]["group"] == "pages-deploy"


def test_preview_soak_caller_handles_disabled_preview_gracefully() -> None:
    soak_text = PREVIEW_SOAK_PATH.read_text(encoding="utf-8")
    assert "skipping soak probe" in soak_text or "skipping probe" in soak_text
    assert "exit 0" in soak_text
