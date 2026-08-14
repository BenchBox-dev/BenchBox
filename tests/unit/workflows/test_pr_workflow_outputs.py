"""Pin Develop PR required-lane outputs after shadow evidence was added."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
PR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pr.yml"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(PR_WORKFLOW.read_text(encoding="utf-8"))


def test_required_umbrella_jobs_are_unchanged(workflow: dict[str, Any]) -> None:
    needs = workflow["jobs"]["ci-required-result"]["needs"]
    assert needs == [
        "ci-paths",
        "content-guard",
        "code-lint",
        "code-test",
        "correctness-gate",
        "plan-capture-gate",
        "medium-test",
        "explorer-tokens",
        "site-theme-tokens",
        "explorer-vitest",
        "audit-sha",
        "package-smoke",
        "dependency-audit",
        "parity-check",
    ]


def test_code_lanes_still_path_gated_only(workflow: dict[str, Any]) -> None:
    expected = "${{ needs.ci-paths.outputs.needs-code-ci == 'true' }}"
    for job_id in ("code-lint", "code-test", "correctness-gate", "plan-capture-gate", "medium-test"):
        assert workflow["jobs"][job_id]["if"] == expected


def test_certification_identity_is_observational(workflow: dict[str, Any]) -> None:
    job = workflow["jobs"]["certification-identity"]
    assert "if" not in job
    assert "certification-identity" not in workflow["jobs"]["ci-required-result"]["needs"]
    names = [step.get("name") for step in job["steps"]]
    assert "Record certification identity" in names
    checkout = next(step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False


def test_lane_evidence_cannot_fail_the_required_umbrella(workflow: dict[str, Any]) -> None:
    steps = workflow["jobs"]["ci-required-result"]["steps"]
    record = next(step for step in steps if step.get("name") == "Record certification lane evidence")
    evidence = next(step for step in steps if step.get("name") == "Upload certification lane evidence")
    assert record.get("if") == "always()"
    assert evidence.get("if") == "always()"
    assert evidence.get("continue-on-error") is True
    assert "pr-certification-lanes.json" in record["run"]
    assert evidence["with"]["name"] == "pr-certification-lanes"
