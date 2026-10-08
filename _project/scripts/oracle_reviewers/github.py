from __future__ import annotations

import json
import re
import subprocess
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .retry import State

STATE_ARTIFACT_PREFIX = "oracle-review-shadow-state-"
STATE_FILE = "state.json"


class GitHubError(RuntimeError):
    pass


def _gh(*args: str, accept: str | None = None) -> str:
    argv = ["gh", "api", *(("-H", f"Accept: {accept}") if accept else ()), *args]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise GitHubError(f"gh api {' '.join(args)} failed: {result.stderr.strip()[:500]}")
    return result.stdout


def get_json(path: str) -> Any:
    return json.loads(_gh(path))


def get_paginated(path: str) -> list[Any]:
    pages = json.loads(_gh("--paginate", "--slurp", path))
    return [item for page in pages for item in page]


def get_diff(repo: str, pr: int) -> str | None:
    try:
        return _gh(f"repos/{repo}/pulls/{pr}", accept="application/vnd.github.v3.diff")
    except GitHubError:
        return None


_THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          path
          comments(first: 1) { nodes { author { __typename login } body } }
        }
      }
    }
  }
}
"""


def review_threads(repo: str, pr: int) -> list[dict[str, Any]]:
    owner, name = repo.split("/", 1)
    threads: list[dict[str, Any]] = []
    after: str | None = None
    while True:
        args = ["graphql", "-f", f"query={_THREADS_QUERY}", "-f", f"owner={owner}", "-f", f"name={name}"]
        args += ["-F", f"number={pr}", *(("-f", f"after={after}") if after else ())]
        payload = json.loads(_gh(*args))
        if payload.get("errors"):
            raise GitHubError(f"GitHub GraphQL returned errors: {payload['errors']}")
        connection = payload["data"]["repository"]["pullRequest"]["reviewThreads"]
        for node in connection["nodes"]:
            first = (node["comments"]["nodes"] or [{}])[0]
            threads.append(
                {
                    "resolved": node["isResolved"],
                    "path": node.get("path"),
                    "author": (first.get("author") or {}).get("login"),
                    "author_type": (first.get("author") or {}).get("__typename"),
                    "body": first.get("body") or "",
                }
            )
        if not connection["pageInfo"]["hasNextPage"]:
            return threads
        after = connection["pageInfo"]["endCursor"]


def state_artifact_name(pr: int) -> str:
    return f"{STATE_ARTIFACT_PREFIX}{pr}"


WORKFLOW_PATH = ".github/workflows/oracle-review-shadow.yml"
TRUSTED_EVENTS = frozenset({"pull_request_target", "issue_comment", "schedule", "workflow_dispatch"})


def on_develop(repo: str, sha: str) -> bool:
    try:
        comparison = get_json(f"repos/{repo}/compare/{sha}...develop")
    except GitHubError:
        return False
    return comparison.get("status") in ("ahead", "identical")


def _targets_develop(run: dict[str, Any], pr: int) -> bool:
    pulls = [pull for pull in run.get("pull_requests") or [] if isinstance(pull, dict)]
    return (
        bool(pulls)
        and all((pull.get("base") or {}).get("ref") == "develop" for pull in pulls)
        and any(pull.get("number") == pr for pull in pulls)
    )


def _parse_time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _started_after(run: dict[str, Any], base_changed_at: datetime | None) -> bool:
    if base_changed_at is None:
        return True
    started = _parse_time(run.get("created_at"))
    return started is not None and started > base_changed_at


def base_changed_at(repo: str, pr: int) -> datetime | None:
    events = get_paginated(f"repos/{repo}/issues/{pr}/timeline?per_page=100")
    moments = [_parse_time(event.get("created_at")) for event in events if event.get("event") == "base_ref_changed"]
    if any(moment is None for moment in moments):
        raise GitHubError(f"a base change on #{pr} has no readable time")
    return max(filter(None, moments), default=None)


def trusted_run(
    run: dict[str, Any],
    repo: str,
    pr: int,
    is_on_develop: Callable[[str, str], bool] = on_develop,
    retargeted_at: datetime | None = None,
) -> bool:
    head_sha = str(run.get("head_sha", ""))
    event = run.get("event")
    if not (
        str(run.get("path", "")).split("@", 1)[0] == WORKFLOW_PATH
        and (run.get("repository") or {}).get("full_name") == repo
        and event in TRUSTED_EVENTS
        and re.fullmatch(r"[0-9a-f]{40}", head_sha) is not None
    ):
        return False
    if event == "pull_request_target":
        return _targets_develop(run, pr) and _started_after(run, retargeted_at)
    return is_on_develop(repo, head_sha)


def latest_state(repo: str, pr: int) -> State | None:
    name = state_artifact_name(pr)
    listing = get_json(f"repos/{repo}/actions/artifacts?name={name}&per_page=30")
    candidates = sorted(
        (item for item in listing.get("artifacts", []) if not item.get("expired")),
        key=lambda item: item.get("created_at", ""),
        reverse=True,
    )
    try:
        retargeted_at = base_changed_at(repo, pr)
    except GitHubError:
        retargeted_at = datetime.max.replace(tzinfo=UTC)
    for candidate in candidates:
        run_id = str(candidate["workflow_run"]["id"])
        if not trusted_run(get_json(f"repos/{repo}/actions/runs/{run_id}"), repo, pr, retargeted_at=retargeted_at):
            continue
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                ["gh", "run", "download", run_id, "-n", name, "-D", directory, "-R", repo],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise GitHubError(f"could not download {name} from run {run_id}: {result.stderr.strip()[:500]}")
            return State.from_json(json.loads((Path(directory) / STATE_FILE).read_text(encoding="utf-8")))
    return None


def dispatch(repo: str, workflow: str, pr: int) -> None:
    result = subprocess.run(
        ["gh", "workflow", "run", workflow, "--ref", "develop", "-f", f"pr={pr}", "-R", repo],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GitHubError(f"could not dispatch {workflow} for #{pr}: {result.stderr.strip()[:500]}")
