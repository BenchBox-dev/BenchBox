"""A `published-results` mirror PR must not present an empty check list.

#1542 (`chore(corpus): mirror results-data changes from develop@355cc445`,
base `published-results`) shipped with `statusCheckRollup: []` - not zero
failures, zero checks. Two causes, only one fixable from `develop`:

Cause 1 (fixed here): the PR's author is `app/github-actions` - this
workflow's own `GITHUB_TOKEN` identity. GitHub never starts
`pull_request`-triggered workflow runs for events raised by `GITHUB_TOKEN`
(documented recursion prevention). `validate-submission.yml` is wired to fire
on exactly this PR's base and paths and never will, no matter what its
trigger says.

Cause 2 (not fixable from here): `published-results` carries exactly one
workflow file. `pr-base-guard.yml` - added in #1563 precisely to give a
zero-CI PR at least one check - cannot run there because its file does not
exist on that branch, and `GITHUB_TOKEN` cannot push `.github/workflows/`
changes regardless of the `permissions:` block granted to it (a hard-coded
GitHub Actions restriction, not a configuration choice - see
`adr-published-results-slim-corpus-branch.md`'s "workflow file itself is NOT
auto-mirrored" section). That gap needs a maintainer to manually port the
guard onto `published-results`, tracked in
`docs/operations/results-phase-2-runbook.md`.

The fix pinned here: `sync-results-data-to-published.yml` now validates the
exact content it is about to mirror (the same two gates
`validate-submission.yml` would have run: bundle validation and inventory
freshness) and posts the result as a commit status on the mirror branch's
head SHA. A commit status is a plain Statuses-API write, not a workflow
trigger, so it is unaffected by the GITHUB_TOKEN recursion rule and needs no
new credential - `statuses: write` only widens the permissions already
granted to the token this workflow already holds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
SYNC = WORKFLOWS / "sync-results-data-to-published.yml"

STATUS_API_FRAGMENT = "statuses/"
OPEN_PR_STEP_NAME = "Open or update draft PR"
VALIDATE_STEP_NAME = "Validate mirrored corpus content"
STATUS_STEP_NAME = "Report validation as a commit status on the mirror PR"


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


def _steps() -> list[dict[str, Any]]:
    workflow = _load(SYNC)
    return workflow["jobs"]["mirror"]["steps"]


def _step(name: str) -> dict[str, Any]:
    for step in _steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"sync-results-data-to-published.yml has no step named {name!r}")


def test_published_results_base_mirror_pr_reports_a_commit_status() -> None:
    """The sync workflow must post a check onto the mirror PR it opens.

    This is the fix for Cause 1. Without it, #1542-style PRs show
    `statusCheckRollup: []` forever - `validate-submission.yml` structurally
    cannot fire on a GITHUB_TOKEN-authored PR event, so nothing else will ever
    report either.
    """
    step = _step(STATUS_STEP_NAME)
    run = step.get("run", "")
    assert STATUS_API_FRAGMENT in run, (
        "no step posts to the Statuses API; a mirror PR still ends up with an empty statusCheckRollup"
    )
    workflow = _load(SYNC)
    assert workflow["permissions"].get("statuses") == "write", (
        "workflow lacks statuses: write, so a status-posting call would 403 even if attempted"
    )


def test_published_results_base_mirror_pr_status_condition_matches_pr_creation() -> None:
    """Every mirror PR must get the status, not just some of them.

    If the status step's `if:` were narrower than the PR-opening step's, some
    mirror PRs would open with a check and others would silently keep the
    original zero-check bug - a partial fix that looks complete in the common
    case and regresses exactly the case #1542 hit.
    """
    open_pr_condition = _step(OPEN_PR_STEP_NAME).get("if")
    status_condition = _step(STATUS_STEP_NAME).get("if")
    assert status_condition == open_pr_condition, (
        f"status step condition {status_condition!r} does not match the PR-opening "
        f"step condition {open_pr_condition!r}; some mirror PRs would still end up uncovered"
    )


def test_published_results_base_mirror_pr_status_reflects_real_validation() -> None:
    """The posted status must be derived from an actual validator run, not a rubber stamp.

    A step that always reports `state=success` would make the PR page look
    safe while checking nothing - worse than the current honest emptiness,
    because a false green is harder to notice than no check at all. The
    status step must consume the validate step's own output, and that output
    must in turn depend on running `validate_submission.py` and
    `generate_corpus_inventory.py --check` against the mirrored content.
    """
    status_step = _step(STATUS_STEP_NAME)
    status_env = status_step.get("env", {})
    assert status_env.get("STATE") == "${{ steps.validate.outputs.state }}", (
        "status step does not read steps.validate.outputs.state; it cannot be reporting a real result"
    )

    validate_run = _step(VALIDATE_STEP_NAME).get("run", "")
    assert "scripts/validate_submission.py" in validate_run, (
        "validate step never invokes scripts/validate_submission.py; the reported check validates nothing"
    )
    assert "scripts/generate_corpus_inventory.py" in validate_run and "--check" in validate_run, (
        "validate step never checks corpus-inventory.json freshness"
    )
    assert 'STATE="failure"' in validate_run, (
        "validate step has no failure path; a broken bundle would still report state=success"
    )


def test_published_results_base_mirror_validation_runs_before_the_pr_is_opened() -> None:
    """Validation must happen before the PR exists, matching the chosen design.

    Guidance considered and rejected a new PAT/App-token credential for this
    repo; the token-free alternative is the creating workflow validating its
    own content and reporting on itself, which only works if validation runs
    ahead of (or at worst alongside) PR creation rather than after it.
    """
    names = [step.get("name") for step in _steps()]
    assert names.index(VALIDATE_STEP_NAME) < names.index(OPEN_PR_STEP_NAME), (
        "validation step runs after the PR is opened; the PR could exist before its content is checked"
    )
    assert names.index(STATUS_STEP_NAME) < names.index(OPEN_PR_STEP_NAME), (
        "status is posted after the PR is opened rather than before/alongside it"
    )


def test_published_results_base_mirror_stays_a_corpus_check_not_develops_matrix() -> None:
    """Must-preserve: `published-results` stays a slim corpus branch.

    w0 concluded the domain-appropriate gate for a corpus-only branch is
    exactly `validate-submission.yml`'s own two checks (bundle validation,
    inventory freshness) - not develop's lint/type/pytest matrix. A future
    edit that starts running `ruff`, `ty`, or the fast test suite here would
    quietly reintroduce the ADR-rejected "keep published-results synced with
    develop continuously" design (full package surface for a corpus mirror).
    """
    # Concatenate only the executable `run:` bodies, not the surrounding YAML
    # comments - a comment explaining what NOT to do (as this file's own w0
    # rationale does, right above this test) would otherwise trip a naive
    # whole-file substring check and fail for the wrong reason.
    run_bodies = "\n".join(step.get("run", "") for step in _steps())
    for forbidden in ("ruff check", "ruff format", "ty check", "pytest", "uv sync --group dev"):
        assert forbidden not in run_bodies, (
            f"{forbidden!r} appears in a sync workflow run step; this imports develop's CI matrix onto a corpus mirror"
        )


def test_published_results_base_guard_still_has_no_branch_filter() -> None:
    """Cross-check against #1563's guard: must-preserve constraint from this TODO.

    `pr-base-guard.yml`'s unfiltered trigger is what stops it from becoming a
    required check that can never report (the same failure mode this whole
    TODO is about). Nothing in this change may add a `branches:`/`paths:`
    filter to it - re-assert the guard file's own invariant here so a future
    edit that touches both files in the same PR cannot regress this one
    silently.
    """
    guard = WORKFLOWS / "pr-base-guard.yml"
    pull_request = _triggers(_load(guard))["pull_request"] or {}
    assert "branches" not in pull_request
    assert "paths" not in pull_request


def test_published_results_base_mirror_survives_a_failure_in_its_own_validation_steps() -> None:
    """Adding validation must not create a new way for the mirror PR to not exist.

    The status and PR-opening steps come after the new "Install uv" / "Set up
    Python" / "Validate mirrored corpus content" steps. GitHub skips every
    later step once one fails, so without ``always()`` a flaky toolchain setup
    - or any error the validate step's ``set -uo pipefail`` capture does not
    convert into a reported state - would skip BOTH, leaving no status and no
    mirror PR at all.

    That is strictly worse than the blind PR this change removes: develop's
    Corpus Drift Check would stay red with nothing open to explain why, and
    before these steps existed the PR was always created. Availability of the
    mirror PR is the property being protected here, not its verdict.
    """
    for step_name in (STATUS_STEP_NAME, OPEN_PR_STEP_NAME):
        condition = _step(step_name).get("if", "")
        assert "always()" in condition, (
            f"{step_name!r} does not use always(), so a failure in the validation steps above it "
            "would skip it and the mirror PR would silently not exist"
        )


def test_published_results_base_mirror_never_reports_success_without_a_verdict() -> None:
    """An unreachable verdict must not read as a passing check.

    ``always()`` means the status step can run when the validate step never
    wrote its outputs, so the state can arrive empty. Defaulting that to
    ``success`` would post a green check for content nothing examined - the
    original zero-check bug wearing a passing badge, which is worse than the
    empty rollup because it stops anyone looking.
    """
    body = _step(STATUS_STEP_NAME)["run"]
    assert 'STATE="${STATE:-error}"' in body, (
        "the status step does not default an absent verdict to `error`; an empty state would be posted as-is "
        "or, worse, silently treated as success"
    )
    assert "STATE:-success" not in body, "an absent verdict defaults to success"


def test_published_results_base_mirror_run_is_red_unless_validation_passed() -> None:
    """The run must fail on a missing verdict, not only on an explicit failure.

    ``state == 'failure'`` alone leaves the empty case green: the workflow
    would report success having never established whether the corpus it just
    proposed is publishable.
    """
    condition = _step("Fail the run if mirrored content failed validation").get("if", "")
    assert "!= 'success'" in condition, (
        f"failure gate is {condition!r}; a run that could not determine the verdict would still be green"
    )
