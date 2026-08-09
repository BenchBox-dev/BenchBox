"""Pin CONTRIBUTING.md to the post-#1567/#1592 auto-merge enablement policy.

``make pr-open`` withholds auto-merge; arming is explicit via ``make pr-ready``
or ``make pr-open READY=1`` (the only arm paths — the workflow is revoke-only
since auto-merge-policy-consolidation-2026-08-06, D2). CONTRIBUTING used to
teach the opposite (``gh pr merge --auto --squash`` as part of pr-open). This
module is a cheap docs contract so that drift fails in the fast unit lane.
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


def test_contributing_documents_withhold_and_hands_free_arm_path(contributing_text: str) -> None:
    """Finished-branch path must stay documented: pr-ready / READY=1 / withhold."""
    for required in ("withhold", "pr-ready", "READY=1"):
        assert required in contributing_text, f"CONTRIBUTING missing hands-free arm cue {required!r}"
    # The workflow must be documented as revoke-only: no draft→ready arm path.
    assert "revoke-only" in contributing_text
