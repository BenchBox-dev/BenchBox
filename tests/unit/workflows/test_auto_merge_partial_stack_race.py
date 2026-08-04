"""Guards against auto-merge landing a PR before its later commits are pushed.

`make pr-open` enables squash auto-merge at PR creation. When work continues on
the branch afterwards, the PR can satisfy its checks and merge while a later
commit is still being written, so develop receives a partial change and the
remaining commit is orphaned: the branch is merged, the PR is closed, and
nothing reports that part of the work never landed.

This is not hypothetical. PR #1503 merged carrying only its first commit; the
`Results Explorer browser gate` job that its own PR body described never landed,
and the orphan (b5c56ea9) was found by hand. The detector's own header records
three earlier occurrences in the same remediation.

`auto-merge-on-open.yml` cannot prevent it: it reacts to `synchronize`, and in
this race there is no later push to react to *until after* the merge has already
happened. So the guard is detection, and detection is only useful if it runs
close to the event - hence the trigger assertions below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DETECTOR_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "orphaned-commit-detector.yml"
AUTO_MERGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "auto-merge-on-open.yml"


def _load(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the `on:` block.

    PyYAML resolves an unquoted ``on`` key to the boolean ``True`` under YAML
    1.1, so accept either spelling rather than reading an empty trigger set and
    passing vacuously.
    """
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def test_auto_merge_partial_stack_detector_runs_on_every_develop_push() -> None:
    """The detector must run at the moment a squash merge can strand a commit.

    A `paths:` filter here would scope the push trigger to edits of the detector
    itself, leaving the weekly schedule as the only real coverage - up to seven
    days in which develop is silently missing a change everyone believes landed.
    """
    triggers = _triggers(_load(DETECTOR_WORKFLOW))
    assert "push" in triggers, "detector has no push trigger at all"
    push = triggers["push"] or {}
    assert "paths" not in push, (
        "detector's push trigger is path-filtered, so it only runs when the detector itself changes"
    )


def test_auto_merge_partial_stack_detector_watches_feature_branch_pushes() -> None:
    """A develop-only trigger is structurally too early to catch this race.

    The stranding sequence is: PR merges (develop push) -> *then* the later
    commit is pushed to the feature branch. At the moment the develop push runs,
    the orphan does not exist, so the run that looks best-placed to catch it
    cannot. The push that creates the orphan is the one to the feature branch.
    """
    push = _triggers(_load(DETECTOR_WORKFLOW))["push"] or {}
    branches = push.get("branches")
    assert not branches, (
        f"detector's push trigger is limited to {branches}; a post-merge push to a feature branch "
        "would not be seen, which is exactly the event that creates the orphan"
    )


def test_auto_merge_partial_stack_detector_keeps_its_scheduled_backstop() -> None:
    """Per-merge runs are the guard; the schedule still catches what they miss.

    A push run only sees branches that exist at that moment. The schedule is
    what eventually catches a branch pushed long after its PR closed.
    """
    triggers = _triggers(_load(DETECTOR_WORKFLOW))
    assert "schedule" in triggers, "the weekly backstop was dropped when the push trigger was added"


def test_auto_merge_partial_stack_detector_failure_is_actionable() -> None:
    """The detector must keep its allowlist escape hatch.

    Without one, a single acknowledged orphan makes every subsequent run red and
    the signal decays into noise that people learn to scroll past.
    """
    allowlist = REPO_ROOT / "_project" / "analysis" / "known-stranded-commits.txt"
    assert allowlist.is_file(), "the acknowledged-orphan allowlist is missing"
    detector = (REPO_ROOT / "_project" / "scripts" / "detect_orphaned_commits.py").read_text(encoding="utf-8")
    assert "known-stranded-commits" in detector, "detector no longer consults the allowlist"


def test_auto_merge_partial_stack_soundness_revocation_is_unchanged() -> None:
    """Must-preserve: soundness PRs still have auto-merge withheld and revoked.

    The detector change must not have disturbed the auto-merge path itself.
    """
    workflow = _load(AUTO_MERGE_WORKFLOW)
    types = _triggers(workflow)["pull_request"]["types"]
    assert "synchronize" in types, "auto-merge no longer re-evaluates on push, so a later soundness commit can ride"

    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    commands = [step.get("run", "") for step in steps]
    assert any("--disable-auto" in command for command in commands), "soundness revocation step is gone"
    assert any("--auto --squash" in command for command in commands), (
        "hands-free auto-merge for ordinary PRs is gone - the common case must stay hands-free"
    )


def test_auto_merge_partial_stack_detector_uses_the_pushed_allowlist() -> None:
    """The detector must judge a push by that push's own allowlist.

    It reads the allowlist from the checkout but compares branches against the
    remote, so the checkout ref decides only which allowlist is in force.
    Pinning `ref: develop` meant a branch that acknowledges an orphan was still
    judged by develop's older allowlist, so it could never make its own run
    pass - the check stayed red until after it merged.
    """
    workflow = _load(DETECTOR_WORKFLOW)
    steps = workflow["jobs"]["detect"]["steps"]
    checkout = next(s for s in steps if str(s.get("uses", "")).startswith("actions/checkout"))
    assert "ref" not in checkout.get("with", {}), (
        "detector pins a checkout ref, so a push cannot be judged by its own allowlist"
    )


def test_auto_merge_partial_stack_backstop_runs_at_least_daily() -> None:
    """The schedule is the only cover for orphans pushed to stale branches.

    For a `push` event GitHub runs the workflow file from the pushed commit, so
    an orphaning push to a branch created before the all-branch trigger landed -
    and never rebased - runs that branch's older workflow and detects nothing.
    Only the scheduled run, which reads develop's workflow and allowlist and
    scans every branch, catches those. A weekly cadence left them invisible for
    up to seven days.
    """
    schedule = _triggers(_load(DETECTOR_WORKFLOW))["schedule"]
    crons = [entry["cron"] for entry in schedule]
    assert crons, "detector has no scheduled backstop"
    for cron in crons:
        day_of_week = cron.split()[4]
        day_of_month = cron.split()[2]
        assert day_of_week == "*" and day_of_month == "*", (
            f"backstop cron {cron!r} runs less often than daily; a stale-branch orphan stays invisible until it fires"
        )
