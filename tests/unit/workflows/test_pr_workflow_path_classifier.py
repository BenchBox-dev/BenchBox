"""Guardrails for the develop PR path classifier workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_pr_path_classifier_fetches_base_history_for_merge_base() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
    base_fetch = 'git fetch --no-tags origin "${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"'

    # The classifier uses `git diff origin/develop...HEAD`; a depth-1 base fetch
    # on GitHub's synthetic PR merge ref can leave no merge base available.
    assert '--depth=1 origin "${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"' not in workflow
    assert workflow.count(base_fetch) == 2
