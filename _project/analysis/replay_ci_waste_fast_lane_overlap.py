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


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def outcome_from_log(log: str) -> dict[str, int]:
    matches = [match.groupdict() for match in SUMMARY.finditer(log)]
    if not matches:
        raise ValueError("no pytest final summary found")
    result = max(matches, key=lambda item: int(item["passed"]))
    outcome = {name: int(result[name] or 0) for name in ("passed", "skipped", "failed")}
    outcome["total"] = sum(outcome.values())
    return outcome


def load_source_snapshot(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    descriptor = data.get("source_snapshot")
    if not isinstance(descriptor, dict):
        return {}, ["source snapshot descriptor is missing"]
    relative_path = descriptor.get("path")
    if not isinstance(relative_path, str) or not relative_path:
        return {}, ["source snapshot path is invalid"]
    snapshot_path = (ROOT / relative_path).resolve()
    try:
        snapshot_path.relative_to(ROOT)
    except ValueError:
        return {}, [f"source snapshot is outside the repository: {relative_path}"]
    try:
        raw = snapshot_path.read_bytes()
    except OSError as exc:
        return {}, [f"cannot read source snapshot {relative_path}: {exc}"]
    errors = []
    if sha256(raw) != descriptor.get("sha256"):
        errors.append(f"source snapshot hash drifted: {relative_path}")
    try:
        snapshot = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {}, [*errors, f"source snapshot is not valid JSON: {exc}"]
    if not isinstance(snapshot, dict):
        return {}, [*errors, "source snapshot root must be an object"]
    return snapshot, errors


def validate_source_snapshot(snapshot: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    entries = snapshot.get("entries")
    if snapshot.get("schema") != "fast_lane_source_snapshot_v1" or not isinstance(entries, list):
        return {}, ["source snapshot schema is invalid"]

    errors: list[str] = []
    entries_by_id: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            errors.append("source snapshot entry has no valid id")
            continue
        entry_id = entry["id"]
        if entry_id in entries_by_id:
            errors.append(f"duplicate source snapshot entry {entry_id}")
            continue
        entries_by_id[entry_id] = entry
        lines = entry.get("lines")
        if not isinstance(lines, list) or not lines or not all(isinstance(line, str) for line in lines):
            errors.append(f"{entry_id}: source lines are invalid")
        else:
            content = ("\n".join(lines) + "\n").encode()
            if sha256(content) != entry.get("content_sha256"):
                errors.append(f"{entry_id}: source excerpt hash drifted")
        if not isinstance(entry.get("source_path"), str):
            errors.append(f"{entry_id}: source path is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(entry.get("source_file_sha256", ""))):
            errors.append(f"{entry_id}: source file hash is invalid")
        source_lines = entry.get("source_lines")
        if (
            not isinstance(source_lines, list)
            or len(source_lines) != 2
            or not all(isinstance(line, int) for line in source_lines)
            or source_lines[1] < source_lines[0]
            or (isinstance(lines, list) and source_lines[1] - source_lines[0] + 1 != len(lines))
        ):
            errors.append(f"{entry_id}: source line range is invalid")
        source_shas = entry.get("source_shas")
        if (
            not isinstance(source_shas, list)
            or not source_shas
            or not all(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) for sha in source_shas)
        ):
            errors.append(f"{entry_id}: source SHAs are invalid")
        anchors = entry.get("log_anchors")
        if (
            not isinstance(anchors, list)
            or not anchors
            or not all(isinstance(anchor, str) and anchor for anchor in anchors)
        ):
            errors.append(f"{entry_id}: retained-log anchors are invalid")
    return entries_by_id, errors


def self_check(data: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    cells = data.get("cells")
    if data.get("schema") != "fast_lane_overlap_v2" or not isinstance(cells, list) or len(cells) != 10:
        return ["schema or ten-cell contract is invalid"]

    entries_by_id, errors = validate_source_snapshot(snapshot)

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
        source_ids = cell.get("source_snapshot_ids")
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"{key}: source snapshot references are missing")
            continue
        for entry_id in source_ids:
            entry = entries_by_id.get(entry_id)
            if entry is None:
                errors.append(f"{key}: source snapshot entry is missing: {entry_id}")
            elif cell.get("sha") not in entry.get("source_shas", []):
                errors.append(f"{key}: source snapshot entry {entry_id} is not bound to cell SHA")
    return errors


def replay(data: dict[str, Any], snapshot: dict[str, Any]) -> list[str]:
    errors = self_check(data, snapshot)
    if errors:
        return errors
    repo = data["repository"]
    entries_by_id = {entry["id"]: entry for entry in snapshot["entries"]}
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
            log = run("gh", "run", "view", str(run_id), "--repo", repo, "--job", str(job_id), "--log")
            if outcome_from_log(log) != cell["outcome"]:
                errors.append(f"{run_id}/{job_id}: pytest outcome summary drifted")
            for entry_id in cell["source_snapshot_ids"]:
                for anchor in entries_by_id[entry_id]["log_anchors"]:
                    if anchor not in log:
                        errors.append(f"{run_id}/{job_id}: retained log no longer matches source snapshot {entry_id}")
        except (subprocess.CalledProcessError, ValueError) as exc:
            errors.append(f"{run_id}/{job_id}: cannot replay log: {exc}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot, errors = load_source_snapshot(data)
    if not errors:
        errors = self_check(data, snapshot) if args.self_check else replay(data, snapshot)
    if errors:
        print("FAIL")
        print("\n".join(errors))
        return 1
    print("PASS: fast-lane overlap manifest is consistent" if args.self_check else "PASS: live replay matches manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
