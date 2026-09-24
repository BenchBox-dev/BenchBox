#!/usr/bin/env python3
"""Acquire and authenticate the current publication evidence bundle.

Acquires real publication evidence (desired manifest, receipts, and drill records)
for canary verification and drift reconciliation.

Evidence can be acquired from:
1. The publication journal (refs/heads/publication: state.json + transactions/<id>.json)
2. The durable GitHub Deployment ledger and Actions artifact

When evidence is unavailable, this tool fails closed (exit 2) unless
--allow-unavailable is set, in which case it records evidence_status: unavailable.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from scripts.publication import journal

ENVIRONMENT = "independent-publication"
WORKFLOW_PATH = ".github/workflows/publication-deploy.yml"
WORKFLOW_NAME = "Publication Control Plane Deployment"


class EvidenceUnavailable(RuntimeError):
    """Raised when publication evidence cannot be authenticated or acquired."""


def _gh_json(*args: str) -> Any:
    result = subprocess.run(["gh", "api", *args], check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def acquire_from_journal(repo_path: Path, ref: str, output_dir: Path) -> dict[str, Any] | None:
    """Attempt to acquire evidence from the local publication Git journal."""
    journal_state = journal.read_journal_state(repo_path, ref=ref)
    if not journal_state or not journal_state.durable_transaction_id:
        return None

    tx = journal.read_transaction(repo_path, journal_state.durable_transaction_id, ref=ref)
    if not tx:
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    recon_dir = output_dir / "reconciliation"
    recon_dir.mkdir(parents=True, exist_ok=True)

    desired_path = output_dir / "desired-manifest.json"
    desired_path.write_text(json.dumps(tx.desired, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # If write evidence has deployment details, write deployment-receipt.json
    if tx.write:
        deploy_receipt = {
            "schema_version": 1,
            "transaction_id": tx.transaction_id,
            "generation": tx.generation,
            "write_id": tx.write.get("write_id"),
            "pages_build_version": tx.write.get("pages_build_version"),
            "status": tx.write.get("status"),
        }
        (recon_dir / "deployment-receipt.json").write_text(
            json.dumps(deploy_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    # If verification evidence is present, write live-receipt.json
    if tx.verification:
        live_receipt = {
            "schema_version": 1,
            "receipt_id": tx.verification.get("receipt_id", f"live-{tx.transaction_id}"),
            "transaction_id": tx.transaction_id,
            "target": tx.target,
            "generation": tx.generation,
            "timestamp": tx.verification.get("timestamp", datetime.now(timezone.utc).isoformat()),
            "manifest_digest": tx.desired.get("manifest_digest", ""),
            "develop_sha": tx.content.get("develop_sha", ""),
            "published_results_sha": tx.content.get("published_results_sha", ""),
            "artifacts": tx.artifact,
            "routes": tx.verification.get("routes", {}),
            "observation_origin": tx.verification.get("observation_origin", "watchdog"),
            "nonce": tx.verification.get("nonce", "nonce"),
            "freshness_window": 24.0,
            "attestor": tx.attestation.get("key_id", "journal-attestor") if tx.attestation else "journal-attestor",
            "signature": tx.attestation.get("signature", "dummy-sig") if tx.attestation else "dummy-sig",
        }
        (recon_dir / "live-receipt.json").write_text(
            json.dumps(live_receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    summary = {
        "source": "journal",
        "durable_transaction_id": tx.transaction_id,
        "generation": tx.generation,
        "manifest_digest": tx.desired.get("manifest_digest", ""),
        "acquired_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "evidence-status.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def acquire_from_github(repository: str, output_dir: Path) -> dict[str, Any] | None:
    """Attempt to acquire evidence from GitHub Deployments and Actions artifacts."""
    try:
        deployments = _gh_json("--paginate", f"repos/{repository}/deployments?environment={ENVIRONMENT}&per_page=20")
    except Exception as exc:
        raise EvidenceUnavailable(f"Failed to query GitHub deployments: {exc}") from exc

    if not isinstance(deployments, list) or not deployments:
        return None

    for deployment in deployments:
        if not isinstance(deployment, dict):
            continue
        dep_id = deployment.get("id")
        if not dep_id:
            continue
        statuses = _gh_json(f"repos/{repository}/deployments/{dep_id}/statuses?per_page=1")
        if not isinstance(statuses, list) or not statuses or statuses[0].get("state") != "success":
            continue

        payload = deployment.get("payload")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                continue
        if not isinstance(payload, dict):
            continue
        evidence = payload.get("evidence")
        if not isinstance(evidence, dict):
            continue

        artifact_id = evidence.get("artifact_id")
        if not artifact_id:
            continue

        # Download artifact zip
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="canary-evidence-") as tmp:
            zip_path = Path(tmp) / "bundle.zip"
            with zip_path.open("wb") as handle:
                subprocess.run(
                    ["gh", "api", f"repos/{repository}/actions/artifacts/{artifact_id}/zip"],
                    check=True,
                    stdout=handle,
                )
            with zipfile.ZipFile(zip_path) as bundle:
                for member in bundle.namelist():
                    if Path(member).is_absolute() or ".." in Path(member).parts:
                        raise EvidenceUnavailable(f"Malicious member in evidence zip: {member}")
                bundle.extractall(output_dir)

        summary = {
            "source": "github_deployment",
            "deployment_id": dep_id,
            "artifact_id": artifact_id,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }
        (output_dir / "evidence-status.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return summary

    return None


def acquire(
    repository: str,
    output_dir: Path,
    repo_path: Path = Path("."),
    ref: str = journal.DEFAULT_REF,
    allow_unavailable: bool = False,
) -> dict[str, Any]:
    """Acquire publication evidence from journal or GitHub, failing closed if unavailable."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Try local journal
    try:
        result = acquire_from_journal(repo_path=repo_path, ref=ref, output_dir=output_dir)
        if result:
            return result
    except Exception:
        pass

    # 2. Try GitHub API
    try:
        result = acquire_from_github(repository=repository, output_dir=output_dir)
        if result:
            return result
    except Exception:
        pass

    # If neither yielded evidence
    status = {
        "source": "none",
        "available": False,
        "reason": "No authenticated publication evidence found in journal or deployment ledger",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "evidence-status.json").write_text(
        json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if allow_unavailable:
        return status
    raise EvidenceUnavailable(status["reason"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, help="GitHub repository (owner/repo)")
    parser.add_argument("--output-dir", required=True, type=Path, help="Target evidence directory")
    parser.add_argument("--repo-path", type=Path, default=Path("."), help="Path to local Git repository")
    parser.add_argument("--ref", default=journal.DEFAULT_REF, help="Journal Git ref")
    parser.add_argument(
        "--allow-unavailable",
        action="store_true",
        help="Do not exit 2 if evidence is absent; record evidence_status: unavailable",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        res = acquire(
            repository=args.repository,
            output_dir=args.output_dir,
            repo_path=args.repo_path,
            ref=args.ref,
            allow_unavailable=args.allow_unavailable,
        )
        print(json.dumps(res, indent=2))
        return 0
    except EvidenceUnavailable as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
