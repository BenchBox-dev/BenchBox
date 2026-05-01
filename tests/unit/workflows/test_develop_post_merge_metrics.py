"""Tests for develop-post-merge metrics jq behavior."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
RED_AT_JQ = r"""
if $post_merge_red == "true" then
  ([($jobs.jobs // [])[] |
    select((.name == "lint" or .name == "fast-test") and .conclusion == "failure" and .completed_at != null) |
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
