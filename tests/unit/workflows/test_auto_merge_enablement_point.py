"""Auto-merge must not be armed merely because a PR was opened.

Arming at creation is only correct if nothing more will be pushed - and the
usual reason something more is pushed is review feedback, which arrives after
the PR exists. A PR armed at creation can satisfy its checks and merge while
the follow-up commit is still being written, leaving develop with a partial
change and the remainder orphaned on a closed branch.

That happened three times in one session: #1503 lost the browser gate job its
own PR body described, and #1521 and #1531 then each lost the very commit that
addressed their own review findings. No local check can prevent it - in all
three the working tree was clean when the PR was opened.

#1567 moved the Makefile hold (`pr-open` withholds; `pr-ready` arms). The
workflow `auto-merge-on-open.yml` still armed on `opened` for any non-draft
PR, so bare `gh pr create` defeated the hold (#1568/#1569). The cross-layer
policy is therefore:

- Local: `pr-open` withholds; `pr-ready` / `READY=1` arms.
- Workflow: arm only on `ready_for_review`; never enable on
  opened/reopened/synchronize. Soundness disable still runs on those events.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"
AUTO_MERGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "auto-merge-on-open.yml"

ARM_COMMAND = "gh pr merge --auto --squash"

# Exact enable/disable `if:` pins for auto-merge-on-open.yml (collapsed form).
ENABLE_IF = "steps.soundness.outputs.soundness_path != 'true' && github.event.action == 'ready_for_review'"
DISABLE_IF = "steps.soundness.outputs.soundness_path == 'true'"


def _target_body(name: str) -> str:
    """Return the recipe lines of a Makefile target."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}:.*?\n((?:\t.*\n|\n)*)", text, re.MULTILINE)
    assert match, f"Makefile has no target {name!r}"
    return match.group(1)


def _load_workflow() -> dict[str, Any]:
    return yaml.safe_load(AUTO_MERGE_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict[str, Any]) -> dict[str, Any]:
    """Return the `on:` block (PyYAML 1.1 may resolve unquoted `on` to True)."""
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None, "workflow has no `on:` block"
    return triggers


def _enable_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs") or {}
    assert "enable" in jobs, "auto-merge workflow has no enable job"
    return jobs["enable"]


