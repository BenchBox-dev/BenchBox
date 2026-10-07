"""A PR based on a feature branch must fail loudly inside the single CI workflow.

The flip retires ``pr-base-guard.yml`` as a standalone workflow and folds the
same policy into ``ci.yml`` as the ``base-guard`` job, because ``ci.yml``
deliberately carries no branch filter: a stacked PR gets the ordinary six
unit checks instead of an empty check list. Without the folded guard its
content could slide into develop under a parent PR, never validated as its
own integration-base diff. These tests pin the two properties that make the
folded guard work: it runs on every PR whatever its base, and it rejects a
base that is not an integration branch.
"""

from __future__ import annotations

import subprocess
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
    """Return the `on:` block.

    PyYAML resolves an unquoted ``on`` key to boolean ``True`` under YAML 1.1,
    so accept either spelling rather than reading an empty trigger set and
    passing vacuously.
    """
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
    """The guard must run on every PR, whatever its base.

    A branch list would defeat the purpose twice over: a stacked base would not
    match it, and the list would go stale as branches are added. Absence cannot
    go stale.
    """
    pull_request = _triggers(_load())["pull_request"] or {}
    assert "branches" not in pull_request, (
        "ci.yml filters on branches, so the stacked PRs base-guard exists to catch would not trigger it"
    )
    assert "paths" not in pull_request, "ci.yml is path-filtered, so a stacked PR could still report nothing"


def test_stacked_pr_base_guard_reevaluates_when_a_pr_is_retargeted() -> None:
    """Retargeting an open PR must re-run the guard.

    Without `edited`, a PR opened against develop and later repointed at a
    feature branch keeps its stale green result.
    """
    types = (_triggers(_load())["pull_request"] or {}).get("types", [])
    assert "edited" in types, "guard does not re-evaluate on retarget; a repointed PR keeps a stale pass"
    assert "opened" in types


def test_stacked_pr_base_guard_reevaluates_when_draft_status_changes() -> None:
    types = (_triggers(_load())["pull_request"] or {}).get("types", [])
    assert "ready_for_review" in types, "guard does not re-evaluate when a draft becomes ready"
    assert "converted_to_draft" in types, "guard does not re-evaluate when a ready PR becomes a draft"
    assert sorted(types) == sorted(
        ["opened", "synchronize", "reopened", "edited", "ready_for_review", "converted_to_draft"]
    ), "ci.yml pull_request types changed; every listed event re-runs the guard and the CI lanes"


def test_stacked_pr_base_guard_names_integration_branches_and_can_fail() -> None:
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
    """A failing guard must fail the tooling unit, not just its own job.

    The merge ruleset requires the unit context, not the raw job, so a guard
    outside the tooling aggregation would be advisory noise a stacked PR
    could merge past.
    """
    workflow = _load()
    tooling = workflow["jobs"]["tooling"]
    assert JOB in tooling["needs"], (
        f"tooling result does not aggregate {JOB}; a stacked-PR failure would not gate merge"
    )
    run_text = "\n".join(str(step.get("run", "")) for step in tooling.get("steps", []))
    assert "base-guard" in run_text, (
        "tooling result never evaluates base-guard; a stacked-PR failure would not gate merge"
    )


def _run_guard(tmp_path: Path, base_ref: str, *, draft: bool) -> subprocess.CompletedProcess[str]:
    step = next(s for s in _job()["steps"] if s.get("name") == STEP_NAME)
    env = step.get("env", {})
    assert env.get("BASE_REF") == "${{ github.base_ref }}"
    assert env.get("IS_DRAFT") == "${{ github.event.pull_request.draft }}"
    script = tmp_path / "base-guard.sh"
    script.write_text(step["run"], encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)],
        env={"PATH": "/usr/bin:/bin", "BASE_REF": base_ref, "IS_DRAFT": "true" if draft else "false"},
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("draft", [True, False])
@pytest.mark.parametrize("base", sorted(INTEGRATION_BRANCHES))
def test_stacked_pr_base_guard_passes_integration_bases(tmp_path: Path, base: str, draft: bool) -> None:
    assert _run_guard(tmp_path, base, draft=draft).returncode == 0


def test_stacked_pr_base_guard_passes_a_draft_on_a_feature_base(tmp_path: Path) -> None:
    result = _run_guard(tmp_path, "fix/parent-branch", draft=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::error::" not in result.stdout


def test_stacked_pr_base_guard_fails_a_ready_pr_on_a_feature_base(tmp_path: Path) -> None:
    result = _run_guard(tmp_path, "fix/parent-branch", draft=False)
    assert result.returncode != 0
    assert "::error::" in result.stdout
    assert "fix/parent-branch" in result.stdout
    assert "retarget this PR at develop" in result.stdout


def test_stacking_rule_is_stated_consistently_in_agent_and_policy_docs() -> None:
    policy = (REPO_ROOT / "docs" / "development" / "pr-base-branch-policy.md").read_text(encoding="utf-8")
    agents = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    index = (REPO_ROOT / "docs" / "development" / "index.md").read_text(encoding="utf-8")
    assert "unsupported" not in index.lower()
    assert "do not support" not in policy.lower()
    assert "never open a pr with `--base`" not in policy.lower()
    for text in (policy, agents):
        assert "git rebase --onto origin/develop <old parent tip>" in text
    assert "converted_to_draft" in policy
    assert "gh pr ready" in policy
    assert "git rebase --onto <new B tip> <old B tip>" in policy
    assert "mark ready" in agents
    allowed = policy.split("## Allowed bases")[1].split("\n## ")[0]
    assert "draft PR in a stack" in allowed
    assert "connector review" in policy
