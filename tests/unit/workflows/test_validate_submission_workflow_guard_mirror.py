"""Pin the trusted-mirror carve-out in the validator/workflow self-green guard.

The "Reject validator or workflow changes in a submission PR" step hard-fails
any PR touching scripts/validate_submission.py, benchbox/validation/bundle.py,
benchbox/core/results/query_status.py, scripts/generate_corpus_inventory.py,
or validate-submission.yml itself. But sync-results-data-to-published.yml
mirrors those exact 5 files onto published-results by design (see that
workflow's header comment), so its auto/results-mirror-* PRs legitimately
touch this guard's file set and were hitting a false-positive hard fail (see
the 3-PR backlog on #1978, #1992, #1998).

This test pins the carve-out this guard step now shares with the "Reject
non-maintainer vendor/ additions" step below it: a TRUSTED_MIRROR condition
gated on same-repo PR, base=published-results, author=github-actions[bot],
and head branch matching auto/results-mirror-*. Any other PR touching these
files - non-mirror, fork, wrong base, or human-authored - must still be
rejected exactly as before.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.utilities.posix_shell import run_posix_shell, skip_without_posix_shell

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"

_STEP_NAME = "Reject validator or workflow changes in a submission PR"


def _guard_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["validate"]["steps"]:
        if step.get("name") == _STEP_NAME:
            return step
    raise AssertionError(f"could not find the {_STEP_NAME!r} step in validate-submission.yml")


def test_guard_step_binds_the_same_trust_signals_as_the_vendor_gate() -> None:
    step = _guard_step()
    env = step.get("env") or {}
    assert env.get("IS_FORK") == "${{ github.event.pull_request.head.repo.fork }}"
    assert env.get("BASE_REF") == "${{ github.event.pull_request.base.ref }}"
    assert env.get("HEAD_REF") == "${{ github.head_ref }}"
    assert env.get("PR_AUTHOR") == "${{ github.event.pull_request.user.login }}"


def test_guard_step_still_covers_all_five_files() -> None:
    script = _guard_step()["run"]
    for f in [
        "scripts/validate_submission.py",
        "benchbox/validation/bundle.py",
        "benchbox/core/results/query_status.py",
        "scripts/generate_corpus_inventory.py",
        ".github/workflows/validate-submission.yml",
    ]:
        assert f in script


def _run_guard_body(*, changed_guard: str, is_fork: str, base_ref: str, head_ref: str, pr_author: str):
    """Execute the real post-diff guard body with CHANGED_GUARD pre-seeded.

    Substituting the `git diff` invocation's result (rather than running it
    against a real repo) keeps this test focused on the trust-gate logic,
    matching the style test_validate_submission_vendor_gate.py uses for the
    sibling guard.
    """
    script = _guard_step()["run"]
    start = script.index('if [ -n "$CHANGED_GUARD" ]; then')
    # Take the whole if/else/fi block (through the trailing "no changes" echo
    # in its else branch) so the extracted fragment is syntactically complete.
    # CHANGED_GUARD is always non-empty in these tests, so the else branch
    # never actually executes.
    body = script[start:]
    skip_without_posix_shell()
    env = {
        "CHANGED_GUARD": changed_guard,
        "IS_FORK": is_fork,
        "BASE_REF": base_ref,
        "HEAD_REF": head_ref,
        "PR_AUTHOR": pr_author,
    }
    return run_posix_shell(
        body,
        capture_output=True,
        text=True,
        env=env,
    )


def test_trusted_mirror_pr_touching_guarded_files_passes() -> None:
    result = _run_guard_body(
        changed_guard="scripts/validate_submission.py\nbenchbox/validation/bundle.py",
        is_fork="false",
        base_ref="published-results",
        head_ref="auto/results-mirror-deadbeef",
        pr_author="github-actions[bot]",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Trusted bot-created same-repo mirror PR" in result.stdout
    assert "::error::" not in result.stdout


@pytest.mark.parametrize(
    ("is_fork", "base_ref", "head_ref", "pr_author"),
    [
        # Fork PR, otherwise exact mirror shape.
        ("true", "published-results", "auto/results-mirror-deadbeef", "github-actions[bot]"),
        # Wrong base branch (not published-results).
        ("false", "develop", "auto/results-mirror-deadbeef", "github-actions[bot]"),
        # Head branch does not match auto/results-mirror-*.
        ("false", "published-results", "feature/community-result", "github-actions[bot]"),
        # Non-bot author (human-authored branch, even with a matching name).
        ("false", "published-results", "auto/results-mirror-deadbeef", "maintainer"),
    ],
    ids=["fork-pr", "wrong-base", "non-matching-branch", "non-bot-author"],
)
def test_untrusted_shapes_touching_guarded_files_are_still_rejected(
    is_fork: str, base_ref: str, head_ref: str, pr_author: str
) -> None:
    result = _run_guard_body(
        changed_guard="scripts/validate_submission.py",
        is_fork=is_fork,
        base_ref=base_ref,
        head_ref=head_ref,
        pr_author=pr_author,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::" in result.stdout
    assert "not allowed" in result.stdout


def test_non_mirror_pr_touching_guarded_files_is_rejected_even_without_bot_signals() -> None:
    """A human PR that happens to touch none of the trust env vars must still fail closed."""
    result = _run_guard_body(
        changed_guard=".github/workflows/validate-submission.yml",
        is_fork="false",
        base_ref="published-results",
        head_ref="feature/tweak-validator",
        pr_author="some-contributor",
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "::error::" in result.stdout