def _steps_by_name(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    named: dict[str, dict[str, Any]] = {}
    for step in job.get("steps") or []:
        name = step.get("name")
        if name:
            named[str(name)] = step
    return named


def _collapsed_if(step: dict[str, Any]) -> str:
    """Normalize a step `if:` to a single-line string for exact comparison.

    PyYAML may leave multi-line folded scalars with internal newlines/spaces;
    collapse whitespace so the pin is the semantic condition, not YAML layout.
    """
    raw = str(step.get("if") or "").strip()
    return re.sub(r"\s+", " ", raw)


# ---------------------------------------------------------------------------
# Makefile layer (hold at pr-open; arm via pr-ready)
# ---------------------------------------------------------------------------


def test_auto_merge_enablement_point_is_not_pr_open() -> None:
    """`pr-open` must not arm auto-merge on its own.

    This is the assertion that fails on the unfixed tree, where pr-open calls
    `gh pr merge --auto --squash` directly for any non-soundness branch.
    """
    body = _target_body("pr-open")
    assert ARM_COMMAND not in body, (
        "pr-open arms auto-merge directly, so a PR can merge before a later commit is pushed"
    )


def test_auto_merge_enablement_point_keeps_a_hands_free_path() -> None:
    """A finished branch must still reach auto-merge without ceremony.

    Withholding by default is only acceptable while arming stays trivial, so
    pin both the explicit target and the one-command escape hatch.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^pr-ready:", text, re.MULTILINE), "no pr-ready target; withholding would be a dead end"
    assert "READY" in _target_body("pr-open"), "pr-open has no READY=1 path to open and arm in one step"


def test_auto_merge_enablement_point_has_one_arming_implementation() -> None:
    """Both entry points must share one arming path.

    The soundness withhold lives in that path. A second copy is how the two
    entry points drift until one of them stops checking.
    """
    text = MAKEFILE.read_text(encoding="utf-8")
    assert text.count(ARM_COMMAND) == 1, (
        f"{ARM_COMMAND!r} appears more than once; the soundness check can drift between copies"
    )


def test_auto_merge_enablement_point_preserves_soundness_withholding() -> None:
    """Must-preserve: soundness-path PRs are still withheld.

    The arming path has to consult the soundness predicate before it arms, or
    moving the enablement point would quietly drop the control that keeps
    oracle-adjacent changes from merging hands-free.
    """
    body = _target_body("pr-arm-auto-merge")
    assert "auto_merge_soundness_paths.py" in body, "arming path no longer consults the soundness predicate"
    arm_index = body.index(ARM_COMMAND)
    check_index = body.index("auto_merge_soundness_paths.py")
    assert check_index < arm_index, "soundness check runs after arming, so it cannot withhold"


# ---------------------------------------------------------------------------
# Workflow layer (do not arm on opened; arm only on ready_for_review)
# ---------------------------------------------------------------------------


def test_auto_merge_workflow_enable_if_is_exact_policy() -> None:
    """Enable step must arm only for non-soundness ready_for_review.

    Exact pin: opened/reopened/synchronize cannot arm even if someone later
    rewrites the condition into a looser OR of event actions.
    """
    workflow = _load_workflow()
    steps = _steps_by_name(_enable_job(workflow))
    enable = steps.get("Enable squash auto-merge")
    assert enable is not None, "enable step missing from auto-merge-on-open.yml"
    assert _collapsed_if(enable) == ENABLE_IF, (
        f"enable step if: drifted from policy pin\n  got:  {_collapsed_if(enable)!r}\n  want: {ENABLE_IF!r}"
    )
    assert ARM_COMMAND in str(enable.get("run") or ""), "enable step no longer arms squash auto-merge"


def test_auto_merge_workflow_does_not_enable_merely_because_pr_was_opened() -> None:
    """No layer may arm auto-merge solely because a non-draft PR was opened.

    After #1567 the Makefile held at pr-open, but this workflow still ran
    `gh pr merge --auto --squash` on the `opened` event for any non-draft
    develop PR. That is the defect under test.
    """
    workflow = _load_workflow()
    steps = _steps_by_name(_enable_job(workflow))
    condition = _collapsed_if(steps["Enable squash auto-merge"])
    # Exact policy already asserted above; restate exclusions for the defect.
    assert condition == ENABLE_IF
    for forbidden in ("opened", "reopened", "synchronize"):
        assert f"== '{forbidden}'" not in condition and f'== "{forbidden}"' not in condition, (
            f"enable step still matches event action {forbidden!r}: {condition!r}"
        )


def test_auto_merge_workflow_keeps_opened_trigger_for_soundness_re_eval() -> None:
    """opened/reopened/synchronize must still run for soundness disable.

    Dropping those triggers would leave a soundness PR that was opened with
    auto-merge already on (or that later gains a soundness commit) without a
    revocation path from this workflow.
    """
    types = _triggers(_load_workflow())["pull_request"]["types"]
    for required in ("opened", "reopened", "ready_for_review", "synchronize"):
        assert required in types, f"pull_request types missing {required!r}: {types}"


def test_auto_merge_workflow_does_not_re_enable_on_synchronize() -> None:
    """synchronize must not re-arm auto-merge.

    Re-enabling on every push would defeat the open-time hold as soon as the
    first post-open push lands, restoring the partial-stack race.
    """
    workflow = _load_workflow()
    condition = _collapsed_if(_steps_by_name(_enable_job(workflow))["Enable squash auto-merge"])
    assert condition == ENABLE_IF
    assert "synchronize" not in condition


def test_auto_merge_workflow_preserves_soundness_disable() -> None:
    """Must-preserve: soundness paths still revoke auto-merge."""
    workflow = _load_workflow()
    steps = _steps_by_name(_enable_job(workflow))
    disable = steps.get("Disable auto-merge for soundness PR")
    assert disable is not None, "soundness disable step is gone"
    assert "--disable-auto" in str(disable.get("run") or ""), "soundness disable no longer calls --disable-auto"
    assert _collapsed_if(disable) == DISABLE_IF, (
        f"disable step if: drifted from policy pin\n  got:  {_collapsed_if(disable)!r}\n  want: {DISABLE_IF!r}"
    )
