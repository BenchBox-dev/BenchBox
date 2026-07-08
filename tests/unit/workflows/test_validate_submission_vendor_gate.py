"""Pin the vendor-subtree governance gate in validate-submission.yml.

The vendor-supplied trust label is ranking-eligible and is granted purely by a
bundle living under results-data/bundles/vendor/. The ENFORCED control that a
community contributor cannot self-grant it is a step in the published-results
submission workflow that rejects non-maintainer additions under vendor/ (the
manifest result_source check in benchbox/validation/bundle.py is advisory only).
This test pins that step so it cannot silently regress.
"""

from __future__ import annotations

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
