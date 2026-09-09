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


def test_resolve_pr_rejects_non_list_payload() -> None:
    with pytest.raises(landing.LandingError, match="non-list"):
        landing.resolve_pr(FakeRun([(0, {"message": "ok"})]), "o/r", "feat/x")


def test_followup_coerce_refuses_missing_owner(tmp_path: Path) -> None:
    with pytest.raises(landing.LandingError, match="owner"):
        landing.coerce_followup({"session": "s", "scope": "pr"})
    with pytest.raises(landing.LandingError, match="object"):
        landing.coerce_followup([])
    assert landing.load_followup(tmp_path, "absent") is None


def test_enqueue_arms_with_match_head_commit() -> None:
    run = FakeRun([(0, "")])
    assert landing.enqueue_pr(run, "o/r", 3, HEAD, HEAD)["enqueued"] is True
    assert "--match-head-commit" in run.calls[0]
    assert HEAD in run.calls[0]


def test_bound_withdraw_refuses_foreign_pr() -> None:
    owned = [{"number": 7, "headRefName": "feat/x", "headRefOid": HEAD}]
    run = FakeRun([(0, owned)])
    with pytest.raises(landing.WrongPR, match="owns PR #7"):
        landing.bound_withdraw(run, "o/r", "feat/x", 9)
    assert all("disable-auto" not in " ".join(c) for c in run.calls)


def test_bound_withdraw_allows_pre_pr_explicit_number() -> None:
    run = FakeRun(
        [
            (0, []),
            (0, {"number": 9, "state": "OPEN", "autoMergeRequest": {"enabledAt": "t"}, "labels": []}),
            (0, ""),
            (0, {"autoMergeRequest": None}),
        ]
    )
    assert landing.bound_withdraw(run, "o/r", "feat/new", 9)["withdrew"] == "auto-merge"


def test_record_followup_refuses_cross_owner_overwrite(tmp_path: Path) -> None:
    landing.record_followup(tmp_path, "k", landing.FollowupState(owner="o", session="s", scope="pr"))
    with pytest.raises(landing.LandingError, match="owned by 'o'"):
        landing.record_followup(tmp_path, "k", landing.FollowupState(owner="r", session="t", scope="pr"))
    same = landing.FollowupState(owner="o", session="s2", scope="pr")
    landing.record_followup(tmp_path, "k", same)
    assert landing.load_followup(tmp_path, "k").session == "s2"


def test_consume_retry_persists_spent_budget(tmp_path: Path) -> None:
    landing.record_followup(tmp_path, "k", landing.FollowupState(owner="o", session="s", scope="pr", head=HEAD))
    assert landing.consume_retry(tmp_path, "k", "rerun", HEAD)["allowed"] is True
    second = landing.consume_retry(tmp_path, "k", "rerun", HEAD)
    assert second["allowed"] is False and "exhausted" in second["reason"]


def _live_checks_payload(head: str, conclusion: str = "success") -> dict:
    runs = [
        {
            "name": name,
            "conclusion": conclusion,
            "head_sha": head,
            "status": "completed",
            "started_at": "2026-09-08T19:00:00Z",
        }
        for name in landing.REQUIRED_CONTEXTS
    ]
    return {"total": len(runs), "runs": runs}


def _live_pr(head: str, decision: str = "APPROVED") -> dict:
    return {
        "number": 3,
        "headRefName": "feat/x",
        "headRefOid": head,
        "labels": [],
        "reviewDecision": decision,
    }


def test_verify_evidence_live_accepts_fresh_evidence() -> None:
    run = FakeRun([(0, _live_checks_payload(HEAD))])
    landing.verify_evidence_live(run, "o/r", _live_pr(HEAD), _evidence(HEAD))


def test_verify_evidence_live_refuses_stale_check() -> None:
    stale = _live_checks_payload(HEAD)
    stale["runs"][0] = {
        "name": landing.REQUIRED_CONTEXTS[0],
        "conclusion": "failure",
        "head_sha": HEAD,
    }
    run = FakeRun([(0, stale)])
    with pytest.raises(landing.LandingError, match="live verification"):
        landing.verify_evidence_live(run, "o/r", _live_pr(HEAD), _evidence(HEAD))


def test_verify_evidence_live_refuses_decision_mismatch() -> None:
    run = FakeRun([(0, _live_checks_payload(HEAD))])
    with pytest.raises(landing.LandingError, match="review decision"):
        landing.verify_evidence_live(run, "o/r", _live_pr(HEAD, "CHANGES_REQUESTED"), _evidence(HEAD))


def test_consume_retry_allows_exactly_once_under_concurrency(tmp_path: Path) -> None:
    import threading

    landing.record_followup(tmp_path, "k", landing.FollowupState(owner="o", session="s", scope="pr", head=HEAD))
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(landing.consume_retry(tmp_path, "k", "rerun", HEAD)))
        for _ in range(4)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sum(1 for r in results if r["allowed"]) == 1


def test_rerecord_never_restores_spent_budget(tmp_path: Path) -> None:
    landing.record_followup(tmp_path, "k", landing.FollowupState(owner="o", session="s", scope="pr", head=HEAD))
    assert landing.consume_retry(tmp_path, "k", "rerun", HEAD)["allowed"] is True
    landing.record_followup(tmp_path, "k", landing.FollowupState(owner="o", session="s2", scope="pr", head=HEAD))
    assert landing.load_followup(tmp_path, "k").attempts == 1
    assert landing.consume_retry(tmp_path, "k", "rerun", HEAD)["allowed"] is False


def test_live_check_verdicts_uses_get_only_invocation() -> None:
    # gh api sends POST whenever -F/--field/--paginate flags are present, and
    # list endpoints answer GET only: a POST 404s, rc != 0, and every landing
    # arm would refuse. Pin the GET-only shape.
    run = FakeRun([(0, _live_checks_payload(HEAD))])
    landing.live_check_verdicts(run, "o/r", HEAD)
    (cmd,) = run.calls
    assert cmd[:2] == ["gh", "api"]
    assert not any(part in ("-F", "--field", "--raw-field", "--paginate") for part in cmd)
    assert cmd[2].startswith("repos/o/r/commits/") and "per_page=100" in cmd[2]


def test_verify_evidence_live_prefers_latest_run_over_stale_success() -> None:
    payload = _live_checks_payload(HEAD)
    payload["runs"].append(
        {
            "name": landing.REQUIRED_CONTEXTS[0],
            "conclusion": "failure",
            "head_sha": HEAD,
            "status": "completed",
            "started_at": "2026-09-08T20:00:00Z",
        }
    )
    payload["total"] = len(payload["runs"])
    run = FakeRun([(0, payload)])
    with pytest.raises(landing.LandingError, match="live verification"):
        landing.verify_evidence_live(run, "o/r", _live_pr(HEAD), _evidence(HEAD))
