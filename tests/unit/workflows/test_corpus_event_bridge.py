"""Contracts for corpus-event-bridge workflow (A8).

Pins:
1. Trigger only on push to published-results branch
2. Path filter: results-data/** only (corpus changes)
3. Extracts merge SHA and verifies it's a real merge commit (2+ parents)
4. Passes ledger-head-sha from branch state via git show published-results:publication/ledger.json
5. Summary never checks out PR content
6. Never receives deploy credentials
7. Uses git cat-file -p to validate merge commit (not trust dispatch verbatim)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/corpus-event-bridge.yml"


def _load_workflow() -> tuple[dict, str]:
    text = WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict)
    return data, text


def _get_on_block(workflow: dict) -> dict:
    on = workflow.get(True) or workflow.get("on")
    assert isinstance(on, dict), "workflow missing `on:` block"
    return on


def test_workflow_exists() -> None:
    assert WORKFLOW.is_file(), f"missing workflow at {WORKFLOW}"


def test_triggers_only_on_published_results_branch() -> None:
    workflow, _ = _load_workflow()
    on = _get_on_block(workflow)
    # Must be push-triggered, not pull_request
    assert "push" in on
    assert "pull_request" not in on
    push = on["push"]
    assert push["branches"] == ["published-results"], f"expected published-results only, got {push.get('branches')}"


def test_triggers_only_on_results_data_path_changes() -> None:
    _, text = _load_workflow()
    # Path filter must limit to results-data/** only
    assert "results-data/**" in text
    assert "paths" in text
    # The path filter should NOT include other directories like scripts/ or .github/
    workflow, _ = _load_workflow()
    push = workflow[True]["push"]
    allowed_paths = push.get("paths", [])
    assert "results-data/**" in allowed_paths
    # Ensure no broad paths that would allow non-corpus changes
    assert "**" not in [p for p in allowed_paths if p != "results-data/**"], (
        f"path filter must be narrow, got broad globs in {allowed_paths}"
    )


def test_workflow_permissions_are_least_privilege() -> None:
    workflow, _ = _load_workflow()
    assert workflow.get("permissions") == {"contents": "read"}, (
        f"event bridge top-level must be contents: read only, got {workflow.get('permissions')!r}"
    )
    job = workflow["jobs"]["dispatch-reconciler"]
    job_perms = job.get("permissions")
    assert isinstance(job_perms, dict)
    assert job_perms.get("actions") == "write", (
        f"dispatch job must grant actions: write for createWorkflowDispatch, got {job_perms!r}"
    )
    assert job_perms.get("contents") == "read"


def test_never_checks_out_pr_content() -> None:
    _, text = _load_workflow()
    # No pull_request / pull_request_target triggers
    assert "pull_request_target" not in text
    assert "pull_request" not in text
    # Checkout pins the published-results branch, not PR refs
    assert "published-results" in text


def test_extracts_merge_sha() -> None:
    _, text = _load_workflow()
    # Must reference the pushed SHA via github.sha and pass it as merge_sha
    assert "github.sha" in text
    assert "merge_sha" in text
    assert "merge-sha" in text or "merge_sha" in text


def test_verifies_merge_commit_has_2_plus_parents() -> None:
    _, text = _load_workflow()
    # Must use git cat-file -p to revalidate the merge commit (REQUIRED 3)
    assert "git cat-file -p" in text
    assert "parent " in text
    assert "parent_count" in text or '"^parent "' in text
    # Must reject non-merge commits (fewer than 2 parents)
    assert "lt 2" in text or "lt 2" in text.replace("$PARENT_COUNT", "")


def test_passes_ledger_head_sha_from_branch_state() -> None:
    _, text = _load_workflow()
    # Must read ledger.json from published-results branch
    assert "git show published-results:publication/ledger.json" in text
    assert "ledger_head_sha" in text
    assert "ledger-head-sha" in text
    # Must fail-closed if ledger_head_sha is empty (uses ::error:: / setFailed)
    assert "::error::" in text
    assert "setFailed" in text


def test_never_receives_deploy_credentials() -> None:
    _, text = _load_workflow()
    # No deploy permissions / secrets
    for needle in ("pages: write", "id-token: write", "deployments: write", "packages: write"):
        assert needle not in text, f"workflow must not grant {needle!r}"
    assert "secrets." not in text, "event bridge must not receive any secrets"


def test_dispatches_reconciler_with_required_inputs() -> None:
    _, text = _load_workflow()
    # Must dispatch corpus-reconciler workflow
    assert "corpus-reconciler.yml" in text
    # Must pass merge-sha, base-sha, ledger-head-sha
    assert "merge-sha" in text
    assert "base-sha" in text
    assert "ledger-head-sha" in text
    assert "createWorkflowDispatch" in text or "workflow_dispatch" in text
    # Workflow file lives on develop (published-results is slim and 404s on dispatch)
    assert "ref: 'develop'" in text or 'ref: "develop"' in text
    assert "ref: 'published-results'" not in text
    assert 'ref: "published-results"' not in text
