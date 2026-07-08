"""Pin the vendor-subtree governance gate in validate-submission.yml.

The vendor-supplied trust label is ranking-eligible and is granted purely by a
bundle living under results-data/bundles/vendor/. The ENFORCED control that a
community contributor cannot self-grant it is a step in the published-results
submission workflow that rejects non-maintainer additions under vendor/ (the
manifest result_source check in benchbox/validation/bundle.py is advisory only).
This test pins that step so it cannot silently regress.
"""

from __future__ import annotations

import re
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

    guard_match = re.search(
        rf'\[\s*"\${fork_var}"\s*=\s*"false"\s*\]\s*;\s*then\n(.*?)\nfi\b',
        run,
        re.DOTALL,
    )
    assert guard_match is not None, (
        f'Could not find a `if [ "${fork_var}" = "false" ]; then ... fi` block - '
        "the fork guard must wrap a then/fi body, not just appear in a condition."
    )
    guarded_body = guard_match.group(1)
    assert "auto/results-mirror-*" in guarded_body, (
        "The mirror branch pattern check must be NESTED inside the "
        f'[ "${fork_var}" = "false" ] guard body, not merely present elsewhere in the '
        "step - otherwise a same-named branch on a fork PR could still reach the bypass."
    )
