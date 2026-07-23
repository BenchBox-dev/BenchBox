#!/usr/bin/env python3
"""Per-PR dev-loop CI-failure baseline metrics for merged `develop` PRs.

Dev PRs land via squash auto-merge once the required checks are green, so a
merged PR's HEAD-SHA check runs are *always* green (see
`_project/scripts/detect_orphaned_commits.py`'s module docstring for the
related squash-merge mechanics). That makes head-SHA check-run status useless
as a CI-failure signal. The real failure cost shows up upstream of the merge:
fix-forward pushes after a PR is opened, PRs that touch the shared fast-test
guard file (`_project/config/fast_test_lane_policy.json`, a frequent
composition-conflict hotspot), and whether the PR's *first* "Develop PR"
workflow run (the required-lane gate, `.github/workflows/pr.yml`) went green
without a fix-forward push.

This script computes, per merged `develop` PR in a trailing window:

  - pushes_after_open: commits on the PR after its first commit (a proxy for
    fix-forward pushes; the initial push that opened the PR is not a "push
    after open").
  - open_to_merge_seconds: PR created_at -> merged_at wall time.
  - touched_fast_test_lane_policy: whether the PR's file list includes
    _project/config/fast_test_lane_policy.json.
  - first_pass_green: whether the PR's FIRST "Develop PR" (.github/workflows/
    pr.yml) workflow run on its head branch concluded "success" -- i.e. the
    required lane went green without a fix-forward push. Uses per-branch
    Actions run history (event=pull_request), not the always-green head-SHA
    check runs.
  - fast_test_job_seconds: wall time of the "test (ubuntu-latest, 3.12)" job
    within that first "Develop PR" run (used to compute the window's average
    / p95 fast-test job wall time).

Runtime data source, in order of preference: the `gh` CLI (`gh api ...`) when
on PATH; otherwise a raw GitHub REST call via `urllib` authenticated with
$GITHUB_TOKEN / $GH_TOKEN; otherwise this prints a "SKIPPED: no GitHub API
access" notice and exits 0 (mirrors the `|| true` graceful-degradation
pattern the existing `dev-loop-metrics` Make target uses for `gh run list`,
Makefile ~line 1520). This script performs read-only GitHub API calls; it
never mutates PRs, branches, or workflow state.

Usage:
    uv run -- python _project/scripts/dev_loop_pr_metrics.py
    uv run -- python _project/scripts/dev_loop_pr_metrics.py --days 28 --json
    uv run -- python _project/scripts/dev_loop_pr_metrics.py --collect-durations

--collect-durations is a separate, local-machine-only mode: it runs the fast
test lane under `pytest --durations=20` and prints the slowest tests. It does
not touch the GitHub API and is not part of the default run (see the module
TODO context: dev-loop-metrics-ci-failure-baseline-2).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPO = "joeharris76/BenchBox"
FAST_LANE_POLICY_PATH = "_project/config/fast_test_lane_policy.json"
REQUIRED_LANE_WORKFLOW_NAME = "Develop PR"
FAST_TEST_JOB_NAME = "test (ubuntu-latest, 3.12)"
API_RETRY_ATTEMPTS = 3


@dataclass
class PrMetrics:
    number: int
    title: str
    head_ref: str
    created_at: str
    merged_at: str
    open_to_merge_seconds: float
    pushes_after_open: int
    touched_fast_test_lane_policy: bool
    first_pass_green: bool | None
    fast_test_job_seconds: float | None


# ---------------------------------------------------------------------------
# GitHub API access -- gh CLI, then urllib+token, else graceful skip.
# ---------------------------------------------------------------------------
def _gh_available() -> bool:
    return shutil.which("gh") is not None


def _gh_api(path: str) -> object | None:
    """GET *path* via the `gh api` CLI. Returns None on any failure."""
    try:
        proc = subprocess.run(
            ["gh", "api", path],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _urllib_api(path: str, token: str) -> object | None:
    """GET https://api.github.com{path} via urllib. Returns None on failure."""
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "benchbox-dev-loop-pr-metrics",
        },
    )
    for attempt in range(API_RETRY_ATTEMPTS):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                try:
                    return json.load(resp)
                except ValueError:
                    return None
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if attempt == API_RETRY_ATTEMPTS - 1:
                return None
        # TimeoutError/OSError: read-path timeouts are NOT URLError subclasses;
        # they must still resolve to the graceful-skip contract, never a crash.
        except (urllib.error.URLError, TimeoutError, OSError):
            if attempt == API_RETRY_ATTEMPTS - 1:
                return None
    return None


