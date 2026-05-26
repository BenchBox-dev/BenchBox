"""Tests for the PR review follow-up orchestrator."""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Sequence

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "pr_review_followups"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


pr_review_followups = _load_script()


class RecordingRunner:
    def __init__(
        self,
        responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] | None = None,
        *,
        scripted: dict[tuple[str, ...], list[subprocess.CompletedProcess[str]]] | None = None,
    ) -> None:
        self.commands: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.responses = responses or {}
        # Per-call queue keyed by argv tuple. Earlier entries are consumed first;
        # once exhausted, the runner falls back to `responses` then to a 0-rc
        # default. Patch 2 needs this so the same argv (`git commit -m ...`) can
        # return rc=1 once and rc=0 the next time.
        self.scripted = {key: list(values) for key, values in (scripted or {}).items()}
        self.cwd = Path.cwd()

    def run(self, args: Sequence[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        argv = list(args)
        self.commands.append(argv)
        self.inputs.append(input_text)
        key = tuple(argv)
        if key in self.scripted and self.scripted[key]:
            return self.scripted[key].pop(0)
        if key in self.responses:
            return self.responses[key]
        return subprocess.CompletedProcess(argv, 0, "", "")


def _pr():
    return pr_review_followups.PullRequest(
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
    return pr_review_followups.ReviewComment(
        id=comment_id,
        body=body,
        path="benchbox/example.py",
        html_url=f"https://github.com/joeharris76/BenchBox/pull/123#discussion_r{comment_id}",
        user_login=user_login,
        created_at=created_at,
        in_reply_to_id=in_reply_to_id,
    )


def _issue_comment(
    comment_id: int,
    *,
    user_login: str = "chatgpt-codex-connector[bot]",
    created_at: str = "2026-05-04T11:00:00Z",
    body: str = "ordinary comment",
):
    return pr_review_followups.IssueComment(
        id=comment_id,
        body=body,
        html_url=f"https://github.com/joeharris76/BenchBox/pull/123#issuecomment-{comment_id}",
        user_login=user_login,
        created_at=created_at,
    )


def test_pending_comments_skip_action_marker_replies_and_post_merge_comments() -> None:
    action_reply = _comment(
        2,
        user_login="joeharris76",
        in_reply_to_id=1,
        body=f"<!-- {pr_review_followups.ACTION_MARKER}: comment_id=1 --> done",
    )
    comments = [
        _comment(1),
        action_reply,
        _comment(3),
        _comment(4, created_at="2026-05-04T12:30:00Z"),
        _comment(5, user_login="other-reviewer"),
    ]

    pending = pr_review_followups.pending_comments_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    assert [item.comment.id for item in pending] == [3]


def test_action_marker_match_requires_html_comment_at_start_of_line() -> None:
    """Substring matching let unrelated quotes silently kill future sweeps.

    The strict matcher only accepts the marker inside an HTML comment that
    starts at the beginning of a line — the shape `build_reply_body` posts.
    """
    quoted_marker_reply = _comment(
        2,
        user_login="joeharris76",
        in_reply_to_id=1,
        body=(
            "Discussion: I noticed the script uses the marker "
            f"`{pr_review_followups.ACTION_MARKER}` to dedupe. "
            "We should document this somewhere."
        ),
    )
    real_marker_reply = _comment(
        4,
        user_login="joeharris76",
        in_reply_to_id=3,
        body=(
            f"<!-- {pr_review_followups.ACTION_MARKER}: pr=123 comment_id=3 -->\n"
            "Follow-up sweep actioned this Codex review comment."
        ),
    )
    comments = [_comment(1), quoted_marker_reply, _comment(3), real_marker_reply]

    pending = pr_review_followups.pending_comments_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    # comment 1 is still pending because the quoted-marker reply doesn't
    # match; comment 3 is skipped because the real marker reply does.
    assert [item.comment.id for item in pending] == [1]


def test_usage_limit_retry_needed_when_latest_limit_comment_has_no_later_trigger() -> None:
    comments = [
        _issue_comment(
            10,
            body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT,
            created_at="2026-05-04T10:00:00Z",
        ),
        _issue_comment(11, user_login="joeharris76", body="maintenance note", created_at="2026-05-04T10:05:00Z"),
    ]

    retry = pr_review_followups.usage_limit_review_retry_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    assert retry is not None
    assert retry.usage_comment.id == 10


def test_usage_limit_retry_tracks_later_trigger_as_awaiting_review_result() -> None:
    comments = [
        _issue_comment(
            10,
            body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT,
            created_at="2026-05-04T10:00:00Z",
        ),
        _issue_comment(
            11,
            user_login="joeharris76",
            body=pr_review_followups.CODEX_REVIEW_TRIGGER_BODY,
            created_at="2026-05-04T10:05:00Z",
        ),
    ]

    retry = pr_review_followups.usage_limit_review_retry_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    assert retry is not None
    assert retry.usage_comment.id == 10
    assert retry.trigger_comment is not None
    assert retry.trigger_comment.id == 11
    assert retry.needs_trigger is False


def test_usage_limit_retry_skips_later_review_result() -> None:
    comments = [
        _issue_comment(
            10,
            body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT,
            created_at="2026-05-04T10:00:00Z",
        ),
        _issue_comment(
            11,
            body=f"\n{pr_review_followups.CODEX_REVIEW_RESULT_MARKERS[0]}\n\nFinding text",
            created_at="2026-05-04T10:05:00Z",
        ),
    ]

    retry = pr_review_followups.usage_limit_review_retry_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    assert retry is None


def test_usage_limit_retry_skips_later_no_findings_review_result() -> None:
    comments = [
        _issue_comment(
            10,
            body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT,
            created_at="2026-05-04T10:00:00Z",
        ),
        _issue_comment(
            11,
            body="Codex Review: Didn't find any major issues.",
            created_at="2026-05-04T10:05:00Z",
        ),
    ]

    retry = pr_review_followups.usage_limit_review_retry_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    assert retry is None


def test_prompt_carries_completed_sweep_patterns() -> None:
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(10), replies=())

    prompt = pr_review_followups.build_executor_prompt(pending, repo="joeharris76/BenchBox", base="develop")

    assert "Do not commit, push, open a PR, or reply on GitHub" in prompt
    assert "Historical DONE-item verification commands should stay executable" in prompt
    assert "_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml" in prompt
    assert "_project/audits/pr-review-sweep-template.md" in prompt


def test_prompt_template_file_exists_and_renders_comment_metadata() -> None:
    template_path = pr_review_followups.PROMPT_TEMPLATE_PATH
    assert template_path.exists(), f"prompt template file missing at {template_path}"

    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(77), replies=())
    prompt = pr_review_followups.build_executor_prompt(pending, repo="joeharris76/BenchBox", base="develop")

    assert "Comment id: 77" in prompt
    assert "Path: benchbox/example.py" in prompt
    assert "joeharris76/BenchBox" in prompt


def test_reply_body_contains_skip_marker_and_disposition() -> None:
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(11), replies=())
    result = pr_review_followups.ActionResult(
        pending=pending,
        disposition="fixed",
        summary="Disposition: fixed\nEvidence: updated the current code and ran tests.",
    )

    body = pr_review_followups.build_reply_body(result, branch="feat/codex-followups")

    assert pr_review_followups.ACTION_MARKER in body
    assert "comment_id=11" in body
    assert "Disposition: fixed" in body
    assert "Future sweeps skip comments" in body
    # The reply body itself must match the strict marker matcher so the
    # *next* sweep recognizes its own previous reply.
    assert pr_review_followups.ACTION_MARKER_REGEX.search(body)


