"""Workflow-shell checks over deep independent Git histories."""

from __future__ import annotations

from typing import Any

import pytest

from tests.unit.test_soundness_review_flag import _git, _run_queue_guard, queue_history as queue_history

# Real fetches and trusted checker subprocesses exceed the fast-test budget.
pytestmark = [pytest.mark.unit, pytest.mark.medium]


@pytest.mark.parametrize("advanced_branch", ["source", "trunk"])
def test_anchor_merge_base_survives_long_independent_history(
    queue_history: dict[str, Any], advanced_branch: str
) -> None:
    repo = queue_history["repo"]
    parent = _git(repo, "rev-parse", advanced_branch)
    commits = []
    for index in range(55):
        message = f"Independent history {index}\n"
        commits.append(
            f"commit refs/heads/{advanced_branch}\nmark :{index + 1}\n"
            f"committer Test Fixture <fixture@example.invalid> {1790760000 + index} +0000\n"
            f"data {len(message)}\n{message}from {parent}\n\n"
        )
        parent = f":{index + 1}"
    _git(repo, "fast-import", "--quiet", input="".join(commits))
    _git(repo, "checkout", advanced_branch)
    queue_history["head" if advanced_branch == "source" else "base"] = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "advanced-queue", queue_history["base"])
    (repo / queue_history["source_path"]).write_text("approved source\n", encoding="utf-8")
    _git(repo, "add", queue_history["source_path"])
    _git(repo, "commit", "-m", "Squash approved source onto advanced base")

    result = _run_queue_guard(queue_history)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "content verified in queue" in result.stderr
