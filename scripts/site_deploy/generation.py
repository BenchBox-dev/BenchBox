from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from scripts.site_deploy import deployments
from scripts.site_deploy.candidate import CandidateError, semver_key
from scripts.site_deploy.githubapi import ApiError, GitHubClient
from scripts.site_deploy.receipt import (
    ReceiptError,
    is_last_known_good,
    parse_status_description,
    receipt_sha256,
    validate_receipt,
)

DEPLOY = "deploy"
NOOP = "noop"
REFUSE = "refuse"
MODES = ("preview", "deploy", "rollback")


class GenerationAuthorityError(RuntimeError):
    pass


@dataclass(frozen=True)
class Deployed:
    generation: int
    trunk_sha: str
    release_tag: str
    corpus_sha: str
    run_id: int
    receipt_sha256: str
    artifact_sha256: str
    ui_version: int
    snapshot_version: int
    newer_unreceipted: bool = False
    link_baseline: dict[str, list[list[str]]] = field(default_factory=dict)


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str


AncestryCheck = Callable[[str, str], bool]


def deployed_from_receipt(receipt: dict[str, Any], receipt_sha: str, newer_unreceipted: bool = False) -> Deployed:
    baseline = receipt.get("link_baseline")
    link_baseline: dict[str, list[list[str]]] = {}
    if isinstance(baseline, dict) and isinstance(baseline.get("links"), list) and baseline.get("release_tag"):
        link_baseline = {str(baseline["release_tag"]): [[str(part) for part in entry] for entry in baseline["links"]]}
    return Deployed(
        generation=receipt["generation"],
        trunk_sha=receipt["trunk_sha"],
        release_tag=receipt["release_tag"],
        corpus_sha=receipt["corpus_sha"],
        run_id=receipt["run_id"],
        receipt_sha256=receipt_sha,
        artifact_sha256=receipt["artifact"]["sha256"],
        ui_version=int(receipt["versions"]["ui_expected"]),
        snapshot_version=int(receipt["versions"]["snapshot"]),
        newer_unreceipted=newer_unreceipted,
        link_baseline=link_baseline,
    )


def generation_gate(
    *,
    candidate_trunk: str,
    candidate_tag: str,
    deployed: Deployed | None,
    mode: str,
    is_ancestor: AncestryCheck,
    candidate_corpus: str | None = None,
) -> Decision:
    if mode not in MODES:
        return Decision(REFUSE, f"unknown mode {mode!r}")
    if deployed is None:
        if mode == "rollback":
            return Decision(REFUSE, "rollback needs a deployed generation to roll back from")
        return Decision(DEPLOY, "no deployed generation; first deployment")
    same_trunk = candidate_trunk == deployed.trunk_sha
    same_tag = candidate_tag == deployed.release_tag
    same_corpus = mode != "rollback" or candidate_corpus is None or candidate_corpus == deployed.corpus_sha
    if same_trunk and same_tag and same_corpus:
        return Decision(NOOP, f"generation {deployed.generation} already deployed")
    if mode == "rollback":
        return Decision(DEPLOY, "rollback to a previously deployed generation")
    try:
        if semver_key(candidate_tag) < semver_key(deployed.release_tag):
            return Decision(REFUSE, f"release {candidate_tag} is older than deployed {deployed.release_tag}")
    except CandidateError as exc:
        return Decision(REFUSE, str(exc))
    if not same_trunk:
        try:
            if is_ancestor(candidate_trunk, deployed.trunk_sha):
                return Decision(REFUSE, f"trunk {candidate_trunk} is older than deployed {deployed.trunk_sha}")
            if not is_ancestor(deployed.trunk_sha, candidate_trunk):
                return Decision(REFUSE, f"trunk {candidate_trunk} diverges from deployed {deployed.trunk_sha}")
        except CandidateError as exc:
            return Decision(REFUSE, f"ancestry unknown: {exc}")
    return Decision(DEPLOY, f"candidate advances generation {deployed.generation}")


def recheck_decision(
    *,
    resolved_receipt_sha256: str | None,
    deployed: Deployed | None,
    candidate_trunk: str,
    candidate_tag: str,
    candidate_corpus: str | None,
    mode: str,
    is_ancestor: AncestryCheck,
) -> Decision:
    current = deployed.receipt_sha256 if deployed else None
    if resolved_receipt_sha256 != current:
        return Decision(
            REFUSE, f"deployed generation changed since resolution ({resolved_receipt_sha256} -> {current})"
        )
    decision = generation_gate(
        candidate_trunk=candidate_trunk,
        candidate_tag=candidate_tag,
        candidate_corpus=candidate_corpus,
        deployed=deployed,
        mode=mode,
        is_ancestor=is_ancestor,
    )
    return decision


@dataclass(frozen=True)
class ReceiptPointer:
    sha256: str
    run_id: int
    newer_unreceipted: bool


def deployed_receipt_run(client: GitHubClient, allow_bootstrap: bool) -> ReceiptPointer | None:
    newer_unreceipted = False
    try:
        for deployment in deployments.scan_deployments(client):
            statuses = client.get_list(f"deployments/{deployment['id']}/statuses")
            successes = sorted(
                (status for status in statuses if status.get("state") == "success"),
                key=lambda item: str(item.get("created_at") or ""),
                reverse=True,
            )
            if not successes:
                continue
            for status in successes:
                parsed = parse_status_description(str(status.get("description") or ""))
                if parsed is not None:
                    if newer_unreceipted and not allow_bootstrap:
                        raise GenerationAuthorityError(
                            "the newest successful github-pages deployment carries no site-deploy receipt; "
                            "rerun with bootstrap enabled to order against the newest receipt-bearing generation"
                        )
                    return ReceiptPointer(parsed[0], parsed[1], newer_unreceipted)
            newer_unreceipted = True
    except (ApiError, KeyError) as exc:
        raise GenerationAuthorityError(f"deployment lookup failed: {exc}") from exc
    if allow_bootstrap:
        return None
    raise GenerationAuthorityError(
        f"none of the newest {deployments.DEPLOYMENT_SCAN_LIMIT} github-pages deployments carries a site-deploy "
        "receipt; rerun with bootstrap enabled for the first generation"
    )


def read_deployed(
    client: GitHubClient,
    load_receipt: Callable[[int, str | None], bytes],
    allow_bootstrap: bool = False,
    require_good: bool = True,
) -> Deployed | None:
    found = deployed_receipt_run(client, allow_bootstrap)
    if found is None:
        return None
    expected_sha, run_id = found.sha256, found.run_id
    try:
        raw = load_receipt(run_id, expected_sha)
    except (OSError, ValueError) as exc:
        raise GenerationAuthorityError(f"receipt artifact for run {run_id} is unavailable: {exc}") from exc
    if receipt_sha256(raw) != expected_sha:
        raise GenerationAuthorityError(f"receipt for run {run_id} does not match its recorded sha256")
    try:
        receipt = validate_receipt(json.loads(raw))
    except (ValueError, ReceiptError) as exc:
        raise GenerationAuthorityError(f"receipt for run {run_id} is invalid: {exc}") from exc
    if receipt["run_id"] != run_id:
        raise GenerationAuthorityError(f"receipt for run {run_id} names run {receipt['run_id']}")
    if require_good and not is_last_known_good(receipt):
        raise GenerationAuthorityError(f"deployed receipt for run {run_id} is not last-known-good")
    return deployed_from_receipt(receipt, expected_sha, found.newer_unreceipted)
