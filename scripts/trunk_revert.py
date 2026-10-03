#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

REPOSITORY = "BenchBox-dev/BenchBox"
BASE_BRANCH = "develop"
TRUNK_WORKFLOW = "trunk.yml"
REVERT_PREFIX = "fix/revert-"
GRACE = timedelta(minutes=30)
RED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})
RUN_FIELDS = "conclusion,status,updatedAt"

Runner = Callable[[list[str]], tuple[int, str]]


class TrunkError(Exception):
    pass


def live_run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout if proc.returncode == 0 else (proc.stderr or proc.stdout)


def _check(run: Runner, cmd: list[str], what: str) -> str:
    code, out = run(cmd)
    if code != 0:
        raise TrunkError(f"{what} failed: {out.strip()}")
    return out


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def trunk_red_since(run: Runner = live_run, repo: str = REPOSITORY) -> datetime | None:
    code, out = run(
        ["gh", "run", "list", "--repo", repo, "--workflow", TRUNK_WORKFLOW, "--branch", BASE_BRANCH]
        + ["--status", "completed", "--limit", "5", "--json", RUN_FIELDS]
    )
    if code != 0:
        raise TrunkError(f"gh run list failed: {out.strip()}")
    try:
        runs = json.loads(out) if out.strip() else []
        if not runs:
            raise TrunkError(f"no {TRUNK_WORKFLOW} runs on {BASE_BRANCH} yet")
        completed = [
            (_parse_time(item["updatedAt"]), item.get("conclusion"))
            for item in runs
            if item.get("status") == "completed"
        ]
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise TrunkError(f"unreadable gh run list output: {exc}") from exc
    for finished, conclusion in sorted(completed, key=lambda pair: pair[0], reverse=True):
        if conclusion == "success":
            return None
        if conclusion in RED_CONCLUSIONS:
            return finished
    return None


def trunk_gate(
    branch: str,
    run: Runner = live_run,
    repo: str = REPOSITORY,
    now: datetime | None = None,
    grace: timedelta = GRACE,
) -> str | None:
    if branch.startswith(REVERT_PREFIX):
        return None
    try:
        red_since = trunk_red_since(run, repo)
    except TrunkError as exc:
        print(f"trunk-gate: warning: could not read {TRUNK_WORKFLOW} runs ({exc}); not blocking", file=sys.stderr)
        return None
    if red_since is None:
        return None
    age = (now or datetime.now(UTC)) - red_since
    if age <= grace:
        return None
    minutes = int(age.total_seconds() // 60)
    return (
        f"develop has been red for {minutes} minutes (newest completed {TRUNK_WORKFLOW} run failed at "
        f"{red_since.isoformat()}). Fix it or revert the culprit with `make trunk-revert PR=<number>`; "
        f"branches named {REVERT_PREFIX}* are exempt."
    )


def revert_commands(number: int, oid: str, title: str, repo: str = REPOSITORY) -> list[list[str]]:
    branch = f"{REVERT_PREFIX}{number}"
    subject = f'Revert "{title}" (#{number})'
    return [
        ["git", "fetch", "origin", BASE_BRANCH, "--quiet"],
        ["git", "switch", "--no-track", "-c", branch, f"origin/{BASE_BRANCH}"],
        ["git", "revert", "--no-edit", oid],
        ["git", "commit", "--amend", "-m", subject, "-m", f"This reverts commit {oid}."],
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--repo", repo, "--base", BASE_BRANCH, "--head", branch, "--fill"],
    ]


def revert(number: int, run: Runner = live_run, repo: str = REPOSITORY) -> int:
    try:
        view = json.loads(
            _check(
                run,
                ["gh", "pr", "view", str(number), "--repo", repo, "--json", "state,mergeCommit,title"],
                f"reading PR #{number}",
            )
        )
        if view.get("state") != "MERGED":
            raise TrunkError(f"PR #{number} is {view.get('state')!r}, not MERGED; there is nothing to revert")
        oid = (view.get("mergeCommit") or {}).get("oid") or ""
        if not re.fullmatch(r"[0-9a-f]{40}", oid):
            raise TrunkError(f"PR #{number} has no usable merge commit ({oid!r})")
        title = view.get("title") or ""
        if not title.strip():
            raise TrunkError(f"PR #{number} has no title")
        if _check(run, ["git", "status", "--porcelain"], "checking the worktree").strip():
            raise TrunkError("the worktree has uncommitted or untracked changes; commit or remove them first")
        fetch, switch, revert_cmd, amend, push, create = revert_commands(number, oid, title, repo)
        _check(run, fetch, "fetching origin/develop")
        _check(
            run,
            ["git", "merge-base", "--is-ancestor", oid, f"origin/{BASE_BRANCH}"],
            f"confirming {oid[:9]} is on origin/{BASE_BRANCH}",
        )
        _check(run, switch, f"creating {REVERT_PREFIX}{number}")
        code, out = run(revert_cmd)
        if code != 0:
            run(["git", "revert", "--abort"])
            raise TrunkError(f"git revert failed (the revert conflicts with later changes?): {out.strip()}")
        _check(run, amend, "writing the revert commit message")
        _check(run, push, "pushing the revert branch")
        print(_check(run, create, "opening the revert PR").strip())
    except (TrunkError, ValueError, AttributeError) as exc:
        print(f"trunk-revert: refusing: {exc}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Revert a merged PR on develop, or gate new PRs while trunk is red.")
    sub = parser.add_subparsers(dest="command", required=True)
    rev = sub.add_parser("revert", help="open a revert PR for a merged PR")
    rev.add_argument("--pr", type=int, required=True)
    rev.add_argument("--repo", default=REPOSITORY)
    gate = sub.add_parser("gate", help="refuse a new branch while trunk is red")
    gate.add_argument("--branch", required=True)
    gate.add_argument("--repo", default=REPOSITORY)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        print(f"trunk: --repo must be owner/name, got {args.repo!r}", file=sys.stderr)
        return 2
    if args.command == "revert":
        if args.pr <= 0:
            print("trunk-revert: --pr must be a positive PR number", file=sys.stderr)
            return 2
        return revert(args.pr, repo=args.repo)
    refusal = trunk_gate(args.branch, repo=args.repo)
    if refusal:
        print(f"Refusing to open PR: {refusal}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
