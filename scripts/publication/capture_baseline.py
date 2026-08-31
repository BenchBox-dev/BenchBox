#!/usr/bin/env python3
"""Capture and validate the evidence-fresh independent publication baseline."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT / "docs/operations/publication-baseline-2026-08-31.json"
REPOSITORY = "BenchBox-dev/BenchBox"
BRANCHES = ("develop", "release", "published-results")
CORPUS_PREFIX = "results-data/bundles/"


def run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def gh(path: str) -> Any:
    return json.loads(run("gh", "api", path))


def branch_sha(branch: str) -> str:
    line = run("git", "ls-remote", "origin", f"refs/heads/{branch}")
    if not line:
        raise RuntimeError(f"origin/{branch} does not exist")
    return line.split()[0]


def tree_paths(ref: str, prefix: str = CORPUS_PREFIX) -> dict[str, int]:
    output = run("git", "ls-tree", "-r", "--long", ref, "--", prefix)
    paths: dict[str, int] = {}
    for line in output.splitlines():
        metadata, path = line.split("\t", 1)
        size = metadata.split()[3]
        if size != "-":
            paths[path] = int(size)
    return paths


def sha256_url(url: str) -> tuple[str, int, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": "BenchBox-publication-baseline/1"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - fixed HTTPS production URL
        payload = response.read()
        headers = {key.lower(): value for key, value in response.headers.items()}
    return hashlib.sha256(payload).hexdigest(), len(payload), headers


def iso_duration_seconds(start: str, end: str) -> int:
    return int(
        (
            datetime.fromisoformat(end.replace("Z", "+00:00")) - datetime.fromisoformat(start.replace("Z", "+00:00"))
        ).total_seconds()
    )


def capture() -> dict[str, Any]:
    captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    shas = {branch: branch_sha(branch) for branch in BRANCHES}
    trees = {branch: tree_paths(f"origin/{branch}") for branch in BRANCHES}
    accepted = sorted(set(trees["develop"]) | set(trees["published-results"]))
    published_only = sorted(set(trees["published-results"]) - set(trees["develop"]))

    pages = gh(f"repos/{REPOSITORY}/pages")
    workflow_permissions = gh(f"repos/{REPOSITORY}/actions/permissions/workflow")
    branch_rules = {branch: gh(f"repos/{REPOSITORY}/rules/branches/{branch}") for branch in BRANCHES}
    environments = gh(f"repos/{REPOSITORY}/environments")["environments"]
    deployments = gh(f"repos/{REPOSITORY}/deployments?environment=github-pages&per_page=10")
    current = next(item for item in deployments if item["ref"] == "release")
    statuses = gh(f"repos/{REPOSITORY}/deployments/{current['id']}/statuses")
    successful_status = next(item for item in statuses if item["state"] == "success")
    run_id = int(successful_status["log_url"].split("/runs/")[1].split("/")[0])
    run = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    artifacts = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts")["artifacts"]
    mirror_prs = gh(f"repos/{REPOSITORY}/pulls?state=open&base=published-results&per_page=100")
    database_sha, database_bytes, database_headers = sha256_url("https://benchbox.dev/results/data/results.duckdb")

    return {
        "schema_version": 1,
        "captured_at": captured_at,
        "repository": REPOSITORY,
        "repository_policy": {"workflow_permissions": workflow_permissions, "branch_rules": branch_rules},
        "branches": {name: {"sha": shas[name]} for name in BRANCHES},
        "workflow": {
            "path": ".github/workflows/docs.yml",
            "deploy_trigger": "push to release",
            "run_id": run_id,
            "run_url": run["html_url"],
            "head_sha": run["head_sha"],
            "status": run["status"],
            "conclusion": run["conclusion"],
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
            "duration_seconds": iso_duration_seconds(run["created_at"], run["updated_at"]),
        },
        "pages": {
            "url": pages["html_url"],
            "cname": pages["cname"],
            "build_type": pages["build_type"],
            "configured_source": pages["source"],
            "environment": next(item for item in environments if item["name"] == "github-pages"),
            "deployment": {
                "id": current["id"],
                "sha": current["sha"],
                "ref": current["ref"],
                "created_at": current["created_at"],
                "state": successful_status["state"],
                "environment_url": successful_status["environment_url"],
                "rollback": "Re-run Documentation on the prior known-good release SHA or revert release through its protected PR flow.",
            },
            "artifacts": [
                {
                    key: artifact[key]
                    for key in ("id", "name", "size_in_bytes", "expired", "created_at", "expires_at", "digest")
                }
                for artifact in artifacts
            ],
            "bandwidth": {
                "telemetry": "unavailable",
                "reason": "GitHub Pages and repository APIs expose artifact bytes and HTTP cache headers, not transfer totals.",
                "database_content_length": database_bytes,
                "database_cache_control": database_headers.get("cache-control"),
            },
        },
        "corpus": {
            "path_semantics": "set union, never a target count",
            "develop": {"file_count": len(trees["develop"]), "bytes": sum(trees["develop"].values())},
            "published_results": {
                "file_count": len(trees["published-results"]),
                "bytes": sum(trees["published-results"].values()),
            },
            "release": {"file_count": len(trees["release"]), "bytes": sum(trees["release"].values())},
            "accepted_path_union": accepted,
            "accepted_path_union_count": len(accepted),
            "published_only_paths": published_only,
            "published_only_count": len(published_only),
        },
        "live_database": {
            "url": "https://benchbox.dev/results/data/results.duckdb",
            "sha256": database_sha,
            "bytes": database_bytes,
            "etag": database_headers.get("etag"),
            "last_modified": database_headers.get("last-modified"),
        },
        "open_mirror_prs": [
            {
                "number": item["number"],
                "title": item["title"],
                "draft": item["draft"],
                "head": item["head"]["ref"],
                "url": item["html_url"],
            }
            for item in mirror_prs
        ],
        "freeze": {
            "destructive_corpus_rewrites": "blocked",
            "mirror_retirement": "blocked",
            "release_deploy_removal": "blocked",
            "incident_owner": "BenchBox maintainers",
        },
    }


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("corpus", {}).get("path_semantics") != "set union, never a target count":
        errors.append("corpus inventory must declare set-union semantics")
    accepted = set(data.get("corpus", {}).get("accepted_path_union", []))
    published_only = set(data.get("corpus", {}).get("published_only_paths", []))
    if not published_only <= accepted:
        errors.append("published-only paths must be contained in the accepted union")
    if data.get("workflow", {}).get("head_sha") != data.get("branches", {}).get("release", {}).get("sha"):
        errors.append("deployed workflow SHA must equal the captured release SHA")
    if data.get("pages", {}).get("deployment", {}).get("state") != "success":
        errors.append("captured Pages deployment is not successful")
    if any(value != "blocked" for key, value in data.get("freeze", {}).items() if key != "incident_owner"):
        errors.append("all destructive migration surfaces must remain blocked")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        data = json.loads(args.output.read_text())
        errors = validate(data)
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        print(f"publication baseline valid: {args.output}")
        return 0
    data = capture()
    errors = validate(data)
    if errors:
        raise RuntimeError("; ".join(errors))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
