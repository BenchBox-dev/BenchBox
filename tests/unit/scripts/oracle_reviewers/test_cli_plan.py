from __future__ import annotations

import json
import stat
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from _project.scripts.oracle_reviewers import cli, github
from _project.scripts.oracle_reviewers.dedup import fingerprint
from _project.scripts.oracle_reviewers.retry import Reviewed, State

from .conftest import POLICY_PATH

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO = "BenchBox-dev/BenchBox"
HEAD = "a" * 40
BASE = "b" * 40
DIFF = "diff --git a/x b/x\n"
MERGE_BASE = "e" * 40


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
    def __init__(
        self,
        pull: dict[str, Any],
        files: list[dict[str, Any]],
        state: State | None = None,
        threads: Sequence[dict[str, Any]] | None = (),
        diff: str = DIFF,
    ) -> None:
        self.pull = pull
        self.files = files
        self.state = state
        self.threads = None if threads is None else list(threads)
        self.diff = diff
        self.diff_reads = 0
        self.merge_base: str | None = MERGE_BASE
        self.dispatched: list[int] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(github, "get_json", self._json)
        monkeypatch.setattr(github, "get_paginated", self._paginated)
        monkeypatch.setattr(github, "get_diff", self._diff)
        monkeypatch.setattr(github, "review_threads", self._threads)
        monkeypatch.setattr(github, "latest_state", lambda repo, pr: self.state)
        monkeypatch.setattr(github, "dispatch", lambda repo, workflow, pr: self.dispatched.append(pr))

    def _json(self, path: str) -> dict[str, Any]:
        if "/compare/" in path:
            return {"merge_base_commit": {"sha": self.merge_base}}
        return self.pull

    def _threads(self, repo: str, pr: int) -> list[dict[str, Any]]:
        if self.threads is None:
            raise github.GitHubError("threads unavailable")
        return self.threads

    def _diff(self, repo: str, pr: int) -> str:
        self.diff_reads += 1
        return self.diff

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


@pytest.mark.parametrize(
    "pull",
    [_pull(draft=True), _pull(head={"sha": HEAD, "repo": {"full_name": "someone/BenchBox"}})],
    ids=["draft", "fork"],
)
def test_sweep_skips_draft_and_fork_prs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, pull: dict[str, Any]) -> None:
    due = State(7, HEAD, "pending", datetime.now(UTC) - timedelta(hours=2), pending_cause="all-absent")
    fake = FakeGitHub(pull, SOUNDNESS, due)
    looked_up: list[int] = []
    fake.install(monkeypatch)
    monkeypatch.setattr(github, "latest_state", lambda repo, pr: looked_up.append(pr) or due)
    _env(monkeypatch, tmp_path, "schedule", {}, "refs/heads/develop")
    assert cli.main(["sweep", "--policy", str(POLICY_PATH)]) == 0
    assert fake.dispatched == []
    assert looked_up == []


CHECKER = "benchbox/core/equivalence/checker.py"
CAPTURE = "benchbox/core/expected_results/registry.py"
TWO_FILES = [
    {"filename": CHECKER, "additions": 4, "deletions": 1, "sha": "1" * 40},
    {"filename": CAPTURE, "additions": 2, "deletions": 0, "sha": "2" * 40},
]
TWO_FILE_DIFF = (
    f"diff --git a/{CHECKER} b/{CHECKER}\n--- a/{CHECKER}\n+++ b/{CHECKER}\n@@ -1,1 +1,2 @@\n a\n+checker change\n"
    f"diff --git a/{CAPTURE} b/{CAPTURE}\n--- a/{CAPTURE}\n+++ b/{CAPTURE}\n@@ -1,1 +1,2 @@\n a\n+capture change\n"
)
OLD_HEAD = "c" * 40


def _basis(tier: str = "medium-high", merge_base: str = MERGE_BASE) -> str:
    chain = {"medium-high": "sonnet,sol,luna,muse,agy", "very-high": "opus,sol"}[tier]
    blocking = {"medium-high": "Critical,High", "very-high": "Critical,High,Medium"}[tier]
    return f"{tier}|{blocking}|{chain}|{merge_base}"


def _reviewed_state(files: dict[str, str], basis: str = _basis(), outcome: str = "failure") -> State:
    reviewed = Reviewed(OLD_HEAD, basis, outcome, files)
    return State(7, OLD_HEAD, outcome, datetime.now(UTC) - timedelta(hours=1), reviewed=reviewed)


def test_push_without_soundness_change_carries_the_result_without_a_reviewer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    files = [*TWO_FILES, {"filename": "README.md", "additions": 1, "deletions": 0, "sha": "9" * 40}]
    fake = FakeGitHub(_pull(), files, _reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}))
    _, values, plan = _plan(monkeypatch, tmp_path, fake)
    assert values["decision"] == "carry" and values["post"] == "true"
    assert plan["reviewed_head"] == OLD_HEAD
    assert plan["chain"] == []
    assert fake.diff_reads == 0
    assert not (tmp_path / "plan" / "brief.md").exists()


