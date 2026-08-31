#!/usr/bin/env python3
"""Replay the exact 2026-08-31 CI-waste cohort from its pinned manifest."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any, cast

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from _project.scripts import dev_loop_pr_metrics as metrics  # noqa: E402
from scripts import path_filter_decision as path_filter  # noqa: E402

DEFAULT_MANIFEST = Path(__file__).with_name("ci-waste-remeasure-2026-08-31-manifest.json")
PR_EVENTS = frozenset({"pull_request", "pull_request_target"})
MERGE_EVENTS = frozenset({"merge_group"})
DISTRIBUTION_METRICS = (
    "required_gate_seconds",
    "merge_unblock_seconds",
    "all_workflow_seconds",
    "completed_runner_minutes",
    "cancelled_runner_minutes",
    "cancelled_job_count",
    "incomplete_job_count",
    "setup_runner_minutes",
    "execution_runner_minutes",
    "public_standard_runner_usd",
)


class ReplayError(RuntimeError):
    """The pinned cohort could not be replayed exactly."""


def _suite_id(item: dict[str, Any]) -> int | None:
    suite = item.get("check_suite") or {}
    value = item.get("check_suite_id") or suite.get("id")
    return int(value) if value is not None else None


def _timestamp(value: object) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _eligible_runs(
    runs: list[dict[str, Any]],
    head_sha: str,
    allowed_events: frozenset[str],
    snapshot_at: str,
) -> list[dict[str, Any]]:
    cutoff = _timestamp(snapshot_at)
    return [
        run
        for run in runs
        if run.get("head_sha") == head_sha
        and run.get("event") in allowed_events
        and run.get("created_at")
        and _timestamp(run["created_at"]) <= cutoff
    ]


def _filter_check_runs(check_runs: list[dict[str, Any]], suite_ids: set[int]) -> list[dict[str, Any]]:
    return [check for check in check_runs if _suite_id(check) in suite_ids]


def _fetch_one(client: metrics.GitHubClient, path: str) -> dict[str, Any]:
    value = client.get(path)
    if not isinstance(value, dict):
        raise ReplayError(f"GitHub API read failed or returned an unexpected object: {path}")
    return cast(dict[str, Any], value)


def _run_tuple(run: dict[str, Any]) -> tuple[int, str, int | None]:
    return int(run["id"]), str(run.get("event")), _suite_id(run)


def _assert_discovered_run_set(
    discovered_runs: list[dict[str, Any]],
    expected_runs: dict[int, tuple[str, int]],
    head_sha: str,
    allowed_events: frozenset[str],
    snapshot_at: str,
) -> None:
    eligible = _eligible_runs(discovered_runs, head_sha, allowed_events, snapshot_at)
    actual = {_run_tuple(run) for run in eligible}
    expected = {(run_id, event, suite_id) for run_id, (event, suite_id) in expected_runs.items()}
    if len(actual) != len(eligible) or actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ReplayError(f"eligible run set differs for {head_sha}: missing={missing}, extra={extra}")


def _assert_routing(changed_files: list[str], code_routed: bool, rules: dict[str, list[str]]) -> None:
    normalized = path_filter.ordered_unique(path_filter.normalize_path(path) for path in changed_files)
    decision = path_filter.classify_paths(normalized, rules, forced_code_paths=())
    actual = bool(decision["needs_code_ci"])
    if actual != code_routed:
        raise ReplayError(f"routing classification differs: expected code_routed={code_routed}, got {actual}")


def _assert_pr_metadata(live_pr: dict[str, Any], row: dict[str, Any], base_ref: str) -> None:
    expected = {
        "merged": True,
        "head_sha": str(row["head_sha"]),
        "merged_at": str(row["merged_at"]),
        "base_ref": base_ref,
    }
    actual = {
        "merged": live_pr.get("merged") is True,
        "head_sha": str((live_pr.get("head") or {}).get("sha") or ""),
        "merged_at": str(live_pr.get("merged_at") or ""),
        "base_ref": str((live_pr.get("base") or {}).get("ref") or ""),
    }
    if actual != expected:
        raise ReplayError(f"PR metadata differs: expected {expected}, got {actual}")


def _replay_row(
    client: metrics.GitHubClient,
    row: dict[str, Any],
    allowed_events: frozenset[str],
    snapshot_at: str,
) -> dict[str, Any]:
    head_sha = str(row["head_sha"])
    expected_runs = {int(run_id): (str(event), int(suite_id)) for run_id, event, suite_id in row["runs"]}
    discovered_runs = client.get_paginated(
        f"/repos/{client.repo}/actions/runs?head_sha={head_sha}",
        item_key="workflow_runs",
    )
    _assert_discovered_run_set(discovered_runs, expected_runs, head_sha, allowed_events, snapshot_at)

    fetched_runs = [_fetch_one(client, f"/repos/{client.repo}/actions/runs/{run_id}") for run_id in expected_runs]
    runs = _eligible_runs(fetched_runs, head_sha, allowed_events, snapshot_at)
    if {int(run["id"]) for run in runs} != set(expected_runs):
        raise ReplayError(f"run event/head filtering changed the pinned run set for {head_sha}")

    for run in runs:
        run_id = int(run["id"])
        actual = (str(run.get("event")), _suite_id(run))
        if actual != expected_runs[run_id]:
            raise ReplayError(f"run {run_id} event/suite mismatch: expected {expected_runs[run_id]}, got {actual}")

    jobs: list[dict[str, Any]] = []
    for run in runs:
        run_id = int(run["id"])
        run_jobs = client.get_paginated(
            f"/repos/{client.repo}/actions/runs/{run_id}/jobs",
            item_key="jobs",
        )
        foreign_jobs = [job.get("id") for job in run_jobs if int(job.get("run_id") or -1) != run_id]
        if foreign_jobs:
            raise ReplayError(f"run {run_id} returned jobs owned by another run: {foreign_jobs}")
        jobs.extend(run_jobs)

    all_check_runs = client.get_paginated(
        f"/repos/{client.repo}/commits/{head_sha}/check-runs",
        item_key="check_runs",
    )
    suite_ids = {suite_id for _, suite_id in expected_runs.values()}
    check_runs = _filter_check_runs(all_check_runs, suite_ids)
    observed_suite_ids = {_suite_id(check) for check in check_runs}
    if not observed_suite_ids.issubset(suite_ids):
        raise ReplayError(f"foreign check suite survived filtering for {head_sha}")

    return metrics.event_fanout_metrics(
        runs=runs,
        jobs=jobs,
        check_runs=check_runs,
        merged_at=row.get("merged_at"),
    )


def _distribution(values: list[float]) -> dict[str, float]:
    return {
        "median": statistics.median(values),
        "minimum": min(values),
        "maximum": max(values),
    }


def _summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise ReplayError("cannot summarize an empty cohort")
    summary: dict[str, Any] = {
        "rows": len(rows),
        "schemas": sorted({str(row["metrics"]["schema"]) for row in rows}),
    }
    for key in DISTRIBUTION_METRICS:
        values = [float(row["metrics"][key]) for row in rows]
        summary[key] = _distribution(values)

    queue_values = [
        float(row["metrics"]["queue_delay_seconds"])
        for row in rows
        if row["metrics"]["queue_delay_seconds"] is not None
    ]
    summary["queue_delay_seconds"] = {
        "recorded_count": len(queue_values),
        "unrecorded_count": len(rows) - len(queue_values),
        "distribution": _distribution(queue_values) if queue_values else None,
    }

    names_by_row = [set(row["metrics"]["workflow_run_counts"]) for row in rows]
    common = set.intersection(*names_by_row)
    union = set.union(*names_by_row)
    summary["common_workflows"] = sorted(common)
    summary["workflow_presence"] = {
        name: sum(name in names for names in names_by_row) for name in sorted(union - common)
    }
    return summary


def _assert_matches(actual: Any, expected: Any, path: str = "expected") -> None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict) or set(actual) != set(expected):
            raise ReplayError(f"{path} keys differ: expected {sorted(expected)}, got {sorted(actual)}")
        for key, value in expected.items():
            _assert_matches(actual[key], value, f"{path}.{key}")
        return
    if isinstance(expected, list):
        if actual != expected:
            raise ReplayError(f"{path} differs: expected {expected!r}, got {actual!r}")
        return
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        if not isinstance(actual, (int, float)) or not math.isclose(actual, expected, abs_tol=1e-9):
            raise ReplayError(f"{path} differs: expected {expected!r}, got {actual!r}")
        return
    if actual != expected:
        raise ReplayError(f"{path} differs: expected {expected!r}, got {actual!r}")


def replay(manifest: dict[str, Any]) -> dict[str, Any]:
    repo = str(manifest["repository"])
    client = metrics.make_client(repo)
    if client is None:
        raise ReplayError("no authenticated read-only GitHub API access is available")

    measurement = manifest["measurement"]
    rules_path = REPO_ROOT / manifest["routing"]["rules_path"]
    rules = path_filter.load_rules(rules_path)
    if manifest["routing"]["forced_code_paths"]:
        raise ReplayError("this cohort requires an empty forced_code_paths input")

    pull_request_rows = []
    for row in manifest["pull_requests"]:
        number = int(row["number"])
        live_pr = _fetch_one(client, f"/repos/{repo}/pulls/{number}")
        _assert_pr_metadata(live_pr, row, str(measurement["base_ref"]))
        changed_files = [str(path) for path in manifest["changed_files"][str(number)]]
        live_files = client.get_paginated(f"/repos/{repo}/pulls/{number}/files")
        live_filenames = [path_filter.normalize_path(str(item["filename"])) for item in live_files]
        if live_filenames != changed_files:
            raise ReplayError(f"PR #{number} changed-file inputs differ from the manifest")
        _assert_routing(changed_files, bool(row["code_routed"]), rules)
        row_metrics = _replay_row(client, row, PR_EVENTS, str(measurement["pull_request_snapshot_at"]))
        pull_request_rows.append({**row, "metrics": row_metrics})
    merge_group_rows = []
    for row in manifest["merge_groups"]:
        row_metrics = _replay_row(client, row, MERGE_EVENTS, str(measurement["merge_group_snapshot_at"]))
        merge_group_rows.append({**row, "metrics": row_metrics})

    result = {
        "pull_request_code_routed": _summarize([row for row in pull_request_rows if row["code_routed"]]),
        "pull_request_all": _summarize(pull_request_rows),
        "merge_group": _summarize(merge_group_rows),
    }
    _assert_matches(result, manifest["expected"])
    return result


def _expect_replay_error(label: str, action: Callable[[], None]) -> None:
    try:
        action()
    except ReplayError:
        return
    raise ReplayError(f"negative control did not fail: {label}")


def self_test() -> None:
    head = "a" * 40
    snapshot_at = "2026-08-31T12:00:00Z"
    runs = [
        {"id": 1, "head_sha": head, "event": "pull_request", "check_suite_id": 11, "created_at": snapshot_at},
        {
            "id": 2,
            "head_sha": head,
            "event": "pull_request_target",
            "check_suite_id": 12,
            "created_at": snapshot_at,
        },
        {"id": 3, "head_sha": head, "event": "push", "check_suite_id": 13, "created_at": snapshot_at},
        {"id": 4, "head_sha": head, "event": "merge_group", "check_suite_id": 14, "created_at": snapshot_at},
    ]
    retained_pr_ids = [run["id"] for run in _eligible_runs(runs, head, PR_EVENTS, snapshot_at)]
    if retained_pr_ids != [1, 2]:
        raise ReplayError(f"PR event filter regression: retained {retained_pr_ids}")
    retained_merge_ids = [run["id"] for run in _eligible_runs(runs, head, MERGE_EVENTS, snapshot_at)]
    if retained_merge_ids != [4]:
        raise ReplayError(f"merge event filter regression: retained {retained_merge_ids}")

    check_runs = [
        {"id": 101, "check_suite": {"id": 11}},
        {"id": 102, "check_suite": {"id": 12}},
        {"id": 103, "check_suite": {"id": 99}},
    ]
    retained_check_ids = [check["id"] for check in _filter_check_runs(check_runs, {11, 12})]
    if retained_check_ids != [101, 102]:
        raise ReplayError(f"check-suite filter regression: retained {retained_check_ids}")

    _expect_replay_error(
        "manifest omitted an eligible run",
        lambda: _assert_discovered_run_set(runs, {1: ("pull_request", 11)}, head, PR_EVENTS, snapshot_at),
    )
    rules = path_filter.load_rules(REPO_ROOT / ".github/path-filters.yml")
    _expect_replay_error(
        "routing classification altered",
        lambda: _assert_routing(["benchbox/core/system.py"], False, rules),
    )
    _expect_replay_error(
        "expected published metric altered",
        lambda: _assert_matches({"rows": 1}, {"rows": 2}),
    )
    pr_row = {"head_sha": head, "merged_at": snapshot_at}
    mismatched_pr = {
        "merged": True,
        "head": {"sha": "b" * 40},
        "merged_at": snapshot_at,
        "base": {"ref": "develop"},
    }
    _expect_replay_error(
        "PR head metadata altered",
        lambda: _assert_pr_metadata(mismatched_pr, pr_row, "develop"),
    )
    print(
        "PASS: event/suite filters and negative controls for omitted run, routing drift, "
        "expected-metric drift, and PR metadata drift"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    result = replay(manifest)
    print(json.dumps({"verified_against_manifest": True, "summary": result}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (metrics.ApiFailure, ReplayError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1) from error