class GitHubClient:
    """Thin GET-only GitHub API client: gh CLI first, urllib+token fallback."""

    def __init__(self, repo: str, use_gh: bool, token: str | None) -> None:
        self.repo = repo
        self.use_gh = use_gh
        self.token = token

    def get(self, path: str) -> object | None:
        if self.use_gh:
            return _gh_api(path)
        if self.token:
            return _urllib_api(path, self.token)
        return None

    def get_paginated(
        self,
        path: str,
        item_key: str | None = None,
        stop: Callable[[dict], bool] | None = None,
    ) -> list[dict]:
        """GET pages of a list endpoint (raw list or {item_key: [...]}).

        `stop` halts pagination once any item on the current page satisfies
        it, so windowed queries do not download the whole collection.
        """
        items: list[dict] = []
        page = 1
        sep = "&" if "?" in path else "?"
        while True:
            data = self.get(f"{path}{sep}per_page=100&page={page}")
            if data is None:
                break
            batch = data.get(item_key, []) if item_key else data
            if not isinstance(batch, list) or not batch:
                break
            items.extend(batch)
            if stop is not None and any(stop(item) for item in batch):
                break
            if len(batch) < 100:
                break
            page += 1
        return items


def make_client(repo: str) -> GitHubClient | None:
    """Return a usable GitHubClient, or None if no API access is available."""
    if _gh_available():
        probe = _gh_api(f"/repos/{repo}")
        if probe is not None:
            return GitHubClient(repo, use_gh=True, token=None)
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        probe = _urllib_api(f"/repos/{repo}", token)
        if probe is not None:
            return GitHubClient(repo, use_gh=False, token=token)
    return None


# ---------------------------------------------------------------------------
# Metric collection
# ---------------------------------------------------------------------------
def _iso_to_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def fetch_merged_prs(client: GitHubClient, since: datetime) -> list[dict]:
    """Merged develop PRs with merged_at >= since, newest first."""
    prs = client.get_paginated(
        f"/repos/{client.repo}/pulls?state=closed&base=develop&sort=updated&direction=desc",
        stop=lambda pr: _iso_to_dt(pr["updated_at"]) < since,
    )
    merged: list[dict] = []
    for pr in prs:
        merged_at = pr.get("merged_at")
        if not merged_at:
            continue
        if _iso_to_dt(merged_at) < since:
            # Results are sorted by `updated`, not `merged_at`; a closed-but-
            # never-merged PR can be more recently updated than an older
            # merge. Filter rather than break, but stop once even `updated`
            # itself has aged out (nothing later in the page can be newer).
            if _iso_to_dt(pr["updated_at"]) < since:
                break
            continue
        merged.append(pr)
    return merged


def pushes_after_open(client: GitHubClient, number: int) -> int:
    commits = client.get_paginated(f"/repos/{client.repo}/pulls/{number}/commits")
    return max(0, len(commits) - 1)


def touched_fast_test_lane_policy(client: GitHubClient, number: int) -> bool:
    files = client.get_paginated(f"/repos/{client.repo}/pulls/{number}/files")
    return any(f.get("filename") == FAST_LANE_POLICY_PATH for f in files)


def first_pass_green_and_job_seconds(client: GitHubClient, head_ref: str) -> tuple[bool | None, float | None]:
    """First "Develop PR" pull_request-event run on head_ref: (green?, fast-test job seconds)."""
    runs = client.get_paginated(
        f"/repos/{client.repo}/actions/runs?branch={head_ref}&event=pull_request",
        item_key="workflow_runs",
    )
    candidates = [r for r in runs if r.get("name") == REQUIRED_LANE_WORKFLOW_NAME]
    if not candidates:
        return None, None
    first_run = min(candidates, key=lambda r: _iso_to_dt(r["created_at"]))
    green = first_run.get("conclusion") == "success"

    job_seconds: float | None = None
    jobs = client.get_paginated(f"/repos/{client.repo}/actions/runs/{first_run['id']}/jobs", item_key="jobs")
    for job in jobs:
        if job.get("name") == FAST_TEST_JOB_NAME and job.get("started_at") and job.get("completed_at"):
            started = _iso_to_dt(job["started_at"])
            completed = _iso_to_dt(job["completed_at"])
            job_seconds = (completed - started).total_seconds()
            break
    return green, job_seconds


def collect_pr_metrics(client: GitHubClient, pr: dict) -> PrMetrics:
    number = pr["number"]
    head_ref = pr["head"]["ref"]
    created_at = pr["created_at"]
    merged_at = pr["merged_at"]
    open_to_merge = (_iso_to_dt(merged_at) - _iso_to_dt(created_at)).total_seconds()
    first_pass_green, fast_test_seconds = first_pass_green_and_job_seconds(client, head_ref)
    return PrMetrics(
        number=number,
        title=pr.get("title", ""),
        head_ref=head_ref,
        created_at=created_at,
        merged_at=merged_at,
        open_to_merge_seconds=open_to_merge,
        pushes_after_open=pushes_after_open(client, number),
        touched_fast_test_lane_policy=touched_fast_test_lane_policy(client, number),
        first_pass_green=first_pass_green,
        fast_test_job_seconds=fast_test_seconds,
    )


