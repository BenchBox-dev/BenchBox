"""Tests for the Codex PR review follow-up orchestrator."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Sequence

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "codex_pr_review_followups"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


codex_pr_review_followups = _load_script()


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: Sequence[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        del input_text
        self.commands.append(list(args))
        return subprocess.CompletedProcess(list(args), 0, "", "")


def _pr():
    return codex_pr_review_followups.PullRequest(
        number=123,
        title="Example merged PR",
        merged_at="2026-05-04T12:00:00Z",
        url="https://github.com/joeharris76/BenchBox/pull/123",
    )


def _comment(
    comment_id: int,
    *,
    user_login: str = "chatgpt-codex-connector[bot]",
    created_at: str = "2026-05-04T11:00:00Z",
    in_reply_to_id: int | None = None,
    body: str = "[P1] Fix the current behavior",
):
    return codex_pr_review_followups.ReviewComment(
        id=comment_id,
        body=body,
        path="benchbox/example.py",
        html_url=f"https://github.com/joeharris76/BenchBox/pull/123#discussion_r{comment_id}",
        user_login=user_login,
        created_at=created_at,
        in_reply_to_id=in_reply_to_id,
    )


def test_pending_comments_skip_action_marker_replies_and_post_merge_comments() -> None:
    action_reply = _comment(
        2,
        user_login="joeharris76",
        in_reply_to_id=1,
        body=f"<!-- {codex_pr_review_followups.ACTION_MARKER}: comment_id=1 --> done",
    )
    comments = [
        _comment(1),
        action_reply,
        _comment(3),
        _comment(4, created_at="2026-05-04T12:30:00Z"),
        _comment(5, user_login="other-reviewer"),
    ]

    pending = codex_pr_review_followups.pending_comments_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    assert [item.comment.id for item in pending] == [3]


def test_prompt_carries_completed_sweep_patterns() -> None:
    pending = codex_pr_review_followups.PendingComment(pr=_pr(), comment=_comment(10), replies=())

    prompt = codex_pr_review_followups.build_codex_prompt(pending, repo="joeharris76/BenchBox", base="develop")

    assert "Do not commit, push, open a PR, or reply on GitHub" in prompt
    assert "Historical DONE-item verification commands should stay executable" in prompt
    assert "_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml" in prompt
    assert "_project/audits/codex-weekly-sweep-template.md" in prompt


def test_reply_body_contains_skip_marker_and_disposition() -> None:
    pending = codex_pr_review_followups.PendingComment(pr=_pr(), comment=_comment(11), replies=())
    result = codex_pr_review_followups.ActionResult(
        pending=pending,
        disposition="fixed",
        summary="Disposition: fixed\nEvidence: updated the current code and ran tests.",
    )

    body = codex_pr_review_followups.build_reply_body(result, branch="feat/codex-followups")

    assert codex_pr_review_followups.ACTION_MARKER in body
    assert "comment_id=11" in body
    assert "Disposition: fixed" in body
    assert "Future sweeps skip comments" in body


def test_submit_branch_guard_refuses_protected_branches() -> None:
    with pytest.raises(RuntimeError, match="Claim a feature worktree"):
        codex_pr_review_followups.ensure_action_branch("develop", no_submit=False)

    codex_pr_review_followups.ensure_action_branch("develop", no_submit=True)


def test_stage_paths_uses_explicit_paths_not_git_add_all() -> None:
    runner = RecordingRunner()

    codex_pr_review_followups.stage_paths(runner, ["Makefile", "_project/scripts/codex_pr_review_followups.py"])

    assert runner.commands == [
        ["git", "add", "--", "Makefile", "_project/scripts/codex_pr_review_followups.py"],
    ]
