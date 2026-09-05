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

    failed_write = failed_transaction.write or {}
    expected_deployment = failed_write.get("id") or failed_write.get("write_id")
    if (
        barrier_evidence.get("provider_status", "").upper() not in {"CANCELED", "FAILED", "ERROR"}
        or barrier_evidence.get("quiescence_observed") is not True
        or barrier_evidence.get("deployment_id") != expected_deployment
    ):
        raise TransactionError("Affirmative provider activation barrier evidence is required before preparing rollback")

    tx_id = transaction_id or str(uuid.uuid4())

    restore_source = {
        "parent_transaction_id": parent_durable_transaction.transaction_id,
        "parent_generation": parent_durable_transaction.generation,
        "manifest_digest": parent_durable_transaction.content.get("manifest_digest"),
        "artifact_digest": parent_durable_transaction.artifact.get("archive_sha256"),
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
        data["state"] = STATE_ROLLBACK_VERIFIED if current.kind == KIND_ROLLBACK else STATE_EXTERNALLY_VERIFIED
        data["verification"] = {
            "challenge": payload.get("challenge"),
            "verifier_sha": payload.get("verifier_sha"),
            "observation_digest": obs_digest,
            "verified_at": ev["timestamp"],
        }
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
