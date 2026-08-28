"""A PR based on a feature branch must not present an empty check list.

Every other PR workflow filters on `branches: [develop]` (or release /
published-results), so a PR whose base is another feature branch triggers
nothing at all. The PR page looks calm rather than alarming - no failing
checks, because no checks - and the content reaches develop only when the
parent merges, never having been validated on its own.

`pr-base-guard.yml` is the one check such a PR does get. These tests pin the
two properties that make it work: it carries no branch filter (so it always
reports), and it rejects a base that is not an integration branch.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
GUARD = WORKFLOWS / "pr-base-guard.yml"

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


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_stacked_pr_base_guard_exists() -> None:
    assert GUARD.is_file(), "pr-base-guard.yml is missing; a stacked PR would present an empty check list"


def test_stacked_pr_base_guard_has_no_branch_filter() -> None:
    """The guard must run on every PR, whatever its base.

    A branch list would defeat the purpose twice over: a stacked base would not
    match it, and the list would go stale as branches are added. Absence cannot
    go stale.
    """
    pull_request = _triggers(_load(GUARD))["pull_request"] or {}
    assert "branches" not in pull_request, (
        "pr-base-guard filters on branches, so the stacked PRs it exists to catch would not trigger it"
    )
    assert "paths" not in pull_request, "pr-base-guard is path-filtered, so a stacked PR could still report nothing"


def test_stacked_pr_base_guard_reevaluates_when_a_pr_is_retargeted() -> None:
    """Retargeting an open PR must re-run the guard.

    Without `edited`, a PR opened against develop and later repointed at a
    feature branch keeps its stale green result.
    """
    types = (_triggers(_load(GUARD))["pull_request"] or {}).get("types", [])
    assert "edited" in types, "guard does not re-evaluate on retarget; a repointed PR keeps a stale pass"
    assert "opened" in types


def test_stacked_pr_base_guard_accepts_only_integration_branches() -> None:
    """The guard's accept list must be exactly the branches CI actually covers."""
    body = GUARD.read_text(encoding="utf-8")
    accepted = {branch for branch in INTEGRATION_BRANCHES if branch in body}
    assert accepted == INTEGRATION_BRANCHES, (
        f"guard does not name every integration branch: missing {INTEGRATION_BRANCHES - accepted}"
    )
    assert "exit 1" in body, "guard never fails, so a stacked PR would still show an all-green check list"


def test_every_other_pr_workflow_still_filters_to_integration_branches() -> None:
    """Pin the premise this guard exists for.

    If the other workflows ever stop filtering, stacked PRs would get real CI
    and this guard becomes redundant rather than load-bearing - which is worth
    noticing deliberately rather than discovering later.
    """
    filtered: list[str] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == GUARD.name:
            continue
        workflow = _load(path)
        if not isinstance(workflow, dict):
            continue
        triggers = workflow.get("on", workflow.get(True))
        if not isinstance(triggers, dict):
            continue
        pull_request = triggers.get("pull_request")
        if pull_request is None:
            continue
        branches = (pull_request or {}).get("branches")
        if branches:
            filtered.append(path.name)
            assert set(branches) <= INTEGRATION_BRANCHES, (
                f"{path.name} filters on {branches}, which is outside the known integration branches"
            )
    assert filtered, "no PR workflow filters on an integration branch; this guard's premise no longer holds"
