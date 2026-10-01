#!/usr/bin/env python3
"""Arm a pull request for its exact head after a live check that nothing holds it.

The merge queue and the required status checks decide whether a PR merges; this
helper only enqueues the head the author pushed. It reads the live PR first and
refuses, without merging, when a durable hold, a requested change, a draft or
closed state, or a head other than the local one says the PR is not ready to be
armed. Re-enqueueing after a spurious queue ejection uses the same command, so
a policy hold is never mistaken for a queue failure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Callable, Sequence

HOLD_LABEL = "no-auto-merge"
REPOSITORY = "BenchBox-dev/BenchBox"

Runner = Callable[[Sequence[str]], tuple[int, str]]


def _run(cmd: Sequence[str]) -> tuple[int, str]:
    proc = subprocess.run(list(cmd), text=True, capture_output=True, timeout=120, check=False)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def refusals(view: dict, head: str) -> list[str]:
    """Return why the live PR must not be armed; an empty list means it may be."""
    reasons: list[str] = []
    if view.get("state") != "OPEN":
        reasons.append(f"PR is {view.get('state')!r}, not OPEN")
    if view.get("isDraft"):
        reasons.append("PR is a draft")
    labels = {label.get("name") for label in view.get("labels") or []}
    if HOLD_LABEL in labels:
        reasons.append(f"durable hold label {HOLD_LABEL!r} is present; remove it deliberately to release the hold")
    if view.get("reviewDecision") == "CHANGES_REQUESTED":
        reasons.append("a reviewer requested changes")
    if view.get("headRefOid") != head:
        reasons.append(f"pushed head {str(view.get('headRefOid'))[:9]} is not local HEAD {head[:9]}; push first")
    return reasons


def arm(pr: str | None, head: str | None, repo: str = REPOSITORY, run: Runner = _run) -> int:
    if head is None:
        code, out = run(["git", "rev-parse", "HEAD"])
        if code != 0:
            print(f"pr-arm: cannot read local HEAD: {out.strip()}", file=sys.stderr)
            return 1
        head = out.strip()
    selector = [pr] if pr else []
    code, out = run(
        [
            "gh",
            "pr",
            "view",
            *selector,
            "--repo",
            repo,
            "--json",
            "number,state,isDraft,labels,reviewDecision,headRefOid",
        ]
    )
    if code != 0:
        print(f"pr-arm: cannot read the pull request: {out.strip()}", file=sys.stderr)
        return 1
    try:
        view = json.loads(out)
    except json.JSONDecodeError:
        print(f"pr-arm: unreadable pull request state: {out[:200]!r}", file=sys.stderr)
        return 1
    reasons = refusals(view, head)
    if reasons:
        for reason in reasons:
            print(f"pr-arm: refusing to arm PR #{view.get('number')}: {reason}", file=sys.stderr)
        return 2
    code, out = run(["gh", "pr", "merge", str(view["number"]), "--repo", repo, "--squash", "--match-head-commit", head])
    print(out.strip())
    return code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pr", help="pull request number; default: the PR for the current branch")
    parser.add_argument("--head", help="exact head SHA to arm; default: local HEAD")
    parser.add_argument("--repo", default=REPOSITORY)
    args = parser.parse_args(argv)
    return arm(args.pr, args.head, args.repo)


if __name__ == "__main__":
    raise SystemExit(main())
