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
PR = 7


def _run(**over: Any) -> dict[str, Any]:
    run = {
        "path": ".github/workflows/oracle-review-shadow.yml",
        "repository": {"full_name": REPO},
        "event": "issue_comment",
        "head_sha": SHA,
        "created_at": "2026-10-07T23:05:42Z",
    }
    run.update(over)
    return run


def _always(repo: str, sha: str) -> bool:
    return True


def _never(repo: str, sha: str) -> bool:
    return False


def _pull(base_ref: str, number: int = PR) -> dict[str, Any]:
    return {
        "id": 2000 + number,
        "number": number,
        "url": f"https://api.github.com/repos/{REPO}/pulls/{number}",
        "head": {"ref": "feature", "sha": SHA, "repo": {"id": 1, "name": "BenchBox"}},
        "base": {"ref": base_ref, "sha": "b" * 40, "repo": {"id": 1, "name": "BenchBox"}},
    }


def _target_run(base_ref: str = "develop", **over: Any) -> dict[str, Any]:
    return _run(event="pull_request_target", pull_requests=[_pull(base_ref)], **over)


def test_trusted_run_accepts_this_workflow_from_develop() -> None:
    assert github.trusted_run(_run(), REPO, PR, _always)
    assert github.trusted_run(_target_run(), REPO, PR, _never)


def test_trusted_run_accepts_a_pull_request_target_run_whose_head_is_the_pr_head() -> None:
    assert github.trusted_run(_target_run(), REPO, PR, lambda repo, sha: False)


@pytest.mark.parametrize("event", ["issue_comment", "schedule", "workflow_dispatch"])
def test_trusted_run_checks_develop_ancestry_for_other_events(event: str) -> None:
    assert github.trusted_run(_run(event=event), REPO, PR, _always)
    assert not github.trusted_run(_run(event=event), REPO, PR, _never)


@pytest.mark.parametrize("pull_requests", [None, [], [_pull("release/1.0")], [_pull("main"), _pull("feature")]])
def test_trusted_run_rejects_a_pull_request_target_run_not_based_on_develop(pull_requests: Any) -> None:
    run = _run(event="pull_request_target", pull_requests=pull_requests)
    assert not github.trusted_run(run, REPO, PR, _always)


def test_trusted_run_accepts_a_pull_request_target_run_for_several_develop_pulls() -> None:
    run = _run(event="pull_request_target", pull_requests=[_pull("develop", 3), _pull("develop")])
    assert github.trusted_run(run, REPO, PR, _never)


@pytest.mark.parametrize(
    "pull_requests",
    [[_pull("main"), _pull("develop")], [_pull("develop"), _pull("release/1.0")]],
    ids=["main-first", "release-last"],
)
def test_trusted_run_rejects_a_pull_request_target_run_that_also_targets_another_base(pull_requests: Any) -> None:
    run = _run(event="pull_request_target", pull_requests=pull_requests)
    assert not github.trusted_run(run, REPO, PR, _always)


def test_trusted_run_rejects_a_pull_request_target_run_for_another_pull_request() -> None:
    assert not github.trusted_run(_target_run(), REPO, PR + 1, _always)
    run = _run(event="pull_request_target", pull_requests=[_pull("develop", 3)])
    assert not github.trusted_run(run, REPO, PR, _always)


def test_trusted_run_rejects_a_pull_request_target_run_from_another_workflow() -> None:
    assert not github.trusted_run(_target_run(path=".github/workflows/other.yml"), REPO, PR, _always)
    assert not github.trusted_run(_target_run(head_sha="not-a-sha"), REPO, PR, _always)
    assert not github.trusted_run(_target_run(repository={"full_name": "someone/BenchBox"}), REPO, PR, _always)


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
    assert not github.trusted_run(run, REPO, PR, _always)


def test_trusted_run_rejects_workflow_code_that_is_not_on_develop() -> None:
    assert not github.trusted_run(_run(), REPO, PR, _never)


@pytest.mark.parametrize(
    ("status", "expected"),
    [("ahead", True), ("identical", True), ("behind", False), ("diverged", False)],
)
def test_on_develop_reads_the_compare_status(monkeypatch: pytest.MonkeyPatch, status: str, expected: bool) -> None:
    paths: list[str] = []

    def get_json(path: str) -> Any:
        paths.append(path)
        return {"status": status}

    monkeypatch.setattr(github, "get_json", get_json)
    assert github.on_develop(REPO, SHA) is expected
    assert paths == [f"repos/{REPO}/compare/{SHA}...develop"]


