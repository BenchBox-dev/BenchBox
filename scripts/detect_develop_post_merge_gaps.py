#!/usr/bin/env python3
"""Detect develop commits that never got a develop-post-merge workflow run.

GitHub has been observed to drop push delivery for consecutive develop merges
(see docs/operations/develop-post-merge-gaps.md). When that happens, the
push-triggered ``develop-post-merge.yml`` workflow never starts for those
SHAs, so develop tip can sit un-gated until the next successful delivery or
the scheduled sweep.

This script is the instrumentation half of the fix:

- given recent develop commit SHAs and recent ``develop-post-merge`` run
  head SHAs, report which commits lack any run (any status/conclusion);
- exit non-zero when gaps remain so a scheduled/canary workflow can fail
  loudly instead of silently.

It does **not** open PRs, re-run gates, or mutate repository state. The
scheduled sweep in ``develop-post-merge.yml`` is the coverage half: it re-runs
the same gates against the current tip within a bounded window.

Usage:
    # Offline / unit-testable pure check (stdin or flags):
    python scripts/detect_develop_post_merge_gaps.py \\
        --commits-file commits.txt --runs-file runs.txt

    # Live check against origin/develop + GitHub Actions API via gh:
    python scripts/detect_develop_post_merge_gaps.py --live

Exit codes:
    0 - every looked-up SHA has at least one develop-post-merge run
    1 - one or more SHAs lack a run (gap class still present)
    2 - usage / I/O error
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_COMMIT_LIMIT = 20
DEFAULT_RUN_LIMIT = 100
WORKFLOW_FILE = "develop-post-merge.yml"


# ---------------------------------------------------------------------------
# Pure logic (unit-tested; no git/network)
# ---------------------------------------------------------------------------
def normalize_sha(value: str) -> str:
    """Lowercase full/short SHA; reject empty tokens."""
    sha = value.strip().lower()
    if not sha:
        raise ValueError("empty SHA")
    return sha


def parse_sha_lines(text: str) -> list[str]:
    """Parse one SHA per line; ignore blanks and # comments."""
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # Allow "sha message..." lines from `git log --format=%H %s`.
        token = line.split()[0]
        out.append(normalize_sha(token))
    return out


def find_uncovered(commit_shas: list[str], run_head_shas: set[str]) -> list[str]:
    """Return commit SHAs (in order) that have no matching run headSha.

    Matching is prefix-aware so a short run headSha can cover a full commit
    SHA and vice versa (gh sometimes returns full SHAs; tests may use shorts).
    """
    normalized_runs = {normalize_sha(s) for s in run_head_shas}
    uncovered: list[str] = []
    for commit in commit_shas:
        c = normalize_sha(commit)
        if any(c == r or c.startswith(r) or r.startswith(c) for r in normalized_runs):
            continue
        uncovered.append(c)
    return uncovered


def format_report(
    commit_shas: list[str],
    uncovered: list[str],
    *,
    commit_limit: int,
    run_count: int,
) -> str:
    """Human-readable summary for logs / job annotations."""
    lines = [
        "develop-post-merge gap detector",
        f"  commits checked: {len(commit_shas)} (limit {commit_limit})",
        f"  run headShas supplied: {run_count}",
        f"  uncovered: {len(uncovered)}",
    ]
    if uncovered:
        lines.append("  missing develop-post-merge run for:")
        for sha in uncovered:
            lines.append(f"    - {sha}")
        lines.append(
            "  A missing SHA means GitHub never delivered (or never recorded) a "
            "push-triggered develop-post-merge run for that commit. The hourly "
            "schedule on develop-post-merge.yml re-gates the *tip* only; this "
            "detector keeps intermediate push-drop SHAs visible until they age "
            "out of the lookback window. See docs/operations/develop-post-merge-gaps.md."
        )
    else:
        lines.append("  all checked develop commits have at least one post-merge run.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Live I/O (git + gh)
# ---------------------------------------------------------------------------
def _run(cmd: list[str]) -> str:
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"required executable not found: {cmd[0]}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        raise RuntimeError(f"command failed ({exc.returncode}): {' '.join(cmd)}\n{stderr}") from exc
    return completed.stdout


def live_commit_shas(limit: int, branch: str = "origin/develop") -> list[str]:
    out = _run(["git", "log", "--format=%H", f"-{limit}", branch])
    return parse_sha_lines(out)


def live_run_head_shas(limit: int, workflow: str = WORKFLOW_FILE) -> set[str]:
    """List recent workflow run headShas via the gh CLI.

    Includes every status/conclusion: a queued or failed run still proves the
    push was not silently dropped. Only a total absence of runs for a SHA is
    a gap.
    """
    raw = _run(
        [
            "gh",
            "run",
            "list",
            f"--workflow={workflow}",
            f"--limit={limit}",
            "--json",
            "headSha",
        ]
    )
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh run list returned non-JSON: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError("gh run list JSON was not a list")
    shas: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        head = row.get("headSha")
        if isinstance(head, str) and head.strip():
            shas.add(normalize_sha(head))
    return shas


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Read origin/develop commits and gh run list (requires git + gh).",
    )
    parser.add_argument(
        "--commits-file",
        type=Path,
        help="File of develop commit SHAs (one per line). Required unless --live.",
    )
    parser.add_argument(
        "--runs-file",
        type=Path,
        help="File of develop-post-merge run headShas (one per line). Required unless --live.",
    )
    parser.add_argument(
        "--commit-limit",
        type=int,
        default=DEFAULT_COMMIT_LIMIT,
        help=f"How many recent develop commits to check (live mode). Default {DEFAULT_COMMIT_LIMIT}.",
    )
    parser.add_argument(
        "--run-limit",
        type=int,
        default=DEFAULT_RUN_LIMIT,
        help=f"How many recent workflow runs to load (live mode). Default {DEFAULT_RUN_LIMIT}.",
    )
    parser.add_argument(
        "--branch",
        default="origin/develop",
        help="git rev-list/log target for --live (default origin/develop).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON on stdout (human report still goes to stderr).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.live:
            if args.commit_limit < 1 or args.run_limit < 1:
                raise RuntimeError("--commit-limit and --run-limit must be >= 1")
            commit_shas = live_commit_shas(args.commit_limit, branch=args.branch)
            run_shas = live_run_head_shas(args.run_limit)
        else:
            if args.commits_file is None or args.runs_file is None:
                parser.error("provide --live, or both --commits-file and --runs-file")
            commit_shas = parse_sha_lines(args.commits_file.read_text(encoding="utf-8"))
            run_shas = set(parse_sha_lines(args.runs_file.read_text(encoding="utf-8")))
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    uncovered = find_uncovered(commit_shas, run_shas)
    report = format_report(
        commit_shas,
        uncovered,
        commit_limit=args.commit_limit if args.live else len(commit_shas),
        run_count=len(run_shas),
    )
    # Human report on stderr so --json stdout stays pure.
    sys.stderr.write(report)
    if uncovered:
        for sha in uncovered:
            # GitHub Actions annotation when running in CI.
            print(f"::error title=develop-post-merge gap::No develop-post-merge run for {sha}", file=sys.stderr)

    if args.json:
        payload = {
            "commits_checked": commit_shas,
            "run_head_shas": sorted(run_shas),
            "uncovered": uncovered,
            "ok": not uncovered,
        }
        json.dump(payload, sys.stdout, indent=2, sort_keys=True)
        sys.stdout.write("\n")

    return 1 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
