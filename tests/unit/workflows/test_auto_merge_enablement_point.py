"""Auto-merge must not be armed at PR creation.

Arming at creation is only correct if nothing more will be pushed - and the
usual reason something more is pushed is review feedback, which arrives after
the PR exists. A PR armed at creation can satisfy its checks and merge while
the follow-up commit is still being written, leaving develop with a partial
change and the remainder orphaned on a closed branch.

That happened three times in one session: #1503 lost the browser gate job its
own PR body described, and #1521 and #1531 then each lost the very commit that
addressed their own review findings. No local check can prevent it - in all
three the working tree was clean when the PR was opened.

So `pr-open` withholds, `pr-ready` arms, and `pr-open READY=1` keeps the
one-command path for a branch already known to be final.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE = REPO_ROOT / "Makefile"

ARM_COMMAND = "gh pr merge --auto --squash"


def _target_body(name: str) -> str:
    """Return the recipe lines of a Makefile target."""
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}:.*?\n((?:\t.*\n|\n)*)", text, re.MULTILINE)
    assert match, f"Makefile has no target {name!r}"
    return match.group(1)


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
