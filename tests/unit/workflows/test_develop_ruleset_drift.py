"""Security and required-check contract for per-PR governance drift."""

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "develop-ruleset-drift.yml"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_ruleset_drift_uses_trusted_base_code_with_minimal_permissions() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["ruleset-drift"]
    checkout = job["steps"][0]

    assert workflow["permissions"] == {"contents": "read"}
    assert checkout["uses"] == "actions/checkout@v4"
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha }}"
    assert checkout["with"]["persist-credentials"] is False
    assert "head.sha" not in WORKFLOW.read_text(encoding="utf-8")


def test_ruleset_drift_fails_closed_and_preserves_evidence() -> None:
    workflow = _workflow()
    job = workflow["jobs"]["ruleset-drift"]
    check = job["steps"][1]
    upload = job["steps"][2]

    assert job["name"] == "ruleset-drift"
    assert check["env"] == {"RULESET_DRIFT_TOKEN": "${{ secrets.RULESET_DRIFT_TOKEN }}"}
    assert "scripts/ruleset_drift_check.py" in check["run"]
    assert "--require-bypass-actor-visibility" in check["run"]
    assert "set +e" not in check["run"]
    assert upload["if"] == "always()"
    assert upload["with"]["retention-days"] == 30
