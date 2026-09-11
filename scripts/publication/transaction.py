#!/usr/bin/env python3
"""Canonical publication transaction schema, builder, and state machine.

Implements the single state transition engine shared by promotion,
rollback, and external recovery (Slice B).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from scripts.publication.reconciliation import DEFAULT_MAX_AGE_HOURS, validate_live_receipt_contract

SCHEMA_VERSION = 1
OBJECT_TYPE = "publication-transaction"

# Transaction kinds
KIND_PROMOTION = "promotion"
KIND_ROLLBACK = "rollback"
KIND_LEGACY_RECOVERY = "legacy_recovery"

# States
STATE_PREPARED = "prepared"
STATE_WRITE_STARTED = "write-started"
STATE_WRITE_ACKNOWLEDGED = "write-acknowledged"
STATE_EXTERNALLY_VERIFIED = "externally-verified"
STATE_DURABLE = "durable"
STATE_RECOVERY_REQUIRED = "recovery-required"
STATE_ROLLBACK_WRITE_STARTED = "rollback-write-started"
STATE_ROLLBACK_VERIFIED = "rollback-verified"
STATE_ROLLBACK_DURABLE = "rollback-durable"
STATE_TERMINAL_FAILURE = "terminal-failure"

VALID_STATES = {
    STATE_PREPARED,
    STATE_WRITE_STARTED,
    STATE_WRITE_ACKNOWLEDGED,
    STATE_EXTERNALLY_VERIFIED,
    STATE_DURABLE,
    STATE_RECOVERY_REQUIRED,
    STATE_ROLLBACK_WRITE_STARTED,
    STATE_ROLLBACK_VERIFIED,
    STATE_ROLLBACK_DURABLE,
    STATE_TERMINAL_FAILURE,
}
VALID_KINDS = {KIND_PROMOTION, KIND_ROLLBACK, KIND_LEGACY_RECOVERY}

# Events
EVENT_PREPARE = "prepare"
EVENT_START_WRITE = "start-write"
EVENT_ACKNOWLEDGE_WRITE = "acknowledge-write"
EVENT_VERIFY_SUCCESS = "verify-success"
EVENT_COMMIT_DURABLE = "commit-durable"
EVENT_FAIL_WRITE = "fail-write"
EVENT_FAIL_VERIFICATION = "fail-verification"
EVENT_START_ROLLBACK = "start-rollback"
EVENT_VERIFY_ROLLBACK = "verify-rollback"
EVENT_COMMIT_ROLLBACK = "commit-rollback"
EVENT_MARK_TERMINAL = "mark-terminal"


class TransactionError(Exception):
    """Base exception for invalid transaction operations or state transitions."""


def canonical_json(data: dict[str, Any]) -> str:
    """Return compact, sorted UTF-8 JSON representation."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def compute_digest(data: dict[str, Any]) -> str:
    """Compute SHA-256 digest of canonical JSON."""
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def validate_live_receipt(
    current: Transaction,
    payload: dict[str, Any],
    *,
    max_age_hours: float | None = DEFAULT_MAX_AGE_HOURS,
) -> dict[str, Any]:
    """Validate signed receipt evidence and bind it to the current transaction."""
    receipt = payload.get("attestation")
    if not isinstance(receipt, dict):
        raise TransactionError("A signed live-receipt attestation is required for verification success")
    try:
        if max_age_hours is None or max_age_hours != DEFAULT_MAX_AGE_HOURS:
            contract_findings = validate_live_receipt_contract(receipt, max_age_hours=max_age_hours)
        else:
            contract_findings = validate_live_receipt_contract(receipt)
    except TypeError:
        contract_findings = validate_live_receipt_contract(receipt)
    if contract_findings:
        raise TransactionError(f"Live-receipt attestation is invalid: {contract_findings[0].description}")

    artifact = receipt.get("artifact") if isinstance(receipt.get("artifact"), dict) else {}
    receipt_target = receipt.get("target")
    expected_target = current.target
    expected_host = str(current.target.get("base_url") or current.target.get("url") or "").rstrip("/").split("://")[-1]
    target_matches = receipt_target == expected_target or (
        isinstance(receipt_target, str)
        and receipt_target.rstrip("/").split("://")[-1]
        in {
            expected_host,
            str(current.target.get("environment") or ""),
        }
    )
    artifact_set = receipt.get("artifacts") if isinstance(receipt.get("artifacts"), dict) else {}
    pages_artifact = artifact_set.get("pages_assembly") if isinstance(artifact_set.get("pages_assembly"), dict) else {}
    receipt_artifact_digest = (
        receipt.get("artifact_digest") or artifact.get("archive_sha256") or pages_artifact.get("digest")
    )
    routes = receipt.get("routes") or receipt.get("probes")
    receipt_observation_digest = receipt.get("observation_digest")
    if receipt_observation_digest is None and isinstance(routes, list):
        receipt_observation_digest = hashlib.sha256(canonical_json({"routes": routes}).encode("utf-8")).hexdigest()
    bindings = {
        "target": (expected_target if target_matches else receipt_target, expected_target),
        "generation": (receipt.get("generation"), current.generation),
        "manifest_digest": (receipt.get("manifest_digest"), current.content.get("manifest_digest")),
        "artifact_digest": (
            receipt_artifact_digest,
            current.artifact.get("archive_sha256") or current.artifact.get("site_tree_sha256"),
        ),
        "observation_digest": (
            receipt_observation_digest,
            payload.get("observation_digest") or receipt_observation_digest,
        ),
    }
    mismatches = [name for name, (actual, expected) in bindings.items() if actual != expected or actual is None]
    if mismatches:
        raise TransactionError(f"Live-receipt attestation does not match transaction fields: {', '.join(mismatches)}")
    return receipt


