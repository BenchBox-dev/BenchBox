from __future__ import annotations

import re
from typing import Any

from scripts.site_deploy import receipt as receipt_module
from scripts.site_deploy.githubapi import ApiError, GitHubClient

ENVIRONMENT = "github-pages"
DEPLOYMENT_SCAN_LIMIT = 100
RUN_LINK_FIELDS = ("log_url", "target_url")


class DeploymentLookupError(RuntimeError):
    pass


def scan_deployments(client: GitHubClient) -> list[dict[str, Any]]:
    return client.get_first(f"deployments?environment={ENVIRONMENT}", DEPLOYMENT_SCAN_LIMIT)


def newest_deployment_id(client: GitHubClient, exclude_run_id: int | None = None) -> int | None:
    pattern = run_link_pattern(exclude_run_id) if exclude_run_id is not None else None
    try:
        for deployment in scan_deployments(client):
            if pattern is not None:
                statuses = client.get_list(f"deployments/{deployment['id']}/statuses")
                if any(pattern.search(str(status.get(name) or "")) for status in statuses for name in RUN_LINK_FIELDS):
                    continue
            return int(deployment["id"])
    except (ApiError, KeyError) as exc:
        raise DeploymentLookupError(str(exc)) from exc
    return None


def run_link_pattern(run_id: int) -> re.Pattern[str]:
    return re.compile(rf"/actions/runs/{run_id}(?:[/?#]|$)")


def find_run_deployment_id(client: GitHubClient, run_id: int, sha: str | None = None) -> int:
    pattern = run_link_pattern(run_id)
    try:
        for deployment in scan_deployments(client):
            if sha and deployment.get("sha") not in (None, sha):
                continue
            statuses = client.get_list(f"deployments/{deployment['id']}/statuses")
            if any(pattern.search(str(status.get(name) or "")) for status in statuses for name in RUN_LINK_FIELDS):
                return int(deployment["id"])
    except (ApiError, KeyError) as exc:
        raise DeploymentLookupError(f"deployment history is unreadable: {exc}") from exc
    raise DeploymentLookupError(
        f"none of the newest {DEPLOYMENT_SCAN_LIMIT} {ENVIRONMENT} deployments links to run {run_id}"
    )


def post_receipt_status(
    client: GitHubClient, deployment_id: int, receipt_sha256: str, run_id: int, log_url: str, environment_url: str
) -> dict[str, Any]:
    body = {
        "state": "success",
        "description": receipt_module.status_description(receipt_sha256, run_id),
        "log_url": log_url,
        "environment_url": environment_url,
        "auto_inactive": False,
    }
    try:
        return client.post(f"deployments/{deployment_id}/statuses", body)
    except ApiError as exc:
        raise DeploymentLookupError(f"receipt status was not recorded: {exc}") from exc
