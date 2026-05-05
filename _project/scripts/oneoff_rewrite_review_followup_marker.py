#!/usr/bin/env python3
"""One-off migration: rewrite the OLD action marker in existing GitHub replies.

Run AFTER the rename PR lands. The PR-review-followup routine previously posted
replies carrying the marker

    benchbox-codex-review-followup-actioned

The rename moved the marker to

    benchbox-pr-review-followup-actioned

Existing replies on GitHub still carry the OLD marker, so the new routine
would re-action threads that were already actioned. This script walks merged
PRs, finds review-comment replies whose body contains the OLD marker, and
PATCHes each one in place to use the NEW marker. Body content otherwise
unchanged.

Dry-run by default (lists matches, no writes). Pass --apply to mutate.

After this lands successfully, delete this script in a follow-up PR — it is
intentionally one-off and not part of the routine surface.

Usage:
  uv run -- python _project/scripts/oneoff_rewrite_review_followup_marker.py
  uv run -- python _project/scripts/oneoff_rewrite_review_followup_marker.py --apply
  uv run -- python _project/scripts/oneoff_rewrite_review_followup_marker.py \
      --repo joeharris76/BenchBox --since 2026-01-01 --apply
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

OLD_MARKER = "benchbox-codex-review-followup-actioned"
NEW_MARKER = "benchbox-pr-review-followup-actioned"


@dataclass(frozen=True)
class CommentHit:
    pr_number: int
    comment_id: int
    html_url: str
    body: str


def gh_json(args: list[str]) -> Any:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh failed ({result.returncode}): {' '.join(args)}\n{result.stderr.strip()}")
    text = result.stdout.strip()
    return json.loads(text) if text else None


def list_merged_prs(repo: str, since: str | None, limit: int) -> list[int]:
    args = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "merged",
        "--base",
        "develop",
        "--limit",
        str(limit),
        "--json",
        "number,mergedAt",
    ]
    raw = gh_json(args) or []
    numbers: list[int] = []
    for item in raw:
        merged_at = str(item.get("mergedAt") or "")
        if since and merged_at and merged_at < since:
            continue
        numbers.append(int(item["number"]))
    # Also check open PRs — markers can land on those too.
    open_args = [
        "gh",
        "pr",
        "list",
        "--repo",
        repo,
        "--state",
        "open",
        "--base",
        "develop",
        "--limit",
        str(limit),
        "--json",
        "number",
    ]
    for item in gh_json(open_args) or []:
        numbers.append(int(item["number"]))
    return sorted(set(numbers))


def fetch_review_comments(repo: str, pr_number: int) -> list[dict[str, Any]]:
    args = [
        "gh",
        "api",
        "--paginate",
        f"repos/{repo}/pulls/{pr_number}/comments?per_page=100",
        "--jq",
        ".[] | @json",
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"gh failed for PR #{pr_number}: {result.stderr.strip()}")
    rows: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def collect_hits(repo: str, since: str | None, limit: int) -> list[CommentHit]:
    hits: list[CommentHit] = []
    for pr_number in list_merged_prs(repo, since, limit):
        for comment in fetch_review_comments(repo, pr_number):
            body = str(comment.get("body") or "")
            if OLD_MARKER not in body:
                continue
            hits.append(
                CommentHit(
                    pr_number=pr_number,
                    comment_id=int(comment["id"]),
                    html_url=str(comment.get("html_url") or ""),
                    body=body,
                )
            )
    return hits


def patch_comment(repo: str, comment_id: int, new_body: str) -> None:
    args = [
        "gh",
        "api",
        "-X",
        "PATCH",
        f"repos/{repo}/pulls/comments/{comment_id}",
        "-f",
        f"body={new_body}",
    ]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"PATCH failed for comment {comment_id}: {result.stderr.strip()}")


def resolve_repo(explicit: str | None) -> str:
    if explicit:
        return explicit
    args = ["gh", "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"]
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError("Could not resolve repo via `gh repo view`. Pass --repo.")
    name = result.stdout.strip()
    if not name:
        raise RuntimeError("Empty repo name from `gh repo view`. Pass --repo.")
    return name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("PR_REVIEW_REPO"))
    parser.add_argument(
        "--since",
        default=None,
        help="Only scan PRs merged on or after this ISO date (YYYY-MM-DD). Default: all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1000,
        help="Max PRs to fetch per state (open/merged). Default: 1000.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually PATCH the comments. Without this flag, only print matches.",
    )
    args = parser.parse_args(argv)

    repo = resolve_repo(args.repo)
    print(f"Scanning {repo} for replies containing OLD marker `{OLD_MARKER}` ...")
    hits = collect_hits(repo, args.since, args.limit)

    if not hits:
        print("No replies with the OLD marker found. Nothing to do.")
        return 0

    print(f"\nFound {len(hits)} reply comment(s) carrying the OLD marker:\n")
    for hit in hits:
        print(f"  PR #{hit.pr_number} comment {hit.comment_id}: {hit.html_url}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to PATCH each comment.")
        return 0

    print(f"\nApplying rewrite ({OLD_MARKER} -> {NEW_MARKER}) ...")
    failures: list[CommentHit] = []
    for hit in hits:
        new_body = hit.body.replace(OLD_MARKER, NEW_MARKER)
        try:
            patch_comment(repo, hit.comment_id, new_body)
            print(f"  patched PR #{hit.pr_number} comment {hit.comment_id}")
        except RuntimeError as exc:
            print(f"  FAILED  PR #{hit.pr_number} comment {hit.comment_id}: {exc}", file=sys.stderr)
            failures.append(hit)

    if failures:
        print(f"\n{len(failures)} comment(s) failed to update. Re-run --apply to retry.")
        return 1
    print(f"\nDone. {len(hits)} comment(s) rewritten to the new marker.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
