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
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

DEFAULT_CODEX_AUTHORS = ("chatgpt-codex-connector[bot]", "chatgpt-codex-connector")
ACTION_MARKER = "benchbox-codex-review-followup-actioned"
ACTION_MARKER_REGEX = re.compile(rf"(?m)^<!--\s*{re.escape(ACTION_MARKER)}\b")
DEFAULT_COMMIT_MESSAGE = "fix: address stale Codex PR review follow-ups"
PER_COMMENT_COMMIT_PREFIX = "fix(codex-followup)"
MAX_REPLY_SUMMARY_CHARS = 8000
PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent / "prompts" / "codex_pr_review_followup.md"
MIN_CODEX_VERSION = (0, 20, 0)


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
    """REST fallback: fetch review comments for a single PR.

    Used when the GraphQL batch path is not viable (e.g. tests injecting a
    minimal recording runner). Production runs go through
    `fetch_review_comments_batched`.
    """
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


REVIEW_COMMENTS_GRAPHQL_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 50, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          comments(first: 100) {
            nodes {
              databaseId
              body
              path
              url
              createdAt
              diffHunk
              line
              originalLine
              originalCommit { oid }
              commit { oid }
              replyTo { databaseId }
              author { login }
            }
          }
        }
      }
    }
  }
}
""".strip()


def _graphql_comment_to_api_shape(node: dict[str, Any]) -> dict[str, Any]:
    author = node.get("author") or {}
    reply_to = node.get("replyTo") or {}
    original_commit = node.get("originalCommit") or {}
    commit = node.get("commit") or {}
    return {
        "id": node.get("databaseId"),
        "body": node.get("body") or "",
        "path": node.get("path") or "",
        "html_url": node.get("url") or "",
        "user": {"login": author.get("login") or ""},
        "created_at": node.get("createdAt") or "",
        "diff_hunk": node.get("diffHunk") or "",
        "in_reply_to_id": reply_to.get("databaseId"),
        "original_commit_id": original_commit.get("oid"),
        "commit_id": commit.get("oid"),
        "line": node.get("line"),
        "original_line": node.get("originalLine"),
    }


def fetch_review_comments_via_graphql(
    runner: CommandRunner, *, repo: str, pr_number: int
) -> list[ReviewComment] | None:
    """Fetch one PR's review comments via a single GraphQL request (paginated).

    Returns None if the GraphQL endpoint is unavailable in this environment
    (the caller falls back to the REST path). Each merged PR still costs one
    GraphQL roundtrip, but each roundtrip pulls every thread + comment for
    that PR — replacing the prior per-page REST chain.
    """
    owner, _, name = repo.partition("/")
    if not owner or not name:
        return None

    cursor: str | None = None
    rows: list[dict[str, Any]] = []
    while True:
        args = [
            "gh",
            "api",
            "graphql",
            "-f",
            f"query={REVIEW_COMMENTS_GRAPHQL_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={name}",
            "-F",
            f"number={pr_number}",
        ]
        if cursor is not None:
            args.extend(["-F", f"cursor={cursor}"])
        result = runner.run(args)
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout) if result.stdout.strip() else {}
        except json.JSONDecodeError:
            return None
        pr = (((payload.get("data") or {}).get("repository") or {}).get("pullRequest") or {})
        threads = (pr.get("reviewThreads") or {})
        for thread in threads.get("nodes") or []:
            for node in (thread.get("comments") or {}).get("nodes") or []:
                if node.get("databaseId") is None:
                    continue
                rows.append(_graphql_comment_to_api_shape(node))
        page_info = threads.get("pageInfo") or {}
        if not page_info.get("hasNextPage"):
            break
        cursor = page_info.get("endCursor")
        if not cursor:
            break
    return [review_comment_from_api(row) for row in rows]


def load_pr_review_comments(
    runner: CommandRunner, *, repo: str, pr_number: int
) -> list[ReviewComment]:
    """Prefer GraphQL; fall back to REST on any failure for resilience."""
    via_graphql = fetch_review_comments_via_graphql(runner, repo=repo, pr_number=pr_number)
    if via_graphql is not None:
        return via_graphql
    return fetch_pr_review_comments(runner, repo=repo, pr_number=pr_number)


def has_action_marker(replies: Sequence[ReviewComment]) -> bool:
    """Match the marker only inside an HTML comment at start-of-line.

    Substring matching let any reply that quoted the marker string (e.g. in a
    meta-discussion) silently kill future sweeps for the thread.
    """
    return any(ACTION_MARKER_REGEX.search(reply.body) for reply in replies)


def comment_precedes_merge(comment: ReviewComment, pr: PullRequest) -> bool:
    comment_time = parse_github_time(comment.created_at)
    merged_time = parse_github_time(pr.merged_at)
    if merged_time is None:
        raise ValueError(f"PR #{pr.number} is missing mergedAt; should be filtered upstream")
    if comment_time is None:
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
        comments = load_pr_review_comments(runner, repo=repo, pr_number=pr.number)
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


def git_status_snapshot(runner: CommandRunner) -> str:
    """Snapshot of working-tree state used as a disposition baseline.

    `git diff` only sees unstaged tracked-file changes. Codex may stage edits
    (`git add`) or create new untracked files; both must count as "fixed".
    `git status --porcelain` covers all three: modified, staged, and untracked.
    """
    return checked(runner, ["git", "status", "--porcelain"]).stdout


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


def load_prompt_template(path: Path = PROMPT_TEMPLATE_PATH) -> str:
    return path.read_text(encoding="utf-8")


def build_codex_prompt(
    item: PendingComment,
    *,
    repo: str,
    base: str,
    template: str | None = None,
) -> str:
    comment = item.comment
    pr = item.pr
    rendered = (template or load_prompt_template()).format(
        repo=repo,
        base=base,
        pr_number=pr.number,
        pr_title=pr.title,
        pr_url=pr.url,
        pr_merged_at=pr.merged_at,
        comment_html_url=comment.html_url,
        comment_id=comment.id,
        comment_path=comment.path,
        comment_line=comment.line,
        comment_original_line=comment.original_line,
        comment_commit_id=comment.commit_id,
        comment_original_commit_id=comment.original_commit_id,
        comment_diff_hunk=comment.diff_hunk,
        comment_body=comment.body,
    )
    return rendered.strip()


def check_codex_version(
    runner: CommandRunner, *, minimum: tuple[int, int, int] = MIN_CODEX_VERSION
) -> tuple[int, int, int]:
    """Probe `codex --version` and assert it parses to >= minimum.

    Surfaces a clear remediation when the binary is missing or too old, so the
    routine fails fast instead of mid-loop with an opaque flag-not-recognized
    error from a stale codex CLI.
    """
    try:
        result = runner.run(["codex", "--version"])
    except FileNotFoundError as exc:
        raise RuntimeError(
            "codex CLI not found on PATH. Install codex-cli "
            f">= {'.'.join(str(p) for p in minimum)} (https://github.com/openai/codex)."
        ) from exc
    if result.returncode != 0:
        raise CommandError(["codex", "--version"], result)
    text = (result.stdout or result.stderr or "").strip()
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if not match:
        raise RuntimeError(f"Could not parse codex CLI version from output: {text!r}")
    parsed = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
    if parsed < minimum:
        raise RuntimeError(
            f"codex CLI {'.'.join(str(p) for p in parsed)} is below the required "
            f">= {'.'.join(str(p) for p in minimum)}. Upgrade codex-cli."
        )
    return parsed


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
    before = git_status_snapshot(runner)
    prompt = build_codex_prompt(item, repo=repo, base=base)
    # codex-cli >= 0.20 dropped `--ask-for-approval`. The config-override
    # syntax (`-c approval_policy=<mode>`) works across the supported version
    # range and is forward-stable.
    cmd = [
        "codex",
        "exec",
        "--cd",
        str(runner.cwd),
        "--sandbox",
        codex_sandbox,
        "-c",
        f"approval_policy={codex_approval}",
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

    after = git_status_snapshot(runner)
    disposition = "fixed" if after != before else "no-current-action"
    summary = result.stdout.strip() or result.stderr.strip() or f"Disposition: {disposition}"
    return ActionResult(pending=item, disposition=disposition, summary=summary)


def commit_message_for_result(result: ActionResult) -> str:
    """One commit per actioned comment, with PR# + comment id for traceability."""
    pr = result.pending.pr
    comment = result.pending.comment
    headline = first_body_line(comment.body)
    subject = f"{PER_COMMENT_COMMIT_PREFIX}: PR #{pr.number} comment {comment.id} — {headline}"
    # Keep commit subjects under the conventional ~100-char soft cap; truncate
    # the codex headline before composing rather than after, so the trailer
    # stays intact.
    if len(subject) > 100:
        keep = 100 - (len(subject) - len(headline)) - 1
        subject = (
            f"{PER_COMMENT_COMMIT_PREFIX}: PR #{pr.number} comment {comment.id} — "
            f"{headline[: max(keep, 1)]}…"
        )
    body = (
        f"Disposition: {result.disposition}\n"
        f"Source: {comment.html_url}\n"
        f"Path: {comment.path}\n"
    )
    return f"{subject}\n\n{body}"


