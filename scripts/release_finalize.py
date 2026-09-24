"""Merge one checked release PR and tag its exact merge commit, with safe resume."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.+-]+)?\Z")


class FinalizeError(Exception):
    """A release invariant is unproven or contradicted."""


def command(*args: str, pending_ok: bool = False, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False, env=env)
    if result.returncode:
        if pending_ok and result.returncode == 8:
            raise FinalizeError("Required PR checks are pending. Wait for GitHub Actions, then rerun.")
        raise FinalizeError(f"{' '.join(args[:3])} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def json_command(*args: str, pending_ok: bool = False) -> Any:
    output = command(*args, pending_ok=pending_ok)
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise FinalizeError(f"{' '.join(args[:3])} returned invalid JSON") from exc


def require_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise FinalizeError(f"{label} is missing or is not a commit SHA")
    return value


def release_pr(version: str) -> dict[str, Any]:
    rows = json_command(
        "gh",
        "pr",
        "list",
        "--base",
        "release",
        "--head",
        f"v{version}",
        "--state",
        "all",
        "--limit",
        "100",
        "--json",
        "number,state,mergedAt,mergeCommit,headRefOid,baseRefName,headRefName",
    )
    if not isinstance(rows, list):
        raise FinalizeError("Release PR query returned an unexpected shape")
    candidates = [row for row in rows if row.get("state") in ("OPEN", "MERGED")]
    if len(candidates) != 1:
        raise FinalizeError(f"Expected one open or merged release PR for v{version}; found {len(candidates)}")
    pr = candidates[0]
    if pr.get("baseRefName") != "release" or pr.get("headRefName") != f"v{version}":
        raise FinalizeError("Release PR branch identity changed")
    return pr


def view_pr(number: int) -> dict[str, Any]:
    pr = json_command(
        "gh",
        "pr",
        "view",
        str(number),
        "--json",
        "number,state,mergedAt,mergeCommit,headRefOid,baseRefName,headRefName",
    )
    if not isinstance(pr, dict) or pr.get("number") != number:
        raise FinalizeError("Release PR lookup returned a different PR")
    return pr


def check_required_contexts(number: int, required_contexts: tuple[str, ...]) -> None:
    rows = json_command("gh", "pr", "checks", str(number), "--required", "--json", "name,bucket,state", pending_ok=True)
    if not isinstance(rows, list):
        raise FinalizeError("Required PR checks returned an unexpected shape")
    for name in required_contexts:
        matches = [row for row in rows if row.get("name") == name]
        if len(matches) != 1:
            raise FinalizeError(f"Required release context {name} is missing or duplicated")
        if matches[0].get("bucket") != "pass":
            raise FinalizeError(f"Required release context {name} is {matches[0].get('bucket')}; fix the PR first")


def merge_pr(pr: dict[str, Any], version: str, required_contexts: tuple[str, ...]) -> None:
    number = pr["number"]
    head = require_sha(pr.get("headRefOid"), "Release PR head")
    check_required_contexts(number, required_contexts)
    refreshed = view_pr(number)
    if (refreshed.get("state"), refreshed.get("baseRefName"), refreshed.get("headRefName")) != (
        "OPEN",
        "release",
        f"v{version}",
    ) or refreshed.get("headRefOid") != head:
        raise FinalizeError("Release PR state or head changed while checking required contexts")
    # The REST merge endpoint rejects a concurrent head change when sha is set.
    command(
        "gh",
        "api",
        "--method",
        "PUT",
        f"repos/{{owner}}/{{repo}}/pulls/{number}/merge",
        "--raw-field",
        f"sha={head}",
        "--raw-field",
        "merge_method=squash",
    )


def merged_commit(pr: dict[str, Any], version: str) -> str:
    if (pr.get("state"), pr.get("baseRefName"), pr.get("headRefName")) != ("MERGED", "release", f"v{version}"):
        raise FinalizeError("Release PR is not confirmed merged into release")
    if not pr.get("mergedAt"):
        raise FinalizeError("Merged release PR has no mergedAt timestamp")
    merge = pr.get("mergeCommit")
    return require_sha(merge.get("oid") if isinstance(merge, dict) else None, "Release PR merge commit")


def tag_merge_commit(version: str, commit: str) -> str:
    tag = f"v{version}"
    command("git", "fetch", "origin", "--tags")
    release = command("git", "rev-parse", "origin/release^{commit}")
    require_sha(release, "Fetched origin/release")
    command("git", "cat-file", "-e", f"{commit}^{{commit}}")
    result = subprocess.run(["git", "merge-base", "--is-ancestor", commit, release], capture_output=True, check=False)
    if result.returncode:
        raise FinalizeError("The PR merge commit is not reachable from fetched origin/release")

    remote = command("git", "ls-remote", "--tags", "origin", f"refs/tags/{tag}")
    local = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{tag}"], text=True, capture_output=True
    )
    if local.returncode not in (0, 1):
        raise FinalizeError("Could not inspect the local release tag")
    if remote and local.returncode != 0:
        raise FinalizeError("Remote release tag was not fetched locally")
    if local.returncode == 0:
        target = command("git", "rev-parse", f"refs/tags/{tag}^{{commit}}")
        if target != commit:
            raise FinalizeError(f"Local tag {tag} points to {target}, not PR merge commit {commit}")
    if remote:
        remote_oid = remote.split()[0]
        if remote_oid != local.stdout.strip():
            raise FinalizeError(f"Remote tag {tag} differs from the local tag")
        return "already pushed"
    if local.returncode != 0:
        command("git", "tag", tag, commit)
    push_env = os.environ.copy()
    push_env["PRE_COMMIT_ALLOW_NO_CONFIG"] = "1"
    command("git", "push", "origin", f"refs/tags/{tag}:refs/tags/{tag}", env=push_env)
    return "pushed"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--required-contexts", required=True, help="Space-separated required release contexts")
    args = parser.parse_args(argv)
    try:
        if not VERSION_RE.fullmatch(args.version):
            raise FinalizeError("VERSION must be X.Y.Z with an optional release suffix")
        required_contexts = tuple(args.required_contexts.split())
        if not required_contexts or len(required_contexts) != len(set(required_contexts)):
            raise FinalizeError("Required release contexts must be a nonempty, unique set")
        git_dir = command("git", "rev-parse", "--absolute-git-dir")
        common_dir = command("git", "rev-parse", "--git-common-dir")
        if os.path.samefile(git_dir, common_dir):
            raise FinalizeError("release-finalize requires a linked worktree")
        pr = release_pr(args.version)
        number = pr["number"]
        if pr["state"] == "OPEN":
            merge_pr(pr, args.version, required_contexts)
            pr = view_pr(number)
        commit = merged_commit(pr, args.version)
        result = tag_merge_commit(args.version, commit)
        print(f"Release PR #{number} merged at {commit}; tag v{args.version} {result}.")
        print("Verify the matching release.yml run, PyPI files, installation, and GitHub Release before closeout.")
        return 0
    except (FinalizeError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