def test_trigger_usage_limit_review_retry_posts_codex_review_comment() -> None:
    runner = RecordingRunner()
    retry = pr_review_followups.UsageLimitReviewRetry(
        pr=_pr(),
        usage_comment=_issue_comment(99, body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT),
    )

    pr_review_followups.trigger_usage_limit_review_retry(
        runner,
        repo="joeharris76/BenchBox",
        retry=retry,
    )

    assert runner.commands == [
        [
            "gh",
            "pr",
            "comment",
            "123",
            "--repo",
            "joeharris76/BenchBox",
            "--body",
            pr_review_followups.CODEX_REVIEW_TRIGGER_BODY,
        ]
    ]


def test_trigger_usage_limit_review_retry_retries_transient_gh_failure_then_succeeds() -> None:
    transient = subprocess.CompletedProcess([], 1, "", "gh: HTTP 503: Service Unavailable\n")
    success = subprocess.CompletedProcess([], 0, "", "")
    retry = pr_review_followups.UsageLimitReviewRetry(
        pr=_pr(),
        usage_comment=_issue_comment(99, body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT),
    )
    command = (
        "gh",
        "pr",
        "comment",
        "123",
        "--repo",
        "joeharris76/BenchBox",
        "--body",
        pr_review_followups.CODEX_REVIEW_TRIGGER_BODY,
    )
    runner = RecordingRunner(scripted={command: [transient, success]})
    sleeps: list[float] = []

    pr_review_followups.trigger_usage_limit_review_retry(
        runner,
        repo="joeharris76/BenchBox",
        retry=retry,
        sleeper=sleeps.append,
    )

    assert runner.commands == [list(command), list(command)]
    assert sleeps == [1]


def test_submit_branch_guard_refuses_protected_branches() -> None:
    with pytest.raises(RuntimeError, match="Claim a feature worktree"):
        pr_review_followups.ensure_action_branch("develop", no_submit=False)

    pr_review_followups.ensure_action_branch("develop", no_submit=True)


def test_stage_paths_uses_explicit_paths_not_git_add_all() -> None:
    runner = RecordingRunner()

    pr_review_followups.stage_paths(runner, ["Makefile", "_project/scripts/pr_review_followups.py"])

    assert runner.commands == [
        ["git", "add", "--", "Makefile", "_project/scripts/pr_review_followups.py"],
    ]


