"""Tests for develop-post-merge metrics jq behavior."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
# Mirrors the live filter in develop-post-merge.yml's metrics step so the
# fixture stays in sync with the workflow. If the workflow adds another job
# to the post-merge gate, extend this filter and add a fixture exercising
# the new job's failure timestamp.
RED_AT_JQ = r"""
if $post_merge_red == "true" then
  ([($jobs.jobs // [])[] |
    select((.name == "lint" or .name == "fast-test" or .name == "explorer-tokens" or .name == "medium-test") and .conclusion == "failure" and .completed_at != null) |
    .completed_at] | min // null)
else null end
"""


def run_red_at_jq(jobs: dict, post_merge_red: str = "true") -> str | None:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required for workflow metrics fixture tests")
    result = subprocess.run(
        [
            jq,
            "-n",
            "--argjson",
            "jobs",
            json.dumps(jobs),
            "--arg",
            "post_merge_red",
            post_merge_red,
            RED_AT_JQ,
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_failed_post_merge_jobs_use_earliest_completion_timestamp() -> None:
    jobs = {
        "jobs": [
            {
                "name": "fast-test",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:10:00Z",
            },
            {
                "name": "lint",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:03:00Z",
            },
            {
                "name": "docs",
                "conclusion": "failure",
                "completed_at": "2026-05-01T09:55:00Z",
            },
            {
                "name": "lint",
                "conclusion": "failure",
                "completed_at": None,
            },
        ]
    }

    assert run_red_at_jq(jobs) == "2026-05-01T10:03:00Z"


def test_workflow_metrics_expression_uses_min_not_max() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")

    assert ".completed_at] | min // null" in workflow
    assert ".completed_at] | max // null" not in workflow


def test_explorer_tokens_failure_counted_in_red_at() -> None:
    # Mirror of test_failed_post_merge_jobs_use_earliest_completion_timestamp
    # but with an `explorer-tokens` failure as the earliest. Locks in the
    # blind-spot remediation (token-scan gate) as a tracked post-merge red
    # signal — not just lint and fast-test.
    jobs = {
        "jobs": [
            {
                "name": "lint",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:10:00Z",
            },
            {
                "name": "explorer-tokens",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:01:00Z",
            },
            {
                "name": "fast-test",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:05:00Z",
            },
        ]
    }

    assert run_red_at_jq(jobs) == "2026-05-01T10:01:00Z"


def test_medium_test_failure_counted_in_red_at() -> None:
    # Mirror of test_explorer_tokens_failure_counted_in_red_at for the medium
    # speed tier's post-merge CI home (medium-tier-ci-home.yaml). While
    # medium-test is demoted (job-level continue-on-error, see
    # test_medium_test_is_visibility_only_not_auto_revert_trigger), this
    # branch of the jq filter is inert in practice: MEDIUM_TEST_RESULT reads
    # "success" under continue-on-error, so post_merge_red never flips on a
    # medium-test failure alone. Kept wired (and pinned here) so the metrics
    # row is complete the moment the job is promoted.
    jobs = {
        "jobs": [
            {
                "name": "lint",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:10:00Z",
            },
            {
                "name": "medium-test",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:01:00Z",
            },
            {
                "name": "fast-test",
                "conclusion": "failure",
                "completed_at": "2026-05-01T10:05:00Z",
            },
        ]
    }

    assert run_red_at_jq(jobs) == "2026-05-01T10:01:00Z"


def test_workflow_metrics_filter_includes_explorer_tokens() -> None:
    # The jq filter inside develop-post-merge.yml's metrics step decides
    # which job names are counted as post-merge-red signals. If
    # `explorer-tokens` is dropped from the filter, the gate would still
    # flip the `post_merge_red` shell flag but the metrics row would
    # under-report the red event timestamp.
    workflow = (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    assert '.name == "explorer-tokens"' in workflow


def test_post_merge_red_shell_flag_includes_explorer_tokens() -> None:
    # The shell `post_merge_red` flag is the gate the auto-revert and
    # metrics rows both branch on. If a future workflow cleanup drops
    # EXPLORER_TOKENS_RESULT from this expression, the gate would flag
    # red but no auto-revert PR would open and the metrics row would be
    # marked green — silently regressing the blind-spot remediation.
    workflow = (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    assert '${EXPLORER_TOKENS_RESULT}" = "failure"' in workflow


def test_post_merge_red_shell_flag_includes_medium_test() -> None:
    # Same guard as test_post_merge_red_shell_flag_includes_explorer_tokens,
    # for the medium-test job added by medium-tier-ci-home.yaml. Inert while
    # medium-test carries continue-on-error (the result reads "success"),
    # but kept wired so promotion only needs the workflow-side flip.
    workflow = (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    assert '${MEDIUM_TEST_RESULT}" = "failure"' in workflow


def test_auto_revert_triggers_on_explorer_tokens_failure() -> None:
    # The auto-revert-on-failure job's `if:` expression decides which
    # post-merge red events open a revert PR. Adding `explorer-tokens`
    # to the trigger was the blind-spot remediation; this test prevents
    # an inadvertent removal during a future `if:` cleanup.
    workflow_yaml = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    )
    auto_revert = workflow_yaml["jobs"]["auto-revert-on-failure"]
    assert "explorer-tokens" in auto_revert["needs"]
    # The `if:` is a single string after yaml.safe_load.
    assert "needs.explorer-tokens.result == 'failure'" in auto_revert["if"]


def test_medium_test_is_visibility_only_not_auto_revert_trigger() -> None:
    # The medium tier has known-red tests on clean develop (stale
    # cross-surface-applicability artifact, plus undispositioned failures
    # observed under a contended sandbox measurement — see
    # medium-tier-ci-home.yaml). Until a full clean run of the tier is
    # green, medium-test must be visibility-only: continue-on-error and
    # EXCLUDED from the auto-revert-on-failure trigger, so an innocent
    # merge can never be auto-reverted for a pre-existing tier failure.
    # When promoting, flip these assertions to the explorer-tokens pattern
    # (needs + if:failure trigger, no continue-on-error).
    workflow_yaml = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    )
    medium_test = workflow_yaml["jobs"]["medium-test"]
    auto_revert = workflow_yaml["jobs"]["auto-revert-on-failure"]

    assert medium_test.get("continue-on-error") is True
    assert "medium-test" not in auto_revert["needs"]
    assert "needs.medium-test.result" not in auto_revert["if"]


def test_close_orphaned_prs_waits_for_post_merge_validation_success() -> None:
    # Closing superseded PRs is only safe after the post-merge validation
    # jobs have passed. Otherwise a failing develop push can be auto-reverted
    # after ancestor PRs were already closed as superseded.
    workflow_yaml = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    )
    close_orphaned_prs = workflow_yaml["jobs"]["close-orphaned-prs"]
    assert close_orphaned_prs["needs"] == ["lint", "fast-test", "explorer-tokens"]
    assert close_orphaned_prs.get("if") is None


def test_post_merge_explorer_tokens_job_runs_unconditionally() -> None:
    # The post-merge `explorer-tokens` job must have no `if:` so it always
    # runs against the merged develop tree. If a future cleanup added an
    # `if:` (e.g. mirroring the PR-time path-gated form), the post-merge
    # re-scan would silently stop firing while the auto-revert wiring would
    # still reference `needs.explorer-tokens.result == 'failure'` — a state
    # that could no longer occur. The whole blind-spot remediation
    # (squash-race regressions tripping auto-revert) depends on this job
    # running on every push to develop.
    workflow_yaml = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "develop-post-merge.yml").read_text(encoding="utf-8")
    )
    job = workflow_yaml["jobs"]["explorer-tokens"]
    assert job.get("if") is None, (
        f"post-merge explorer-tokens job must have no `if:` (always runs); found: {job.get('if')!r}"
    )
