#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from soundness_paths import any_soundness_path

CONNECTOR_LOGIN = "chatgpt-codex-connector"
ORACLE_LOGIN = "benchbox-oracle"
CONNECTOR = "connector"
ORACLE = "oracle"
SIGNALS = {CONNECTOR: (CONNECTOR_LOGIN, "Codex connector"), ORACLE: (ORACLE_LOGIN, "oracle")}
ORACLE_CONTEXT = "oracle-review-shadow"
_ORACLE_VERDICT = re.compile(rf"### {ORACLE_CONTEXT}: (?P<state>[a-z]+) for `(?P<sha>[0-9a-f]{{40}})`")
# Accounts whose stand-in attestation substitutes for the Codex connector when it
# cannot review (for example at its usage limit). The attestation must name the
# exact head commit, so it records who vouched for which reviewed code.
STANDIN_ATTESTERS = frozenset({"joeharris76"})
_STANDIN_MARKER = re.compile(r"Stand-in oracle review: APPROVE ([0-9a-f]{40})")


def _attested_shas(comment: dict[str, Any]) -> list[str]:
    match = _STANDIN_MARKER.fullmatch((comment.get("body") or "").strip())
    return [match.group(1)] if match else []


def _is_standin(comment: dict[str, Any], head_sha: str, not_before: datetime | None) -> bool:
    # Exact login and a human account: a "[bot]" suffix is not stripped here. An
    # edited comment does not count, because its text may not be the author's.
    return (
        comment.get("login") in STANDIN_ATTESTERS
        and comment.get("user_type") == "User"
        and comment.get("updated_at") in (None, comment.get("created_at"))
        and (not_before is None or _parse_time(comment["created_at"]) > not_before)
        and head_sha in _attested_shas(comment)
    )


API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
WORKFLOW_PATH = ".github/workflows/oracle-review.yml"
HEAD_MOVING_RUN_SUFFIXES = ("(opened)", "(synchronize)")
PASS = 0
WAITING = 1
ERROR = 2
_STATUS_NAMES = {PASS: "pass", WAITING: "waiting", ERROR: "error"}

