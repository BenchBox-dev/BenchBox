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
