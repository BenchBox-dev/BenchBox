from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
WORKFLOW = WORKFLOWS / "ci.yml"
JOB = "base-guard"
STEP_NAME = "Check base branch"

INTEGRATION_BRANCHES = {"develop", "release", "published-results"}


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def _load() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job() -> dict[str, Any]:
    jobs = _load()["jobs"]
    assert JOB in jobs, f"ci.yml has no {JOB!r} job; a stacked PR would present no base-policy failure"
    return jobs[JOB]


def test_stacked_pr_base_guard_lives_in_ci_workflow() -> None:
    _job()


def test_stacked_pr_base_guard_has_no_branch_filter() -> None:
    pull_request = _triggers(_load())["pull_request"] or {}
    assert "branches" not in pull_request, (
        "ci.yml filters on branches, so the stacked PRs base-guard exists to catch would not trigger it"
    )
    assert "paths" not in pull_request, "ci.yml is path-filtered, so a stacked PR could still report nothing"


def test_stacked_pr_base_guard_reevaluates_when_a_pr_is_retargeted() -> None:
    types = (_triggers(_load())["pull_request"] or {}).get("types", [])
    assert "edited" in types, "guard does not re-evaluate on retarget; a repointed PR keeps a stale pass"
    assert "opened" in types


def test_stacked_pr_base_guard_accepts_only_integration_branches() -> None:
    job = _job()
    assert job.get("if") == "${{ github.event_name == 'pull_request' }}", (
        "base-guard must run on every PR event so a stacked base always reports"
    )
    step = next((s for s in job.get("steps", []) if s.get("name") == STEP_NAME), None)
    assert step is not None, f"base-guard has no {STEP_NAME!r} step"
    body = str(step.get("run", ""))
    accepted = {branch for branch in INTEGRATION_BRANCHES if branch in body}
    assert accepted == INTEGRATION_BRANCHES, (
        f"guard does not name every integration branch: missing {INTEGRATION_BRANCHES - accepted}"
    )
    assert "exit 1" in body, "guard never fails, so a stacked PR would still show an all-green check list"


def test_stacked_pr_base_guard_feeds_the_tooling_result() -> None:
    workflow = _load()
    tooling = workflow["jobs"]["tooling"]
    assert JOB in tooling["needs"], (
        f"tooling result does not aggregate {JOB}; a stacked-PR failure would not gate merge"
    )
    run_text = "\n".join(str(step.get("run", "")) for step in tooling.get("steps", []))
    assert "base-guard" in run_text, (
        "tooling result never evaluates base-guard; a stacked-PR failure would not gate merge"
    )
