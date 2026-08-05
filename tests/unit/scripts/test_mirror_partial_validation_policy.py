"""Trusted-mirror vs community partial-validation policy.

The maintainer seed corpus includes ``summary.validation=partial`` cohorts.
After #1573 the mirror path ran full community validation and rejected those
bundles even when privacy was clean. The mirror workflow must pass
``--allow-partial-validation``; community validate-submission must not.
"""

from __future__ import annotations

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


def test_community_validate_submission_does_not_allow_partial() -> None:
    text = COMMUNITY_WORKFLOW.read_text(encoding="utf-8")
    assert "--allow-partial-validation" not in text
    # Community still requires the manifest for non-mirror heads.
    assert "--require-manifest" in text


def test_community_message_string_still_requires_passed() -> None:
    bundle = (REPO_ROOT / "benchbox" / "validation" / "bundle.py").read_text(encoding="utf-8")
    assert "must be 'passed' for public submissions" in bundle
