from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from _project.scripts.oracle_reviewers import github
from _project.scripts.oracle_reviewers.retry import State

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO = "BenchBox-dev/BenchBox"
SHA = "d" * 40


def _run(**over: Any) -> dict[str, Any]:
    run = {
        "path": ".github/workflows/oracle-review-shadow.yml",
        "repository": {"full_name": REPO},
        "event": "issue_comment",
        "head_sha": SHA,
    }
    run.update(over)
    return run


def _always(repo: str, sha: str) -> bool:
    return True


def test_trusted_run_accepts_this_workflow_from_develop() -> None:
    assert github.trusted_run(_run(), REPO, _always)
    assert github.trusted_run(_run(event="pull_request_target"), REPO, _always)


@pytest.mark.parametrize(
    "run",
    [
        _run(path=".github/workflows/other.yml"),
        _run(event="pull_request"),
        _run(event="push"),
        _run(repository={"full_name": "someone/BenchBox"}),
        _run(head_sha="not-a-sha"),
    ],
)
def test_trusted_run_rejects_other_sources(run: dict[str, Any]) -> None:
    assert not github.trusted_run(run, REPO, _always)


def test_trusted_run_rejects_workflow_code_that_is_not_on_develop() -> None:
    assert not github.trusted_run(_run(), REPO, lambda repo, sha: False)


def test_latest_state_skips_untrusted_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    state = State(7, "a" * 40, "pending", datetime(2026, 10, 5, tzinfo=UTC))
    listing = {
        "artifacts": [
            {"created_at": "2026-10-05T12:00:00Z", "workflow_run": {"id": 2}, "expired": False},
            {"created_at": "2026-10-05T11:00:00Z", "workflow_run": {"id": 1}, "expired": False},
            {"created_at": "2026-10-05T13:00:00Z", "workflow_run": {"id": 3}, "expired": True},
        ]
    }
    runs = {"2": _run(event="pull_request"), "1": _run()}
    downloaded: list[str] = []

    def get_json(path: str) -> Any:
        if path.startswith(f"repos/{REPO}/actions/artifacts"):
            return listing
        if path.startswith(f"repos/{REPO}/actions/runs/"):
            return runs[path.rsplit("/", 1)[1]]
        return {"status": "ahead"}

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        downloaded.append(argv[3])
        directory = Path(argv[argv.index("-D") + 1])
        (directory / github.STATE_FILE).write_text(json.dumps(state.to_json()), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(github, "get_json", get_json)
    monkeypatch.setattr(github.subprocess, "run", fake_run)
    assert github.latest_state(REPO, 7) == state
    assert downloaded == ["1"]


def test_latest_state_without_artifacts_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "get_json", lambda path: {"artifacts": []})
    assert github.latest_state(REPO, 7) is None


def test_review_threads_pages_and_keeps_the_first_comment(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = [
        {"hasNextPage": True, "endCursor": "c1", "nodes": [_thread(False, "a.py", "benchbox-oracle", "**High**: A")]},
        {"hasNextPage": False, "endCursor": None, "nodes": [_thread(True, "b.py", None, "")]},
    ]
    calls: list[tuple[str, ...]] = []

    def fake_gh(*args: str, accept: str | None = None) -> str:
        calls.append(args)
        page = pages[len(calls) - 1]
        connection = {"pageInfo": {"hasNextPage": page["hasNextPage"], "endCursor": page["endCursor"]}}
        connection["nodes"] = page["nodes"]
        return json.dumps({"data": {"repository": {"pullRequest": {"reviewThreads": connection}}}})

    monkeypatch.setattr(github, "_gh", fake_gh)
    assert github.review_threads(REPO, 7) == [
        {"resolved": False, "path": "a.py", "author": "benchbox-oracle", "body": "**High**: A"},
        {"resolved": True, "path": "b.py", "author": None, "body": ""},
    ]
    assert "after=c1" in calls[1] and not any(arg.startswith("after=") for arg in calls[0])
    flags = dict(zip(calls[0][1::2], calls[0][2::2], strict=False))
    assert calls[0][0] == "graphql"
    assert [calls[0][index - 1] for index, arg in enumerate(calls[0]) if arg.startswith(("owner=", "name="))] == [
        "-f",
        "-f",
    ]
    assert flags["-F"] == "number=7"


def test_review_threads_raises_on_graphql_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "_gh", lambda *args, accept=None: json.dumps({"errors": [{"message": "no"}]}))
    with pytest.raises(github.GitHubError, match="GraphQL"):
        github.review_threads(REPO, 7)


def _thread(resolved: bool, path: str, author: str | None, body: str) -> dict[str, Any]:
    comment = {"author": {"login": author} if author else None, "body": body}
    return {"isResolved": resolved, "path": path, "comments": {"nodes": [comment]}}
