"""Guardrails for the develop PR path classifier workflow."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _ci_required_result_script() -> str:
    workflow = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["ci-required-result"]["steps"]
    for step in steps:
        if step.get("name") == "Aggregate required result":
            return step["run"]
    raise AssertionError("ci-required-result aggregate step not found")


def _run_ci_required_result(**env_overrides: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "CI_PATHS_RESULT": "success",
        "CONTENT_RESULT": "skipped",
        "LINT_RESULT": "skipped",
        "TEST_RESULT": "skipped",
        "CONTENT_GUARD_NEEDED": "false",
        "NEEDS_CODE_CI": "false",
        "SAFE_CONTENT_ONLY": "true",
        **env_overrides,
    }
    return subprocess.run(
        ["bash", "-c", _ci_required_result_script()],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )


def test_pr_path_classifier_fetches_base_history_for_merge_base() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8")
    base_fetch = 'git fetch --no-tags origin "${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"'

    # The classifier uses `git diff origin/develop...HEAD`; a depth-1 base fetch
    # on GitHub's synthetic PR merge ref can leave no merge base available.
    # Three consumers of the full base history today:
    #   - ci-paths (path classifier)
    #   - content-guard (recreates path lists for content validators)
    #   - explorer-tokens (greps the diff for results-explorer/src changes)
    assert '--depth=1 origin "${{ github.base_ref }}:refs/remotes/origin/${{ github.base_ref }}"' not in workflow
    assert workflow.count(base_fetch) == 3


def test_ci_required_result_preserves_content_guard_failure() -> None:
    result = _run_ci_required_result(
        CONTENT_GUARD_NEEDED="true",
        CONTENT_RESULT="failure",
    )

    assert result.returncode == 1
    assert "content-guard=failure" in result.stdout
    assert "Content-only PR; skipped Python code CI." not in result.stdout