@dataclass(frozen=True)
class Effect:
    action: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Transaction:
    transaction_id: str
    target: dict[str, str]
    kind: str
    generation: int
    parent_transaction_id: str | None
    recovery_of: str | None
    restore_source: dict[str, Any] | None
    approval: dict[str, Any]
    controller: dict[str, Any]
    owner: dict[str, Any]
    content: dict[str, Any]
    desired: dict[str, Any]
    artifact: dict[str, Any]
    state: str = STATE_PREPARED
    write: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    certification: dict[str, Any] | None = None
    failure: dict[str, Any] | None = None
    event: dict[str, Any] = field(default_factory=dict)
    attestation: dict[str, Any] | None = None
    object_type: str = OBJECT_TYPE
    transaction_schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def digest(self) -> str:
        d = self.to_dict()
        d["attestation"] = None
        return compute_digest(d)


def prepare_promotion(
    *,
    target: dict[str, str],
    generation: int,
    parent_transaction_id: str | None,
    approval: dict[str, Any],
    controller: dict[str, Any],
    owner: dict[str, Any],
    content: dict[str, Any],
    artifact: dict[str, Any],
    transaction_id: str | None = None,
) -> tuple[Transaction, Effect]:
    """Prepare a new promotion transaction in PREPARED state."""
    tx_id = transaction_id or str(uuid.uuid4())

    desired_payload = {
        "content_digest": content.get("manifest_digest"),
        "target": target,
        "generation": generation,
        "parent_transaction_id": parent_transaction_id,
    }
    desired = {
        "digest": compute_digest(desired_payload),
        "payload": desired_payload,
    }

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_PREPARE,
        "actor": controller.get("workflow_path", "controller"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tx = Transaction(
        transaction_id=tx_id,
        target=target,
        kind=KIND_PROMOTION,
        generation=generation,
        parent_transaction_id=parent_transaction_id,
        recovery_of=None,
        restore_source=None,
        approval=approval,
        controller=controller,
        owner=owner,
        content=content,
        desired=desired,
        artifact=artifact,
        state=STATE_PREPARED,
        event=event,
    )
    return tx, Effect(action="persist_prepared", data={"transaction_id": tx.transaction_id})


def prepare_rollback(
    *,
    failed_transaction: Transaction,
    parent_durable_transaction: Transaction,
    generation: int,
    controller: dict[str, Any],
    owner: dict[str, Any],
    barrier_evidence: dict[str, Any],
    transaction_id: str | None = None,
) -> tuple[Transaction, Effect]:
    """Prepare a successor rollback transaction describing restored parent bytes."""
    if failed_transaction.state not in (STATE_RECOVERY_REQUIRED, STATE_WRITE_STARTED, STATE_WRITE_ACKNOWLEDGED):
        raise TransactionError(f"Cannot initiate rollback from non-recoverable state: {failed_transaction.state}")
    if generation <= failed_transaction.generation:
        raise TransactionError("Rollback generation must advance beyond the failed transaction generation")

    if parent_durable_transaction.state not in (STATE_DURABLE, STATE_ROLLBACK_DURABLE):
        raise TransactionError("Rollback source must be a durable transaction")
    if failed_transaction.parent_transaction_id != parent_durable_transaction.transaction_id:
        raise TransactionError("Rollback source must match the failed transaction parent")
    if failed_transaction.target != parent_durable_transaction.target:
        raise TransactionError("Rollback source target must match the failed transaction target")

    failed_write = failed_transaction.write or {}
    expected_deployment = failed_write.get("id")
    provider_identity_matches = (
        expected_deployment is not None and barrier_evidence.get("deployment_id") == expected_deployment
    )
    provider_absence_matches = (
        expected_deployment is None
        and barrier_evidence.get("provider_deployment_absent") is True
        and barrier_evidence.get("artifact_id") == failed_transaction.artifact.get("artifact_id")
        and barrier_evidence.get("pages_build_version") == failed_write.get("pages_build_version")
    )
    if (
        barrier_evidence.get("provider_status", "").upper() not in {"CANCELED", "FAILED", "ERROR"}
        or barrier_evidence.get("quiescence_observed") is not True
        or not (provider_identity_matches or provider_absence_matches)
    ):
        raise TransactionError("Affirmative provider activation barrier evidence is required before preparing rollback")

    tx_id = transaction_id or str(uuid.uuid4())

    restore_source = {
        "parent_transaction_id": parent_durable_transaction.transaction_id,
        "parent_generation": parent_durable_transaction.generation,
        "manifest_digest": parent_durable_transaction.content.get("manifest_digest"),
        "artifact_digest": parent_durable_transaction.artifact.get("archive_sha256")
        or parent_durable_transaction.artifact.get("site_tree_sha256"),
        "barrier_evidence": barrier_evidence,
    }

    desired_payload = {
        "content_digest": parent_durable_transaction.content.get("manifest_digest"),
        "target": failed_transaction.target,
        "generation": generation,
        "parent_transaction_id": failed_transaction.parent_transaction_id,
        "recovery_of": failed_transaction.transaction_id,
    }
    desired = {
        "digest": compute_digest(desired_payload),
        "payload": desired_payload,
    }

    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": EVENT_START_ROLLBACK,
        "actor": controller.get("workflow_path", "watchdog"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    tx = Transaction(
        transaction_id=tx_id,
        target=failed_transaction.target,
        kind=KIND_ROLLBACK,
        generation=generation,
        parent_transaction_id=failed_transaction.parent_transaction_id,
        recovery_of=failed_transaction.transaction_id,
        restore_source=restore_source,
        approval=failed_transaction.approval,
        controller=controller,
        owner=owner,
        content=parent_durable_transaction.content,
        desired=desired,
        artifact=parent_durable_transaction.artifact,
        state=STATE_ROLLBACK_WRITE_STARTED,
        event=event,
    )
    return tx, Effect(
        action="create_deployment",
        data={
            "artifact_id": tx.artifact.get("artifact_id"),
            "pages_build_version": tx.restore_source.get("manifest_digest", "")[:40],
        },
    )


def _handle_prepared(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_START_WRITE:
        intent_commit_oid = payload.get("intent_commit_oid")
        if not intent_commit_oid:
            raise TransactionError("intent_commit_oid is required to start write")
        data["state"] = STATE_WRITE_STARTED
        data["write"] = {
            "write_id": payload.get("write_id", str(uuid.uuid4())),
            "intent_commit_oid": intent_commit_oid,
            "pages_build_version": intent_commit_oid,
            "status": "in_flight",
            "started_at": ev["timestamp"],
        }
        tx = Transaction(**data)
        return tx, Effect(
            action="create_deployment",
            data={
                "artifact_id": tx.artifact.get("artifact_id"),
                "pages_build_version": intent_commit_oid,
            },
        )

    if event_type == EVENT_FAIL_WRITE:
        data["state"] = STATE_RECOVERY_REQUIRED
        data["failure"] = {
            "code": payload.get("code", "PRE_SEND_FAILURE"),
            "stage": "pre_send",
            "reason": payload.get("reason", "Write failed before provider transmission"),
        }
        return Transaction(**data), Effect(action="escalate_recovery", data=data["failure"])

    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


def _handle_write_started(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_ACKNOWLEDGE_WRITE:
        provider_id = payload.get("id")
        if not provider_id:
            raise TransactionError("Provider deployment id is required for write acknowledgement")
        data["state"] = STATE_WRITE_ACKNOWLEDGED
        write_info = dict(data.get("write") or {})
        write_info.update(
            {
                "id": provider_id,
                "status_url": payload.get("status_url"),
                "status": payload.get("status", "SUCCESS"),
                "observed_at": ev["timestamp"],
            }
        )
        deployed_artifact_id = payload.get("artifact_id")
        if deployed_artifact_id not in (None, ""):
            data["artifact"] = {**(data.get("artifact") or {}), "artifact_id": int(deployed_artifact_id)}
        data["write"] = write_info
        tx = Transaction(**data)
        return tx, Effect(action="probe_endpoints", data={"write_id": write_info.get("write_id")})

    if event_type == EVENT_FAIL_WRITE:
        data["state"] = STATE_RECOVERY_REQUIRED
        data["failure"] = {
            "code": payload.get("code", "POST_SEND_FAILURE"),
            "stage": "post_send",
            "reason": payload.get("reason", "Provider deployment write failed or timed out"),
        }
        return Transaction(**data), Effect(action="escalate_recovery", data=data["failure"])

    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


def _handle_write_acknowledged(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_VERIFY_SUCCESS or (current.kind == KIND_ROLLBACK and event_type == EVENT_VERIFY_ROLLBACK):
        obs_digest = payload.get("observation_digest")
        if not obs_digest:
            raise TransactionError("observation_digest is required for verification success")
        attestation = validate_live_receipt(current, payload)
        data["state"] = STATE_ROLLBACK_VERIFIED if current.kind == KIND_ROLLBACK else STATE_EXTERNALLY_VERIFIED
        data["verification"] = {
            "challenge": payload.get("challenge"),
            "verifier_sha": payload.get("verifier_sha"),
            "observation_digest": obs_digest,
            "verified_at": ev["timestamp"],
        }
        data["attestation"] = attestation
        tx = Transaction(**data)
        next_action = "commit_rollback" if current.kind == KIND_ROLLBACK else "commit_durable"
        return tx, Effect(action=next_action, data={"transaction_id": tx.transaction_id})

    if event_type == EVENT_FAIL_VERIFICATION:
        data["state"] = STATE_TERMINAL_FAILURE if current.kind == KIND_ROLLBACK else STATE_RECOVERY_REQUIRED
        data["failure"] = {
            "code": payload.get("code", "VERIFICATION_FAILURE"),
            "stage": "verification",
            "reason": payload.get("reason", "External probe verification failed"),
        }
        return Transaction(**data), Effect(action="escalate_recovery", data=data["failure"])

    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


def _handle_externally_verified(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_COMMIT_DURABLE:
        data["state"] = STATE_DURABLE
        tx = Transaction(**data)
        return tx, Effect(action="advance_durable_head", data={"durable_transaction_id": tx.transaction_id})
    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


def _handle_rollback_write_started(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_ACKNOWLEDGE_WRITE:
        provider_id = payload.get("id")
        if not provider_id:
            raise TransactionError("Provider deployment id is required for rollback acknowledgement")
        data["state"] = STATE_WRITE_ACKNOWLEDGED
        data["write"] = {
            "id": provider_id,
            "status_url": payload.get("status_url"),
            "status": payload.get("status", "SUCCESS"),
            "observed_at": ev["timestamp"],
        }
        tx = Transaction(**data)
        return tx, Effect(action="probe_endpoints", data={"transaction_id": tx.transaction_id})

    if event_type == EVENT_FAIL_WRITE:
        data["state"] = STATE_TERMINAL_FAILURE
        data["failure"] = {
            "code": payload.get("code", "ROLLBACK_WRITE_FAILURE"),
            "stage": "post_send",
            "reason": payload.get("reason", "Rollback provider write failed"),
        }
        return Transaction(**data), Effect(action="terminal_stop", data=data["failure"])

    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


def _handle_rollback_verified(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_COMMIT_ROLLBACK:
        data["state"] = STATE_ROLLBACK_DURABLE
        tx = Transaction(**data)
        return tx, Effect(action="advance_durable_head", data={"durable_transaction_id": tx.transaction_id})
    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


def _handle_recovery_required(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any],
    ev: dict[str, Any],
    data: dict[str, Any],
) -> tuple[Transaction, Effect]:
    if event_type == EVENT_MARK_TERMINAL:
        data["state"] = STATE_TERMINAL_FAILURE
        data["failure"] = {
            "code": payload.get("code", "MANUAL_TERMINAL_ESCALATION"),
            "stage": "terminal",
            "reason": payload.get("reason", "Marked terminal due to unresolvable ambiguity"),
        }
        return Transaction(**data), Effect(action="terminal_stop", data=data["failure"])

    if event_type == EVENT_VERIFY_SUCCESS:
        # Forward reconciliation of a post-send failure whose provider write
        # provably landed: the deployment reached the provider's terminal-success
        # state and the live routes serve the approved candidate. Only a
        # promotion whose failure was recorded at the post-send stage qualifies;
        # a pre-send or verification failure has no landed write to reconcile.
        # Allowlist promotions rather than denylist rollbacks: this handler also
        # serves legacy_recovery, whose journal states exclude externally-verified,
        # so reconciling one forward would corrupt the journal on reload.
        if current.kind != KIND_PROMOTION:
            raise TransactionError(f"Recovery reconciliation applies only to promotions, not kind {current.kind!r}")
        failure = current.failure or {}
        if failure.get("stage") != "post_send":
            raise TransactionError("Recovery reconciliation requires a post-send failure with a landed provider write")
        obs_digest = payload.get("observation_digest")
        if not obs_digest:
            raise TransactionError("observation_digest is required for recovery reconciliation")

        # The provider status must be bound to *this* transaction's deployment.
        # The deploy step sends `pages_build_version: github.sha`, which the
        # provider resolves to the controller's workflow SHA, so that SHA is the
        # provider-side identity of this transaction's write. It is a journal
        # field, so it cannot be altered without a CAS-protected journal write.
        # Requiring the caller to name that same identity makes an unrelated or
        # stale deployment's success unable to reconcile this transaction.
        expected_deployment_id = (current.controller or {}).get("workflow_sha")
        pages_deployment_id = payload.get("pages_deployment_id")
        if not expected_deployment_id:
            raise TransactionError("Recovery reconciliation requires the transaction's controller workflow SHA")
        if pages_deployment_id != expected_deployment_id:
            raise TransactionError(
                "Recovery reconciliation requires Pages deployment evidence bound to this transaction's "
                f"controller SHA {expected_deployment_id!r}, got: {pages_deployment_id!r}"
            )

        pages_status = str(payload.get("pages_deployment_status") or "").lower()
        if pages_status != "succeed":
            raise TransactionError(
                "Recovery reconciliation requires a Pages deployment status of 'succeed', "
                f"got: {payload.get('pages_deployment_status')!r}"
            )
        attestation = validate_live_receipt(current, payload)
        data["state"] = STATE_EXTERNALLY_VERIFIED
        data["verification"] = {
            "challenge": payload.get("challenge"),
            "verifier_sha": payload.get("verifier_sha"),
            "observation_digest": obs_digest,
            "pages_deployment_id": pages_deployment_id,
            "pages_deployment_status": pages_status,
            "reconciled_from": STATE_RECOVERY_REQUIRED,
            "verified_at": ev["timestamp"],
        }
        data["attestation"] = attestation
        tx = Transaction(**data)
        return tx, Effect(action="commit_durable", data={"transaction_id": tx.transaction_id})

    raise TransactionError(f"Invalid transition: event '{event_type}' from state '{current.state}'")


_HANDLERS = {
    STATE_PREPARED: _handle_prepared,
    STATE_WRITE_STARTED: _handle_write_started,
    STATE_WRITE_ACKNOWLEDGED: _handle_write_acknowledged,
    STATE_EXTERNALLY_VERIFIED: _handle_externally_verified,
    STATE_ROLLBACK_WRITE_STARTED: _handle_rollback_write_started,
    STATE_ROLLBACK_VERIFIED: _handle_rollback_verified,
    STATE_RECOVERY_REQUIRED: _handle_recovery_required,
}


def transition(
    current: Transaction,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> tuple[Transaction, Effect]:
    """Execute a pure state transition and return (new_transaction, next_effect)."""
    payload = payload or {}
    ev = {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "actor": payload.get("actor", current.controller.get("workflow_path", "controller")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    data = current.to_dict()
    data["event"] = ev

    handler = _HANDLERS.get(current.state)
    if not handler:
        raise TransactionError(
            f"Invalid transition: event '{event_type}' is not allowed from terminal or unhandled state '{current.state}'"
        )

    return handler(current, event_type, payload, ev, data)