def test_latest_state_skips_untrusted_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    state = State(7, "a" * 40, "pending", datetime(2026, 10, 5, tzinfo=UTC))
    listing = {
        "artifacts": [
            {"created_at": "2026-10-05T12:00:00Z", "workflow_run": {"id": 2}, "expired": False},
            {"created_at": "2026-10-05T11:00:00Z", "workflow_run": {"id": 1}, "expired": False},
            {"created_at": "2026-10-05T13:00:00Z", "workflow_run": {"id": 3}, "expired": True},
        ]
    }
    runs = {"2": _run(event="pull_request"), "1": _target_run()}
    downloaded: list[str] = []

    def get_json(path: str) -> Any:
        if path.startswith(f"repos/{REPO}/actions/artifacts"):
            return listing
        if path.startswith(f"repos/{REPO}/actions/runs/"):
            return runs[path.rsplit("/", 1)[1]]
        raise AssertionError(f"unexpected request {path}")

    def fake_run(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        downloaded.append(argv[3])
        directory = Path(argv[argv.index("-D") + 1])
        (directory / github.STATE_FILE).write_text(json.dumps(state.to_json()), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(github, "get_json", get_json)
    monkeypatch.setattr(github, "get_paginated", lambda path: [])
    monkeypatch.setattr(github.subprocess, "run", fake_run)
    assert github.latest_state(REPO, 7) == state
    assert downloaded == ["1"]


def test_latest_state_skips_a_pull_request_target_run_not_based_on_develop(monkeypatch: pytest.MonkeyPatch) -> None:
    listing = {"artifacts": [{"created_at": "2026-10-05T12:00:00Z", "workflow_run": {"id": 5}, "expired": False}]}

    def get_json(path: str) -> Any:
        if path.startswith(f"repos/{REPO}/actions/artifacts"):
            return listing
        return _target_run("release/1.0")

    def no_download(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("an untrusted run must not be downloaded")

    monkeypatch.setattr(github, "get_json", get_json)
    monkeypatch.setattr(github, "get_paginated", lambda path: [])
    monkeypatch.setattr(github.subprocess, "run", no_download)
    assert github.latest_state(REPO, 7) is None


BEFORE_RETARGET = "2026-10-07T22:00:00Z"
RETARGET = "2026-10-07T23:00:00Z"
AFTER_RETARGET = "2026-10-07T23:05:42Z"


def _retarget() -> datetime:
    return datetime(2026, 10, 7, 23, 0, tzinfo=UTC)


def test_trusted_run_rejects_a_pull_request_target_run_started_before_the_retarget() -> None:
    early = _target_run(created_at=BEFORE_RETARGET)
    assert not github.trusted_run(early, REPO, PR, _always, _retarget())
    assert github.trusted_run(_target_run(created_at=AFTER_RETARGET), REPO, PR, _always, _retarget())
    assert github.trusted_run(early, REPO, PR, _always, None)


@pytest.mark.parametrize("created_at", [None, "", "not a time"])
def test_trusted_run_rejects_an_unreadable_start_time_once_retargeted(created_at: Any) -> None:
    run = _target_run(created_at=created_at)
    assert not github.trusted_run(run, REPO, PR, _always, _retarget())


def test_a_retarget_does_not_affect_events_that_run_develop_code() -> None:
    assert github.trusted_run(_run(created_at=BEFORE_RETARGET), REPO, PR, _always, _retarget())


def test_base_changed_at_takes_the_latest_base_change(monkeypatch: pytest.MonkeyPatch) -> None:
    paths: list[str] = []

    def paginated(path: str) -> list[Any]:
        paths.append(path)
        return [
            {"event": "labeled", "created_at": "2026-10-07T23:30:00Z"},
            {"event": "base_ref_changed", "created_at": BEFORE_RETARGET},
            {"event": "base_ref_changed", "created_at": RETARGET},
        ]

    monkeypatch.setattr(github, "get_paginated", paginated)
    assert github.base_changed_at(REPO, 7) == _retarget()
    assert paths == [f"repos/{REPO}/issues/7/timeline?per_page=100"]


def test_base_changed_at_is_none_without_a_base_change(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "get_paginated", lambda path: [{"event": "labeled", "created_at": RETARGET}])
    assert github.base_changed_at(REPO, 7) is None


def test_base_changed_at_refuses_an_unreadable_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github, "get_paginated", lambda path: [{"event": "base_ref_changed", "created_at": "?"}])
    with pytest.raises(github.GitHubError):
        github.base_changed_at(REPO, 7)


def _state_listing(run_id: int) -> dict[str, Any]:
    return {"artifacts": [{"created_at": "2026-10-07T23:10:00Z", "workflow_run": {"id": run_id}, "expired": False}]}


def _no_download(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    raise AssertionError("an untrusted run must not be downloaded")


def test_latest_state_skips_a_pull_request_target_run_started_before_a_retarget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def get_json(path: str) -> Any:
        if path.startswith(f"repos/{REPO}/actions/artifacts"):
            return _state_listing(5)
        return _target_run(created_at=BEFORE_RETARGET)

    monkeypatch.setattr(github, "get_json", get_json)
    monkeypatch.setattr(github, "get_paginated", lambda path: [{"event": "base_ref_changed", "created_at": RETARGET}])
    monkeypatch.setattr(github.subprocess, "run", _no_download)
    assert github.latest_state(REPO, 7) is None


def test_latest_state_fails_closed_when_the_timeline_cannot_be_read(monkeypatch: pytest.MonkeyPatch) -> None:
    def get_json(path: str) -> Any:
        if path.startswith(f"repos/{REPO}/actions/artifacts"):
            return _state_listing(5)
        return _target_run()

    def broken(path: str) -> list[Any]:
        raise github.GitHubError("HTTP 502")

    monkeypatch.setattr(github, "get_json", get_json)
    monkeypatch.setattr(github, "get_paginated", broken)
    monkeypatch.setattr(github.subprocess, "run", _no_download)
    assert github.latest_state(REPO, 7) is None


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
        {"resolved": False, "path": "a.py", "author": "benchbox-oracle", "author_type": "Bot", "body": "**High**: A"},
        {"resolved": True, "path": "b.py", "author": None, "author_type": None, "body": ""},
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
    comment = {"author": {"__typename": "Bot", "login": author} if author else None, "body": body}
    return {"isResolved": resolved, "path": path, "comments": {"nodes": [comment]}}