_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          comments(first: 1) { nodes { author { __typename login } } }
        }
      }
    }
  }
}
"""


class CheckError(RuntimeError):
    pass


def _login(value: str | None) -> str:
    return (value or "").removesuffix("[bot]")


def _is_reviewer(login: str | None, signal: str, account_type: str | None = None) -> bool:
    return _login(login) == SIGNALS[signal][0] and (signal == CONNECTOR or account_type == "Bot")


def _oracle_verdict(reviews: list[dict[str, Any]], head_sha: str) -> tuple[str | None, datetime | None]:
    latest = max(reviews, key=lambda review: _parse_time(review["submitted_at"]), default=None)
    if latest is None:
        return None, None
    match = _ORACLE_VERDICT.match(latest.get("body") or "")
    state = match.group("state") if match and match.group("sha") == head_sha else None
    return state, _parse_time(latest["submitted_at"])


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(
    head_sha: str,
    head_date: str | None,
    files: Iterable[str],
    reviews: Iterable[dict[str, Any]],
    reactions: Iterable[dict[str, Any]],
    threads: Iterable[dict[str, Any]],
    paths: Callable[[Iterable[str]], bool],
    base_date: str | None = None,
    comments: Iterable[dict[str, Any]] = (),
    signal: str = CONNECTOR,
) -> tuple[int, str]:
    if not paths(files):
        return PASS, "oracle-review: not a soundness path change"

    name = SIGNALS[signal][1]
    base_time = _parse_time(base_date) if base_date else None
    head_reviews = [
        review
        for review in reviews
        if _is_reviewer(review.get("login"), signal, review.get("user_type"))
        and review.get("commit_id") == head_sha
        and review.get("state") not in {"PENDING", "DISMISSED"}
        and (base_time is None or (review.get("submitted_at") and _parse_time(review["submitted_at"]) > base_time))
    ]
    review_signal = bool(head_reviews)
    reaction_signal = False
    standin_after = base_time
    verdict = None
    if signal == CONNECTOR:
        head_time = _parse_time(head_date or "")
        head_time = max(head_time, base_time) if base_time else head_time
        reaction_signal = any(
            _is_reviewer(reaction.get("login"), signal)
            and reaction.get("content") == "+1"
            and _parse_time(reaction["created_at"]) > head_time
            for reaction in reactions
        )
    else:
        verdict, verdict_time = _oracle_verdict(head_reviews, head_sha)
        standin_after = max(filter(None, (base_time, verdict_time)), default=None)
    standin = next((comment for comment in comments if _is_standin(comment, head_sha, standin_after)), None)
    if review_signal and signal == ORACLE and verdict != "success" and not standin:
        return WAITING, (
            f"oracle-review: the oracle's latest review of {head_sha} reports {verdict or 'no verdict'}, not "
            "success; fix the findings, or post a stand-in attestation after that review, then rerun this check"
        )
    if not (review_signal or reaction_signal or standin):
        return WAITING, (
            f"oracle-review: waiting for the {name}'s review of {head_sha}, or a stand-in attestation "
            f"'Stand-in oracle review: APPROVE {head_sha}' from a listed attester; rerun this check after it lands"
        )

    open_threads = sum(
        1
        for thread in threads
        if not thread.get("resolved") and _is_reviewer(thread.get("author"), signal, thread.get("author_type"))
    )
    if open_threads:
        return WAITING, (
            f"oracle-review: {open_threads} unresolved {name} review thread(s) on {head_sha}; "
            "resolve them and rerun this check"
        )

    if review_signal and (signal == CONNECTOR or verdict == "success"):
        return PASS, f"oracle-review: pass ({name} review of {head_sha})"
    if reaction_signal:
        return PASS, f"oracle-review: pass (Codex connector +1 after the head commit {head_sha})"
    assert standin is not None
    return PASS, f"oracle-review: pass (stand-in review attested by {standin.get('login')} for {head_sha})"


def _request(token: str, url: str, body: dict[str, Any] | None = None) -> Any:
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "benchbox-oracle-review-check",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise CheckError(f"GitHub returned HTTP {exc.code} for {url}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise CheckError(f"GitHub request to {url} failed: {exc}") from exc


def _paginate(token: str, path: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = _request(token, f"{API_ROOT}{path}?per_page={PAGE_SIZE}&page={page}")
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            return items
        page += 1


def fetch_pull(token: str, repo: str, pr: int) -> dict[str, Any]:
    return _request(token, f"{API_ROOT}/repos/{repo}/pulls/{pr}")


def head_transition_date(committer_date: str, run_dates: Iterable[str]) -> str:
    return max([committer_date, *run_dates], key=_parse_time)


def own_run_dates(runs: Iterable[dict[str, Any]]) -> list[str]:
    own = [run for run in runs if (run.get("path") or "").split("@", 1)[0] == WORKFLOW_PATH]
    if not own:
        return []
    first_run = min((run["created_at"] for run in own), key=_parse_time)
    head_moves = [
        run["created_at"] for run in own if (run.get("display_title") or "").endswith(HEAD_MOVING_RUN_SUFFIXES)
    ]
    return [first_run, *head_moves]


def fetch_head_date(token: str, repo: str, sha: str) -> str:
    committer_date = _request(token, f"{API_ROOT}/repos/{repo}/commits/{sha}")["commit"]["committer"]["date"]
    runs = _request(
        token,
        f"{API_ROOT}/repos/{repo}/actions/runs?head_sha={sha}&event=pull_request&per_page={PAGE_SIZE}",
    )["workflow_runs"]
    return head_transition_date(committer_date, own_run_dates(runs))


def changed_paths(items: Iterable[dict[str, Any]]) -> list[str]:
    paths: list[str] = []
    for item in items:
        paths.append(item["filename"])
        if item.get("previous_filename"):
            paths.append(item["previous_filename"])
    return paths


def fetch_files(token: str, repo: str, pr: int) -> list[dict[str, Any]]:
    return _paginate(token, f"/repos/{repo}/pulls/{pr}/files")


def path_matcher(listed_files: int, changed_files: int) -> Callable[[Iterable[str]], bool]:
    if listed_files < changed_files:
        return lambda _paths: True
    return any_soundness_path


def fetch_reviews(token: str, repo: str, pr: int) -> list[dict[str, Any]]:
    return [
        {
            "login": (item.get("user") or {}).get("login"),
            "user_type": (item.get("user") or {}).get("type"),
            "commit_id": item.get("commit_id"),
            "state": item.get("state"),
            "submitted_at": item.get("submitted_at"),
            "body": item.get("body"),
        }
        for item in _paginate(token, f"/repos/{repo}/pulls/{pr}/reviews")
    ]


def fetch_reactions(token: str, repo: str, pr: int) -> list[dict[str, Any]]:
    return [
        {
            "login": (item.get("user") or {}).get("login"),
            "content": item.get("content"),
            "created_at": item["created_at"],
        }
        for item in _paginate(token, f"/repos/{repo}/issues/{pr}/reactions")
    ]


def fetch_comments(token: str, repo: str, pr: int) -> list[dict[str, Any]]:
    return [
        {
            "login": (item.get("user") or {}).get("login"),
            "user_type": (item.get("user") or {}).get("type"),
            "body": item.get("body"),
            "created_at": item["created_at"],
            "updated_at": item.get("updated_at"),
        }
        for item in _paginate(token, f"/repos/{repo}/issues/{pr}/comments")
    ]


def latest_base_change(events: Iterable[dict[str, Any]]) -> str | None:
    dates = [event["created_at"] for event in events if event.get("event") == "base_ref_changed"]
    return max(dates, key=_parse_time) if dates else None


def fetch_base_change_date(token: str, repo: str, pr: int) -> str | None:
    return latest_base_change(_paginate(token, f"/repos/{repo}/issues/{pr}/timeline"))


def fetch_threads(token: str, repo: str, pr: int) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    threads: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        payload = _request(
            token,
            f"{API_ROOT}/graphql",
            {"query": _THREADS_QUERY, "variables": {"owner": owner, "name": name, "number": pr, "after": after}},
        )
        if payload.get("errors"):
            raise CheckError(f"GitHub GraphQL returned errors: {payload['errors']}")
        connection = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in connection["nodes"]:
            comments = node["comments"]["nodes"]
            author = (comments[0].get("author") or {}) if comments else {}
            threads.append(
                {"resolved": node["isResolved"], "author": author.get("login"), "author_type": author.get("__typename")}
            )
        if not connection["pageInfo"]["hasNextPage"]:
            return threads
        after = connection["pageInfo"]["endCursor"]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Require a review of the head commit on result-affecting pull requests, from the Codex connector "
            "or the oracle reviewer chain, or a stand-in attestation for the exact head commit from a listed "
            "attester."
        )
    )
    parser.add_argument("--repo", required=True, help="Repository as OWNER/NAME.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
    parser.add_argument(
        "--signal",
        choices=sorted(SIGNALS),
        default=CONNECTOR,
        help="Reviewer whose review of the head this check requires. The other is reported for comparison only.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        print("oracle-review: error: GITHUB_TOKEN is not set", file=sys.stderr)
        return ERROR
    if args.repo.count("/") != 1:
        print("oracle-review: error: --repo must be OWNER/NAME", file=sys.stderr)
        return ERROR
    try:
        pull = fetch_pull(token, args.repo, args.pr)
        head_sha = pull["head"]["sha"]
        items = fetch_files(token, args.repo, args.pr)
        files = changed_paths(items)
        matcher = path_matcher(len(items), pull["changed_files"])
        if not matcher(files):
            print("oracle-review: not a soundness path change")
            return PASS
        reviews = fetch_reviews(token, args.repo, args.pr)
        threads = fetch_threads(token, args.repo, args.pr)
        base_date = fetch_base_change_date(token, args.repo, args.pr)
        comments = fetch_comments(token, args.repo, args.pr)

        def run(signal: str) -> tuple[int, str]:
            head_date, reactions = (None, [])
            if signal == CONNECTOR:
                head_date = fetch_head_date(token, args.repo, head_sha)
                reactions = fetch_reactions(token, args.repo, args.pr)
            return decide(head_sha, head_date, files, reviews, reactions, threads, matcher, base_date, comments, signal)

        status, message = run(args.signal)
    except (CheckError, KeyError, ValueError) as exc:
        print(f"oracle-review: error: {exc}", file=sys.stderr)
        return ERROR
    print(message)
    for other in sorted(set(SIGNALS) - {args.signal}):
        try:
            other_status, other_message = run(other)
        except (CheckError, KeyError, TypeError, ValueError) as exc:
            print(f"parity: {other}: not evaluated: {exc}")
            continue
        print(f"parity: required={args.signal} {_STATUS_NAMES[status]}; {other} {_STATUS_NAMES[other_status]}")
        print(f"parity: {other}: {other_message}")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
