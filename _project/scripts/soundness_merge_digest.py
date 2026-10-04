#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from oracle_review_check import STANDIN_ATTESTERS, _attested_shas

MANIFEST_PATH = ".github/soundness-paths.txt"
PREDICATE_PATH = "_project/scripts/soundness_paths.py"
GOVERNANCE_PATHS = frozenset(
    {
        MANIFEST_PATH,
        PREDICATE_PATH,
        "_project/scripts/soundness_merge_digest.py",
        ".github/workflows/soundness-merge-digest.yml",
    }
)
PREDICATE_DRIVER = (
    "import json, sys; sys.path.insert(0, sys.argv[1]); from soundness_paths import is_soundness_path; "
    "print(json.dumps([p for p in json.load(sys.stdin) if is_soundness_path(p)]))"
)
DEFAULT_REPO = "BenchBox-dev/BenchBox"
BASE_BRANCH = "develop"
STATE_LABEL = "soundness-merge-digest"
GAP_LABEL = "soundness-review-gap"
CHECKPOINT_PATTERN = re.compile(r"<!-- soundness-digest-checkpoint: ([0-9a-f]{40}) -->")
EXTERNAL_REVIEW_PATTERN = re.compile(
    r"(?im)^[ \t]*(?:[-*+][ \t]+)?(?:\**(?:external[ \t]+)?reviewer\**[ \t]*:\**|soundness[ \t]+review:)[ \t]*(?:external[ \t]+)?(codex|muse|agy)\b"
)
CONNECTOR_LOGINS = frozenset({"chatgpt-codex-connector", "chatgpt-codex-connector[bot]"})
THREAD_PAGE = 100
MAX_PULL_COMMITS = 250
PULL_EVENTS = frozenset({"pull_request", "pull_request_target"})


class ReadError(RuntimeError):
    pass


@dataclass(frozen=True)
class Review:
    login: str
    commit_sha: str
    submitted_at: str
    state: str


@dataclass(frozen=True)
class Reaction:
    login: str
    content: str
    created_at: str


@dataclass(frozen=True)
class Comment:
    login: str
    body: str
    created_at: str
    user_type: str = ""
    updated_at: str | None = None


@dataclass(frozen=True)
class Thread:
    resolved: bool
    started_by: str
    first_comment_sha: str


@dataclass(frozen=True)
class PullCommit:
    sha: str
    arrived_at: str
    is_refresh: bool


@dataclass(frozen=True)
class PullEvidence:
    number: int
    author: str
    merged_at: str
    commits: tuple[PullCommit, ...]
    reviews: tuple[Review, ...] = ()
    reactions: tuple[Reaction, ...] = ()
    comments: tuple[Comment, ...] = ()
    threads: tuple[Thread, ...] = ()

    @property
    def content_cutoff(self) -> str:
        content = [c for c in self.commits if not c.is_refresh]
        return content[-1].arrived_at if content else ""

    @property
    def content_shas(self) -> frozenset[str]:
        last = max((i for i, c in enumerate(self.commits) if not c.is_refresh), default=0)
        return frozenset(c.sha for c in self.commits[last:])


@dataclass(frozen=True)
class Entry:
    sha: str
    subject: str
    files: tuple[str, ...]
    pull: PullEvidence | None
    signals: tuple[str, ...]
    unreviewed_threads: int

    @property
    def needs_attention(self) -> bool:
        return self.pull is None or not self.signals or self.unreviewed_threads > 0

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.pull is None:
            reasons.append("no merged pull request")
        elif not self.signals:
            reasons.append("no completed review after the last content commit")
        if self.unreviewed_threads:
            reasons.append(f"{self.unreviewed_threads} reviewer thread(s) resolved with no later commit")
        return tuple(reasons)


