"""Tests for Documentation workflow superseded-run cancellation.

docs.yml runs on nearly every code PR push; without a concurrency group
every superseded run finishes. Cancellation must apply to pull_request runs
for the same PR only: pushes to develop and release feed the deploy job and
must never cancel each other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS = REPO_ROOT / ".github" / "workflows" / "docs.yml"

EXPECTED_GROUP = (
    "${{ github.event_name == 'pull_request' "
    "&& format('docs-pr-{0}', github.event.pull_request.number) "
    "|| format('docs-{0}-{1}', github.sha, github.run_id) }}"
)
EXPECTED_CANCEL = "${{ github.event_name == 'pull_request' }}"

REQUIRED_CONTEXTS = frozenset({"ci-required-result", "Results Explorer browser gate", "ruleset-drift"})


def _workflow() -> dict[str, object]:
    return yaml.safe_load(DOCS.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _evaluate(event: str, number: int | None, sha: str) -> tuple[str, bool]:
    """Mirror the committed concurrency expressions for one event row."""
    workflow = _workflow()
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == EXPECTED_GROUP
    assert concurrency["cancel-in-progress"] == EXPECTED_CANCEL
    if event == "pull_request":
        assert number is not None
        return f"docs-pr-{number}", True
    return f"docs-{sha}-123", False


def test_docs_cancels_superseded_pr_runs_only() -> None:
    group, cancel = _evaluate("pull_request", 123, "a" * 40)
    assert cancel is True
    assert group == "docs-pr-123"


def test_two_quick_pushes_to_same_pr_share_cancel_group() -> None:
    first = _evaluate("pull_request", 123, "a" * 40)
    second = _evaluate("pull_request", 123, "b" * 40)
    assert first == second == ("docs-pr-123", True)


def test_develop_and_release_pushes_never_cancel() -> None:
    for event, sha in (("push", "c" * 40), ("push", "d" * 40), ("workflow_dispatch", "e" * 40)):
        group, cancel = _evaluate(event, None, sha)
        assert cancel is False, event
        assert group == f"docs-{sha}-123"
    assert _evaluate("push", None, "c" * 40)[0] != _evaluate("push", None, "d" * 40)[0]


def test_path_filter_not_narrowed() -> None:
    # NOTE: PyYAML parses the bare `on:` trigger key as boolean True.
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    paths = triggers["pull_request"]["paths"]
    for required in ("benchbox/**", "scripts/**", "Makefile", "docs/**"):
        assert required in paths


def test_docs_declares_no_required_check() -> None:
    jobs = _workflow()["jobs"]
    names = {str(job.get("name", job_id)) for job_id, job in jobs.items()}
    assert not (names & REQUIRED_CONTEXTS)
