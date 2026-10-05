from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from _project.scripts.oracle_reviewers import cli, github
from _project.scripts.oracle_reviewers.retry import State

from .conftest import POLICY_PATH

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO = "BenchBox-dev/BenchBox"
HEAD = "a" * 40
BASE = "b" * 40
DIFF = "diff --git a/x b/x\n"


def _pull(**over: Any) -> dict[str, Any]:
    pull = {
        "number": 7,
        "state": "open",
        "draft": False,
        "labels": [{"name": "author-family:codex"}],
        "base": {"ref": "develop", "sha": BASE},
        "head": {"sha": HEAD, "repo": {"full_name": REPO}},
    }
    pull.update(over)
    return pull


class FakeGitHub:
    def __init__(self, pull: dict[str, Any], files: list[dict[str, Any]], state: State | None = None) -> None:
        self.pull = pull
        self.files = files
        self.state = state
        self.dispatched: list[int] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(github, "get_json", lambda path: self.pull)
        monkeypatch.setattr(github, "get_paginated", self._paginated)
        monkeypatch.setattr(github, "get_diff", lambda repo, pr: DIFF)
        monkeypatch.setattr(github, "latest_state", lambda repo, pr: self.state)
        monkeypatch.setattr(github, "dispatch", lambda repo, workflow, pr: self.dispatched.append(pr))

    def _paginated(self, path: str) -> list[dict[str, Any]]:
        return [self.pull] if path.startswith(f"repos/{REPO}/pulls?") else self.files


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, event_name: str, event: dict[str, Any], ref: str) -> Path:
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event), encoding="utf-8")
    output = tmp_path / "out.txt"
    output.write_text("", encoding="utf-8")
    for key, value in {
        "GITHUB_REPOSITORY": REPO,
        "GITHUB_RUN_ID": "99",
        "GITHUB_EVENT_NAME": event_name,
        "GITHUB_EVENT_PATH": str(event_path),
        "GITHUB_REF": ref,
        "GITHUB_OUTPUT": str(output),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    return output


def _plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fake: FakeGitHub,
    *,
    event_name: str = "pull_request_target",
    event: dict[str, Any] | None = None,
    ref: str = "refs/heads/develop",
) -> tuple[int, dict[str, str], dict[str, Any]]:
    fake.install(monkeypatch)
    output = _env(monkeypatch, tmp_path, event_name, event or {"action": "synchronize"}, ref)
    out_dir = tmp_path / "plan"
    code = cli.main(["plan", "--policy", str(POLICY_PATH), "--pr", "7", "--out", str(out_dir)])
    values = dict(line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines())
    plan = json.loads((out_dir / "plan.json").read_text(encoding="utf-8")) if (out_dir / "plan.json").is_file() else {}
    return code, values, plan


SOUNDNESS = [{"filename": "benchbox/core/equivalence/checker.py", "additions": 4, "deletions": 1}]


def test_soundness_pr_plans_a_review_with_a_private_brief(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS))
    assert code == 0
    assert values["decision"] == "review" and values["post"] == "true" and values["head_sha"] == HEAD
    assert plan["tier"] == "medium-high"
    assert plan["excluded_families"] == ["codex"]
    assert [item["name"] for item in plan["chain"]] == ["sonnet", "sol", "luna", "muse", "agy"]
    assert plan["brief_mode"] == "inline"
    brief = tmp_path / "plan" / "brief.md"
    assert stat.S_IMODE(brief.stat().st_mode) == 0o600
    assert HEAD in brief.read_text(encoding="utf-8")


def test_non_soundness_pr_posts_success_without_reviewers(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    files = [{"filename": "README.md", "additions": 1, "deletions": 0}]
    _, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), files))
    assert values["decision"] == "success" and values["post"] == "true"
    assert plan["chain"] == []


def test_fork_pr_never_reaches_a_reviewer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pull = _pull(head={"sha": HEAD, "repo": {"full_name": "someone/BenchBox"}})
    _, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(pull, SOUNDNESS))
    assert values["decision"] == "fork" and values["post"] == "true"
    assert plan["decision_reason"] == "fork: owner review"
    assert plan["chain"] == []
    assert not (tmp_path / "plan" / "brief.md").exists()


@pytest.mark.parametrize(
    ("pull", "reason"),
    [
        (_pull(state="closed"), "not open"),
        (_pull(base={"ref": "release", "sha": BASE}), "does not target develop"),
        (_pull(draft=True), "draft"),
    ],
)
def test_guards_skip_without_posting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pull: dict[str, Any], reason: str
) -> None:
    _, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(pull, SOUNDNESS))
    assert values["decision"] == "skip" and values["post"] == "false"
    assert reason in plan["decision_reason"]


def test_stale_event_head_is_left_to_the_newer_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    event = {"action": "synchronize", "pull_request": {"head": {"sha": "c" * 40}}}
    _, values, _ = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS), event=event)
    assert values["decision"] == "skip"


def test_comment_run_resolves_the_head_through_the_api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    event = {"action": "created", "issue": {"number": 7, "pull_request": {}}, "comment": {"body": "/oracle-review"}}
    _, values, plan = _plan(
        monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS), event_name="issue_comment", event=event
    )
    assert values["decision"] == "review"
    assert plan["head_sha"] == HEAD
    assert plan["manual"] is True


def test_dispatch_outside_develop_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    code, values, _ = _plan(
        monkeypatch,
        tmp_path,
        FakeGitHub(_pull(), SOUNDNESS),
        event_name="workflow_dispatch",
        event={"inputs": {"pr": "7"}},
        ref="refs/heads/feature",
    )
    assert code == 2
    assert values == {}


def test_comment_rerun_after_a_decisive_result_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = State(7, HEAD, "success", datetime.now(UTC) - timedelta(hours=3))
    _, values, plan = _plan(
        monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS, state), event_name="issue_comment", event={}
    )
    assert values["decision"] == "skip" and values["post"] == "false"
    assert "already has a success result" in plan["decision_reason"]


def test_pending_pool_reset_is_carried_into_the_plan(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    later = datetime.now(UTC) + timedelta(hours=2)
    earlier = datetime.now(UTC) - timedelta(hours=1)
    state = State(7, "c" * 40, "pending", earlier, (), {"claude": later, "codex": earlier})
    _, _, plan = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS, state))
    assert plan["pool_blocked_until"] == {"claude": later.isoformat()}


def test_invalid_pr_number_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    FakeGitHub(_pull(), SOUNDNESS).install(monkeypatch)
    _env(monkeypatch, tmp_path, "workflow_dispatch", {}, "refs/heads/develop")
    with pytest.raises(SystemExit, match="invalid pull request number"):
        cli.main(["plan", "--policy", str(POLICY_PATH), "--pr", "7; rm -rf /", "--out", str(tmp_path / "p")])


def test_sweep_dispatches_only_due_pending_prs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    due = State(7, HEAD, "pending", datetime.now(UTC) - timedelta(hours=2), pending_cause="all-absent")
    fake = FakeGitHub(_pull(), SOUNDNESS, due)
    fake.install(monkeypatch)
    _env(monkeypatch, tmp_path, "schedule", {}, "refs/heads/develop")
    assert cli.main(["sweep", "--policy", str(POLICY_PATH)]) == 0
    assert fake.dispatched == [7]
    fresh = FakeGitHub(_pull(), SOUNDNESS, State(7, HEAD, "pending", datetime.now(UTC), pending_cause="all-absent"))
    fresh.install(monkeypatch)
    assert cli.main(["sweep", "--policy", str(POLICY_PATH)]) == 0
    assert fresh.dispatched == []