def review_signals(evidence: PullEvidence) -> tuple[str, ...]:
    cutoff = evidence.content_cutoff

    def in_window(at: str) -> bool:
        return cutoff <= at <= evidence.merged_at

    signals: list[str] = []
    if any(
        r.login in CONNECTOR_LOGINS
        and r.commit_sha in evidence.content_shas
        and r.state != "PENDING"
        and r.submitted_at <= evidence.merged_at
        for r in evidence.reviews
    ):
        signals.append("connector-review")
    if any(r.login in CONNECTOR_LOGINS and r.content == "+1" and in_window(r.created_at) for r in evidence.reactions):
        signals.append("connector-approval")
    for comment in evidence.comments:
        match = EXTERNAL_REVIEW_PATTERN.search(comment.body)
        if match and in_window(comment.created_at):
            signals.append(f"external-review:{match.group(1).lower()}")
        if (
            comment.login in STANDIN_ATTESTERS
            and comment.user_type == "User"
            and comment.updated_at in (None, comment.created_at)
            and in_window(comment.created_at)
            and evidence.commits[-1].sha in _attested_shas({"body": comment.body})
        ):
            signals.append("stand-in")
    return tuple(dict.fromkeys(signals))


def unreviewed_thread_count(evidence: PullEvidence) -> int:
    return sum(
        1
        for thread in evidence.threads
        if thread.resolved
        and thread.started_by != evidence.author
        and thread.first_comment_sha in evidence.content_shas
    )


def classify(sha: str, subject: str, files: Sequence[str], pull: PullEvidence | None) -> Entry:
    return Entry(
        sha=sha,
        subject=subject,
        files=tuple(files),
        pull=pull,
        signals=review_signals(pull) if pull else (),
        unreviewed_threads=unreviewed_thread_count(pull) if pull else 0,
    )


def render(entries: Sequence[Entry], *, since: str, until: str) -> str:
    lines = [f"Soundness-path commits on develop from {since[:9]} to {until[:9]}: {len(entries)}.", ""]
    if not entries:
        return "\n".join(lines + ["None."])
    lines += ["| Commit | Pull request | Review signal | Attention |", "|---|---|---|---|"]
    for entry in entries:
        pull = f"#{entry.pull.number}" if entry.pull else "none"
        signal = ", ".join(entry.signals) or "none"
        attention = "; ".join(entry.reasons) or "-"
        lines.append(f"| `{entry.sha[:9]}` {entry.subject} | {pull} | {signal} | {attention} |")
    return "\n".join(lines)


def gap_issue_body(entry: Entry) -> str:
    pull = f"#{entry.pull.number}" if entry.pull else "no pull request"
    files = "\n".join(f"- `{path}`" for path in entry.files)
    return (
        f"<!-- soundness-gap:{entry.sha} -->\n"
        f"Commit `{entry.sha}` ({pull}) changed paths on the soundness list and merged to develop.\n\n"
        f"Why it is listed: {'; '.join(entry.reasons)}.\n\n"
        f"Soundness-path files:\n{files}\n\n"
        "Next step: run an external adversarial review of the commit (codex, muse or agy), post it as a "
        "comment, and either record a clean result here or open a fix or revert pull request."
    )


def run(args: Sequence[str], *, input_text: str | None = None, cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(list(args), input=input_text, capture_output=True, text=True, check=False, cwd=cwd)
    except OSError as exc:
        raise ReadError(f"{args[0]} could not run: {exc}") from exc
    if result.returncode != 0:
        raise ReadError(f"{' '.join(args[:4])} failed: {result.stderr.strip()[:300]}")
    return result.stdout


def gh_json(*args: str) -> Any:
    return json.loads(run(["gh", *args]))


def gh_pages(endpoint: str) -> list[Any]:
    pages = gh_json("api", "--paginate", "--slurp", endpoint)
    return [item for page in pages for item in (page if isinstance(page, list) else [page])]


def merged_commits(ref: str, since: str) -> list[str]:
    return run(["git", "log", "--first-parent", "--reverse", "--format=%H", f"{since}..{ref}"]).split()


def commit_files(sha: str, *, cwd: Path | None = None) -> list[str]:
    return run(["git", "diff", "--name-only", "--no-renames", f"{sha}~1", sha], cwd=cwd).splitlines()


def is_ancestor(commit: str, descendant: str, *, cwd: Path | None = None) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, descendant], capture_output=True, text=True, check=False, cwd=cwd
    )
    if result.returncode not in (0, 1):
        raise ReadError(f"git merge-base failed for {commit[:9]}: {result.stderr.strip()[:200]}")
    return result.returncode == 0


