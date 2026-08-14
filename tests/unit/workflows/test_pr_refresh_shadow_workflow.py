"""Trust and permission contracts for the refresh-shadow workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SHADOW = REPO_ROOT / ".github" / "workflows" / "develop-refresh-shadow.yml"
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"
ADMIN = REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md"


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    return triggers


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(SHADOW.read_text(encoding="utf-8"))


def test_shadow_uses_pull_request_target_and_is_not_required(workflow: dict[str, Any]) -> None:
    triggers = _triggers(workflow)
    assert "pull_request_target" in triggers
    assert triggers["pull_request_target"]["branches"] == ["develop"]
    text = SHADOW.read_text(encoding="utf-8")
    assert "ci-required-result" not in text
    assert "Results Explorer browser gate" not in text
    admin = ADMIN.read_text(encoding="utf-8")
    assert "refresh-shadow" in admin
    assert "not a required" in admin.lower() or "observational" in admin.lower()
    required_block = admin.split("Required status checks:", 1)[1].split("```text", 1)[1].split("```", 1)[0]
    assert "refresh-shadow" not in required_block


def test_shadow_permissions_are_read_only(workflow: dict[str, Any]) -> None:
    perms = workflow["permissions"]
    assert perms == {
        "contents": "read",
        "actions": "read",
        "pull-requests": "read",
    }
    assert "write" not in yaml.safe_dump(perms)


def test_shadow_checks_out_trusted_base_only(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["refresh-shadow"]
    checkout = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha }}"
    assert checkout["with"]["persist-credentials"] is False
    text = SHADOW.read_text(encoding="utf-8")
    checkout_region = text.split("actions/checkout", 1)[-1].split("Fetch PR commits", 1)[0]
    assert "pull_request.head.sha" not in checkout_region
    assert "ref: ${{ github.event.pull_request.head.sha }}" not in text
    assert "ref: ${{ github.sha }}" not in text


def test_shadow_does_not_skip_or_replace_required_pr_lanes() -> None:
    pr = yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))
    required = pr["jobs"]["ci-required-result"]["needs"]
    for name in (
        "ci-paths",
        "content-guard",
        "code-lint",
        "code-test",
        "correctness-gate",
        "plan-capture-gate",
        "medium-test",
    ):
        assert name in required
    lint_if = pr["jobs"]["code-lint"]["if"]
    test_if = pr["jobs"]["code-test"]["if"]
    assert "refresh" not in lint_if
    assert "refresh" not in test_if
    assert "shadow" not in lint_if
    assert "shadow" not in test_if


def test_shadow_collector_fail_closes_without_inventing_prior_identity(workflow: dict[str, Any]) -> None:
    text = SHADOW.read_text(encoding="utf-8")
    assert "pr-certification-identity" in text
    assert "pr-certification-lanes" in text
    assert "actions/artifacts/" in text
    assert "gh" in text and "api" in text
    assert "scripts/pr_refresh_certification.py" in text
    assert "missing_path_evidence" in text
    classify = next(
        step
        for step in workflow["jobs"]["refresh-shadow"]["steps"]
        if step.get("name") == "Classify refresh in shadow mode"
    )
    assert "contents: write" not in yaml.safe_dump(classify)


def test_shadow_uploads_bounded_decision_artifact(workflow: dict[str, Any]) -> None:
    upload = next(
        step for step in workflow["jobs"]["refresh-shadow"]["steps"] if step.get("name") == "Upload shadow decision"
    )
    assert upload["if"] == "always()"
    assert upload["with"]["path"] == "shadow-decision.json"
    assert "refresh-shadow-" in str(upload["with"]["name"])
    text = SHADOW.read_text(encoding="utf-8")
    assert "duration_ms" in text
    assert "This record is not a required check" in text
