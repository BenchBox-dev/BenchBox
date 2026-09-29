"""Reading and writing the durable deployment record.

Each production run leaves two things behind: a workflow artifact holding its
final receipt, and a status on the ``github-pages`` Deployment it created whose
description names the run. The status is the index; the artifact is the receipt.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from scripts.site_deploy.github import Api, gh_post
from scripts.site_deploy.receipt import RECEIPT_NAME, ReceiptError, parse_deployment_description, validate_receipt

PAGES_ENVIRONMENT = "github-pages"
WORKFLOW_PATH = ".github/workflows/site-deploy.yml"
RECEIPT_ARTIFACT_PREFIX = "site-deploy-receipt-"
ARTIFACT_NAME_PREFIX = "site-deploy-artifact-"

Download = Callable[[str, int], bytes]


@dataclass(frozen=True)
class LiveRecord:
    """The newest live Pages deployment and, if it is ours, the run that made it."""

    deployment_id: int
    run_id: int
    verified: bool  # False when the deployment went live but failed its post-deploy probes
    description: str


def find_live_record(repo: str, api: Api, limit: int = 30) -> tuple[LiveRecord | None, bool]:
    """Newest live deployment, and whether a foreign writer deployed after the last site-deploy.

    Returns ``(record, foreign_since)``. ``record`` is the newest deployment that
    is still live and was written by site-deploy, or ``None``. ``foreign_since`` is
    true when a live deployment from some other writer is newer than that record
    (or when no site-deploy record exists but the site has other deployments).
    """
    foreign_seen = False
    for deployment in api(f"repos/{repo}/deployments?environment={PAGES_ENVIRONMENT}&per_page={limit}") or []:
        statuses = api(f"repos/{repo}/deployments/{deployment['id']}/statuses?per_page=10") or []
        if not statuses or statuses[0].get("state") != "success":
            continue  # failed, pending, or superseded: not what is live
        description = str(statuses[0].get("description") or "")
        parsed = parse_deployment_description(description)
        if parsed is None:
            foreign_seen = True
            continue
        return LiveRecord(int(deployment["id"]), int(parsed["run"]), parsed["st"] == "ok", description), foreign_seen
    return None, foreign_seen


def _unzip_receipt(payload: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = [name for name in archive.namelist() if name.endswith(RECEIPT_NAME)]
        if not names:
            raise ReceiptError(f"artifact has no {RECEIPT_NAME}")
        data = json.loads(archive.read(names[0]))
    problems = validate_receipt(data)
    if problems:
        raise ReceiptError("invalid receipt: " + "; ".join(problems))
    return data


def fetch_receipt(
    repo: str, run_id: int, api: Api, download: Download, *, allow_failed_run: bool = False
) -> dict[str, Any]:
    """Download and validate the final receipt of a site-deploy run.

    The run must be a site-deploy run on trunk and, unless ``allow_failed_run`` is
    set (used only for the currently live deployment, whose run may have failed its
    probes), a successful one. The receipt must name that same run, so a receipt
    cannot be borrowed from another workflow or attempt.
    """
    run = api(f"repos/{repo}/actions/runs/{run_id}") or {}
    path = str(run.get("path", "")).split("@", 1)[0]
    if path != WORKFLOW_PATH:
        raise ReceiptError(f"run {run_id} is not a site-deploy run (workflow path {path!r})")
    if run.get("conclusion") != "success" and not (allow_failed_run and run.get("conclusion") == "failure"):
        raise ReceiptError(f"run {run_id} did not conclude successfully ({run.get('conclusion')!r})")
    if run.get("head_branch") != "develop":
        raise ReceiptError(f"run {run_id} did not run from develop ({run.get('head_branch')!r})")
    artifacts = (api(f"repos/{repo}/actions/runs/{run_id}/artifacts") or {}).get("artifacts", [])
    wanted = f"{RECEIPT_ARTIFACT_PREFIX}{run_id}"
    match = next((a for a in artifacts if a.get("name") == wanted and not a.get("expired")), None)
    if match is None:
        raise ReceiptError(f"run {run_id} has no unexpired artifact {wanted!r}")
    receipt = _unzip_receipt(download(repo, int(match["id"])))
    if str(receipt.get("workflow", {}).get("run_id")) != str(run_id):
        raise ReceiptError(f"receipt in run {run_id} names run {receipt.get('workflow', {}).get('run_id')}")
    return receipt


def find_run_deployment(repo: str, api: Api, sha: str, run_started_at: str) -> int | None:
    """The ``github-pages`` deployment this run created (newest for ``sha`` since the run began)."""
    deployments = api(f"repos/{repo}/deployments?environment={PAGES_ENVIRONMENT}&sha={sha}&per_page=100") or []
    since = [d for d in deployments if str(d.get("created_at", "")) >= run_started_at]
    if not since:
        return None
    return int(max(since, key=lambda d: str(d["created_at"]))["id"])


def record_deployment_status(repo: str, deployment_id: int, description: str, log_url: str) -> None:
    """Attach the receipt index to a Deployment as a ``success`` status."""
    gh_post(
        f"repos/{repo}/deployments/{deployment_id}/statuses",
        {
            "state": "success",
            "description": description,
            "log_url": log_url,
            "environment": PAGES_ENVIRONMENT,
        },
    )