def _pct(values: list[float], p: int) -> float | None:
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, max(0, -(-len(s) * p // 100) - 1))
    return s[idx]


def summarize(metrics: list[PrMetrics]) -> dict:
    merge_times = [m.open_to_merge_seconds for m in metrics]
    pushes = [m.pushes_after_open for m in metrics]
    fast_job = [m.fast_test_job_seconds for m in metrics if m.fast_test_job_seconds is not None]
    green_known = [m for m in metrics if m.first_pass_green is not None]
    green_count = sum(1 for m in green_known if m.first_pass_green)
    return {
        "pr_count": len(metrics),
        "open_to_merge_seconds_median": statistics.median(merge_times) if merge_times else None,
        "pushes_after_open_median": statistics.median(pushes) if pushes else None,
        "fast_test_lane_policy_touch_rate": (
            sum(1 for m in metrics if m.touched_fast_test_lane_policy) / len(metrics) if metrics else None
        ),
        "first_pass_green_rate": (green_count / len(green_known)) if green_known else None,
        "first_pass_green_sample_size": len(green_known),
        "fast_test_job_seconds_avg": statistics.fmean(fast_job) if fast_job else None,
        "fast_test_job_seconds_p95": _pct(fast_job, 95),
    }


# ---------------------------------------------------------------------------
# --collect-durations: local-machine-only pytest --durations mode.
# ---------------------------------------------------------------------------
DURATIONS_PYTEST_CMD = [
    "uv",
    "run",
    "--",
    "python",
    "-m",
    "pytest",
    "tests",
    "-m",
    "fast and not (slow or stress or resource_heavy or live_integration)",
    "--durations=20",
    "-q",
    "--no-header",
    "-p",
    "no:cacheprovider",
]


def run_collect_durations() -> int:
    print(
        "Local-machine measure only (wall-clock durations vary by hardware; "
        "not comparable across CI runners or between machines)."
    )
    print(f"Running: {' '.join(DURATIONS_PYTEST_CMD)}")
    proc = subprocess.run(DURATIONS_PYTEST_CMD, cwd=REPO_ROOT, check=False)
    return proc.returncode


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--repo",
        default=os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO),
        help=f"owner/name (default: $GITHUB_REPOSITORY or {DEFAULT_REPO})",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=28,
        help="trailing window in days (default: 28)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON (summary + per-PR rows) instead of text",
    )
    parser.add_argument(
        "--collect-durations",
        action="store_true",
        help=(
            "local-machine-only mode: run the fast test lane with "
            "pytest --durations=20 and print the slowest 20 tests. Does not "
            "touch the GitHub API; mutually exclusive with the default mode."
        ),
    )
    args = parser.parse_args(argv)

    if args.collect_durations:
        return run_collect_durations()

    client = make_client(args.repo)
    if client is None:
        print("SKIPPED: no GitHub API access (no `gh` CLI and no usable GITHUB_TOKEN/GH_TOKEN).")
        return 0

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    prs = fetch_merged_prs(client, since)
    metrics = [collect_pr_metrics(client, pr) for pr in prs]
    summary = summarize(metrics)

    if args.json:
        print(
            json.dumps(
                {
                    "repo": args.repo,
                    "since": since.isoformat(),
                    "summary": summary,
                    "prs": [asdict(m) for m in metrics],
                },
                indent=2,
            )
        )
        return 0

    print(f"Dev-loop PR metrics for {args.repo} since {since.date().isoformat()} ({len(metrics)} merged develop PRs)")
    print(f"  open-to-merge P50: {summary['open_to_merge_seconds_median']!r} seconds")
    print(f"  pushes-after-open P50: {summary['pushes_after_open_median']!r}")
    print(f"  fast_test_lane_policy.json touch rate: {summary['fast_test_lane_policy_touch_rate']!r}")
    print(
        "  first-pass required-lane green rate: "
        f"{summary['first_pass_green_rate']!r} (n={summary['first_pass_green_sample_size']})"
    )
    print(
        f"  fast-test job seconds avg/p95: {summary['fast_test_job_seconds_avg']!r} / {summary['fast_test_job_seconds_p95']!r}"
    )
    for m in metrics:
        print(
            f"  PR #{m.number}: pushes_after_open={m.pushes_after_open} "
            f"open_to_merge_s={m.open_to_merge_seconds:.0f} "
            f"fast_lane_policy_touched={m.touched_fast_test_lane_policy} "
            f"first_pass_green={m.first_pass_green} "
            f"fast_test_job_s={m.fast_test_job_seconds}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
