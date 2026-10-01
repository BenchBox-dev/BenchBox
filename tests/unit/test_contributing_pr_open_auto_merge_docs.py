"""Pin CONTRIBUTING.md to the arm-the-exact-head, monitor-to-merge policy.

A PR is done when it is merged. The author arms the exact head with
``gh pr merge <n> --squash --match-head-commit <head>`` and monitors the queue; a
push after arming is handled by arming the new head, not by holding PRs back.
``auto-merge-on-open.yml`` is revoke-only. CONTRIBUTING used to teach that
``make pr-open`` withholds auto-merge until a human runs ``make pr-ready``, which
turned every green PR into a hand-back. This module is a cheap docs contract so
that drift back to that wording fails in the fast unit lane.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"


@pytest.fixture(scope="module")
def contributing_text() -> str:
    return CONTRIBUTING.read_text(encoding="utf-8")


def test_contributing_does_not_claim_pr_open_arms_auto_merge(contributing_text: str) -> None:
    """Bare pr-open must not be documented as arming auto-merge.

    The pre-#1567 one-liner ``gh pr merge --auto --squash`` as a pr-open step
    is the specific false claim that stranded follow-up commits.
    """
    assert "merge --auto --squash" not in contributing_text, (
        "CONTRIBUTING still documents gh pr merge --auto --squash; pr-open withholds"
    )
    # Headline step must not promise "open with auto-merge in one shot".
    assert "open the PR with auto-merge in one shot" not in contributing_text


def test_contributing_documents_arming_the_exact_head_and_monitoring_to_merge(contributing_text: str) -> None:
    """The finished-branch path is: arm the exact head, then monitor until merged."""
    contributing_text = " ".join(contributing_text.split())  # tolerate reflowed lines
    for required in (
        "--match-head-commit",
        "monitor to merge",
        "You are done when the PR is merged",
        "[WRITE-CLOSEOUT-001]",
    ):
        assert required in contributing_text, f"CONTRIBUTING missing cue {required!r}"
    # The workflow is documented as revoke-only: there is no draft-to-ready arm path.
    assert "only revokes and never arms" in contributing_text


def test_contributing_does_not_teach_holding_a_finished_pr(contributing_text: str) -> None:
    """No wording that withholds auto-merge or waits for a human to mark a PR ready."""
    lowered = contributing_text.lower()
    for forbidden in ("withhold", "remains held", "stays held", "when the branch is final", "marked final"):
        assert forbidden not in lowered, f"CONTRIBUTING still teaches holding a finished PR: {forbidden!r}"
