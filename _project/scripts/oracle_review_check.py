#!/usr/bin/env python3
"""Require the Codex connector's review on result-affecting pull requests.

Every human and agent in this repository posts as the owner account, so the
connector's GitHub App identity is the only review signal that cannot be
forged. The connector either submits a review (recording the commit it
reviewed) or, when it finds nothing, adds a thumbs-up reaction to the PR.

Exit codes: 0 pass or skip, 1 waiting for the review, 2 error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from soundness_paths import any_soundness_path  # noqa: E402

CONNECTOR_LOGIN = "chatgpt-codex-connector"
API_ROOT = "https://api.github.com"
PAGE_SIZE = 100
PASS = 0
WAITING = 1
ERROR = 2

_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          comments(first: 1) { nodes { author { login } } }
        }
      }
    }
  }
}
"""


class CheckError(RuntimeError):
    """A GitHub call failed or returned an unusable response."""


def _login(value: str | None) -> str:
    return (value or "").removesuffix("[bot]")


def _is_connector(login: str | None) -> bool:
    return _login(login) == CONNECTOR_LOGIN


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def decide(
    head_sha: str,
    head_date: str,
    files: Iterable[str],
    reviews: Iterable[dict[str, Any]],
    reactions: Iterable[dict[str, Any]],
    threads: Iterable[dict[str, Any]],
    paths: Callable[[Iterable[str]], bool],
) -> tuple[int, str]:
    """Return ``(status, message)`` for one pull request.

    ``reviews`` items carry ``login``, ``commit_id`` and ``state``;
    ``reactions`` items carry ``login``, ``content`` and ``created_at``;
    ``threads`` items carry ``resolved`` and ``author`` (the first comment's
    login). ``paths`` reports whether any changed file is result-affecting.
    """
    if not paths(files):
        return PASS, "oracle-review: not a soundness path change"

    review_signal = any(
        _is_connector(review.get("login"))
        and review.get("commit_id") == head_sha
        and review.get("state") not in {"PENDING", "DISMISSED"}
        for review in reviews
    )
    head_time = _parse_time(head_date)
    reaction_signal = any(
        _is_connector(reaction.get("login"))
        and reaction.get("content") == "+1"
        and _parse_time(reaction["created_at"]) > head_time
        for reaction in reactions
    )
    if not (review_signal or reaction_signal):
        return WAITING, (
            f"oracle-review: waiting for the Codex connector's review of {head_sha}; rerun this check after it lands"
        )

    open_threads = sum(1 for thread in threads if not thread.get("resolved") and _is_connector(thread.get("author")))
    if open_threads:
        return WAITING, (
            f"oracle-review: {open_threads} unresolved Codex connector review thread(s) on {head_sha}; "
            "resolve them and rerun this check"
        )

    if review_signal:
        return PASS, f"oracle-review: pass (Codex connector review of {head_sha})"
    return PASS, f"oracle-review: pass (Codex connector +1 after the head commit {head_sha})"


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


def fetch_head_sha(token: str, repo: str, pr: int) -> str:
    return _request(token, f"{API_ROOT}/repos/{repo}/pulls/{pr}")["head"]["sha"]


def fetch_head_date(token: str, repo: str, sha: str) -> str:
    return _request(token, f"{API_ROOT}/repos/{repo}/commits/{sha}")["commit"]["committer"]["date"]


def fetch_files(token: str, repo: str, pr: int) -> list[str]:
    return [item["filename"] for item in _paginate(token, f"/repos/{repo}/pulls/{pr}/files")]


def fetch_reviews(token: str, repo: str, pr: int) -> list[dict[str, Any]]:
    return [
        {
            "login": (item.get("user") or {}).get("login"),
            "commit_id": item.get("commit_id"),
            "state": item.get("state"),
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
            author = ((comments[0].get("author") or {}).get("login")) if comments else None
            threads.append({"resolved": node["isResolved"], "author": author})
        if not connection["pageInfo"]["hasNextPage"]:
            return threads
        after = connection["pageInfo"]["endCursor"]


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, help="Repository as OWNER/NAME.")
    parser.add_argument("--pr", required=True, type=int, help="Pull request number.")
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
        head_sha = fetch_head_sha(token, args.repo, args.pr)
        files = fetch_files(token, args.repo, args.pr)
        if not any_soundness_path(files):
            print("oracle-review: not a soundness path change")
            return PASS
        status, message = decide(
            head_sha,
            fetch_head_date(token, args.repo, head_sha),
            files,
            fetch_reviews(token, args.repo, args.pr),
            fetch_reactions(token, args.repo, args.pr),
            fetch_threads(token, args.repo, args.pr),
            any_soundness_path,
        )
    except (CheckError, KeyError, ValueError) as exc:
        print(f"oracle-review: error: {exc}", file=sys.stderr)
        return ERROR
    print(message)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