def commit_changes_for_result(
    runner: CommandRunner, result: ActionResult
) -> bool:
    """Stage + commit codex-produced changes for one comment.

    Returns True when a commit was created. Called *before* the GitHub reply
    is posted so a crash between codex and reply leaves no phantom-actioned
    state on GitHub: either the commit landed (next run sees no change), or
    nothing happened (next run reprocesses the comment cleanly).
    """
    if result.disposition != "fixed":
        return False
    paths = git_changed_paths(runner)
    if not paths:
        return False
    print("==> Staging changed paths for this comment")
    for path in paths:
        print(f"  {path}")
    stage_paths(runner, paths)
    staged_paths = checked(runner, ["git", "diff", "--cached", "--name-only"]).stdout.splitlines()
    if not staged_paths:
        return False
    checked(runner, ["git", "commit", "-m", commit_message_for_result(result)])
    return True


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


def finalize_changes(
    runner: CommandRunner,
    *,
    base_ref: str,
    commit_message: str,
    no_submit: bool,
) -> None:
    """Run preflight + open the PR over the per-comment commits already on HEAD.

    Per-comment commits are produced inside `run_action_loop` *before* the
    GitHub reply is posted. This finalizer's job is just to (a) sweep up any
    leftover unstaged paths into a fallback batch commit (codex output that
    was somehow missed by `commit_changes_for_result`), (b) run preflight,
    (c) open the PR.
    """
    paths = git_changed_paths(runner)
    commits = local_commit_count(runner, base_ref)
    if not paths and commits == 0:
        print("No file changes or local commits were produced; skipping PR submission.")
        return

    if paths:
        print("\n==> Sweeping leftover changed paths into fallback commit")
        for path in paths:
            print(f"  {path}")
        stage_paths(runner, paths)
        staged = checked(runner, ["git", "diff", "--cached", "--name-only"]).stdout.splitlines()
        if staged:
            checked(runner, ["git", "commit", "-m", commit_message])

    print("\n==> Running pr-preflight")
    checked(runner, ["make", "pr-preflight"])

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
            check_codex_version(runner)
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
        # Order matters: commit BEFORE replying. A crash between codex and
        # the reply leaves nothing on GitHub; a crash between commit and
        # reply leaves a benign uncommented commit. Reply-before-commit
        # would create phantom-actioned threads that future sweeps would
        # silently skip even though no fix landed.
        commit_changes_for_result(runner, result)
        results.append(result)
        if not args.no_reply:
            reply_to_comment(runner, repo=repo, result=result, branch=branch)

    print(f"\nActioned {len(results)} Codex review comment(s).")
    finalize_changes(
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