def test_check_executor_version_accepts_supported_release() -> None:
    runner = RecordingRunner(
        responses={
            ("codex", "--version"): subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 0.128.0\n", "")
        }
    )

    parsed = pr_review_followups.check_executor_version(runner)

    assert parsed == (0, 128, 0)


def test_check_executor_version_rejects_too_old_release() -> None:
    runner = RecordingRunner(
        responses={
            ("codex", "--version"): subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 0.10.0\n", "")
        }
    )

    with pytest.raises(RuntimeError, match="below the required"):
        pr_review_followups.check_executor_version(runner)


def test_check_executor_version_surfaces_missing_binary() -> None:
    class MissingBinaryRunner(RecordingRunner):
        def run(self, args, input_text=None):  # type: ignore[override]
            self.commands.append(list(args))
            raise FileNotFoundError("codex")

    runner = MissingBinaryRunner()

    with pytest.raises(RuntimeError, match="Executor binary `codex` not found"):
        pr_review_followups.check_executor_version(runner)


def test_run_executor_for_comment_uses_config_override_for_approval_policy() -> None:
    """The legacy `--ask-for-approval` flag was dropped in codex-cli >= 0.20.

    The orchestrator must use `-c approval_policy=<mode>` so it works against
    current and future codex releases.
    """
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(50), replies=())
    runner = RecordingRunner()

    result = pr_review_followups.run_executor_for_comment(
        runner,
        pending,
        repo="joeharris76/BenchBox",
        base="develop",
        executor_model=None,
        executor_sandbox="workspace-write",
        executor_approval="never",
    )

    executor_calls = [cmd for cmd in runner.commands if cmd and cmd[0] == "codex"]
    assert executor_calls, "expected at least one executor invocation"
    executor_argv = executor_calls[0]
    assert "--ask-for-approval" not in executor_argv
    assert "-c" in executor_argv
    assert "approval_policy=never" in executor_argv
    assert result.disposition == "no-current-action"  # RecordingRunner produces no diff


def test_run_executor_for_comment_treats_clean_local_commit_as_fixed() -> None:
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(51), replies=())
    runner = RecordingRunner(
        scripted={
            ("git", "rev-parse", "HEAD"): [
                subprocess.CompletedProcess(["git", "rev-parse", "HEAD"], 0, "before-sha\n", ""),
                subprocess.CompletedProcess(["git", "rev-parse", "HEAD"], 0, "after-sha\n", ""),
            ],
            ("git", "status", "--porcelain"): [
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, "", ""),
                subprocess.CompletedProcess(["git", "status", "--porcelain"], 0, "", ""),
            ],
        }
    )

    result = pr_review_followups.run_executor_for_comment(
        runner,
        pending,
        repo="joeharris76/BenchBox",
        base="develop",
        executor_model=None,
        executor_sandbox="workspace-write",
        executor_approval="never",
    )

    assert result.disposition == "fixed"


def test_commit_message_for_result_includes_pr_and_comment_id() -> None:
    pending = pr_review_followups.PendingComment(
        pr=_pr(), comment=_comment(101, body="[P1] Tighten the merge guard"), replies=()
    )
    result = pr_review_followups.ActionResult(pending=pending, disposition="fixed", summary="ok")

    message = pr_review_followups.commit_message_for_result(result)

    assert message.startswith("fix(pr-followup):")
    assert "PR #123" in message
    assert "comment 101" in message
    assert "Source: " in message


