#!/usr/bin/env python3
"""Action stale Codex web-agent review comments left on merged PRs.

The script is intentionally an orchestrator, not a static fixer. It gathers
candidate inline review comments, skips comments that already carry the
BenchBox action marker reply, asks local `codex exec` to assess and fix each
remaining finding against the current tree, replies to the source comment, and
then optionally submits one batched PR through the existing Make workflow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

DEFAULT_CODEX_AUTHORS = ("chatgpt-codex-connector[bot]", "chatgpt-codex-connector")
ACTION_MARKER = "benchbox-codex-review-followup-actioned"
DEFAULT_COMMIT_MESSAGE = "fix: address stale Codex PR review follow-ups"
MAX_REPLY_SUMMARY_CHARS = 1800


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    merged_at: str
    url: str
    head_ref_name: str | None = None


@dataclass(frozen=True)
class ReviewComment:
    id: int
    body: str
    path: str
    html_url: str
    user_login: str
    created_at: str
    diff_hunk: str = ""
    in_reply_to_id: int | None = None
    original_commit_id: str | None = None
    commit_id: str | None = None
    line: int | None = None
    original_line: int | None = None


@dataclass(frozen=True)
class PendingComment:
    pr: PullRequest
    comment: ReviewComment
    replies: tuple[ReviewComment, ...]


@dataclass(frozen=True)
class ActionResult:
    pending: PendingComment
    disposition: str
    summary: str


class CommandError(RuntimeError):
    """Raised when an external command fails."""

    def __init__(self, args: Sequence[str], result: subprocess.CompletedProcess[str]) -> None:
        output = (result.stderr or result.stdout or "").strip()
        command = " ".join(args)
        super().__init__(f"Command failed ({result.returncode}): {command}\n{output}")
        self.args_list = tuple(args)
        self.result = result


class CommandRunner:
    """Thin subprocess wrapper for production and tests."""

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, args: Sequence[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            list(args),
            cwd=self.cwd,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )


def checked(runner: CommandRunner, args: Sequence[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    result = runner.run(args, input_text=input_text)
    if result.returncode != 0:
        raise CommandError(args, result)
    return result


def parse_github_time(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_bound(value: str | None, *, end_of_day: bool = False) -> dt.datetime | None:
    if not value:
        return None
    if len(value) == 10:
        parsed_date = dt.date.fromisoformat(value)
        parsed_time = dt.time.max if end_of_day else dt.time.min
        return dt.datetime.combine(parsed_date, parsed_time, tzinfo=dt.timezone.utc)
    return parse_github_time(value)


def gh_json(runner: CommandRunner, args: Sequence[str]) -> Any:
    result = checked(runner, args)
    text = result.stdout.strip()
    if not text:
        return None
    return json.loads(text)


def gh_json_lines(runner: CommandRunner, args: Sequence[str]) -> list[dict[str, Any]]:
    result = checked(runner, args)
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        parsed = json.loads(line)
        if isinstance(parsed, dict):
            rows.append(parsed)
        else:
            raise ValueError(f"Expected JSON object from gh output, got {type(parsed).__name__}")
    return rows


def resolve_repo(runner: CommandRunner, repo: str | None) -> str:
    if repo:
        return repo
    result = checked(runner, ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"])
    resolved = result.stdout.strip()
    if not resolved:
        raise RuntimeError("Could not resolve GitHub repository from gh repo view")
    return resolved


def discover_merged_pull_requests(
    runner: CommandRunner,
    *,
    repo: str,
    base: str,
    limit: int,
    since: dt.datetime | None,
    until: dt.datetime | None,
) -> list[PullRequest]:
    raw = gh_json(
        runner,
        [
            "gh",
            "pr",
            "list",
            "--repo",
            repo,
            "--state",
            "merged",
            "--base",
            base,
            "--limit",
            str(limit),
            "--json",
            "number,title,mergedAt,url,headRefName",
        ],
    )
    if not isinstance(raw, list):
        raise ValueError("gh pr list did not return a JSON list")

    pull_requests: list[PullRequest] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        merged_at = str(item.get("mergedAt") or "")
        merged_time = parse_github_time(merged_at)
        if merged_time is None:
            continue
        if since is not None and merged_time < since:
            continue
        if until is not None and merged_time > until:
            continue
        pull_requests.append(
            PullRequest(
                number=int(item["number"]),
                title=str(item.get("title") or ""),
                merged_at=merged_at,
                url=str(item.get("url") or ""),
                head_ref_name=item.get("headRefName"),
            )
        )
    return sorted(pull_requests, key=lambda pr: pr.number)


def review_comment_from_api(item: dict[str, Any]) -> ReviewComment:
    user = item.get("user")
    user_login = user.get("login") if isinstance(user, dict) else ""
    return ReviewComment(
        id=int(item["id"]),
        body=str(item.get("body") or ""),
        path=str(item.get("path") or ""),
        html_url=str(item.get("html_url") or ""),
        user_login=str(user_login or ""),
        created_at=str(item.get("created_at") or ""),
        diff_hunk=str(item.get("diff_hunk") or ""),
        in_reply_to_id=item.get("in_reply_to_id"),
        original_commit_id=item.get("original_commit_id"),
        commit_id=item.get("commit_id"),
        line=item.get("line"),
        original_line=item.get("original_line"),
    )


def fetch_pr_review_comments(runner: CommandRunner, *, repo: str, pr_number: int) -> list[ReviewComment]:
    rows = gh_json_lines(
        runner,
        [
            "gh",
            "api",
            "--paginate",
            f"repos/{repo}/pulls/{pr_number}/comments?per_page=100",
            "--jq",
            ".[] | @json",
        ],
    )
    return [review_comment_from_api(row) for row in rows]


def has_action_marker(replies: Sequence[ReviewComment]) -> bool:
    return any(ACTION_MARKER in reply.body for reply in replies)


def comment_precedes_merge(comment: ReviewComment, pr: PullRequest) -> bool:
    comment_time = parse_github_time(comment.created_at)
    merged_time = parse_github_time(pr.merged_at)
    if comment_time is None or merged_time is None:
        return False
    return comment_time < merged_time


def pending_comments_for_pr(
    pr: PullRequest,
    comments: Sequence[ReviewComment],
    *,
    author_logins: set[str],
) -> list[PendingComment]:
    replies_by_parent: dict[int, list[ReviewComment]] = {}
    for comment in comments:
        if comment.in_reply_to_id is not None:
            replies_by_parent.setdefault(int(comment.in_reply_to_id), []).append(comment)

    pending: list[PendingComment] = []
    for comment in comments:
        if comment.in_reply_to_id is not None:
            continue
        if comment.user_login not in author_logins:
            continue
        if not comment_precedes_merge(comment, pr):
            continue
        replies = tuple(replies_by_parent.get(comment.id, []))
        if has_action_marker(replies):
            continue
        pending.append(PendingComment(pr=pr, comment=comment, replies=replies))
    return pending


def discover_pending_comments(
    runner: CommandRunner,
    *,
    repo: str,
    base: str,
    limit_prs: int,
    since: dt.datetime | None,
    until: dt.datetime | None,
    author_logins: set[str],
) -> list[PendingComment]:
    pending: list[PendingComment] = []
    pull_requests = discover_merged_pull_requests(
        runner,
        repo=repo,
        base=base,
        limit=limit_prs,
        since=since,
        until=until,
    )
    for pr in pull_requests:
        comments = fetch_pr_review_comments(runner, repo=repo, pr_number=pr.number)
        pending.extend(pending_comments_for_pr(pr, comments, author_logins=author_logins))
    return pending


def first_body_line(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:160]
    return "(empty comment)"


def print_pending_table(pending: Sequence[PendingComment]) -> None:
    if not pending:
        print("No pending Codex PR review comments found.")
        return
    print(f"{'PR':>6}  {'Comment':>12}  {'Path':<52}  Finding")
    print(f"{'-' * 6}  {'-' * 12}  {'-' * 52}  {'-' * 40}")
    for item in pending:
        path = item.comment.path[:52]
        print(f"#{item.pr.number:<5}  {item.comment.id:>12}  {path:<52}  {first_body_line(item.comment.body)}")


def git_diff(runner: CommandRunner) -> str:
    return checked(runner, ["git", "diff", "--binary"]).stdout


def git_changed_paths(runner: CommandRunner) -> list[str]:
    paths: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only"],
        ["git", "diff", "--cached", "--name-only"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        result = checked(runner, cmd)
        paths.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(paths)


def local_commit_count(runner: CommandRunner, base_ref: str) -> int:
    result = checked(runner, ["git", "rev-list", "--count", f"{base_ref}..HEAD"])
    return int(result.stdout.strip() or "0")


def current_branch(runner: CommandRunner) -> str:
    return checked(runner, ["git", "branch", "--show-current"]).stdout.strip()


def truncate_summary(text: str, limit: int = MAX_REPLY_SUMMARY_CHARS) -> str:
    normalized = textwrap.dedent(text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 15].rstrip() + "\n[truncated]"


def build_codex_prompt(item: PendingComment, *, repo: str, base: str) -> str:
    comment = item.comment
    pr = item.pr
    return textwrap.dedent(
        f"""
        You are actioning one stale Codex web-agent inline PR review comment for BenchBox.

        Source:
        - Repository: {repo}
        - Base branch: {base}
        - Merged PR: #{pr.number} {pr.title}
        - PR URL: {pr.url}
        - PR merged at: {pr.merged_at}
        - Review comment: {comment.html_url}
        - Comment id: {comment.id}
        - Path: {comment.path}
        - Line: current={comment.line}, original={comment.original_line}
        - Commit: current={comment.commit_id}, original={comment.original_commit_id}

        Required workflow:
        1. Inspect the current repository state before editing. Do not assume the old PR diff still reflects the tree.
        2. Decide whether the finding still requires action on the current branch.
        3. If a fix is still required, make the smallest coherent fix and add/update focused regression coverage.
        4. Run the narrowest relevant verification command. Use `uv run --` for Python tooling.
        5. If no fix is currently required, leave files unchanged and explain the evidence.
        6. Do not commit, push, open a PR, or reply on GitHub. The outer Make routine handles those steps.

        Carry-over patterns from the completed Codex follow-up TODOs:
        - A stale GitHub thread is not enough evidence. Verify current behavior before fixing or dismissing.
        - Some comments are already fixed by later merges; close those with concrete current-file evidence, not code churn.
        - Historical DONE-item verification commands should stay executable when the comment identifies a real command defect.
        - Comments on obsolete DONE verification commands can be closed as no-current-action only when the command is not reused
          and the current sweep/template captures the protocol hygiene lesson.
        - Cross-check related blind-spots and weakened tests when the finding is about regression coverage.
        - Prefer focused tests over broad rewrites.

        Useful local references:
        - `_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml`
        - `_project/TODO/main/active/codex-pr-review-followups-week-2026-05-03.yaml`
        - `_project/audits/codex-weekly-sweep-template.md`
        - `_project/audits/codex-thread-rescan-week-2026-05-01.md`

        Diff hunk from the original PR comment:
        ```diff
        {comment.diff_hunk}
        ```

        Codex web-agent comment body:
        ```markdown
        {comment.body}
        ```

        Final response format:
        - `Disposition: fixed` or `Disposition: no-current-action`
        - `Evidence:` one short paragraph with files/tests checked
        - `Verification:` command(s) run, or why verification was not applicable
        """
    ).strip()


def run_codex_for_comment(
    runner: CommandRunner,
    item: PendingComment,
    *,
    repo: str,
    base: str,
    codex_model: str | None,
    codex_sandbox: str,
    codex_approval: str,
) -> ActionResult:
    before = git_diff(runner)
    prompt = build_codex_prompt(item, repo=repo, base=base)
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(runner.cwd),
        "--sandbox",
        codex_sandbox,
        "--ask-for-approval",
        codex_approval,
    ]
    if codex_model:
        cmd.extend(["--model", codex_model])
    cmd.append("-")

    print(f"\n==> PR #{item.pr.number} comment {item.comment.id}: {item.comment.html_url}", flush=True)
    result = runner.run(cmd, input_text=prompt)
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode != 0:
        raise CommandError(cmd, result)

    after = git_diff(runner)
    disposition = "fixed" if after != before else "no-current-action"
    summary = result.stdout.strip() or result.stderr.strip() or f"Disposition: {disposition}"
    return ActionResult(pending=item, disposition=disposition, summary=summary)


def build_reply_body(result: ActionResult, *, branch: str) -> str:
    comment = result.pending.comment
    pr = result.pending.pr
    summary = truncate_summary(result.summary)
    return textwrap.dedent(
        f"""
        <!-- {ACTION_MARKER}: pr={pr.number} comment_id={comment.id} branch={branch} -->
        Follow-up sweep actioned this Codex review comment.

        Disposition: {result.disposition}
        Branch: `{branch}`

        Summary:
        {summary}

        Future sweeps skip comments that already have this marker reply.
        """
    ).strip()


def reply_to_comment(runner: CommandRunner, *, repo: str, result: ActionResult, branch: str) -> None:
    pr_number = result.pending.pr.number
    comment_id = result.pending.comment.id
    body = build_reply_body(result, branch=branch)
    checked(
        runner,
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repo}/pulls/{pr_number}/comments/{comment_id}/replies",
            "-f",
            f"body={body}",
        ],
    )
    print(f"Replied to PR #{pr_number} comment {comment_id}.")


def ensure_clean_start(runner: CommandRunner, *, allow_dirty: bool, base_ref: str) -> None:
    changed = git_changed_paths(runner)
    local_commits = local_commit_count(runner, base_ref)
    if (changed or local_commits) and not allow_dirty:
        joined = "\n".join(f"  - {path}" for path in changed) if changed else "  (none)"
        raise RuntimeError(
            "Refusing to start with an in-progress branch. Commit/stash unrelated work or rerun with "
            f"--allow-dirty.\nChanged paths:\n{joined}\nLocal commits ahead of {base_ref}: {local_commits}"
        )


def ensure_action_branch(branch: str, *, no_submit: bool) -> None:
    if no_submit:
        return
    if branch in {"", "develop", "main"}:
        raise RuntimeError(
            f"Refusing to action comments from branch {branch or '(detached)'} because the routine submits a PR. "
            "Claim a feature worktree first or rerun with --no-submit."
        )


def stage_paths(runner: CommandRunner, paths: Sequence[str]) -> None:
    if not paths:
        return
    checked(runner, ["git", "add", "--", *paths])


def submit_changes(
    runner: CommandRunner,
    *,
    base_ref: str,
    commit_message: str,
    no_submit: bool,
) -> None:
    paths = git_changed_paths(runner)
    commits_before = local_commit_count(runner, base_ref)
    if not paths and commits_before == 0:
        print("No file changes or local commits were produced; skipping PR submission.")
        return

    if paths:
        print("\n==> Staging changed paths")
        for path in paths:
            print(f"  {path}")
        stage_paths(runner, paths)

    print("\n==> Running pr-preflight")
    checked(runner, ["make", "pr-preflight"])

    staged_paths = checked(runner, ["git", "diff", "--cached", "--name-only"]).stdout.splitlines()
    if staged_paths:
        checked(runner, ["git", "commit", "-m", commit_message])

    if no_submit:
        print("Skipping PR submission because --no-submit was set.")
        return

    print("\n==> Opening PR through existing make pr-open flow")
    checked(runner, ["make", "pr-open"])


def run_action_loop(args: argparse.Namespace, runner: CommandRunner) -> int:
    repo = resolve_repo(runner, args.repo)
    since = parse_bound(args.since)
    until = parse_bound(args.until, end_of_day=True)
    authors = set(args.author)
    branch = ""
    if args.command == "run":
        if not args.dry_run:
            branch = current_branch(runner)
            ensure_action_branch(branch, no_submit=args.no_submit)
        ensure_clean_start(runner, allow_dirty=args.allow_dirty or args.dry_run, base_ref=f"origin/{args.base}")
    pending = discover_pending_comments(
        runner,
        repo=repo,
        base=args.base,
        limit_prs=args.limit_prs,
        since=since,
        until=until,
        author_logins=authors,
    )
    if args.max_comments > 0:
        pending = pending[: args.max_comments]

    print_pending_table(pending)
    if args.command == "list" or args.dry_run or not pending:
        return 0

    results: list[ActionResult] = []
    for item in pending:
        result = run_codex_for_comment(
            runner,
            item,
            repo=repo,
            base=args.base,
            codex_model=args.codex_model,
            codex_sandbox=args.codex_sandbox,
            codex_approval=args.codex_approval,
        )
        results.append(result)
        if not args.no_reply:
            reply_to_comment(runner, repo=repo, result=result, branch=branch)

    print(f"\nActioned {len(results)} Codex review comment(s).")
    submit_changes(
        runner,
        base_ref=f"origin/{args.base}",
        commit_message=args.commit_message,
        no_submit=args.no_submit,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("list", "run"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--repo", default=os.environ.get("CODEX_REVIEW_REPO"))
        sub.add_argument("--base", default=os.environ.get("CODEX_REVIEW_BASE", "develop"))
        sub.add_argument("--limit-prs", type=int, default=int(os.environ.get("CODEX_REVIEW_PR_LIMIT", "1000")))
        sub.add_argument("--max-comments", type=int, default=int(os.environ.get("CODEX_REVIEW_MAX_COMMENTS", "0")))
        sub.add_argument("--since", default=os.environ.get("CODEX_REVIEW_SINCE"))
        sub.add_argument("--until", default=os.environ.get("CODEX_REVIEW_UNTIL"))
        sub.add_argument("--author", action="append", default=list(DEFAULT_CODEX_AUTHORS))
    run_parser = subparsers.choices["run"]
    run_parser.add_argument("--dry-run", action="store_true")
    run_parser.add_argument("--allow-dirty", action="store_true")
    run_parser.add_argument("--no-reply", action="store_true")
    run_parser.add_argument("--no-submit", action="store_true")
    run_parser.add_argument("--codex-model", default=os.environ.get("CODEX_REVIEW_MODEL"))
    run_parser.add_argument(
        "--codex-sandbox",
        default=os.environ.get("CODEX_REVIEW_CODEX_SANDBOX", "workspace-write"),
    )
    run_parser.add_argument("--codex-approval", default=os.environ.get("CODEX_REVIEW_CODEX_APPROVAL", "never"))
    run_parser.add_argument("--commit-message", default=DEFAULT_COMMIT_MESSAGE)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runner = CommandRunner(Path.cwd())
    try:
        return run_action_loop(args, runner)
    except (CommandError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
