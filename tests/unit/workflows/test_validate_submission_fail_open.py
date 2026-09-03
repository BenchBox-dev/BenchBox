"""The submission gate must FAIL when the validator fails.

Observed on PR #1629 (a maintainer corpus mirror into `published-results`):
`scripts/validate_submission.py` posted "Submission Validation: FAILED" with
**105 of 105 bundles failing**, yet the `Validate bundles` step exited 0 and the
required check went green.

Cause: the validator's stdout is piped into `tee`, and a bash pipeline returns
the status of its LAST command. GitHub Actions' default shell for `run:` is
`bash -e {0}` -- `-e` but NOT `-o pipefail` -- and this workflow declared no
`defaults.run.shell`, so `tee`'s zero exit masked the validator's non-zero one
completely.

It also silently disarmed the next step: `Check corpus inventory` is gated on
`steps.validate.outcome == 'success'`, which had become permanently true.

The rung below runs the REAL `run:` block out of the workflow under a real
shell, substituting only the validator invocation, and asserts the exit status.
Asserting that the string "pipefail" appears in the YAML would be the weaker
test: it pins the current spelling of the fix rather than the behaviour, and
would keep passing if someone later restructured the step into a pipeline that
loses the status a different way.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.utilities.posix_shell import run_posix_shell, skip_without_posix_shell

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"

# The real validator invocation inside the step, replaced with a stub whose exit
# status we control. Everything else about the block -- the shell options, the
# `| tee` pipe, the manifest-waiver branch -- is executed verbatim.
# A2 w2 adds $CORPUS_ARG (via --corpus-changed-paths) before --pr-comment; allow both.
_VALIDATOR_CALL = (
    "xargs -d '\\n' uv run -- python scripts/validate_submission.py "
    "$REQUIRE_MANIFEST $ALLOW_PARTIAL_VALIDATION --pr-comment /tmp/pr_comment.md < /tmp/changed_bundles.txt"
)
_VALIDATOR_CALL_WITH_CORPUS = (
    "xargs -d '\\n' uv run -- python scripts/validate_submission.py "
    "$REQUIRE_MANIFEST $ALLOW_PARTIAL_VALIDATION $CORPUS_ARG --pr-comment /tmp/pr_comment.md < /tmp/changed_bundles.txt"
)
# Accept either the pre-w2 or w2+ form; test will try both


def _validate_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return next(step for step in workflow["jobs"]["validate"]["steps"] if step.get("id") == "validate")


def _run_step_with_validator_exiting(status: int, tmp_path: Path):
    """Execute the real `Validate bundles` run block with a stubbed validator.

    The stub stands in for the validator only. `xargs -d` is GNU-only and the
    real call would die on BSD xargs for a reason unrelated to this gate, so
    substituting it keeps the rung from going red incidentally on macOS -- the
    exact "red for the wrong reason" trap this suite is meant to avoid.
    """
    script = _validate_step()["run"]
    # Accept either corpus-arg or non-corpus form (w2 migration)
    matched = _VALIDATOR_CALL_WITH_CORPUS if _VALIDATOR_CALL_WITH_CORPUS in script else _VALIDATOR_CALL
    assert matched in script, (
        "the validator invocation in validate-submission.yml no longer matches what this test "
        "substitutes; update _VALIDATOR_CALL so the rung keeps exercising the real block"
    )
    # `exit N | tee` preserves the pipeline shape the bug lived in.
    script = script.replace(matched, f"(exit {status})")
    _PARITY_CALL = (
        'uv run -- python scripts/publication/validator_parity.py --base-sha "$_BASE_SHA" '
        '--merge-sha "$_MERGE_SHA" --head-sha "$_HEAD_SHA" --corpus-changed-paths "$_CORPUS_FILE" '
        "$REQUIRE_MANIFEST $ALLOW_PARTIAL_VALIDATION"
    )
    assert _PARITY_CALL in script, (
        "the validator_parity invocation in validate-submission.yml no longer matches what this "
        "test substitutes; update _PARITY_CALL so the rung keeps exercising the real block"
    )
    script = script.replace(_PARITY_CALL, "(exit 0)")
    # Mirror GitHub's default `run:` interpreter: bash with -e and no pipefail.
    return run_posix_shell(
        f"set -e\n{script}",
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={
            "IS_FORK": "false",
            "HEAD_REF": "auto/results-mirror-deadbeef",
            "PR_AUTHOR": "github-actions[bot]",
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
    )


def test_failing_validator_fails_the_step(tmp_path: Path) -> None:
    """must_preserve: a non-zero validator must make the gate non-zero.

    This is the PR #1629 regression. Without `set -o pipefail` in the block,
    `tee` returns 0 and this assertion is what catches it.
    """
    skip_without_posix_shell()

    result = _run_step_with_validator_exiting(1, tmp_path)

    assert result.returncode != 0, (
        "the Validate bundles step exited 0 with a FAILING validator -- the submission gate is "
        "fail-open. The validator's status is being swallowed by the `| tee` pipeline (GitHub's "
        "default shell is `bash -e`, without `-o pipefail`), so bad bundles reach "
        "published-results with a green check. See PR #1629."
    )


def test_passing_validator_still_passes_the_step(tmp_path: Path) -> None:
    """The fix must not make the gate unconditionally red.

    Without this, `test_failing_validator_fails_the_step` would still pass if
    the step were broken into always failing -- a green-to-red overcorrection
    that blocks every legitimate submission.
    """
    skip_without_posix_shell()

    result = _run_step_with_validator_exiting(0, tmp_path)

    assert result.returncode == 0, (
        f"the Validate bundles step exited {result.returncode} with a PASSING validator; stderr:\n{result.stderr}"
    )


def test_corpus_inventory_step_is_gated_on_the_validate_outcome() -> None:
    """The downstream gate depends on the fix above actually working.

    `Check corpus inventory` runs only `if steps.validate.outcome == 'success'`.
    While the step above was fail-open that condition was permanently true, so
    the inventory check silently lost its skip-on-failure behaviour too. Pinned
    here so the coupling is visible to whoever edits either step.
    A2 w4 adds corpus-only gating (success || corpus-only) — accept either.
    """
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    step = next(s for s in workflow["jobs"]["validate"]["steps"] if s.get("name") == "Check corpus inventory")

    assert step["if"] in (
        "steps.validate.outcome == 'success'",
        "steps.validate.outcome == 'success' || steps.changed.outputs.has_bundles == 'corpus-only'",
    )