def test_run_action_loop_commits_before_replying(monkeypatch, tmp_path) -> None:
    """A crash between the executor run and the reply must not leave a phantom
    actioned thread on GitHub. The order is: executor → commit → reply.
    """
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "commit.gpgsign", "false"], check=True)
    (repo_root / "README").write_text("ok\n")
    subprocess.run(["git", "-C", str(repo_root), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "branch", "-M", "develop"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-q", "-b", "chore/test"], check=True)
    # Pretend origin/develop is the same SHA as the seed commit so
    # local_commit_count returns 0 at start.
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/develop", head], check=True)

    # Fake codex shim that writes a deterministic file to simulate a fix.
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    codex_shim = fake_bin / "codex"
    codex_shim.write_text(
        textwrap.dedent(
            """
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${1:-}" == "--version" ]]; then
              echo "codex-cli 0.128.0"
              exit 0
            fi
            # exec subcommand: write a fix file inside the cwd given via --cd.
            cd_dir="."
            for ((i=1; i<=$#; i++)); do
              if [[ "${!i}" == "--cd" ]]; then
                next=$((i+1))
                cd_dir="${!next}"
              fi
            done
            mkdir -p "$cd_dir"
            echo "codex-fix" > "$cd_dir/codex-fix.txt"
            cat <<'OUT'
            Disposition: fixed
            Evidence: created codex-fix.txt
            Verification: cat codex-fix.txt
            OUT
            """
        ).strip()
        + "\n"
    )
    codex_shim.chmod(codex_shim.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}")

    pending_pr = pr_review_followups.PullRequest(
        number=42, title="t", merged_at="2026-05-04T12:00:00Z", url="https://example/42"
    )
    pending_comment = pr_review_followups.ReviewComment(
        id=999,
        body="[P1] do the thing",
        path="codex-fix.txt",
        html_url="https://example/42#999",
        user_login="chatgpt-codex-connector[bot]",
        created_at="2026-05-04T10:00:00Z",
    )
    pending_item = pr_review_followups.PendingComment(pr=pending_pr, comment=pending_comment, replies=())

    side_effect_log: list[str] = []

    monkeypatch.setattr(pr_review_followups, "resolve_repo", lambda runner, repo: "joeharris76/BenchBox")
    monkeypatch.setattr(
        pr_review_followups,
        "discover_pending_comments",
        lambda runner, **_: [pending_item],
    )

    real_commit = pr_review_followups.commit_changes_for_result

    def trace_commit(runner, result):
        side_effect_log.append("commit")
        return real_commit(runner, result)

    def trace_reply(runner, *, repo, result, branch):
        side_effect_log.append("reply")
        # Don't actually call gh; just record.

    def trace_finalize(runner, **kwargs):
        side_effect_log.append("finalize")

    monkeypatch.setattr(pr_review_followups, "commit_changes_for_result", trace_commit)
    monkeypatch.setattr(pr_review_followups, "reply_to_comment", trace_reply)
    monkeypatch.setattr(pr_review_followups, "finalize_changes", trace_finalize)

    runner = pr_review_followups.CommandRunner(repo_root)
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--no-submit",
            "--no-usage-limit-review-retry",
        ]
    )
    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert side_effect_log == ["commit", "reply", "finalize"]

    # Per-comment commit landed before reply ran.
    log_out = subprocess.run(
        ["git", "-C", str(repo_root), "log", "--oneline"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert "comment 999" in log_out


def test_run_action_loop_triggers_usage_limit_review_retry(monkeypatch) -> None:
    retry = pr_review_followups.UsageLimitReviewRetry(
        pr=_pr(),
        usage_comment=_issue_comment(99, body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT),
    )
    finalize_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pr_review_followups, "check_executor_version", lambda runner: (0, 128, 0))
    monkeypatch.setattr(pr_review_followups, "discover_pending_comments", lambda runner, **_: [])
    monkeypatch.setattr(pr_review_followups, "discover_usage_limit_review_retries", lambda runner, **_: [retry])
    monkeypatch.setattr(
        pr_review_followups,
        "finalize_changes",
        lambda runner, **kwargs: finalize_calls.append(kwargs),
    )

    runner = RecordingRunner()
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--no-submit",
        ]
    )

    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert [cmd for cmd in runner.commands if cmd[:3] == ["gh", "pr", "comment"]] == [
        [
            "gh",
            "pr",
            "comment",
            "123",
            "--repo",
            "joeharris76/BenchBox",
            "--body",
            pr_review_followups.CODEX_REVIEW_TRIGGER_BODY,
        ]
    ]
    assert finalize_calls == [
        {
            "base_ref": "origin/develop",
            "commit_message": args.commit_message,
            "no_submit": True,
        }
    ]


def test_run_action_loop_caps_usage_limit_review_retries_with_max_comments(monkeypatch) -> None:
    retries = [
        pr_review_followups.UsageLimitReviewRetry(
            pr=pr_review_followups.PullRequest(
                number=number,
                title=f"Example merged PR {number}",
                merged_at="2026-05-04T12:00:00Z",
                url=f"https://github.com/joeharris76/BenchBox/pull/{number}",
            ),
            usage_comment=_issue_comment(number, body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT),
        )
        for number in (123, 124, 125)
    ]
    finalize_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pr_review_followups, "check_executor_version", lambda runner: (0, 128, 0))
    monkeypatch.setattr(pr_review_followups, "discover_pending_comments", lambda runner, **_: [])
    monkeypatch.setattr(pr_review_followups, "discover_usage_limit_review_retries", lambda runner, **_: retries)
    monkeypatch.setattr(
        pr_review_followups,
        "finalize_changes",
        lambda runner, **kwargs: finalize_calls.append(kwargs),
    )

    runner = RecordingRunner()
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--max-comments",
            "1",
            "--no-submit",
        ]
    )

    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert [cmd for cmd in runner.commands if cmd[:3] == ["gh", "pr", "comment"]] == [
        [
            "gh",
            "pr",
            "comment",
            "123",
            "--repo",
            "joeharris76/BenchBox",
            "--body",
            pr_review_followups.CODEX_REVIEW_TRIGGER_BODY,
        ]
    ]
    assert finalize_calls == [
        {
            "base_ref": "origin/develop",
            "commit_message": args.commit_message,
            "no_submit": True,
        }
    ]


