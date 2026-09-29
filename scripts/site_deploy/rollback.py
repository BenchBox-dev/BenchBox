"""Rollback: redeploy the exact artifact a prior receipt names.

Rollback never rebuilds. It accepts only a receipt that was probed green in
production, checks the retained archive against the receipt's sha256, checks the
extracted tree against its tree digest and route checksums, and applies the same
mixed-version rule as a forward deploy before anything reaches Pages.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from scripts.site_deploy import gates, generation, receipt
from scripts.site_deploy.pipeline import PipelineError, utc_now, workflow_context


def plan_rollback(
    *,
    repo_root: Path,
    target_receipt: dict[str, Any],
    deployed_receipt: dict[str, Any] | None,
    live_unconfirmed: bool = False,
) -> tuple[generation.Decision, generation.RollbackTarget, generation.DeployedState | None]:
    target = receipt.rollback_target_from_receipt(target_receipt)
    deployed = receipt.deployed_state_from_receipt(deployed_receipt) if deployed_receipt else None
    relations = generation.relations_for(repo_root, target.generation, deployed.generation) if deployed else None
    return generation.decide_rollback(target, deployed, relations, live_unconfirmed=live_unconfirmed), target, deployed


def stage_rollback(
    *,
    target_receipt: dict[str, Any],
    deployed_receipt: dict[str, Any],
    archive: Path,
    out_dir: Path,
    target: str,
    waive_cache_window: bool = False,
    workflow: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify and extract the retained artifact; return the candidate rollback receipt."""
    site_dir = out_dir / "site"
    if site_dir.exists():
        raise PipelineError(f"refusing to stage over an existing directory: {site_dir}")
    receipt.verify_archive(archive, target_receipt)
    receipt.extract_tar_safely(archive, site_dir)
    identity = receipt.verify_extracted_tree(site_dir, target_receipt)

    target_versions = receipt.explorer_versions_from_receipt(target_receipt)
    deployed_versions = receipt.explorer_versions_from_receipt(deployed_receipt)
    mixed = gates.gate_mixed_versions(deployed_versions, target_versions, waive_cache_window=waive_cache_window)
    if not mixed.ok:
        raise PipelineError(f"rollback refused: {mixed.detail}")

    restored = receipt.rollback_target_from_receipt(target_receipt)
    deployed = receipt.deployed_state_from_receipt(deployed_receipt)
    trunk_q, tag_q = generation.quarantine_after_rollback(deployed, restored.generation)
    ctx = workflow or workflow_context()
    run_id = ctx.get("run_id", "local")
    rolled = receipt.new_receipt(
        receipt_id=f"site-deploy-{run_id}-{ctx.get('run_attempt', '1')}",
        operation="rollback",
        target=target,
        generation=restored.generation,
        routes=target_receipt["routes"],
        identity_evidence=target_receipt["candidate_identity"],
        identity=identity,
        archive_sha256=target_receipt["artifact"]["sha256"],
        explorer=target_receipt.get("explorer", {}),
        gates=[mixed.to_dict()],
        checksums=target_receipt["checksums"],
        quarantine=(trunk_q, tag_q),
        workflow=ctx,
        created_at=utc_now(),
        rollback={
            "restored_receipt_id": target_receipt["receipt_id"],
            "restored_run_id": target_receipt.get("workflow", {}).get("run_id"),
            "replaced_receipt_id": deployed_receipt["receipt_id"],
        },
    )
    (out_dir / receipt.RECEIPT_NAME).write_text(receipt.dumps(rolled), encoding="utf-8")
    return rolled
