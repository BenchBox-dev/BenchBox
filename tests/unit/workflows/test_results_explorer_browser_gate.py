"""Contract tests for the Results Explorer browser lane wiring.

The browser workflow calls its Chromium job "blocking". That word is only true
if two separate things hold: the job must actually run on the branches we care
about, and it must not be `continue-on-error`. Neither is visible from the job
name, and both have been wrong at some point.

These tests pin the workflow-local half of the contract. Whether Chromium is a
*required status check* lives in the repository ruleset, which no unit test can
reach; that half is verified by the tracked item's `gh api` rung.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "results-explorer-browser.yml"

CHROMIUM_JOB = "chromium"
GATE_JOB = "browser-required-result"
ADVISORY_JOBS = ("firefox-smoke", "webkit-smoke")

# The status-check context GitHub sees, and therefore the exact string that
# must appear in the develop ruleset. It is the job's `name:`, not its id.
GATE_CONTEXT = "Results Explorer browser gate"


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the `on:` block.

    PyYAML resolves an unquoted ``on`` key to the boolean ``True`` (YAML 1.1),
    so accept either spelling rather than silently reading an empty trigger set
    and passing.
    """
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def test_lane_runs_on_develop_pushes(workflow: dict[str, Any]) -> None:
    """develop pushes must rebuild the browser lane.

    PRs into develop are not sufficient: a squash merge produces a commit no PR
    ever ran, so a bad interaction between two independently green PRs would
    only surface whenever the next explorer PR happened to rebuild.
    """
    push_branches = _triggers(workflow)["push"]["branches"]
    assert "develop" in push_branches, f"browser lane does not run on develop pushes: {push_branches}"


def test_gate_context_matches_the_documented_required_check(workflow: dict[str, Any]) -> None:
    """The ruleset pins a context string; renaming the job silently breaks it.

    A required context that no job reports leaves every PR unmergeable, so the
    job name, the admin runbook, and the live ruleset have to agree.
    """
    assert workflow["jobs"][GATE_JOB]["name"] == GATE_CONTEXT
    runbook = (REPO_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text(encoding="utf-8")
    assert GATE_CONTEXT in runbook, "required gate context is not recorded in the repo admin runbook"


def test_lane_still_runs_on_pull_requests_into_develop(workflow: dict[str, Any]) -> None:
    """The push trigger is an addition, not a replacement for PR coverage."""
    pr_branches = _triggers(workflow)["pull_request"]["branches"]
    assert "develop" in pr_branches, f"browser lane no longer runs on develop PRs: {pr_branches}"


def test_chromium_job_is_not_continue_on_error(workflow: dict[str, Any]) -> None:
    """A `continue-on-error` job reports success no matter what it found.

    The Chromium job's name asserts that it blocks. If this ever flips to true
    the name becomes a lie and every downstream reader - human or ruleset - is
    misled.
    """
    chromium = workflow["jobs"][CHROMIUM_JOB]
    assert chromium.get("continue-on-error", False) is False, "Chromium job is continue-on-error but claims to block"


def test_chromium_job_name_claims_blocking_only_while_it_can_block(workflow: dict[str, Any]) -> None:
    """Keep the job name and the job's actual semantics in sync."""
    chromium = workflow["jobs"][CHROMIUM_JOB]
    if "blocking" in chromium["name"].lower() and "non-blocking" not in chromium["name"].lower():
        assert chromium.get("continue-on-error", False) is False, (
            "job name says 'blocking' while continue-on-error suppresses its result"
        )


def test_advisory_browsers_are_not_silently_promoted(workflow: dict[str, Any]) -> None:
    """Firefox and WebKit graduate individually, by explicit decision.

    They are advisory until each independently clears the graduation criterion
    in `docs/operations/browser-ci.md`. Making Chromium genuinely blocking must
    not drag them along as a side effect.
    """
    for job_id in ADVISORY_JOBS:
        job = workflow["jobs"][job_id]
        assert job.get("continue-on-error") is True, f"{job_id} was promoted to blocking without an explicit decision"
        assert "non-blocking" in job["name"].lower(), f"{job_id} name no longer marks it advisory"


def test_pull_request_trigger_has_no_paths_filter(workflow: dict[str, Any]) -> None:
    """The required gate must report on *every* PR, so the workflow must start.

    This is the deadlock guard. `Results Explorer browser gate` is a required
    status check, and GitHub leaves a PR permanently unmergeable while a
    required check has not reported. A path-filtered workflow does not run at
    all, so it never reports - which would block every PR that happens to touch
    nothing under `results-explorer/`. Filtering belongs in `explorer-changes`,
    not in the trigger.
    """
    pull_request = _triggers(workflow)["pull_request"]
    assert "paths" not in pull_request, (
        "pull_request has a paths filter; the required gate would never report on unrelated PRs"
    )


def test_expensive_browser_jobs_are_gated_on_change_detection(workflow: dict[str, Any]) -> None:
    """Dropping the trigger filter must not run a 25-minute suite on every PR."""
    for job_id in (CHROMIUM_JOB, *ADVISORY_JOBS):
        job = workflow["jobs"][job_id]
        assert job.get("if") == "needs.explorer-changes.outputs.needed == 'true'", (
            f"{job_id} is not gated on explorer-changes; it would run on every PR"
        )


def test_required_gate_job_always_runs_and_gates_on_chromium(workflow: dict[str, Any]) -> None:
    """The required check must always reach a conclusion, and reflect Chromium."""
    gate = workflow["jobs"][GATE_JOB]
    assert gate.get("if") == "always()", "gate job does not always run; a skipped Chromium would leave it unreported"
    assert CHROMIUM_JOB in gate["needs"], "gate job does not depend on Chromium"
    assert "explorer-changes" in gate["needs"], "gate job cannot distinguish 'not needed' from 'skipped in error'"


def test_required_gate_does_not_silently_promote_advisory_browsers(workflow: dict[str, Any]) -> None:
    """Firefox and WebKit must stay out of the required gate's dependencies.

    Adding either to `needs` would make it merge-blocking without the explicit
    per-browser graduation decision that `docs/operations/browser-ci.md`
    requires.
    """
    gate_needs = workflow["jobs"][GATE_JOB]["needs"]
    for job_id in ADVISORY_JOBS:
        assert job_id not in gate_needs, f"{job_id} was promoted to blocking via the required gate's needs"


def test_chromium_runs_the_full_suite_entrypoint(workflow: dict[str, Any]) -> None:
    """The gate must run the deterministic full-suite entrypoint.

    `test:e2e:chromium` regenerates fixtures, rebuilds dist, and runs the
    failures specs at `--retries=0` in a separate invocation. Swapping it for a
    bare `playwright test` would quietly drop the cold-load regression guard.
    """
    steps = workflow["jobs"][CHROMIUM_JOB]["steps"]
    run_commands = [step.get("run", "") for step in steps]
    assert any("test:e2e:chromium" in command for command in run_commands), (
        "Chromium job no longer runs the npm test:e2e:chromium entrypoint"
    )