def test_run_action_loop_spends_max_comments_on_pending_before_usage_limit_retries(monkeypatch) -> None:
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(321), replies=())
    retry = pr_review_followups.UsageLimitReviewRetry(
        pr=pr_review_followups.PullRequest(
            number=124,
            title="Example merged PR 124",
            merged_at="2026-05-04T12:00:00Z",
            url="https://github.com/joeharris76/BenchBox/pull/124",
        ),
        usage_comment=_issue_comment(99, body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT),
    )
    executor_calls: list[int] = []
    finalize_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pr_review_followups, "check_executor_version", lambda runner: (0, 128, 0))
    monkeypatch.setattr(pr_review_followups, "discover_pending_comments", lambda runner, **_: [pending])
    monkeypatch.setattr(pr_review_followups, "discover_usage_limit_review_retries", lambda runner, **_: [retry])
    monkeypatch.setattr(
        pr_review_followups,
        "run_executor_for_comment",
        lambda runner, item, **_: (
            executor_calls.append(item.comment.id)
            or pr_review_followups.ActionResult(pending=item, disposition="no-current-action", summary="skip")
        ),
    )
    monkeypatch.setattr(pr_review_followups, "commit_changes_for_result", lambda runner, result: None)
    monkeypatch.setattr(
        pr_review_followups,
        "finalize_changes",
        lambda runner, **kwargs: finalize_calls.append(kwargs),
    )

    runner = RecordingRunner()
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--max-comments",
            "1",
            "--no-reply",
            "--no-submit",
        ]
    )

    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert executor_calls == [321]
    assert [cmd for cmd in runner.commands if cmd[:3] == ["gh", "pr", "comment"]] == []
    assert finalize_calls == [
        {
            "base_ref": "origin/develop",
            "commit_message": args.commit_message,
            "no_submit": True,
        }
    ]


def test_run_action_loop_does_not_duplicate_inflight_usage_limit_retry(monkeypatch) -> None:
    retry = pr_review_followups.UsageLimitReviewRetry(
        pr=_pr(),
        usage_comment=_issue_comment(99, body=pr_review_followups.CODEX_USAGE_LIMIT_REVIEW_TEXT),
        trigger_comment=_issue_comment(
            100,
            user_login="joeharris76",
            body=pr_review_followups.CODEX_REVIEW_TRIGGER_BODY,
            created_at="2026-05-04T11:05:00Z",
        ),
    )
    finalize_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pr_review_followups, "check_executor_version", lambda runner: (0, 128, 0))
    monkeypatch.setattr(pr_review_followups, "discover_pending_comments", lambda runner, **_: [])
    monkeypatch.setattr(pr_review_followups, "discover_usage_limit_review_retries", lambda runner, **_: [retry])
    monkeypatch.setattr(
        pr_review_followups,
        "finalize_changes",
        lambda runner, **kwargs: finalize_calls.append(kwargs),
    )

    runner = RecordingRunner()
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--no-submit",
        ]
    )

    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert [cmd for cmd in runner.commands if cmd[:3] == ["gh", "pr", "comment"]] == []
    assert finalize_calls == [
        {
            "base_ref": "origin/develop",
            "commit_message": args.commit_message,
            "no_submit": True,
        }
    ]


# ---------------------------------------------------------------------------
# Patch 1 — reply_to_comment retries transient gh api failures
# ---------------------------------------------------------------------------


def _reply_args(repo: str, pr_number: int, comment_id: int) -> tuple[str, ...]:
    return (
        "gh",
        "api",
        "-X",
        "POST",
        f"repos/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
    )


def test_reply_to_comment_retries_transient_gh_failure_then_succeeds() -> None:
    """A flaky `gh api` (network drop, 5xx) must be retried, not crash the sweep."""
    transient = subprocess.CompletedProcess(
        [],
        1,
        "",
        "error connecting to api.github.com\ncheck your internet connection or https://githubstatus.com\n",
    )
    success = subprocess.CompletedProcess([], 0, "", "")
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(33), replies=())
    result = pr_review_followups.ActionResult(pending=pending, disposition="fixed", summary="ok")

    sleeps: list[float] = []

    class GhScriptedRunner(RecordingRunner):
        def __init__(self) -> None:
            super().__init__()
            self.gh_responses = [transient, success]

        def run(self, args, input_text=None):  # type: ignore[override]
            argv = list(args)
            self.commands.append(argv)
            self.inputs.append(input_text)
            if (
                argv[:4] == ["gh", "api", "-X", "POST"]
                and "/replies" in (argv[4] if len(argv) > 4 else "")
                and self.gh_responses
            ):
                return self.gh_responses.pop(0)
            return subprocess.CompletedProcess(argv, 0, "", "")

    runner = GhScriptedRunner()

    pr_review_followups.reply_to_comment(
        runner,
        repo="joeharris76/BenchBox",
        result=result,
        branch="fix/sample",
        sleeper=sleeps.append,
    )

    reply_calls = [cmd for cmd in runner.commands if cmd[:4] == ["gh", "api", "-X", "POST"]]
    assert len(reply_calls) == 2, "transient failure should be retried exactly once before success"
    assert sleeps == [1], "first retry must use the 1s backoff slot"
    assert not runner.gh_responses, "scripted responses should be exhausted"


