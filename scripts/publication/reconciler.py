#!/usr/bin/env python3
"""Corpus promotion reconciler — published-results gate and shadow promotion (A8).

Processes JSONL event log entries (merge_sha, base_sha, ts) and validates each
candidate against the current ledger head via set-preserving union.

Usage:
  uv run python scripts/publication/reconciler.py --events-file /tmp/events.jsonl --ledger-head-sha <sha>
  uv run python scripts/publication/reconciler.py --events-file /tmp/events.jsonl --ledger-head-sha <sha> --limit 10 --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PREFIX = "results-data/bundles/"
IGNORED_SUFFIXES = (".manifest.json", ".applied.json", ".plans.json", ".tuning.json", ".gitkeep")
DEFAULT_LIMIT = 100


class ReconcilerError(Exception):
    """Raised when the reconciler encounters a fatal condition."""


def run_git(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command in the repo root."""
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )


def get_corpus_paths(ref: str) -> set[str]:
    """List all primary JSON bundle paths under results-data/bundles/ at *ref*."""
    result = run_git("ls-tree", "-r", "--name-only", ref, "--", CORPUS_PREFIX)
    if result.returncode != 0:
        return set()
    paths: set[str] = set()
    for line in result.stdout.strip().splitlines():
        p = line.strip()
        if not p or not p.endswith(".json"):
            continue
        if any(p.endswith(sfx) for sfx in IGNORED_SUFFIXES):
            continue
        paths.add(p)
    return paths


def verify_merge_commit(merge_sha: str) -> tuple[bool, int, str]:
    """Verify that merge_sha is a real merge commit (2+ parents).

    Returns (is_merge, parent_count, error_message).
    """
    result = run_git("cat-file", "-p", merge_sha)
    if result.returncode != 0:
        return False, 0, f"git cat-file failed for {merge_sha}: {result.stderr.strip()}"

    parents = 0
    for line in result.stdout.splitlines():
        if line.startswith("parent "):
            parents += 1

    if parents < 2:
        return False, parents, f"commit {merge_sha} has {parents} parent(s), expected 2+"
    return True, parents, ""


def verify_base_ancestor(base_sha: str, merge_sha: str) -> tuple[bool, str]:
    """Verify that base_sha is an ancestor of merge_sha."""
    result = run_git("merge-base", "--is-ancestor", base_sha, merge_sha)
    if result.returncode != 0:
        return False, f"{base_sha} is not an ancestor of {merge_sha}"
    return True, ""


def read_event_file(events_path: Path, limit: int) -> list[dict[str, str]]:
    """Read up to *limit* events from a JSONL file."""
    events: list[dict[str, str]] = []
    if not events_path.exists():
        return events
    with events_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
            if len(events) >= limit:
                break
    return events


def reconcile_event(
    event: dict[str, str],
    ledger_head_sha: str,
    generation: int,
) -> tuple[bool, int, str]:
    """Reconcile a single event against the ledger head.

    Returns (accepted, new_generation, reason).
    """
    merge_sha = event.get("merge_sha", "")
    base_sha = event.get("base_sha", "")

    if not merge_sha or len(merge_sha) < 40:
        return False, generation, f"invalid merge_sha: {merge_sha!r}"

    # CRITICAL 3 — Revalidate merge SHA, don't trust dispatch verbatim
    is_merge, parent_count, merge_err = verify_merge_commit(merge_sha)
    if not is_merge:
        return False, generation, f"merge validation failed: {merge_err}"

    # Verify base_sha ancestry
    if not base_sha or len(base_sha) < 40:
        return False, generation, f"invalid base_sha: {base_sha!r}"

    is_ancestor, ancestor_err = verify_base_ancestor(base_sha, merge_sha)
    if not is_ancestor:
        return False, generation, f"ancestry check failed: {ancestor_err}"

    # CRITICAL 1 — Coalesce against ledger head, not candidate parent
    ledger_paths = get_corpus_paths(ledger_head_sha)
    candidate_paths = get_corpus_paths(merge_sha)

    # Every path in the ledger head must exist in the candidate (set-preserving union)
    missing = ledger_paths - candidate_paths
    if missing:
        sorted_missing = sorted(missing)
        return (
            False,
            generation,
            (
                f"coalescing rejected: candidate loses {len(missing)} path(s) "
                f"from ledger head (e.g. {sorted_missing[0]})"
            ),
        )

    new_generation = generation + 1
    return True, new_generation, "accepted"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corpus promotion reconciler")
    parser.add_argument(
        "--events-file",
        type=Path,
        required=True,
        help="Path to JSONL events file",
    )
    parser.add_argument(
        "--ledger-head-sha",
        type=str,
        required=True,
        help="SHA of the current ledger head commit (required, no default)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Maximum events to process (default: {DEFAULT_LIMIT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would happen without making changes",
    )
    args = parser.parse_args(argv)

    # CRITICAL 2 — Reject if --ledger-head-sha is None / empty
    if not args.ledger_head_sha or not args.ledger_head_sha.strip():
        print(json.dumps({"error": "--ledger-head-sha is required and must not be empty"}))
        return 1

    ledger_head_sha = args.ledger_head_sha.strip()

    # Verify ledger_head_sha exists
    result = run_git("cat-file", "-e", ledger_head_sha)
    if result.returncode != 0:
        print(json.dumps({"error": f"ledger_head_sha {ledger_head_sha} does not exist in git"}))
        return 1

    # Read events from file
    events = read_event_file(args.events_file, args.limit)
    if not events:
        print(json.dumps({"status": "no_events", "processed": 0}))
        return 0

    generation = 0
    accepted_count = 0
    rejected_count = 0

    for event in events:
        accepted, new_gen, reason = reconcile_event(event, ledger_head_sha, generation)

        output = {
            "merge_sha": event.get("merge_sha", ""),
            "base_sha": event.get("base_sha", ""),
            "ts": event.get("ts", ""),
            "accepted": accepted,
            "reason": reason,
            "generation": new_gen if accepted else generation,
            "dry_run": args.dry_run,
        }
        print(json.dumps(output))

        if accepted:
            generation = new_gen
            accepted_count += 1
        else:
            rejected_count += 1

    summary = {
        "status": "completed",
        "processed": len(events),
        "accepted": accepted_count,
        "rejected": rejected_count,
        "final_generation": generation,
        "dry_run": args.dry_run,
    }
    print(json.dumps(summary))
    return 1 if rejected_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
