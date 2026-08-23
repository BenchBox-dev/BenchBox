"""Unit tests verifying merge_group triggers and required-context reporting."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"
BROWSER_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "results-explorer-browser.yml"
DRIFT_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "develop-ruleset-drift.yml"


def _load_workflow(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def test_required_workflows_include_merge_group_trigger() -> None:
    """All three required-gate workflows must listen to merge_group: checks_requested."""
    pr = _load_workflow(PR_WORKFLOW)
    browser = _load_workflow(BROWSER_WORKFLOW)
    drift = _load_workflow(DRIFT_WORKFLOW)

    assert "merge_group" in _triggers(pr), "pr.yml missing merge_group trigger"
    assert "merge_group" in _triggers(browser), "results-explorer-browser.yml missing merge_group trigger"
    assert "merge_group" in _triggers(drift), "develop-ruleset-drift.yml missing merge_group trigger"


def test_required_status_check_names_match_ruleset_contract() -> None:
    """The exact status check names required by develop-squash-only must remain unchanged."""
    pr = _load_workflow(PR_WORKFLOW)
    browser = _load_workflow(BROWSER_WORKFLOW)
    drift = _load_workflow(DRIFT_WORKFLOW)

    assert "ci-required-result" in pr["jobs"], "pr.yml must define job ci-required-result"
    assert browser["jobs"]["browser-required-result"]["name"] == "Results Explorer browser gate"
    assert drift["jobs"]["ruleset-drift"]["name"] == "ruleset-drift"


def test_concurrency_groups_handle_merge_group_synthetic_ref() -> None:
    """Concurrency groups must isolate merge_group runs using merge_group.head_ref."""
    pr_text = PR_WORKFLOW.read_text(encoding="utf-8")
    browser_text = BROWSER_WORKFLOW.read_text(encoding="utf-8")
    drift_text = DRIFT_WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.merge_group.head_ref" in pr_text
    assert "github.event.merge_group.head_ref" in browser_text
    assert "github.event.merge_group.head_ref" in drift_text


def test_drift_checkout_uses_trusted_base_on_merge_group() -> None:
    """develop-ruleset-drift must checkout the trusted base SHA on merge_group events."""
    drift = _load_workflow(DRIFT_WORKFLOW)
    checkout_step = drift["jobs"]["ruleset-drift"]["steps"][0]
    assert checkout_step["uses"] == "actions/checkout@v4"
    assert (
        checkout_step["with"]["ref"] == "${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}"
    )
    assert checkout_step["with"]["persist-credentials"] is False
