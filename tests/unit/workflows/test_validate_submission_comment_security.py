"""Pin validate-submission-comment.yml's untrusted-artifact hardening.

Review-followup (2026-07-06): the workflow_run companion posted a PR comment
using a writable `pull-requests: write` token, but derived WHICH PR to post
to from `pr_number.txt` inside an artifact uploaded by validate-submission.yml
-- a workflow that runs PR-supplied code before the artifact is staged. A
workflow_run follower gets a writable token even when the triggering run
could not (GitHub's documented behavior), so trusting that artifact-supplied
PR number would let any submission PR redirect the comment to an arbitrary
PR. The fix derives the target PR from GitHub's own record of which PR the
run's trusted `head_sha` belongs to instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission-comment.yml"
PRODUCER_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"


def _comment_step_script() -> str:
    workflow_yaml = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow_yaml["jobs"]["comment"]["steps"]
    for step in steps:
        if step.get("name") == "Post or update the comment":
            return step["with"]["script"]
    raise AssertionError("could not find the 'Post or update the comment' step")


def test_comment_target_pr_is_not_read_from_the_untrusted_artifact() -> None:
    script = _comment_step_script()
    assert "readFileSync('artifact/pr_number.txt'" not in script, (
        "the comment-target PR number must not be read from the artifact -- "
        "it is attacker-influenced (produced by a PR-supplied-code run)"
    )


def test_comment_target_pr_is_derived_from_trusted_head_sha() -> None:
    script = _comment_step_script()
    assert "context.payload.workflow_run.head_sha" in script
    assert "listPullRequestsAssociatedWithCommit" in script
    # Fail closed rather than guess when the lookup is ambiguous.
    assert "associatedPRs.length !== 1" in script


def test_producer_no_longer_stages_a_pr_number_in_the_artifact() -> None:
    # The companion above no longer reads pr_number.txt; the producer should
    # not manufacture it either, so a reader cannot mistake it for a still-
    # trusted value.
    text = PRODUCER_PATH.read_text(encoding="utf-8")
    assert "pr_number.txt" not in text
