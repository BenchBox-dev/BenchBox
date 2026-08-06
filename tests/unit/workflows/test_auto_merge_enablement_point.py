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
PR, so bare `gh pr create` defeated the hold (#1568/#1569). #1592 narrowed
the workflow arm to `ready_for_review` — which then never fired once (drafts
are unused; 0 events across 150 PRs), so the arm step was deleted outright
(auto-merge-policy-consolidation-2026-08-06, D2). The cross-layer policy is
therefore:

- Local: `pr-open` withholds; `pr-ready` / `READY=1` is the ONLY arm path.
- Workflow: revoke-only (soundness paths + `no-auto-merge` label); it never
  arms on any event. Soundness disable runs on opened/reopened/synchronize.
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

# Exact disable `if:` pins for auto-merge-on-open.yml (collapsed form).
DISABLE_IF = "steps.soundness.outputs.soundness_path == 'true'"
HOLD_DISABLE_IF = "steps.hold.outputs.held == 'true'"


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


def _revoke_job(workflow: dict[str, Any]) -> dict[str, Any]:
    jobs = workflow.get("jobs") or {}
    assert "revoke" in jobs, "auto-merge workflow has no revoke job"
    return jobs["revoke"]


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
# Workflow layer (revoke-only: never arms on any event)
# ---------------------------------------------------------------------------


def test_auto_merge_workflow_never_arms() -> None:
    """The workflow must contain no arm path at all.

    The historical defect was arming on `opened` (defeating the Makefile
    hold — #1568/#1569); the #1592 fix narrowed arming to `ready_for_review`,
    which never fired once (drafts unused). The step was deleted (D2): with
    no arm command in the file, no event — opened, reopened, synchronize, or
    a future looser condition — can arm.
    """
    workflow = _load_workflow()
    text = AUTO_MERGE_WORKFLOW.read_text(encoding="utf-8")
    assert "Enable squash auto-merge" not in text, "the dead arm step is back"
    for step in _revoke_job(workflow).get("steps") or []:
        run = str(step.get("run") or "")
        assert ARM_COMMAND not in run, f"workflow step {step.get('name')!r} arms auto-merge"


def test_auto_merge_workflow_keeps_revocation_triggers() -> None:
    """opened/reopened/synchronize must still run for soundness disable.

    Dropping those triggers would leave a soundness PR that later gains a
    soundness commit without a revocation path from this workflow. `labeled`
    is also required so the durable hold label revokes without needing a
    push. `ready_for_review` must stay absent: a draft cannot carry
    auto-merge (nothing to revoke), and its only historical use was the dead
    arm point.
    """
    types = _triggers(_load_workflow())["pull_request"]["types"]
    for required in ("opened", "reopened", "synchronize", "labeled"):
        assert required in types, f"pull_request types missing {required!r}: {types}"
    assert "ready_for_review" not in types, "ready_for_review is back; the arm point must not return"


def test_auto_merge_workflow_preserves_soundness_disable() -> None:
    """Must-preserve: soundness paths still revoke auto-merge."""
    workflow = _load_workflow()
    steps = _steps_by_name(_revoke_job(workflow))
    disable = steps.get("Disable auto-merge for soundness PR")
    assert disable is not None, "soundness disable step is gone"
    assert "--disable-auto" in str(disable.get("run") or ""), "soundness disable no longer calls --disable-auto"
    assert _collapsed_if(disable) == DISABLE_IF, (
        f"disable step if: drifted from policy pin\n  got:  {_collapsed_if(disable)!r}\n  want: {DISABLE_IF!r}"
    )


def test_auto_merge_workflow_preserves_explicit_hold_disable() -> None:
    """Must-preserve: no-auto-merge label revokes auto-merge independently."""
    workflow = _load_workflow()
    steps = _steps_by_name(_revoke_job(workflow))
    disable = steps.get("Disable auto-merge for explicit hold")
    assert disable is not None, "explicit-hold disable step is gone"
    assert "--disable-auto" in str(disable.get("run") or "")
    assert _collapsed_if(disable) == HOLD_DISABLE_IF, (
        f"hold disable if: drifted from policy pin\n  got:  {_collapsed_if(disable)!r}\n  want: {HOLD_DISABLE_IF!r}"
    )
