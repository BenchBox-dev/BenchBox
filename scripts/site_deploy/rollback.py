from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.site_deploy import artifacts, deployments, receipt as receipt_module
from scripts.site_deploy.githubapi import ApiError, GitHubClient


class RollbackError(RuntimeError):
    pass


@dataclass(frozen=True)
class Restore:
    receipt: dict[str, Any]
    receipt_sha256: str
    tree: Path


def load_restore(receipt_path: Path, tree: Path, target: str = "github-pages") -> Restore:
    if not receipt_path.is_file():
        raise RollbackError(f"receipt is missing: {receipt_path}")
    raw = receipt_path.read_bytes()
    try:
        parsed = receipt_module.validate_receipt(json.loads(raw))
    except (ValueError, receipt_module.ReceiptError) as exc:
        raise RollbackError(f"receipt is invalid: {exc}") from exc
    if not receipt_module.is_last_known_good(parsed, target):
        raise RollbackError("receipt is not last-known-good: probes or gates did not pass on the target")
    try:
        artifacts.verify_tree(tree, parsed["artifact"]["sha256"])
    except artifacts.ArtifactError as exc:
        raise RollbackError(str(exc)) from exc
    return Restore(receipt=parsed, receipt_sha256=receipt_module.receipt_sha256(raw), tree=tree)


def recorded_in_deployments(statuses_by_deployment: list[list[dict[str, Any]]], restore: Restore) -> bool:
    wanted = receipt_module.status_description(restore.receipt_sha256, restore.receipt["run_id"])
    return any(
        status.get("state") == "success" and status.get("description") == wanted
        for statuses in statuses_by_deployment
        for status in statuses
    )


def recorded_shas(client: GitHubClient, run_id: int) -> list[str]:
    found: list[str] = []
    try:
        for deployment in deployments.scan_deployments(client):
            statuses = client.get_list(f"deployments/{deployment['id']}/statuses")
            for status in sorted(statuses, key=lambda item: str(item.get("created_at") or ""), reverse=True):
                if status.get("state") != "success":
                    continue
                parsed = receipt_module.parse_status_description(str(status.get("description") or ""))
                if parsed is not None and parsed[1] == run_id and parsed[0] not in found:
                    found.append(parsed[0])
    except (ApiError, KeyError) as exc:
        raise RollbackError(f"deployment history is unreadable: {exc}") from exc
    return found


def verify_recorded(client: GitHubClient, receipt_sha256: str, run_id: int) -> None:
    if receipt_sha256 not in recorded_shas(client, run_id):
        raise RollbackError(f"receipt {receipt_sha256} of run {run_id} is not recorded on a github-pages deployment")
