"""Pin the vendor-subtree governance gate in validate-submission.yml.

The vendor-supplied trust label is ranking-eligible and is granted purely by a
bundle living under results-data/bundles/vendor/. The ENFORCED control that a
community contributor cannot self-grant it is a step in the published-results
submission workflow that rejects non-maintainer additions under vendor/ (the
manifest result_source check in benchbox/validation/bundle.py is advisory only).
This test pins that step so it cannot silently regress.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "validate-submission.yml"

_STEP_NAME = "Reject non-maintainer vendor/ additions"


def _vendor_gate_step() -> dict:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["validate"]["steps"]:
        if step.get("name") == _STEP_NAME:
            return step
    raise AssertionError(f"could not find the {_STEP_NAME!r} step in validate-submission.yml")


def test_workflow_targets_published_results_submission_prs() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    # PyYAML parses the `on:` key as the boolean True.
    trigger = workflow[True]["pull_request"]
    assert "published-results" in trigger["branches"]
    assert any("results-data/bundles/" in p for p in trigger["paths"])


def test_vendor_gate_step_exists_and_guards_vendor_subtree() -> None:
    step = _vendor_gate_step()
    script = step["run"]
    assert "results-data/bundles/vendor/" in script


def test_vendor_gate_uses_author_association_not_pr_content() -> None:
    step = _vendor_gate_step()
    # The maintainer check must come from GitHub's author_association, which the
    # PR cannot set, not from a manifest field or commit trailer.
    assert step["env"]["AUTHOR_ASSOCIATION"] == "${{ github.event.pull_request.author_association }}"
    script = step["run"]
    for role in ("OWNER", "MEMBER", "COLLABORATOR"):
        assert role in script


def test_vendor_gate_fails_the_pr() -> None:
    script = _vendor_gate_step()["run"]
    # A non-maintainer vendor/ addition must hard-fail the job.
    assert "exit 1" in script
    assert "::error::" in script


def test_vendor_gate_allows_trusted_same_repo_mirror() -> None:
    """#1041 review: a maintainer vendor/ addition on develop is published
    through a same-repo auto/results-mirror-* PR opened by
    sync-results-data-to-published.yml with secrets.GITHUB_TOKEN, authored by
    github-actions[bot] - never OWNER/MEMBER/COLLABORATOR. The gate must let
    that trusted mirror through instead of blocking it, gated on the same
    unforgeable head.repo.fork signal the "Validate bundles" step's manifest
    waiver uses (github.head_ref alone is attacker-controlled on fork PRs).
    """
    step = _vendor_gate_step()
    env = step.get("env") or {}
    run = step["run"]

    fork_var = next((k for k, v in env.items() if "head.repo.fork" in str(v)), None)
    assert fork_var is not None, (
        "The vendor gate step must bind github.event.pull_request.head.repo.fork "
        "into the env so the mirror-bot bypass can gate on it."
    )

    author_var = next((k for k, v in env.items() if "pull_request.user.login" in str(v)), None)
    assert author_var is not None, "The vendor gate must bind the PR author's GitHub login."

    base_var = next((k for k, v in env.items() if "pull_request.base.ref" in str(v)), None)
    assert base_var is not None, "The vendor gate must bind the PR base branch."

    guard_match = re.search(
        rf'\[\s*"\${base_var}"\s*=\s*"published-results"\s*\]\s*&&\s*'
        rf'\[\s*"\${fork_var}"\s*=\s*"false"\s*\]\s*&&\s*'
        rf'\[\s*"\${author_var}"\s*=\s*"github-actions\[bot\]"\s*\]\s*;\s*then\n(.*?)\nfi\b',
        run,
        re.DOTALL,
    )
    assert guard_match is not None, (
        "Could not find a trust guard requiring both a same-repository head and "
        "the exact github-actions[bot] PR author."
    )
    guarded_body = guard_match.group(1)
    assert "auto/results-mirror-*" in guarded_body, (
        "The mirror branch pattern check must be NESTED inside the "
        f'[ "${fork_var}" = "false" ] guard body, not merely present elsewhere in the '
        "step - otherwise a same-named branch on a fork PR could still reach the bypass."
    )


def _evaluate_mirror_trust_gate(*, is_fork: str, base_ref: str, head_ref: str, pr_author: str) -> str:
    run = _vendor_gate_step()["run"]
    gate = run[run.index('TRUSTED_MIRROR="false"') : run.index('case "$AUTHOR_ASSOCIATION"')]
    env = os.environ.copy()
    env.update({"IS_FORK": is_fork, "BASE_REF": base_ref, "HEAD_REF": head_ref, "PR_AUTHOR": pr_author})
    return subprocess.check_output(
        ["bash", "-c", gate + '\nprintf "%s\\n" "$TRUSTED_MIRROR"'],
        env=env,
        text=True,
    ).strip()


@pytest.mark.parametrize(
    ("is_fork", "base_ref", "head_ref", "pr_author"),
    [
        ("true", "published-results", "auto/results-mirror-deadbeef", "github-actions[bot]"),
        ("false", "develop", "auto/results-mirror-deadbeef", "github-actions[bot]"),
        ("false", "published-results", "feature/community-result", "github-actions[bot]"),
        ("false", "published-results", "auto/results-mirror-deadbeef", "maintainer"),
    ],
)
def test_vendor_waiver_rejects_untrusted_mirror_shapes(
    is_fork: str, base_ref: str, head_ref: str, pr_author: str
) -> None:
    assert (
        _evaluate_mirror_trust_gate(
            is_fork=is_fork,
            base_ref=base_ref,
            head_ref=head_ref,
            pr_author=pr_author,
        )
        == "false"
    )


def test_vendor_waiver_accepts_exact_bot_created_same_repo_mirror() -> None:
    assert (
        _evaluate_mirror_trust_gate(
            is_fork="false",
            base_ref="published-results",
            head_ref="auto/results-mirror-deadbeef",
            pr_author="github-actions[bot]",
        )
        == "true"
    )
