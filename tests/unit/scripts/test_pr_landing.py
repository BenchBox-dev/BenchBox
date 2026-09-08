"""Tests for revision/readiness/queue/follow-up landing transactions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("pr_landing", SCRIPTS / "pr_landing.py")
assert spec is not None and spec.loader is not None
landing = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = landing
spec.loader.exec_module(landing)

HEAD = "a" * 40
OTHER = "b" * 40


class FakeRun:
    """Scripted gh stand-in; records every invocation for hold-safety audits."""

    def __init__(self, responses: list[tuple[int, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> tuple[int, str]:
        self.calls.append(cmd)
        rc, payload = self.responses.pop(0)
        return rc, payload if isinstance(payload, str) else json.dumps(payload)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "T"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "f.txt").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    bare = path.parent / (path.name + "-origin.git")
    subprocess.run(["git", "init", "--bare", "-q", str(bare)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "branch", "--set-upstream-to=origin/main", "main"], cwd=path, check=True, capture_output=True
    )
    return path


def _identity(repo: Path, head: str = HEAD) -> landing.GitIdentity:
    return landing.GitIdentity(
        repo=str(repo), branch="feat/x", worktree=str(repo), head=head, base=OTHER, upstream="origin/main"
    )


def _green_checks(head: str = HEAD) -> list[dict]:
    return [
        {
            "name": name,
            "head_sha": head,
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-09-08T00:00:00Z",
        }
        for name in landing.REQUIRED_CONTEXTS
    ]


def _evidence(head: str = HEAD, **over: object) -> landing.ReadyEvidence:
    base = {
        "expected_head": head,
        "review_decision": "APPROVED",
        "dispositions_complete": True,
        "check_runs": _green_checks(head),
    }
    base.update(over)
    return landing.ReadyEvidence(**base)  # type: ignore[arg-type]


def test_resolve_pr_refuses_cross_branch_match() -> None:
    run = FakeRun([(0, [{"number": 9, "headRefName": "feat/other", "headRefOid": HEAD}])])
    with pytest.raises(landing.WrongPR):
        landing.resolve_pr(run, "o/r", "feat/x")


def test_resolve_pr_returns_none_when_absent() -> None:
    assert landing.resolve_pr(FakeRun([(0, [])]), "o/r", "feat/x") is None


def test_withdraw_disables_and_reverifies() -> None:
    run = FakeRun(
        [
            (0, {"number": 3, "state": "OPEN", "autoMergeRequest": {"id": "x"}, "labels": []}),
            (0, {}),
            (0, {"autoMergeRequest": None}),
        ]
    )
    assert landing.withdraw_readiness(run, "o/r", 3)["verified"] is True


def test_withdraw_on_merged_pr_stops_with_race() -> None:
    run = FakeRun([(0, {"number": 3, "state": "MERGED"})])
    with pytest.raises(landing.MergedRace):
        landing.withdraw_readiness(run, "o/r", 3)


def test_withdraw_never_touches_hold_labels() -> None:
    run = FakeRun(
        [(0, {"number": 3, "state": "OPEN", "autoMergeRequest": None, "labels": [{"name": "no-auto-merge"}]})]
    )
    landing.withdraw_readiness(run, "o/r", 3)
    joined = [" ".join(call) for call in run.calls]
    assert not any("add-label" in c or "remove-label" in c or "--label" in c for c in joined)


def test_ready_all_green(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert landing.ready_failures(_identity(repo, head), head, _evidence(head), repo) == []


def test_ready_rejects_late_review_unpublished_and_stale_checks(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "late.txt").write_text("review feedback arriving")
    failures = landing.ready_failures(
        _identity(repo, head),
        head,
        _evidence(
            head, review_decision="CHANGES_REQUESTED", dispositions_complete=False, check_runs=_green_checks(OTHER)
        ),
        repo,
    )
    assert any("unpublished work" in f for f in failures)
    assert any("CHANGES_REQUESTED" in f for f in failures)
    assert any("dispositions" in f for f in failures)
    assert any("not expected head" in f for f in failures)


def test_ready_holds_soundness_without_approval(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    failures = landing.ready_failures(
        _identity(repo, head), head, _evidence(head, hold_labels=["no-auto-merge"], soundness_paths_changed=True), repo
    )
    assert any("no-auto-merge" in f for f in failures)
    assert any("soundness" in f for f in failures)
    ok = landing.ready_failures(
        _identity(repo, head), head, _evidence(head, soundness_paths_changed=True, maintainer_approved=True), repo
    )
    assert ok == []


def test_enqueue_refuses_moved_head() -> None:
    run = FakeRun([])
    with pytest.raises(landing.LandingError, match="moved"):
        landing.enqueue_pr(run, "o/r", 3, HEAD, OTHER)
    assert run.calls == []


def test_enqueue_arms_on_stable_head() -> None:
    run = FakeRun([(0, "")])
    assert landing.enqueue_pr(run, "o/r", 3, HEAD, HEAD)["enqueued"] is True
    assert "--auto" in run.calls[0]


def test_batch_binding_requires_ancestors_and_quiescence(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    member = {"id": "A", "head": head}
    batch = {
        "batch_id": "b",
        "members": [member],
        "owner_generation": 1,
        "integration_head": head,
        "active_writers": [],
    }
    assert landing.check_batch_binding(repo, batch, head) == []
    assert landing.check_batch_binding(repo, {**batch, "active_writers": ["w"]}, head) != []
    assert landing.check_batch_binding(repo, {**batch, "members": [{"id": "B", "head": "c" * 40}]}, head) != []
    assert landing.check_batch_binding(repo, {**batch, "integration_head": OTHER}, head) != []


def test_stale_base_policy_matrix() -> None:
    assert landing.stale_base_decision(queue_verified=True, conflict=False) == "publish-without-refresh"
    assert landing.stale_base_decision(queue_verified=False, conflict=False) == "require-current"
    assert landing.stale_base_decision(queue_verified=True, conflict=True) == "resolve-conflict-first"


def test_followup_roundtrip_and_resume(tmp_path: Path) -> None:
    state = landing.FollowupState(
        owner="o", session="s", scope="pr", pr=1, head=HEAD, phase="queue", next_action="watch queue"
    )
    path = landing.record_followup(tmp_path, "k", state)
    assert path.is_file()
    assert landing.resume_followup(landing.load_followup(tmp_path, "k")) == {
        "status": "queue",
        "next_action": "watch queue",
    }
    assert landing.load_followup(tmp_path, "missing") is None


def test_followup_never_reports_done_from_emptiness() -> None:
    assert landing.resume_followup(landing.FollowupState(owner="o", session="s", scope="pr"))["status"] == "unknown"
    assert landing.resume_followup(landing.FollowupState(owner="o", session="s", scope="pr", terminal="merged")) == {
        "status": "merged",
        "next_action": "",
    }


def test_retry_bounds() -> None:
    state = landing.FollowupState(owner="o", session="s", scope="pr", head=HEAD)
    assert landing.allow_retry(state, "rerun", HEAD)["allowed"] is True
    assert landing.allow_retry(state, "rerun", OTHER)["allowed"] is False
    assert landing.allow_retry(state, "requeue", HEAD)["allowed"] is True
    spent = landing.FollowupState(owner="o", session="s", scope="pr", head=HEAD, attempts=1, reentries=1)
    assert landing.allow_retry(spent, "rerun", HEAD)["allowed"] is False
    assert landing.allow_retry(spent, "requeue", HEAD)["allowed"] is False
