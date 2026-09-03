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


def run_raw(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout


def gh(path: str) -> Any:
    return json.loads(run("gh", "api", path))


def fetch_branch_sha(branch: str) -> str:
    """Fetch a branch without updating its remote-tracking ref and return the fetched SHA."""
    run("git", "fetch", "--no-tags", "origin", f"refs/heads/{branch}")
    return run("git", "rev-parse", "FETCH_HEAD")


def tree_objects(ref: str, prefix: str = CORPUS_PREFIX) -> dict[str, dict[str, Any]]:
    output = run_raw("git", "ls-tree", "-r", "--long", "-z", ref, "--", prefix)
    objects: dict[str, dict[str, Any]] = {}
    for line in output.split("\0"):
        if not line:
            continue
        metadata, path = line.split("\t", 1)
        mode, object_type, object_id, size = metadata.split()
        if size != "-":
            objects[path] = {
                "mode": mode,
                "type": object_type,
                "object_id": object_id,
                "size": int(size),
            }
    return objects


def accepted_objects(trees: dict[str, dict[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for path in sorted(set(trees["develop"]) | set(trees["published-results"])):
        variants: dict[tuple[str, str, str, int], list[str]] = {}
        for branch in ("develop", "published-results"):
            item = trees[branch].get(path)
            if item is None:
                continue
            key = (item["mode"], item["type"], item["object_id"], item["size"])
            variants.setdefault(key, []).append(branch)
        accepted.append(
            {
                "path": path,
                "variants": [
                    {
                        "mode": key[0],
                        "type": key[1],
                        "object_id": key[2],
                        "size": key[3],
                        "branches": branches,
                    }
                    for key, branches in variants.items()
                ],
            }
        )
    return accepted


def current_successful_deployment(deployments: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return the newest release deployment whose latest status is successful."""
    candidates = sorted(
        (item for item in deployments if item["ref"] == "release"),
        key=lambda item: item["created_at"],
        reverse=True,
    )
    for deployment in candidates:
        statuses = sorted(
            gh(f"repos/{REPOSITORY}/deployments/{deployment['id']}/statuses"),
            key=lambda item: item["created_at"],
            reverse=True,
        )
        if statuses and statuses[0]["state"] == "success":
            return deployment, statuses[0]
    raise RuntimeError("no current successful release deployment found")


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
    shas = {branch: fetch_branch_sha(branch) for branch in BRANCHES}
    trees = {branch: tree_objects(shas[branch]) for branch in BRANCHES}
    accepted = sorted(set(trees["develop"]) | set(trees["published-results"]))
    accepted_inventory = accepted_objects(trees)
    published_only = sorted(set(trees["published-results"]) - set(trees["develop"]))

    pages = gh(f"repos/{REPOSITORY}/pages")
    workflow_permissions = gh(f"repos/{REPOSITORY}/actions/permissions/workflow")
    branch_rules = {branch: gh(f"repos/{REPOSITORY}/rules/branches/{branch}") for branch in BRANCHES}
    environments = gh(f"repos/{REPOSITORY}/environments")["environments"]
    deployments = gh(f"repos/{REPOSITORY}/deployments?environment=github-pages&per_page=10")
    current, successful_status = current_successful_deployment(deployments)
    run_id = int(successful_status["log_url"].split("/runs/")[1].split("/")[0])
    run = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    artifacts = gh(f"repos/{REPOSITORY}/actions/runs/{run_id}/artifacts")["artifacts"]
    mirror_prs = gh(f"repos/{REPOSITORY}/pulls?state=open&base=published-results&per_page=100")
    database_sha, database_bytes, database_headers = sha256_url("https://benchbox.dev/results/data/results.duckdb")

    return {
        "schema_version": 2,
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
            "branch_source_shas": shas,
            "branch_objects": trees,
            "develop": {
                "file_count": len(trees["develop"]),
                "bytes": sum(item["size"] for item in trees["develop"].values()),
            },
            "published_results": {
                "file_count": len(trees["published-results"]),
                "bytes": sum(item["size"] for item in trees["published-results"].values()),
            },
            "release": {
                "file_count": len(trees["release"]),
                "bytes": sum(item["size"] for item in trees["release"].values()),
            },
            "accepted_path_union": accepted,
            "accepted_path_union_count": len(accepted),
            "accepted_objects": accepted_inventory,
            "conflicting_paths": [item["path"] for item in accepted_inventory if len(item["variants"]) > 1],
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


def validate_corpus(corpus: dict[str, Any], branches: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if corpus.get("path_semantics") != "set union, never a target count":
        errors.append("corpus inventory must declare set-union semantics")
    branch_objects = corpus.get("branch_objects", {})
    branch_source_shas = corpus.get("branch_source_shas", {})
    develop_objects = branch_objects.get("develop", {})
    published_objects = branch_objects.get("published-results", {})
    release_objects = branch_objects.get("release", {})
    accepted = set(corpus.get("accepted_path_union", []))
    expected_accepted = set(develop_objects) | set(published_objects)
    published_only = set(corpus.get("published_only_paths", []))
    expected_published_only = set(published_objects) - set(develop_objects)
    if branch_source_shas != {branch: branches.get(branch, {}).get("sha") for branch in BRANCHES}:
        errors.append("corpus branch inventories must identify their exact captured source SHAs")
    if accepted != expected_accepted:
        errors.append("accepted path union must exactly match develop and published-results branch objects")
    if not published_only <= accepted:
        errors.append("published-only paths must be contained in the accepted union")
    if published_only != expected_published_only:
        errors.append("published-only paths must exactly match the published-results branch difference")
    if corpus.get("accepted_path_union_count") != len(accepted):
        errors.append("accepted path union count does not match the accepted paths")
    if corpus.get("published_only_count") != len(published_only):
        errors.append("published-only count does not match the published-only paths")
    for key, objects in (
        ("develop", develop_objects),
        ("published_results", published_objects),
        ("release", release_objects),
    ):
        summary = corpus.get(key, {})
        if summary.get("file_count") != len(objects):
            errors.append(f"{key} file count does not match its branch objects")
        if summary.get("bytes") != sum(item.get("size", -1) for item in objects.values()):
            errors.append(f"{key} byte count does not match its branch objects")
        for path, item in objects.items():
            if item.get("type") != "blob" or not item.get("object_id") or item.get("mode") != "100644":
                errors.append(f"{key} object identity is invalid: {path}")
    expected_inventory = accepted_objects(
        {"develop": develop_objects, "published-results": published_objects, "release": release_objects}
    )
    if corpus.get("accepted_objects") != expected_inventory:
        errors.append("accepted object inventory must preserve every branch object identity")
    expected_conflicts = [item["path"] for item in expected_inventory if len(item["variants"]) > 1]
    if corpus.get("conflicting_paths") != expected_conflicts:
        errors.append("conflicting paths must exactly identify multi-object accepted paths")
    return errors


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value.lower())


def validate_live_evidence(data: dict[str, Any]) -> list[str]:
    """Require observed live Pages/database evidence fields for --check."""
    errors: list[str] = []
    live = data.get("live_database")
    if not isinstance(live, dict):
        errors.append("live_database must be present with observed sha256/bytes/url")
    else:
        if not _is_hex64(live.get("sha256")):
            errors.append(f"live_database.sha256 must be a 64-char hex digest, got {live.get('sha256')}")
        if not isinstance(live.get("bytes"), int) or live.get("bytes") <= 0:
            errors.append(f"live_database.bytes must be a positive int, got {live.get('bytes')}")
        url = live.get("url")
        if not isinstance(url, str) or not url.strip():
            errors.append(f"live_database.url must be a non-empty string, got {url}")

    pages = data.get("pages")
    if not isinstance(pages, dict):
        errors.append("pages must be present with bandwidth telemetry and artifacts")
        return errors

    bandwidth = pages.get("bandwidth")
    if not isinstance(bandwidth, dict) or bandwidth.get("telemetry") != "unavailable":
        errors.append('pages.bandwidth.telemetry must be "unavailable" (do not invent bandwidth totals)')

    artifacts = pages.get("artifacts")
    if not isinstance(artifacts, list):
        errors.append("pages.artifacts must be a list of observed artifact records")
    else:
        for idx, item in enumerate(artifacts):
            if not isinstance(item, dict):
                errors.append(f"pages.artifacts[{idx}] must be an object")
                continue
            digest = item.get("digest")
            size = item.get("size_in_bytes", item.get("size"))
            if not isinstance(digest, str) or not digest.strip():
                errors.append(f"pages.artifacts[{idx}] missing digest")
            if not isinstance(size, int) or size < 0:
                errors.append(f"pages.artifacts[{idx}] missing size")
    return errors


def validate(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if data.get("schema_version") != 2:
        errors.append("publication baseline schema version must be 2")
    errors.extend(validate_corpus(data.get("corpus", {}), data.get("branches", {})))
    errors.extend(validate_live_evidence(data))
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