def test_reply_to_comment_does_not_retry_permanent_4xx() -> None:
    """A 404 (comment deleted upstream) must fail loud on the first attempt."""
    permanent = subprocess.CompletedProcess(
        [],
        1,
        "",
        "gh: HTTP 404: Not Found (https://api.github.com/repos/x/y/pulls/1/comments/1/replies)\n",
    )
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(34), replies=())
    result = pr_review_followups.ActionResult(pending=pending, disposition="fixed", summary="ok")

    sleeps: list[float] = []

    class GhPermFailRunner(RecordingRunner):
        def run(self, args, input_text=None):  # type: ignore[override]
            argv = list(args)
            self.commands.append(argv)
            self.inputs.append(input_text)
            if argv[:4] == ["gh", "api", "-X", "POST"]:
                return permanent
            return subprocess.CompletedProcess(argv, 0, "", "")

    runner = GhPermFailRunner()

    with pytest.raises(pr_review_followups.CommandError, match="HTTP 404"):
        pr_review_followups.reply_to_comment(
            runner,
            repo="joeharris76/BenchBox",
            result=result,
            branch="fix/sample",
            sleeper=sleeps.append,
        )

    reply_calls = [cmd for cmd in runner.commands if cmd[:4] == ["gh", "api", "-X", "POST"]]
    assert len(reply_calls) == 1, "permanent 4xx must not retry"
    assert sleeps == [], "no backoff sleep should have happened"


def test_is_transient_gh_failure_classification() -> None:
    """Sanity-check the discriminator covers the flagged classes and nothing else."""
    assert pr_review_followups._is_transient_gh_failure("error connecting to api.github.com")
    assert pr_review_followups._is_transient_gh_failure("check your internet connection or https://githubstatus.com")
    assert pr_review_followups._is_transient_gh_failure("gh: HTTP 503: Service Unavailable")
    assert pr_review_followups._is_transient_gh_failure("gh: HTTP 429: Too Many Requests")
    assert not pr_review_followups._is_transient_gh_failure("gh: HTTP 404: Not Found")
    assert not pr_review_followups._is_transient_gh_failure("gh: HTTP 422: Validation failed")
    assert not pr_review_followups._is_transient_gh_failure("")


# ---------------------------------------------------------------------------
# Patch 2 — commit_changes_for_result retries when a hook auto-fixes paths
# ---------------------------------------------------------------------------


def test_commit_changes_for_result_retries_after_hook_autofix() -> None:
    """ruff-format reformats a staged file, commit aborts, second commit succeeds."""
    pending = pr_review_followups.PendingComment(
        pr=_pr(), comment=_comment(55, body="[P1] Add the missing test"), replies=()
    )
    result = pr_review_followups.ActionResult(pending=pending, disposition="fixed", summary="ok")
    expected_message = pr_review_followups.commit_message_for_result(result)
    commit_argv = ("git", "commit", "-m", expected_message)

    target_path = "tests/unit/example.py"
    diff_name = subprocess.CompletedProcess([], 0, f"{target_path}\n", "")
    diff_cached_name_empty = subprocess.CompletedProcess([], 0, "", "")
    ls_files = subprocess.CompletedProcess([], 0, f"{target_path}\n", "")
    diff_cached_after_stage = subprocess.CompletedProcess([], 0, f"{target_path}\n", "")
    commit_hook_failure = subprocess.CompletedProcess(
        [],
        1,
        "",
        "ruff-format..............................................................Failed\n"
        "- hook id: ruff-format\n"
        f"- files were modified by this hook\n\nReformatted: {target_path}\n",
    )
    porcelain_after_hook = subprocess.CompletedProcess([], 0, f"AM {target_path}\n", "")
    commit_success = subprocess.CompletedProcess([], 0, "ok\n", "")

    runner = RecordingRunner(
        scripted={
            ("git", "diff", "--name-only"): [diff_name],
            ("git", "diff", "--cached", "--name-only"): [
                # First call: from git_changed_paths — nothing pre-staged.
                diff_cached_name_empty,
                # Second call: post-stage_paths to verify staged content.
                diff_cached_after_stage,
            ],
            ("git", "ls-files", "--others", "--exclude-standard"): [ls_files],
            commit_argv: [commit_hook_failure, commit_success],
            ("git", "status", "--porcelain"): [porcelain_after_hook],
        }
    )

    landed = pr_review_followups.commit_changes_for_result(runner, result)

    assert landed is True
    commit_calls = [tuple(cmd) for cmd in runner.commands if tuple(cmd) == commit_argv]
    assert len(commit_calls) == 2, "hook auto-fix must trigger exactly one retry commit"
    add_calls = [cmd for cmd in runner.commands if cmd[:3] == ["git", "add", "--"]]
    assert len(add_calls) == 2, "second `git add` must re-stage the hook-modified path"
    assert add_calls[1] == ["git", "add", "--", target_path]


