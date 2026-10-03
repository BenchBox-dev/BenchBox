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


def test_triggers_cover_pushes_reviews_and_merge_queue() -> None:
    triggers = _triggers()
    assert set(triggers) == {"pull_request", "pull_request_review", "merge_group"}
    assert triggers["merge_group"]["types"] == ["checks_requested"]
    assert triggers["pull_request"]["types"] == ["opened", "synchronize", "reopened", "ready_for_review"]
    assert triggers["pull_request_review"]["types"] == ["submitted", "dismissed"]


def test_permissions_are_read_only() -> None:
    assert _load()["permissions"] == {"actions": "read", "contents": "read", "pull-requests": "read"}
    assert "permissions" not in _load()["jobs"]["oracle-review"]


def test_concurrency_cancels_superseded_runs_per_pull_request() -> None:
    concurrency = _load()["concurrency"]
    assert concurrency["cancel-in-progress"] is True
    assert "github.event.pull_request.number" in concurrency["group"]
    assert "github.event.merge_group.head_sha" in concurrency["group"], "queued groups must not share one slot"


def test_job_invokes_the_script_with_the_pull_request_number_and_token() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    runs = [step for step in steps if SCRIPT in step.get("run", "")]
    assert len(runs) == 1
    step = runs[0]
    assert step["env"]["GITHUB_TOKEN"] == "${{ github.token }}"
    assert "github.event.pull_request.number" in step["env"]["PR_NUMBER"]
    assert "--pr" in step["run"]
    assert "merge_group.head_ref" in step["env"]["MERGE_GROUP_REF"]


def test_actions_are_pinned_to_full_commit_shas() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    for step in steps:
        if "uses" in step:
            ref = step["uses"].split("@", 1)[1]
            assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), step["uses"]


def test_checkout_uses_the_base_commit_so_the_judged_pull_request_cannot_change_the_check() -> None:
    steps = _load()["jobs"]["oracle-review"]["steps"]
    checkouts = [step for step in steps if step.get("uses", "").startswith("actions/checkout@")]
    assert len(checkouts) == 1
    ref = checkouts[0]["with"]["ref"]
    assert "github.event.pull_request.base.sha" in ref
    assert "github.event.merge_group.base_sha" in ref
    assert "head" not in ref


def test_run_name_records_the_event_action_the_script_uses_to_find_head_moves() -> None:
    assert _load()["run-name"] == "oracle-review (${{ github.event.action || github.event_name }})"