def test_push_touching_one_file_reviews_only_that_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    state = _reviewed_state({CHECKER: "1" * 40, CAPTURE: "0" * 40}, outcome="success")
    fake = FakeGitHub(_pull(), TWO_FILES, state, diff=TWO_FILE_DIFF)
    _, values, plan = _plan(monkeypatch, tmp_path, fake)
    assert values["decision"] == "review"
    assert plan["scope"] == "changed" and plan["reviewed_head"] == OLD_HEAD
    assert plan["reviewed_files"] == {CHECKER: "1" * 40, CAPTURE: "2" * 40}
    brief = (tmp_path / "plan" / "brief.md").read_text(encoding="utf-8")
    assert "capture change" in brief and "checker change" not in brief
    assert f"since head {OLD_HEAD} was reviewed" in brief
    assert (tmp_path / "plan" / "diff.patch").read_text(encoding="utf-8") == TWO_FILE_DIFF


@pytest.mark.parametrize(
    ("state", "event"),
    [
        (_reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}, _basis("very-high")), {"action": "synchronize"}),
        (
            _reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}, _basis(merge_base="f" * 40)),
            {"action": "synchronize"},
        ),
        (_reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}, "medium-high"), {"action": "synchronize"}),
        (_reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}), {"action": "edited", "changes": {"base": {}}}),
        (None, {"action": "synchronize"}),
        (_reviewed_state({CHECKER: "1" * 40, CAPTURE: "0" * 40}), {"action": "synchronize"}),
        (_reviewed_state({CHECKER: "1" * 40, "gone.py": "3" * 40}, outcome="success"), {"action": "synchronize"}),
    ],
    ids=[
        "tier-changed",
        "merge-base-moved",
        "older-state",
        "base-changed",
        "no-state",
        "after-failure",
        "file-left-the-diff",
    ],
)
def test_full_review_when_the_last_review_does_not_cover_this_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, state: State | None, event: dict[str, Any]
) -> None:
    fake = FakeGitHub(_pull(), TWO_FILES, state, diff=TWO_FILE_DIFF)
    _, values, plan = _plan(monkeypatch, tmp_path, fake, event=event)
    assert values["decision"] == "review" and plan["scope"] == "full"
    assert "checker change" in (tmp_path / "plan" / "brief.md").read_text(encoding="utf-8")


def test_open_oracle_threads_are_recorded_for_suppression(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    threads = [
        {
            "resolved": False,
            "path": CHECKER,
            "author": "benchbox-oracle",
            "author_type": "Bot",
            "body": "**High**: Drops a row",
        },
        {
            "resolved": True,
            "path": CHECKER,
            "author": "benchbox-oracle",
            "author_type": "Bot",
            "body": "**High**: Fixed",
        },
        {
            "resolved": False,
            "path": CHECKER,
            "author": "someone",
            "author_type": "User",
            "body": "**High**: Human note",
        },
    ]
    _, _, plan = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS, threads=threads))
    assert plan["open_findings"] == [fingerprint(CHECKER, "Drops a row")]


def test_unreadable_threads_suppress_nothing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), SOUNDNESS, threads=None))
    assert values["decision"] == "review" and plan["open_findings"] == []


def test_failure_is_carried_only_while_the_reviewed_files_are_unchanged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    exact = FakeGitHub(_pull(), TWO_FILES, _reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}))
    (tmp_path / "exact").mkdir()
    (tmp_path / "reverted").mkdir()
    _, values, _ = _plan(monkeypatch, tmp_path / "exact", exact)
    assert values["decision"] == "carry"
    reverted = FakeGitHub(
        _pull(), TWO_FILES[:1], _reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}), diff=TWO_FILE_DIFF
    )
    _, values, plan = _plan(monkeypatch, tmp_path / "reverted", reverted)
    assert values["decision"] == "review" and plan["scope"] == "full"


def test_manual_carry_is_recorded_as_a_retry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeGitHub(_pull(), TWO_FILES, _reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}))
    _, values, plan = _plan(monkeypatch, tmp_path, fake, event_name="issue_comment", event={})
    assert values["decision"] == "carry" and plan["manual"] is True


def test_unreadable_merge_base_gives_a_full_review(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = FakeGitHub(_pull(), TWO_FILES, _reviewed_state({CHECKER: "1" * 40, CAPTURE: "2" * 40}), diff=TWO_FILE_DIFF)
    fake.merge_base = None
    _, values, plan = _plan(monkeypatch, tmp_path, fake)
    assert values["decision"] == "review" and plan["scope"] == "full" and plan["review_basis"] == ""


def test_very_high_tier_is_never_scoped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pull = _pull(labels=[{"name": "oracle-tier:very-high"}])
    state = _reviewed_state({CHECKER: "1" * 40, CAPTURE: "0" * 40}, _basis("very-high"), outcome="success")
    _, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(pull, TWO_FILES, state, diff=TWO_FILE_DIFF))
    assert values["decision"] == "review" and plan["scope"] == "full"


def test_a_changed_file_missing_from_the_selected_diff_gives_a_full_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    quoted = TWO_FILE_DIFF.replace(f"diff --git a/{CAPTURE} b/{CAPTURE}", f'diff --git "a/{CAPTURE}" "b/{CAPTURE}"')
    state = _reviewed_state({CHECKER: "1" * 40, CAPTURE: "0" * 40}, outcome="success")
    _, values, plan = _plan(monkeypatch, tmp_path, FakeGitHub(_pull(), TWO_FILES, state, diff=quoted))
    assert values["decision"] == "review" and plan["scope"] == "full"