def test_commit_changes_for_result_does_not_retry_genuine_hook_failure() -> None:
    """If the hook fails without auto-fixing the staged paths, fail loud."""
    pending = pr_review_followups.PendingComment(pr=_pr(), comment=_comment(56, body="[P1] do something"), replies=())
    result = pr_review_followups.ActionResult(pending=pending, disposition="fixed", summary="ok")
    expected_message = pr_review_followups.commit_message_for_result(result)
    commit_argv = ("git", "commit", "-m", expected_message)

    target_path = "tests/unit/example.py"
    diff_name = subprocess.CompletedProcess([], 0, f"{target_path}\n", "")
    diff_cached_empty = subprocess.CompletedProcess([], 0, "", "")
    ls_files = subprocess.CompletedProcess([], 0, "", "")
    diff_cached_after_stage = subprocess.CompletedProcess([], 0, f"{target_path}\n", "")
    # Genuine pre-commit failure (e.g. a test runner detected a real bug):
    # commit fails, but porcelain shows no fresh work-tree mods.
    commit_failure = subprocess.CompletedProcess(
        [], 1, "", "test-runner..............................................................Failed\n"
    )
    porcelain_clean = subprocess.CompletedProcess([], 0, "", "")

    runner = RecordingRunner(
        scripted={
            ("git", "diff", "--name-only"): [diff_name],
            ("git", "diff", "--cached", "--name-only"): [
                diff_cached_empty,
                diff_cached_after_stage,
            ],
            ("git", "ls-files", "--others", "--exclude-standard"): [ls_files],
            commit_argv: [commit_failure],
            ("git", "status", "--porcelain"): [porcelain_clean],
        }
    )

    with pytest.raises(pr_review_followups.CommandError):
        pr_review_followups.commit_changes_for_result(runner, result)

    commit_calls = [tuple(cmd) for cmd in runner.commands if tuple(cmd) == commit_argv]
    assert len(commit_calls) == 1, "genuine hook failure must not retry"


def test_porcelain_paths_with_worktree_mods_parses_added_modified_and_renamed() -> None:
    porcelain = (
        "AM tests/unit/example.py\nM  src/module.py\n M docs/notes.md\n?? new_file.txt\nR  old_name.py -> new_name.py\n"
    )

    paths = pr_review_followups._porcelain_paths_with_worktree_mods(porcelain)

    # AM, " M", "??" all have non-space work-tree column -> included.
    # "M  " has a space work-tree column -> excluded (purely staged).
    # "R  " rename has space work-tree column -> excluded.
    assert paths == {"tests/unit/example.py", "docs/notes.md", "new_file.txt"}


# ---------------------------------------------------------------------------
# Patch 3 — --resume skips comments already committed locally
# ---------------------------------------------------------------------------


def test_resume_skips_comments_already_committed_locally(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "commit.gpgsign", "false"], check=True)
    (repo_root / "README").write_text("ok\n")
    subprocess.run(["git", "-C", str(repo_root), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "branch", "-M", "develop"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/develop", head], check=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-q", "-b", "fix/pr-review-resume"], check=True)
    # A per-comment commit from a prior crashed sweep: PR #999, comment 12345.
    (repo_root / "fix.txt").write_text("prior fix\n")
    subprocess.run(["git", "-C", str(repo_root), "add", "fix.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "commit",
            "-q",
            "-m",
            "fix(pr-followup): PR #999 comment 12345 — recovered fix",
        ],
        check=True,
    )

    already_pr = pr_review_followups.PullRequest(
        number=999, title="prior", merged_at="2026-05-01T00:00:00Z", url="https://example/999"
    )
    already_comment = pr_review_followups.ReviewComment(
        id=12345,
        body="[P1] already done",
        path="fix.txt",
        html_url="https://example/999#12345",
        user_login="chatgpt-codex-connector[bot]",
        created_at="2026-04-30T00:00:00Z",
    )
    fresh_pr = pr_review_followups.PullRequest(
        number=777, title="new", merged_at="2026-05-04T00:00:00Z", url="https://example/777"
    )
    fresh_comment = pr_review_followups.ReviewComment(
        id=88888,
        body="[P1] still to do",
        path="other.txt",
        html_url="https://example/777#88888",
        user_login="chatgpt-codex-connector[bot]",
        created_at="2026-05-03T00:00:00Z",
    )
    pending_already = pr_review_followups.PendingComment(pr=already_pr, comment=already_comment, replies=())
    pending_fresh = pr_review_followups.PendingComment(pr=fresh_pr, comment=fresh_comment, replies=())

    seen_executor_calls: list[int] = []

    monkeypatch.setattr(pr_review_followups, "resolve_repo", lambda runner, repo: "joeharris76/BenchBox")
    monkeypatch.setattr(
        pr_review_followups,
        "discover_pending_comments",
        lambda runner, **_: [pending_already, pending_fresh],
    )
    monkeypatch.setattr(pr_review_followups, "check_executor_version", lambda runner: (0, 128, 0))
    monkeypatch.setattr(
        pr_review_followups,
        "run_executor_for_comment",
        lambda runner, item, **_: (
            seen_executor_calls.append(item.comment.id)
            or pr_review_followups.ActionResult(pending=item, disposition="no-current-action", summary="skip")
        ),
    )
    monkeypatch.setattr(pr_review_followups, "commit_changes_for_result", lambda runner, result: False)
    monkeypatch.setattr(pr_review_followups, "reply_to_comment", lambda runner, **_: None)
    monkeypatch.setattr(pr_review_followups, "finalize_changes", lambda runner, **_: None)

    runner = pr_review_followups.CommandRunner(repo_root)
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--no-submit",
            "--resume",
            "--no-usage-limit-review-retry",
        ]
    )

    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert seen_executor_calls == [88888], (
        "comment 12345 was already committed locally and must be skipped; "
        "only the unrelated comment 88888 should reach run_executor_for_comment"
    )


