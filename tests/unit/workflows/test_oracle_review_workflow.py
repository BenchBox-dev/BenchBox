"""The oracle-review workflow reports a check named exactly ``oracle-review``.

A ruleset requires the check by that name, so the job name, the triggers that
let a landed review re-run it, the read-only token and the script invocation
are pinned here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "oracle-review.yml"
SCRIPT = "_project/scripts/oracle_review_check.py"


def _load() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers() -> dict[str, Any]:
    workflow = _load()
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def test_job_id_and_name_are_the_required_check_name() -> None:
    workflow = _load()
    assert workflow["name"] == "oracle-review"
    assert list(workflow["jobs"]) == ["oracle-review"]
    assert workflow["jobs"]["oracle-review"]["name"] == "oracle-review"


def test_triggers_cover_pushes_reviews_and_manual_runs() -> None:
    triggers = _triggers()
    assert set(triggers) == {"pull_request", "pull_request_review", "workflow_dispatch"}
    assert triggers["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    assert triggers["pull_request_review"]["types"] == ["submitted"]
    assert triggers["workflow_dispatch"]["inputs"]["pr"]["required"] is True


def test_permissions_are_read_only() -> None:
    assert _load()["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "permissions" not in _load()["jobs"]["oracle-review"]


def test_concurrency_cancels_superseded_runs_per_pull_request() -> None:
    concurrency = _load()["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "github.event.pull_request.number || inputs.pr" in concurrency["group"]


def test_job_invokes_the_script_with_the_pull_request_number_and_token() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    runs = [step for step in steps if SCRIPT in step.get("run", "")]
    assert len(runs) == 1
    step = runs[0]
    assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert "github.event.pull_request.number || inputs.pr" in step["env"]["PR_NUMBER"]
    assert "--pr" in step["run"]


def test_actions_are_pinned_to_full_commit_shas() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    for step in steps:
        if "uses" in step:
            ref = step["uses"].split("@", 1)[1]
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), step["uses"]
