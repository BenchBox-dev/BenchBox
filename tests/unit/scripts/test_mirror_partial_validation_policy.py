"""Trusted-mirror vs community partial-validation policy.

The maintainer seed corpus includes ``summary.validation=partial`` cohorts.
After #1573 the mirror path ran full community validation and rejected those
bundles even when privacy was clean. The mirror workflow must pass
``--allow-partial-validation``; community validate-submission must not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SYNC_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "sync-results-data-to-published.yml"
COMMUNITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"


def test_mirror_workflow_allows_partial_validation() -> None:
    text = SYNC_WORKFLOW.read_text(encoding="utf-8")
    assert "--allow-partial-validation" in text
    assert "partial" in text.lower()
    # Privacy and inventory still gate the mirror path.
    assert "validate_submission.py" in text
    assert "generate_corpus_inventory.py --check" in text


def _submission_validation_run() -> str:
    workflow = yaml.safe_load(COMMUNITY_WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["validate"]["steps"]
    return next(step["run"] for step in steps if step.get("name") == "Validate bundles")


def _evaluate_trust_gate(*, is_fork: str, head_ref: str, pr_author: str) -> tuple[str, str]:
    run = _submission_validation_run()
    prefix = run.split("# Trusted bot-created same-repo mirrors", maxsplit=1)[0]
    output = subprocess.check_output(
        ["bash", "-c", prefix + '\nprintf "%s|%s\\n" "$REQUIRE_MANIFEST" "$ALLOW_PARTIAL_VALIDATION"'],
        env={"IS_FORK": is_fork, "HEAD_REF": head_ref, "PR_AUTHOR": pr_author},
        text=True,
    ).strip()
    require_manifest, allow_partial = output.split("|", maxsplit=1)
    return require_manifest, allow_partial


def test_community_validate_submission_defaults_strict() -> None:
    run = _submission_validation_run()

    assert 'REQUIRE_MANIFEST="--require-manifest"' in run
    assert 'ALLOW_PARTIAL_VALIDATION=""' in run
    assert "$REQUIRE_MANIFEST $ALLOW_PARTIAL_VALIDATION" in run


@pytest.mark.parametrize(
    ("is_fork", "head_ref", "pr_author"),
    [
        ("true", "auto/results-mirror-deadbeef", "github-actions[bot]"),
        ("false", "feature/community-result", "github-actions[bot]"),
        ("false", "auto/results-mirror-deadbeef", "maintainer"),
    ],
)
def test_partial_waiver_rejects_untrusted_mirror_shapes(is_fork: str, head_ref: str, pr_author: str) -> None:
    assert _evaluate_trust_gate(is_fork=is_fork, head_ref=head_ref, pr_author=pr_author) == (
        "--require-manifest",
        "",
    )


def test_partial_waiver_accepts_exact_bot_created_same_repo_mirror() -> None:
    assert _evaluate_trust_gate(
        is_fork="false",
        head_ref="auto/results-mirror-deadbeef",
        pr_author="github-actions[bot]",
    ) == ("", "--allow-partial-validation")


def test_community_message_string_still_requires_passed() -> None:
    bundle = (REPO_ROOT / "benchbox" / "validation" / "bundle.py").read_text(encoding="utf-8")
    assert "must be 'passed' for public submissions" in bundle