def test_resume_finalizes_when_all_pending_comments_are_already_committed(monkeypatch, tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "commit.gpgsign", "false"], check=True)
    (repo_root / "README").write_text("ok\n")
    subprocess.run(["git", "-C", str(repo_root), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "branch", "-M", "develop"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/develop", head], check=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-q", "-b", "fix/pr-review-resume"], check=True)
    (repo_root / "fix.txt").write_text("prior fix\n")
    subprocess.run(["git", "-C", str(repo_root), "add", "fix.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "commit",
            "-q",
            "-m",
            "fix(pr-followup): PR #999 comment 12345 — recovered fix",
        ],
        check=True,
    )

    already_pr = pr_review_followups.PullRequest(
        number=999, title="prior", merged_at="2026-05-01T00:00:00Z", url="https://example/999"
    )
    already_comment = pr_review_followups.ReviewComment(
        id=12345,
        body="[P1] already done",
        path="fix.txt",
        html_url="https://example/999#12345",
        user_login="chatgpt-codex-connector[bot]",
        created_at="2026-04-30T00:00:00Z",
    )
    pending_already = pr_review_followups.PendingComment(pr=already_pr, comment=already_comment, replies=())

    executor_calls: list[int] = []
    finalize_calls: list[dict[str, object]] = []

    monkeypatch.setattr(pr_review_followups, "resolve_repo", lambda runner, repo: "joeharris76/BenchBox")
    monkeypatch.setattr(
        pr_review_followups,
        "discover_pending_comments",
        lambda runner, **_: [pending_already],
    )
    monkeypatch.setattr(pr_review_followups, "check_executor_version", lambda runner: (0, 128, 0))
    monkeypatch.setattr(
        pr_review_followups,
        "run_executor_for_comment",
        lambda runner, item, **_: executor_calls.append(item.comment.id),
    )
    monkeypatch.setattr(pr_review_followups, "reply_to_comment", lambda runner, **_: None)
    monkeypatch.setattr(
        pr_review_followups,
        "finalize_changes",
        lambda runner, **kwargs: finalize_calls.append(kwargs),
    )

    runner = pr_review_followups.CommandRunner(repo_root)
    args = pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--no-submit",
            "--resume",
            "--no-usage-limit-review-retry",
        ]
    )

    rc = pr_review_followups.run_action_loop(args, runner)

    assert rc == 0
    assert executor_calls == []
    assert finalize_calls == [
        {
            "base_ref": "origin/develop",
            "commit_message": args.commit_message,
            "no_submit": True,
        }
    ]


def test_discover_locally_committed_pairs_matches_per_comment_subjects(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    subprocess.run(["git", "init", "-q", str(repo_root)], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "t@e.com"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "T"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "commit.gpgsign", "false"], check=True)
    (repo_root / "f").write_text("a\n")
    subprocess.run(["git", "-C", str(repo_root), "add", "f"], check=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", "init"], check=True)
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/develop", head], check=True)
    for subject in (
        "fix(pr-followup): PR #1 comment 100 — first",
        "chore: unrelated commit",
        "fix(pr-followup): PR #2 comment 200 — second",
    ):
        path = repo_root / f"x_{subject[-5:].strip()}.txt"
        path.write_text(subject)
        subprocess.run(["git", "-C", str(repo_root), "add", path.name], check=True)
        subprocess.run(["git", "-C", str(repo_root), "commit", "-q", "-m", subject], check=True)

    runner = pr_review_followups.CommandRunner(repo_root)
    pairs = pr_review_followups.discover_locally_committed_pairs(runner, "origin/develop")

    assert pairs == {(1, 100), (2, 200)}