def merge_adds_content(sha: str, base: str, *, cwd: Path | None = None) -> bool:
    parents = run(["git", "rev-list", "--parents", "-n", "1", sha], cwd=cwd).split()[1:]
    if len(parents) != 2 or not any(is_ancestor(parent, base, cwd=cwd) for parent in parents):
        return True
    result = subprocess.run(
        ["git", "merge-tree", "--write-tree", *parents], capture_output=True, text=True, check=False, cwd=cwd
    )
    if result.returncode == 1:
        return True
    if result.returncode != 0:
        raise ReadError(f"git merge-tree failed for {sha[:9]}: {result.stderr.strip()[:200]}")
    return result.stdout.split()[0] != run(["git", "rev-parse", f"{sha}^{{tree}}"], cwd=cwd).strip()


def commit_subject(sha: str) -> str:
    return run(["git", "show", "-s", "--format=%s", sha]).strip()


def collect_threads(repo: str, number: int) -> tuple[Thread, ...]:
    owner, name = repo.split("/", 1)
    query = """
    query($o: String!, $n: String!, $p: Int!, $first: Int!) {
      repository(owner: $o, name: $n) {
        pullRequest(number: $p) {
          reviewThreads(first: $first) {
            pageInfo { hasNextPage }
            nodes {
              isResolved
              comments(first: 1) { nodes { author { login } originalCommit { oid } } }
            }
          }
        }
      }
    }
    """
    data = gh_json(
        "api",
        "graphql",
        "-f",
        f"query={query}",
        "-f",
        f"o={owner}",
        "-f",
        f"n={name}",
        "-F",
        f"p={number}",
        "-F",
        f"first={THREAD_PAGE}",
    )
    try:
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]
        if threads["pageInfo"]["hasNextPage"]:
            raise ReadError(f"#{number} has more than {THREAD_PAGE} review threads")
        parsed: list[Thread] = []
        for node in threads["nodes"]:
            if not node["comments"]["nodes"]:
                continue
            first = node["comments"]["nodes"][0]
            parsed.append(
                Thread(
                    resolved=bool(node["isResolved"]),
                    started_by=(first.get("author") or {}).get("login", ""),
                    first_comment_sha=(first.get("originalCommit") or {}).get("oid", ""),
                )
            )
    except (KeyError, IndexError, TypeError) as exc:
        raise ReadError(f"#{number} review threads came back malformed: {exc!r}") from exc
    return tuple(parsed)


def merged_pull_number(repo: str, sha: str) -> int | None:
    candidates = [
        pr
        for pr in gh_pages(f"repos/{repo}/commits/{sha}/pulls")
        if pr.get("merge_commit_sha") == sha
        and pr.get("merged_at")
        and (pr.get("base") or {}).get("ref") == BASE_BRANCH
    ]
    if len(candidates) > 1:
        raise ReadError(f"{sha[:9]} is the merge commit of {len(candidates)} pull requests")
    return int(candidates[0]["number"]) if candidates else None


def belongs_to_pull(run_: dict[str, Any], number: int, pull: dict[str, Any]) -> bool:
    if run_.get("event") not in PULL_EVENTS or run_["created_at"] < pull["created_at"]:
        return False
    listed = run_.get("pull_requests") or []
    if listed:
        return any(p.get("number") == number for p in listed)
    head_repo = (pull["head"].get("repo") or {}).get("full_name")
    run_repo = (run_.get("head_repository") or {}).get("full_name")
    return bool(head_repo) and run_repo == head_repo and run_.get("head_branch") == pull["head"]["ref"]


