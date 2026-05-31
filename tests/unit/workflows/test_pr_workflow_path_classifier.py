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
BASH_SNIPPET_TEST = pytest.mark.skipif(
    os.name == "nt",
    reason="ci-required-result aggregator is a Linux GitHub Actions bash snippet",
)


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
        "EXPLORER_TOKENS_RESULT": "skipped",
        "AUDIT_SHA_RESULT": "skipped",
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


@BASH_SNIPPET_TEST
def test_ci_required_result_preserves_content_guard_failure() -> None:
    result = _run_ci_required_result(
        CONTENT_GUARD_NEEDED="true",
        CONTENT_RESULT="failure",
    )

    assert result.returncode == 1
    assert "content-guard=failure" in result.stdout
    assert "Content-only PR; skipped Python code CI." not in result.stdout


@BASH_SNIPPET_TEST
def test_ci_required_result_fails_on_explorer_tokens_failure() -> None:
    # When the explorer-tokens job fires (results-explorer/src changed) and
    # fails, the aggregator must fail the required result. Without this
    # branch, the PR could merge despite a token-scan red — silently
    # regressing the blind-spot remediation.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        EXPLORER_TOKENS_RESULT="failure",
    )

    assert result.returncode == 1
    assert "explorer-tokens=failure" in result.stdout


@BASH_SNIPPET_TEST
def test_ci_required_result_treats_explorer_tokens_skipped_as_success() -> None:
    # Defensive: pin the `|| "skipped"` clause in the aggregator's
    # explorer-tokens check. The (NEEDS_CODE_CI="true",
    # EXPLORER_TOKENS_RESULT="skipped") combination is not produced by any
    # real PR shape today: the explorer-tokens job's `if:` is gated on
    # `needs-code-ci == 'true'`, so when needs-code-ci is true the job runs
    # (its inner detection step skips the scan when no results-explorer/src
    # paths changed, but the *job* still concludes "success", not
    # "skipped"). The only path that yields EXPLORER_TOKENS_RESULT="skipped"
    # is needs-code-ci="false", but the aggregator early-exits at the
    # NEEDS_CODE_CI=false branch before reading EXPLORER_TOKENS_RESULT. The
    # `|| "skipped"` clause is therefore belt-and-braces — this test pins
    # it so a future cleanup that drops the clause is a deliberate choice.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        EXPLORER_TOKENS_RESULT="skipped",
    )

    assert result.returncode == 0
    assert "Code/infra PR; lint and fast tests passed." in result.stdout


@BASH_SNIPPET_TEST
def test_ci_required_result_passes_on_explorer_tokens_success() -> None:
    # Sanity: when explorer-tokens runs and passes alongside lint+test
    # success, the aggregator returns success.
    result = _run_ci_required_result(
        NEEDS_CODE_CI="true",
        SAFE_CONTENT_ONLY="false",
        LINT_RESULT="success",
        TEST_RESULT="success",
        EXPLORER_TOKENS_RESULT="success",
    )

    assert result.returncode == 0
    assert "Code/infra PR; lint and fast tests passed." in result.stdout


def test_ci_required_result_explorer_tokens_in_needs() -> None:
    # If a future cleanup drops `explorer-tokens` from the
    # `ci-required-result.needs:` list, the aggregator wouldn't observe its
    # status at all (always "" → handled as not-success in the bash logic).
    # Lock the wiring in place.
    workflow_yaml = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
    needs = workflow_yaml["jobs"]["ci-required-result"]["needs"]
    assert "explorer-tokens" in needs
