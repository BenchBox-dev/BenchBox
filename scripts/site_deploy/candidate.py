from __future__ import annotations

import re
import subprocess
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from scripts.site_deploy.githubapi import ApiError, GitHubClient

TRUNK_WORKFLOW_FILE = "trunk.yml"
TRUNK_WORKFLOW_PATH = ".github/workflows/trunk.yml"
TRUNK_BRANCH = "develop"
SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_WALK_LIMIT = 50


class CandidateError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    trunk_sha: str
    certifying_run_id: int
    release_tag: str


def semver_key(tag: str) -> tuple[int, int, int]:
    match = SEMVER_TAG.match(tag)
    if not match:
        raise CandidateError(f"not a release tag: {tag!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


def latest_release_tag(tags: list[str]) -> str:
    releases = [tag for tag in tags if SEMVER_TAG.match(tag)]
    if not releases:
        raise CandidateError("no v<major>.<minor>.<patch> release tag exists")
    return max(releases, key=semver_key)


def _git(repo_dir: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo_dir), *args], check=True, capture_output=True, text=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError) as exc:
        raise CandidateError(f"git {' '.join(args)} failed: {exc}") from exc


def release_tags(repo_dir: Path) -> list[str]:
    return _git(repo_dir, "tag", "--list", "v*").split()


def tag_commit(repo_dir: Path, tag: str) -> str:
    sha = _git(repo_dir, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    if not HEX40.match(sha):
        raise CandidateError(f"tag {tag} did not resolve to a commit")
    return sha


def first_parent_shas(repo_dir: Path, ref: str, limit: int = DEFAULT_WALK_LIMIT) -> list[str]:
    return _git(repo_dir, "rev-list", "--first-parent", f"--max-count={limit}", ref).split()


def is_ancestor(repo_dir: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_dir), "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
    )
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise CandidateError(f"ancestry of {ancestor} and {descendant} is unknown: {result.stderr.strip()}")


def certifying_run_id(client: GitHubClient, sha: str) -> int | None:
    query = urllib.parse.urlencode({"event": "push", "branch": TRUNK_BRANCH, "head_sha": sha, "status": "success"})
    try:
        runs = client.get_list(f"actions/workflows/{TRUNK_WORKFLOW_FILE}/runs?{query}", key="workflow_runs")
    except ApiError as exc:
        raise CandidateError(f"trunk run lookup failed for {sha}: {exc}") from exc
    matches = [
        run
        for run in runs
        if run.get("event") == "push"
        and run.get("head_branch") == TRUNK_BRANCH
        and run.get("head_sha") == sha
        and run.get("conclusion") == "success"
        and run.get("path") == TRUNK_WORKFLOW_PATH
        and isinstance(run.get("id"), int)
    ]
    if not matches:
        return None
    return int(max(matches, key=lambda run: str(run.get("created_at") or ""))["id"])


def find_candidate(client: GitHubClient, shas: list[str], release_tag: str) -> Candidate:
    if not shas:
        raise CandidateError("no trunk commits to consider")
    for sha in shas:
        if not HEX40.match(sha):
            raise CandidateError(f"not a full commit SHA: {sha!r}")
        run_id = certifying_run_id(client, sha)
        if run_id is not None:
            return Candidate(trunk_sha=sha, certifying_run_id=run_id, release_tag=release_tag)
    raise CandidateError(
        f"none of the newest {len(shas)} first-parent commits has a successful push run of trunk.yml on develop"
    )
