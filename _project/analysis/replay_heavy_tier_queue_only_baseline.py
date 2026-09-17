#!/usr/bin/env python3
"""Replay the pinned heavy-tier queue-only baseline cohort.

The cohort covers ``pr.yml`` runs with events ``pull_request`` and
``merge_group`` created in [WINDOW_START, WINDOW_END]. The manifest pins every
run ID in that window plus the expected per-job aggregates (runner-minutes,
failure/cancellation counts, p50/p90). The replay re-fetches those runs and
their jobs read-only from the GitHub API and requires:

1. the live windowed run-ID set to equal the pinned set exactly, and
2. the recomputed aggregates to match the pinned expected values.

An offline mode recomputes from local runs/jobs JSON snapshots (the same shape
as the collectors in the handoff evidence directory produce) for manifest
construction audits without spending API budget::

    uv run -- python _project/analysis/replay_heavy_tier_queue_only_baseline.py --self-test
    uv run -- python _project/analysis/replay_heavy_tier_queue_only_baseline.py \\
        --offline --runs-json <runs-pr.yml.json> --jobs-json <jobs-pr.yml.json>

The live replay needs ``gh`` auth and roughly one jobs call per pinned run
(~1,100 calls); it checks the rate-limit budget first and refuses when the
remaining budget is below the estimate. Durations come from job
``started_at``/``completed_at`` timestamps; jobs with conclusion ``None`` or
``skipped``, or with missing timestamps, are excluded exactly as in the
baseline collectors.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = Path(__file__).with_name("heavy-tier-queue-only-2026-09-16-manifest.json")

WINDOW_START = "2026-08-23T00:00:00Z"
WINDOW_END = "2026-09-16T23:59:59Z"
WORKFLOW_FILE = "pr.yml"

HEAVY_JOBS = (
    "medium-test",
    "correctness-gate",
    "plan-capture-gate",
    "tpch-binary-framing",
    "postgres-integration",
    "datafusion-integration",
    "clickhouse-integration",
)
# Jobs whose failure fails ci-required-result on a code-routed tree today.
GATING_HEAVY_JOBS = frozenset({"medium-test", "correctness-gate", "plan-capture-gate", "tpch-binary-framing"})
# continue-on-error samples: red but never blocking.
SAMPLE_HEAVY_JOBS = frozenset({"postgres-integration", "datafusion-integration", "clickhouse-integration"})

MINUTES_TOLERANCE = 0.5
PCTL_TOLERANCE = 0.05


class ReplayError(RuntimeError):
    """The pinned cohort could not be replayed exactly."""


def normalize_job_name(name: str) -> str:
    """Map matrix-expanded display names to canonical job keys."""
    if name.startswith("TPC-H binary framing"):
        return "tpch-binary-framing"
    if name.startswith("test ("):
        return "code-test"
    return name


def _timestamp(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def job_minutes(job: dict[str, Any]) -> float | None:
    """Minutes between started_at and completed_at, or None when excluded.

    Rows with a real conclusion and present, parseable timestamps count even
    when completed_at precedes started_at by a second: startup-cancelled jobs
    carry that clock skew (run 32797475819, thirteen jobs at -1s each), and
    the baseline collectors count them, so excluding them would move the
    pinned cancellation counts.
    """
    if job.get("conclusion") in (None, "skipped"):
        return None
    if not job.get("started_at") or not job.get("completed_at"):
        return None
    try:
        delta = _timestamp(job["completed_at"]) - _timestamp(job["started_at"])
    except (ValueError, TypeError):
        return None
    minutes = delta.total_seconds() / 60
    if math.isnan(minutes) or math.isinf(minutes):
        return None
    return minutes


def aggregate(
    runs: dict[str, dict[str, Any]],
    jobs: dict[str, list[dict[str, Any]]],
    event: str,
) -> dict[str, Any]:
    """Aggregate per-job stats for one event within the pinned window."""
    per_job: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"ran": 0, "fail": 0, "cancelled": 0, "minutes": 0.0, "success_minutes": []}
    )
    run_count = 0
    for run_id, run in runs.items():
        if run.get("event") != event:
            continue
        created = str(run.get("created_at") or "")
        if not (WINDOW_START <= created <= WINDOW_END):
            continue
        if run_id not in jobs:
            raise ReplayError(f"run {run_id} has no jobs payload")
        run_count += 1
        for job in jobs[run_id]:
            minutes = job_minutes(job)
            if minutes is None:
                continue
            key = normalize_job_name(str(job.get("name") or ""))
            entry = per_job[key]
            entry["ran"] += 1
            entry["minutes"] += minutes
            conclusion = job.get("conclusion")
            if conclusion == "failure":
                entry["fail"] += 1
            elif conclusion == "cancelled":
                entry["cancelled"] += 1
            elif conclusion == "success":
                entry["success_minutes"].append(minutes)
    result: dict[str, Any] = {"runs": run_count, "total_minutes": 0.0, "jobs": {}}
    for name in sorted(per_job):
        entry = per_job[name]
        ordered = sorted(entry["success_minutes"])
        if ordered:
            p50 = statistics.median(ordered)
            p90 = ordered[int(0.9 * (len(ordered) - 1))]
        else:
            p50 = 0.0
            p90 = 0.0
        result["jobs"][name] = {
            "ran": entry["ran"],
            "fail": entry["fail"],
            "cancelled": entry["cancelled"],
            "minutes": round(entry["minutes"], 1),
            "p50": round(p50, 1),
            "p90": round(p90, 1),
        }
        result["total_minutes"] += entry["minutes"]
    result["total_minutes"] = round(result["total_minutes"], 1)
    return result


def heavy_failures(
    runs: dict[str, dict[str, Any]],
    jobs: dict[str, list[dict[str, Any]]],
    event: str,
) -> list[dict[str, Any]]:
    """Runs in the window/event where a heavy-tier job concluded failure."""
    found = []
    for run_id, run in runs.items():
        if run.get("event") != event:
            continue
        created = str(run.get("created_at") or "")
        if not (WINDOW_START <= created <= WINDOW_END):
            continue
        conclusions = {}
        for job in jobs.get(run_id, []):
            if job.get("conclusion") in (None, "skipped"):
                continue
            conclusions.setdefault(normalize_job_name(str(job.get("name") or "")), job["conclusion"])
        failed = sorted(name for name in HEAVY_JOBS if conclusions.get(name) == "failure")
        if failed:
            found.append(
                {
                    "run_id": int(run_id),
                    "created_at": created,
                    "head_branch": run.get("head_branch"),
                    "head_sha": run.get("head_sha"),
                    "failed_jobs": failed,
                    "gating": sorted(name for name in failed if name in GATING_HEAVY_JOBS),
                }
            )
    return sorted(found, key=lambda row: row["run_id"])


def _assert_close(actual: float, expected: float, tolerance: float, label: str) -> None:
    if not math.isclose(actual, expected, abs_tol=tolerance):
        raise ReplayError(f"{label} differs: expected {expected!r}, got {actual!r}")


def check_against_expected(actual: dict[str, Any], expected: dict[str, Any], event: str) -> None:
    """Require recomputed aggregates to match the pinned expectations."""
    if actual["runs"] != expected["runs"]:
        raise ReplayError(f"{event} run count differs: expected {expected['runs']!r}, got {actual['runs']!r}")
    _assert_close(actual["total_minutes"], expected["total_minutes"], MINUTES_TOLERANCE, f"{event} total")
    expected_jobs = expected["jobs"]
    if set(actual["jobs"]) != set(expected_jobs):
        missing = sorted(set(expected_jobs) - set(actual["jobs"]))
        extra = sorted(set(actual["jobs"]) - set(expected_jobs))
        raise ReplayError(f"{event} job set differs: missing={missing}, extra={extra}")
    for name, want in expected_jobs.items():
        got = actual["jobs"][name]
        for key in ("ran", "fail", "cancelled"):
            if got[key] != want[key]:
                raise ReplayError(f"{event}/{name} {key} differs: expected {want[key]!r}, got {got[key]!r}")
        _assert_close(got["minutes"], want["minutes"], MINUTES_TOLERANCE, f"{event}/{name} minutes")
        _assert_close(got["p50"], want["p50"], PCTL_TOLERANCE, f"{event}/{name} p50")
        _assert_close(got["p90"], want["p90"], PCTL_TOLERANCE, f"{event}/{name} p90")


def check_failures(actual: list[dict[str, Any]], expected: list[dict[str, Any]], event: str) -> None:
    """Require the heavy-failure run set to match the pinned run IDs."""
    actual_ids = [(row["run_id"], tuple(row["failed_jobs"])) for row in actual]
    expected_ids = [(int(row["run_id"]), tuple(row["failed_jobs"])) for row in expected]
    if actual_ids != expected_ids:
        raise ReplayError(f"{event} heavy-failure set differs: expected {expected_ids!r}, got {actual_ids!r}")


def _gh_api(path: str) -> Any:
    completed = subprocess.run(["gh", "api", path], check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        raise ReplayError(f"GitHub API read failed: {path}: {completed.stderr[:200]}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ReplayError(f"GitHub API returned non-JSON for {path}") from error


def _rate_limit_remaining() -> int:
    try:
        with urllib.request.urlopen("https://api.github.com/rate_limit", timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return int(payload["resources"]["core"]["remaining"])
    except (OSError, ValueError, KeyError, TypeError):
        completed = subprocess.run(
            ["gh", "api", "rate_limit", "--jq", ".resources.core.remaining"],
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            return int(completed.stdout.strip())
        except ValueError:
            return -1


def fetch_live(repo: str, manifest: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch the pinned window's runs and jobs read-only via gh."""
    pinned_pr = {int(run_id) for run_id in manifest["pull_request_run_ids"]}
    pinned_mg = {int(run_id) for run_id in manifest["merge_group_run_ids"]}
    budget = len(pinned_pr) + len(pinned_mg)
    remaining = _rate_limit_remaining()
    if 0 <= remaining < budget + 50:
        raise ReplayError(
            f"insufficient API budget: {budget} jobs calls plus listing pages needed, "
            f"{remaining} remaining; wait for reset instead of a partial replay"
        )
    discovered: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        payload = _gh_api(f"repos/{repo}/actions/workflows/{WORKFLOW_FILE}/runs?per_page=100&page={page}")
        batch = payload.get("workflow_runs") or []
        if not batch:
            break
        for run in batch:
            created = str(run.get("created_at") or "")
            if created < WINDOW_START:
                continue
            if created > WINDOW_END:
                continue
            if run.get("event") not in ("pull_request", "merge_group"):
                continue
            discovered[str(run["id"])] = {
                k: run.get(k)
                for k in (
                    "id",
                    "event",
                    "status",
                    "conclusion",
                    "created_at",
                    "head_branch",
                    "head_sha",
                )
            }
        oldest = min(str(run.get("created_at") or "") for run in batch)
        if oldest < WINDOW_START:
            break
        page += 1
        if page > 60:
            raise ReplayError("run listing exceeded 60 pages without reaching the window start")
    live_pr = set(int(k) for k, v in discovered.items() if v["event"] == "pull_request")
    live_mg = set(int(k) for k, v in discovered.items() if v["event"] == "merge_group")
    if live_pr != pinned_pr or live_mg != pinned_mg:
        raise ReplayError(
            "live windowed run set differs from manifest: "
            f"pr missing={sorted(pinned_pr - live_pr)}, pr extra={sorted(live_pr - pinned_pr)}, "
            f"mg missing={sorted(pinned_mg - live_mg)}, mg extra={sorted(live_mg - pinned_mg)}"
        )
    jobs: dict[str, list[dict[str, Any]]] = {}
    for run_id in sorted(pinned_pr | pinned_mg):
        payload = _gh_api(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100&filter=all")
        entries = payload.get("jobs") or []
        foreign = [job.get("id") for job in entries if int(job.get("run_id") or -1) != run_id]
        if foreign:
            raise ReplayError(f"run {run_id} returned jobs owned by another run: {foreign}")
        jobs[str(run_id)] = [
            {k: job.get(k) for k in ("name", "status", "conclusion", "started_at", "completed_at")} for job in entries
        ]
    return discovered, jobs


def offline_inputs(runs_path: Path, jobs_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load local runs/jobs snapshots keyed by run ID string."""
    runs_raw = json.loads(runs_path.read_text(encoding="utf-8"))
    jobs_raw = json.loads(jobs_path.read_text(encoding="utf-8"))
    if isinstance(runs_raw, dict):
        run_list = runs_raw.get("workflow_runs", list(runs_raw.values()))
    else:
        run_list = runs_raw
    runs = {str(run["id"]): run for run in run_list}
    jobs = {str(key): value for key, value in jobs_raw.items()}
    return runs, jobs


def replay_offline(manifest: dict[str, Any], runs_path: Path, jobs_path: Path) -> dict[str, Any]:
    """Recompute from local snapshots and check against the manifest."""
    runs, jobs = offline_inputs(runs_path, jobs_path)
    pinned = {str(i) for i in manifest["pull_request_run_ids"]} | {str(i) for i in manifest["merge_group_run_ids"]}
    windowed = {
        run_id
        for run_id, run in runs.items()
        if run.get("event") in ("pull_request", "merge_group")
        and WINDOW_START <= str(run.get("created_at") or "") <= WINDOW_END
    }
    if windowed != pinned:
        raise ReplayError(
            "snapshot windowed run set differs from manifest: "
            f"missing={sorted(pinned - windowed)[:10]}, extra={sorted(windowed - pinned)[:10]}"
        )
    return verify_aggregates(manifest, runs, jobs)


def verify_aggregates(manifest: dict[str, Any], runs: dict[str, Any], jobs: dict[str, Any]) -> dict[str, Any]:
    """Aggregate both events and check counts, minutes, and failure sets."""
    expected = manifest["expected"]
    actual_pr = aggregate(runs, jobs, "pull_request")
    actual_mg = aggregate(runs, jobs, "merge_group")
    check_against_expected(actual_pr, expected["pull_request"], "pull_request")
    check_against_expected(actual_mg, expected["merge_group"], "merge_group")
    failures_pr = heavy_failures(runs, jobs, "pull_request")
    failures_mg = heavy_failures(runs, jobs, "merge_group")
    check_failures(failures_pr, manifest["heavy_failures_pull_request"], "pull_request")
    gating_mg = [row for row in failures_mg if row["gating"]]
    if gating_mg != []:
        raise ReplayError(f"merge_group gating failures differ: got {gating_mg!r}")
    if [row["run_id"] for row in failures_mg] != [
        int(row["run_id"]) for row in manifest["merge_group_sample_failures"]
    ]:
        raise ReplayError("merge_group sample-failure run IDs differ from manifest")
    cancellations = {
        name: expected["pull_request"]["jobs"][name]["cancelled"] for name in ("medium-test", "correctness-gate")
    }
    if cancellations != manifest["superseded_cancellations"]:
        raise ReplayError(f"superseded cancellation counts differ: got {cancellations!r}")
    return {
        "verified_against_manifest": True,
        "pull_request": actual_pr,
        "merge_group": actual_mg,
        "heavy_failures_pull_request": failures_pr,
        "heavy_failures_merge_group": failures_mg,
    }


def _expect_replay_error(label: str, action: object) -> None:
    assert callable(action)
    try:
        action()
    except ReplayError:
        return
    raise ReplayError(f"negative control did not fail: {label}")


def self_test() -> None:
    """Offline unit checks plus negative controls; no network access."""
    if normalize_job_name("TPC-H binary framing (macos-latest)") != "tpch-binary-framing":
        raise ReplayError("tpch name normalization regression")
    if normalize_job_name("test (ubuntu-latest, 3.12)") != "code-test":
        raise ReplayError("code-test name normalization regression")
    if normalize_job_name("medium-test") != "medium-test":
        raise ReplayError("plain name normalization regression")

    good = {
        "name": "medium-test",
        "conclusion": "success",
        "started_at": "2026-09-01T00:00:00Z",
        "completed_at": "2026-09-01T00:21:12Z",
    }
    if job_minutes(good) != 21.2:
        raise ReplayError(f"duration regression: {job_minutes(good)}")
    skipped = dict(good, conclusion="skipped")
    if job_minutes(skipped) is not None:
        raise ReplayError("skipped jobs must be excluded")
    missing = dict(good)
    del missing["completed_at"]
    if job_minutes(missing) is not None:
        raise ReplayError("jobs without timestamps must be excluded (fail open)")
    bad = dict(good, started_at="not-a-timestamp")
    if job_minutes(bad) is not None:
        raise ReplayError("unparseable timestamps must be excluded (fail open)")
    skew = dict(
        good,
        conclusion="cancelled",
        started_at="2026-09-01T00:00:01Z",
        completed_at="2026-09-01T00:00:00Z",
    )
    if job_minutes(skew) is None:
        raise ReplayError("startup-cancelled clock-skew rows must count like the baseline")

    runs = {
        "1": {"id": 1, "event": "pull_request", "created_at": "2026-09-01T00:00:00Z"},
        "2": {"id": 2, "event": "merge_group", "created_at": "2026-09-01T00:00:00Z"},
        "3": {"id": 3, "event": "pull_request", "created_at": "2026-08-01T00:00:00Z"},
    }
    jobs = {
        "1": [
            dict(good),
            {
                "name": "medium-test",
                "conclusion": "cancelled",
                "started_at": "2026-09-01T01:00:00Z",
                "completed_at": "2026-09-01T01:05:00Z",
            },
        ],
        "2": [dict(good, name="postgres-integration", conclusion="failure")],
        "3": [dict(good)],
    }
    pr = aggregate(runs, jobs, "pull_request")
    if pr["runs"] != 1 or pr["jobs"]["medium-test"]["ran"] != 2:
        raise ReplayError(f"aggregation regression: {pr}")
    if pr["jobs"]["medium-test"]["cancelled"] != 1:
        raise ReplayError("cancelled counting regression")
    mg_failures = heavy_failures(runs, jobs, "merge_group")
    if len(mg_failures) != 1 or mg_failures[0]["gating"] != []:
        raise ReplayError("sample (continue-on-error) failures must not count as gating")

    _expect_replay_error(
        "altered expected total",
        lambda: check_against_expected(
            pr,
            {"runs": 1, "total_minutes": pr["total_minutes"] + 100.0, "jobs": pr["jobs"]},
            "pull_request",
        ),
    )
    _expect_replay_error(
        "altered failure set",
        lambda: check_failures([{"run_id": 9, "failed_jobs": ["medium-test"]}], [], "pull_request"),
    )
    print(
        "PASS: name normalization, duration parsing with fail-open exclusions, "
        "windowed aggregation, gating-vs-sample failure split, and negative controls"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--runs-json", type=Path, default=None)
    parser.add_argument("--jobs-json", type=Path, default=None)
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("window_start") != WINDOW_START or manifest.get("window_end") != WINDOW_END:
        raise ReplayError("manifest window does not match this replay script")
    if args.offline:
        if not args.runs_json or not args.jobs_json:
            raise ReplayError("--offline requires --runs-json and --jobs-json")
        result = replay_offline(manifest, args.runs_json, args.jobs_json)
    else:
        runs, jobs = fetch_live(str(manifest["repository"]), manifest)
        result = verify_aggregates(manifest, runs, jobs)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ReplayError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
