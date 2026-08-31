"""Replay the bounded fast-lane overlap inventory from GitHub Actions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "_project/analysis/ci-waste-fast-lane-overlap-2026-08-31-manifest.json"
SUMMARY = re.compile(r"(?:(?P<failed>\d+) failed, )?(?P<passed>\d+) passed, (?P<skipped>\d+) skipped")


def run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout


def api(repo: str, path: str) -> Any:
    return json.loads(run("gh", "api", f"repos/{repo}/{path}"))


def source_hash(sha: str, path: str) -> str:
    data = subprocess.run(["git", "show", f"{sha}:{path}"], cwd=ROOT, check=True, capture_output=True).stdout
    return hashlib.sha256(data).hexdigest()


def outcome_from_log(repo: str, cell: dict[str, Any]) -> dict[str, int]:
    log = run("gh", "run", "view", str(cell["run_id"]), "--repo", repo, "--job", str(cell["job_id"]), "--log")
    matches = [match.groupdict() for match in SUMMARY.finditer(log)]
    if not matches:
        raise ValueError("no pytest final summary found")
    result = max(matches, key=lambda item: int(item["passed"]))
    outcome = {name: int(result[name] or 0) for name in ("passed", "skipped", "failed")}
    outcome["total"] = sum(outcome.values())
    return outcome


def self_check(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    cells = data.get("cells")
    if data.get("schema") != "fast_lane_overlap_v1" or not isinstance(cells, list) or len(cells) != 10:
        return ["schema or ten-cell contract is invalid"]
    seen = set()
    for cell in cells:
        key = (cell.get("run_id"), cell.get("job_id"))
        if key in seen:
            errors.append(f"duplicate cell {key}")
        seen.add(key)
        if cell.get("node_id_hash") is not None or cell.get("runner_minutes") is not None:
            errors.append(f"{key}: unavailable fields must be null")
        outcome = cell.get("outcome", {})
        if outcome.get("total") != sum(int(outcome.get(name, 0)) for name in ("passed", "skipped", "failed")):
            errors.append(f"{key}: outcome total is inconsistent")
    return errors


def replay(data: dict[str, Any]) -> list[str]:
    errors = self_check(data)
    repo = data["repository"]
    runs: dict[int, Any] = {}
    jobs: dict[int, Any] = {}
    for cell in data["cells"]:
        run_id, job_id = cell["run_id"], cell["job_id"]
        runs.setdefault(run_id, api(repo, f"actions/runs/{run_id}"))
        if job_id not in jobs:
            payload = api(repo, f"actions/runs/{run_id}/jobs?per_page=100")
            jobs.update({job["id"]: job for job in payload["jobs"]})
        record, job = runs[run_id], jobs.get(job_id)
        if job is None:
            errors.append(f"{run_id}/{job_id}: job missing")
            continue
        for name, actual in (
            ("event", record.get("event")),
            ("sha", record.get("head_sha")),
            ("workflow", record.get("name")),
            ("workflow_path", record.get("path")),
            ("job", job.get("name")),
        ):
            if actual != cell[name]:
                errors.append(f"{run_id}/{job_id}: {name} drifted: {actual!r}")
        step = next((item for item in job.get("steps", []) if item.get("name") == cell["step"]), None)
        if step is None:
            errors.append(f"{run_id}/{job_id}: fast step missing")
            continue
        for name in ("started_at", "completed_at"):
            if step.get(name) != cell[name]:
                errors.append(f"{run_id}/{job_id}: {name} drifted: {step.get(name)!r}")
        if step.get("started_at") and step.get("completed_at"):
            elapsed = int(
                (
                    datetime.fromisoformat(step["completed_at"].replace("Z", "+00:00"))
                    - datetime.fromisoformat(step["started_at"].replace("Z", "+00:00"))
                ).total_seconds()
            )
            if elapsed != cell["duration_seconds"]:
                errors.append(f"{run_id}/{job_id}: duration drifted: {elapsed}")
        try:
            if outcome_from_log(repo, cell) != cell["outcome"]:
                errors.append(f"{run_id}/{job_id}: pytest outcome summary drifted")
        except (subprocess.CalledProcessError, ValueError) as exc:
            errors.append(f"{run_id}/{job_id}: cannot replay log: {exc}")
    for sha, hashes in data["historical_sources"].items():
        for path, expected in hashes.items():
            try:
                if source_hash(sha, path) != expected:
                    errors.append(f"{sha}:{path}: source hash drifted")
            except subprocess.CalledProcessError:
                errors.append(f"{sha}:{path}: historical source unavailable")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors = self_check(data) if args.self_check else replay(data)
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print("PASS: fast-lane overlap manifest is consistent" if args.self_check else "PASS: live replay matches manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
