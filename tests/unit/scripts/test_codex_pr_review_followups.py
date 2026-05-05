"""Tests for the Codex PR review follow-up orchestrator."""

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
    def __init__(self, responses: dict[tuple[str, ...], subprocess.CompletedProcess[str]] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.responses = responses or {}
        self.cwd = Path.cwd()

    def run(self, args: Sequence[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        argv = list(args)
        self.commands.append(argv)
        self.inputs.append(input_text)
        key = tuple(argv)
        if key in self.responses:
            return self.responses[key]
        return subprocess.CompletedProcess(argv, 0, "", "")


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
            f"`{codex_pr_review_followups.ACTION_MARKER}` to dedupe. "
            "We should document this somewhere."
        ),
    )
    real_marker_reply = _comment(
        4,
        user_login="joeharris76",
        in_reply_to_id=3,
        body=(
            f"<!-- {codex_pr_review_followups.ACTION_MARKER}: pr=123 comment_id=3 -->\n"
            "Follow-up sweep actioned this Codex review comment."
        ),
    )
    comments = [_comment(1), quoted_marker_reply, _comment(3), real_marker_reply]

    pending = codex_pr_review_followups.pending_comments_for_pr(
        _pr(),
        comments,
        author_logins={"chatgpt-codex-connector[bot]"},
    )

    # comment 1 is still pending because the quoted-marker reply doesn't
    # match; comment 3 is skipped because the real marker reply does.
    assert [item.comment.id for item in pending] == [1]


def test_prompt_carries_completed_sweep_patterns() -> None:
    pending = codex_pr_review_followups.PendingComment(pr=_pr(), comment=_comment(10), replies=())

    prompt = codex_pr_review_followups.build_codex_prompt(pending, repo="joeharris76/BenchBox", base="develop")

    assert "Do not commit, push, open a PR, or reply on GitHub" in prompt
    assert "Historical DONE-item verification commands should stay executable" in prompt
    assert "_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml" in prompt
    assert "_project/audits/codex-weekly-sweep-template.md" in prompt


def test_prompt_template_file_exists_and_renders_comment_metadata() -> None:
    template_path = codex_pr_review_followups.PROMPT_TEMPLATE_PATH
    assert template_path.exists(), f"prompt template file missing at {template_path}"

    pending = codex_pr_review_followups.PendingComment(pr=_pr(), comment=_comment(77), replies=())
    prompt = codex_pr_review_followups.build_codex_prompt(pending, repo="joeharris76/BenchBox", base="develop")

    assert "Comment id: 77" in prompt
    assert "Path: benchbox/example.py" in prompt
    assert "joeharris76/BenchBox" in prompt


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
    # The reply body itself must match the strict marker matcher so the
    # *next* sweep recognizes its own previous reply.
    assert codex_pr_review_followups.ACTION_MARKER_REGEX.search(body)


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


def test_check_codex_version_accepts_supported_release() -> None:
    runner = RecordingRunner(
        responses={
            ("codex", "--version"): subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 0.128.0\n", "")
        }
    )

    parsed = codex_pr_review_followups.check_codex_version(runner)

    assert parsed == (0, 128, 0)


def test_check_codex_version_rejects_too_old_release() -> None:
    runner = RecordingRunner(
        responses={
            ("codex", "--version"): subprocess.CompletedProcess(["codex", "--version"], 0, "codex-cli 0.10.0\n", "")
        }
    )

    with pytest.raises(RuntimeError, match="below the required"):
        codex_pr_review_followups.check_codex_version(runner)


def test_check_codex_version_surfaces_missing_binary() -> None:
    class MissingBinaryRunner(RecordingRunner):
        def run(self, args, input_text=None):  # type: ignore[override]
            self.commands.append(list(args))
            raise FileNotFoundError("codex")

    runner = MissingBinaryRunner()

    with pytest.raises(RuntimeError, match="codex CLI not found"):
        codex_pr_review_followups.check_codex_version(runner)


def test_run_codex_for_comment_uses_config_override_for_approval_policy() -> None:
    """The legacy `--ask-for-approval` flag was dropped in codex-cli >= 0.20.

    The orchestrator must use `-c approval_policy=<mode>` so it works against
    current and future codex releases.
    """
    pending = codex_pr_review_followups.PendingComment(pr=_pr(), comment=_comment(50), replies=())
    runner = RecordingRunner()

    result = codex_pr_review_followups.run_codex_for_comment(
        runner,
        pending,
        repo="joeharris76/BenchBox",
        base="develop",
        codex_model=None,
        codex_sandbox="workspace-write",
        codex_approval="never",
    )

    codex_calls = [cmd for cmd in runner.commands if cmd and cmd[0] == "codex"]
    assert codex_calls, "expected at least one codex invocation"
    codex_argv = codex_calls[0]
    assert "--ask-for-approval" not in codex_argv
    assert "-c" in codex_argv
    assert "approval_policy=never" in codex_argv
    assert result.disposition == "no-current-action"  # RecordingRunner produces no diff


def test_commit_message_for_result_includes_pr_and_comment_id() -> None:
    pending = codex_pr_review_followups.PendingComment(
        pr=_pr(), comment=_comment(101, body="[P1] Tighten the merge guard"), replies=()
    )
    result = codex_pr_review_followups.ActionResult(pending=pending, disposition="fixed", summary="ok")

    message = codex_pr_review_followups.commit_message_for_result(result)

    assert message.startswith("fix(codex-followup):")
    assert "PR #123" in message
    assert "comment 101" in message
    assert "Source: " in message


def test_run_action_loop_commits_before_replying(monkeypatch, tmp_path) -> None:
    """A crash between the codex run and the reply must not leave a phantom
    actioned thread on GitHub. The order is: codex → commit → reply.
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

    pending_pr = codex_pr_review_followups.PullRequest(
        number=42, title="t", merged_at="2026-05-04T12:00:00Z", url="https://example/42"
    )
    pending_comment = codex_pr_review_followups.ReviewComment(
        id=999,
        body="[P1] do the thing",
        path="codex-fix.txt",
        html_url="https://example/42#999",
        user_login="chatgpt-codex-connector[bot]",
        created_at="2026-05-04T10:00:00Z",
    )
    pending_item = codex_pr_review_followups.PendingComment(pr=pending_pr, comment=pending_comment, replies=())

    side_effect_log: list[str] = []

    monkeypatch.setattr(codex_pr_review_followups, "resolve_repo", lambda runner, repo: "joeharris76/BenchBox")
    monkeypatch.setattr(
        codex_pr_review_followups,
        "discover_pending_comments",
        lambda runner, **_: [pending_item],
    )

    real_commit = codex_pr_review_followups.commit_changes_for_result

    def trace_commit(runner, result):
        side_effect_log.append("commit")
        return real_commit(runner, result)

    def trace_reply(runner, *, repo, result, branch):
        side_effect_log.append("reply")
        # Don't actually call gh; just record.

    def trace_finalize(runner, **kwargs):
        side_effect_log.append("finalize")

    monkeypatch.setattr(codex_pr_review_followups, "commit_changes_for_result", trace_commit)
    monkeypatch.setattr(codex_pr_review_followups, "reply_to_comment", trace_reply)
    monkeypatch.setattr(codex_pr_review_followups, "finalize_changes", trace_finalize)

    runner = codex_pr_review_followups.CommandRunner(repo_root)
    args = codex_pr_review_followups.build_parser().parse_args(
        [
            "run",
            "--repo",
            "joeharris76/BenchBox",
            "--base",
            "develop",
            "--no-submit",
        ]
    )
    rc = codex_pr_review_followups.run_action_loop(args, runner)

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