def server_arrival(repo: str, sha: str, number: int, pull: dict[str, Any]) -> str | None:
    runs = gh_json("api", f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100")["workflow_runs"]
    times = [run_["created_at"] for run_ in runs if belongs_to_pull(run_, number, pull)]
    return min(times) if times else None


def collect_commits(
    repo: str, number: int, pull: dict[str, Any], base: str, *, cwd: Path | None = None
) -> tuple[PullCommit, ...]:
    commits = gh_pages(f"repos/{repo}/pulls/{number}/commits")
    if len(commits) >= MAX_PULL_COMMITS:
        raise ReadError(f"#{number} has {len(commits)} commits, the most the API lists")
    head = pull["head"]["sha"]
    if not commits or len(commits) != pull["commits"] or commits[-1]["sha"] != head:
        raise ReadError(f"#{number} commit list does not match the pull request: {len(commits)} of {pull['commits']}")
    if any(len(c["parents"]) > 1 for c in commits):
        run(["git", "fetch", "--no-tags", "origin", f"refs/pull/{number}/head"], cwd=cwd)
        if run(["git", "rev-parse", "FETCH_HEAD"], cwd=cwd).strip() != head:
            raise ReadError(f"#{number} head moved while its commits were being read")
    built = [
        PullCommit(
            c["sha"],
            c["commit"]["committer"]["date"],
            len(c["parents"]) > 1 and not merge_adds_content(c["sha"], base, cwd=cwd),
        )
        for c in commits
    ]
    content = [i for i, c in enumerate(built) if not c.is_refresh]
    if content:
        index = content[-1]
        arrival = next(
            (t for c in built[index:] if (t := server_arrival(repo, c.sha, number, pull))),
            pull["merged_at"],
        )
        built[index] = replace(built[index], arrived_at=arrival)
    return tuple(built)


def collect_pull(repo: str, sha: str) -> PullEvidence | None:
    number = merged_pull_number(repo, sha)
    if number is None:
        return None
    pull = gh_json("api", f"repos/{repo}/pulls/{number}")
    return PullEvidence(
        number=number,
        author=pull["user"]["login"],
        merged_at=pull["merged_at"],
        commits=collect_commits(repo, number, pull, f"{sha}~1"),
        reviews=tuple(
            Review(
                (r.get("user") or {}).get("login", ""),
                r.get("commit_id") or "",
                r.get("submitted_at") or "",
                r.get("state") or "",
            )
            for r in gh_pages(f"repos/{repo}/pulls/{number}/reviews")
        ),
        reactions=tuple(
            Reaction((r.get("user") or {}).get("login", ""), r["content"], r["created_at"])
            for r in gh_pages(f"repos/{repo}/issues/{number}/reactions")
        ),
        comments=tuple(
            Comment(
                (c.get("user") or {}).get("login", ""),
                c.get("body") or "",
                c["created_at"],
                (c.get("user") or {}).get("type", ""),
                c.get("updated_at"),
            )
            for c in gh_pages(f"repos/{repo}/issues/{number}/comments")
        ),
        threads=collect_threads(repo, number),
    )


def soundness_files(sha: str, files: Sequence[str], *, cwd: Path | None = None) -> list[str]:
    if not files:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for relative in (MANIFEST_PATH, PREDICATE_PATH):
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(run(["git", "show", f"{sha}~1:{relative}"], cwd=cwd), encoding="utf-8")
        output = run(
            [sys.executable, "-c", PREDICATE_DRIVER, str(root / "_project" / "scripts")],
            input_text=json.dumps(list(files)),
            cwd=cwd,
        )
    matched = set(json.loads(output))
    return [path for path in files if path in matched or path in GOVERNANCE_PATHS]


def collect_entries(repo: str, ref: str, since: str) -> list[Entry]:
    entries: list[Entry] = []
    for sha in merged_commits(ref, since):
        files = soundness_files(sha, commit_files(sha))
        if files:
            entries.append(classify(sha, commit_subject(sha), files, collect_pull(repo, sha)))
    return entries


def find_state_issue(repo: str) -> dict[str, Any] | None:
    issues = gh_pages(f"repos/{repo}/issues?labels={STATE_LABEL}&state=all&per_page=100")
    if len(issues) > 1:
        raise ReadError(f"{len(issues)} issues carry the {STATE_LABEL} label; keep exactly one")
    return issues[0] if issues else None


def read_checkpoint(repo: str) -> str | None:
    issue = find_state_issue(repo)
    if issue is None:
        return None
    match = CHECKPOINT_PATTERN.search(issue.get("body") or "")
    if match is None:
        raise ReadError(f"state issue #{issue['number']} has no checkpoint marker; restore it by hand")
    return match.group(1)


def write_checkpoint(repo: str, sha: str, report: str) -> None:
    body = f"<!-- soundness-digest-checkpoint: {sha} -->\n\n{report}\n"
    issue = find_state_issue(repo)
    if issue is None:
        run(["gh", "label", "create", STATE_LABEL, "--repo", repo, "--force", "--color", "0e8a16"])
        run(
            [
                "gh",
                "issue",
                "create",
                "--repo",
                repo,
                "--title",
                "Soundness merge digest",
                "--label",
                STATE_LABEL,
                "--body",
                body,
            ]
        )
    else:
        run(["gh", "issue", "edit", str(issue["number"]), "--repo", repo, "--body", body])


def open_gap_issues(repo: str, entries: Sequence[Entry]) -> list[str]:
    run(["gh", "label", "create", GAP_LABEL, "--repo", repo, "--force", "--color", "b60205"])
    existing = gh_pages(f"repos/{repo}/issues?labels={GAP_LABEL}&state=all&per_page=100")
    known = "\n".join(issue.get("body") or "" for issue in existing)
    opened: list[str] = []
    for entry in entries:
        if entry.needs_attention and f"<!-- soundness-gap:{entry.sha} -->" not in known:
            title = f"Soundness-path commit {entry.sha[:9]} needs an external review: {entry.subject}"[:200]
            run(
                [
                    "gh",
                    "issue",
                    "create",
                    "--repo",
                    repo,
                    "--title",
                    title,
                    "--label",
                    GAP_LABEL,
                    "--body",
                    gap_issue_body(entry),
                ]
            )
            opened.append(entry.sha)
    return opened


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List soundness-path commits that reached develop and the review each had"
    )
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--ref", default="origin/develop")
    parser.add_argument("--since", help="start after this commit; defaults to the stored checkpoint")
    parser.add_argument("--apply", action="store_true", help="open gap issues and advance the checkpoint")
    parser.add_argument(
        "--bootstrap", action="store_true", help="with --apply, record the current head as the first checkpoint"
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        until = run(["git", "rev-parse", args.ref]).strip()
        if args.bootstrap:
            if not args.apply:
                print("--bootstrap needs --apply.", file=sys.stderr)
                return 2
            if read_checkpoint(args.repo) is not None:
                print("A checkpoint is already stored; --bootstrap would skip the commits after it.", file=sys.stderr)
                return 2
            write_checkpoint(args.repo, until, "Checkpoint recorded; the next run reports commits after it.")
            print(f"Recorded checkpoint {until[:9]}.")
            return 0
        since = args.since or read_checkpoint(args.repo)
        if since is None:
            print("No checkpoint stored; pass --since, or run once with --apply --bootstrap.", file=sys.stderr)
            return 2
        since = run(["git", "rev-parse", "--verify", f"{since}^{{commit}}"]).strip()
        if since not in run(["git", "rev-list", "--first-parent", until]).split():
            raise ReadError(f"checkpoint {since[:9]} is not on the first-parent history of {args.ref}")
        entries = collect_entries(args.repo, until, since)
        report = render(entries, since=since, until=until)
        print(report)
        if args.apply:
            opened = open_gap_issues(args.repo, entries)
            write_checkpoint(args.repo, until, report)
            print(f"\nOpened {len(opened)} issue(s); checkpoint is {until[:9]}.")
    except (ReadError, KeyError, TypeError, ValueError) as exc:
        print(f"soundness-merge-digest: {exc!s}; the checkpoint was not advanced", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
