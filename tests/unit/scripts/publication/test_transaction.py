"""Unit tests for canonical publication transaction module (scripts/publication/transaction.py)."""

from __future__ import annotations

import dataclasses

import pytest

from scripts.publication import transaction as tx_mod

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def valid_receipt_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tx_mod, "validate_live_receipt_contract", lambda receipt: [])


def receipt_for(tx: tx_mod.Transaction, observation_digest: str) -> dict[str, object]:
    return {
        "signature": "test-signature",
        "target": tx.target,
        "generation": tx.generation,
        "manifest_digest": tx.content.get("manifest_digest"),
        "artifact_digest": tx.artifact.get("archive_sha256"),
        "observation_digest": observation_digest,
    }


def make_durable(tx: tx_mod.Transaction) -> tx_mod.Transaction:
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": "a" * 40})
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_ACKNOWLEDGE_WRITE, {"id": "durable-deployment"})
    tx, _ = tx_mod.transition(
        tx,
        tx_mod.EVENT_VERIFY_SUCCESS,
        {"observation_digest": "verified", "attestation": receipt_for(tx, "verified")},
    )
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_COMMIT_DURABLE)
    return tx


@pytest.fixture
def base_context() -> dict[str, dict[str, str]]:
    return {
        "target": {
            "repository": "BenchBox-dev/BenchBox",
            "environment": "github-pages",
            "url": "https://benchbox.dev",
        },
        "approval": {
            "permit_sha256": "permit-sha-123456",
            "approver": "joe",
        },
        "controller": {
            "workflow_path": ".github/workflows/publication-transaction.yml",
            "workflow_sha": "a" * 40,
            "run_id": "1001",
            "run_attempt": "1",
        },
        "owner": {
            "run_id": "1001",
            "epoch": "1",
        },
        "content": {
            "manifest_digest": "m" * 64,
            "develop_sha": "d" * 40,
            "published_results_sha": "p" * 40,
        },
        "artifact": {
            "artifact_id": 999,
            "archive_sha256": "art" * 20,
        },
    }


def test_prepare_promotion(base_context: dict[str, dict[str, str]]) -> None:
    tx, effect = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id="parent-uuid-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )

    assert tx.state == tx_mod.STATE_PREPARED
    assert tx.kind == tx_mod.KIND_PROMOTION
    assert tx.generation == 10
    assert tx.parent_transaction_id == "parent-uuid-001"
    assert tx.recovery_of is None
    assert effect.action == "persist_prepared"
    assert tx.desired["payload"]["generation"] == 10
    assert tx.desired["payload"]["content_digest"] == base_context["content"]["manifest_digest"]


def test_promotion_lifecycle_happy_path(base_context: dict[str, dict[str, str]]) -> None:
    tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id="parent-uuid-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )

    # 1. Start write
    intent_oid = "1" * 40
    tx, effect = tx_mod.transition(tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": intent_oid})
    assert tx.state == tx_mod.STATE_WRITE_STARTED
    assert effect.action == "create_deployment"
    assert effect.data["pages_build_version"] == intent_oid

    # 2. Acknowledge write
    tx, effect = tx_mod.transition(
        tx,
        tx_mod.EVENT_ACKNOWLEDGE_WRITE,
        {"id": "dep-456", "status": "SUCCESS", "status_url": "https://api.github.com/..."},
    )
    assert tx.state == tx_mod.STATE_WRITE_ACKNOWLEDGED
    assert effect.action == "probe_endpoints"
    assert tx.write["id"] == "dep-456"

    # 3. Verify success
    obs_digest = "obs" * 20
    tx, effect = tx_mod.transition(
        tx,
        tx_mod.EVENT_VERIFY_SUCCESS,
        {"observation_digest": obs_digest, "challenge": "ch-1", "attestation": receipt_for(tx, obs_digest)},
    )
    assert tx.state == tx_mod.STATE_EXTERNALLY_VERIFIED
    assert effect.action == "commit_durable"
    assert tx.verification["observation_digest"] == obs_digest
    assert tx.attestation["signature"] == "test-signature"

    # 4. Commit durable
    tx, effect = tx_mod.transition(tx, tx_mod.EVENT_COMMIT_DURABLE)
    assert tx.state == tx_mod.STATE_DURABLE
    assert effect.action == "advance_durable_head"


def test_promotion_write_failure_requires_recovery(base_context: dict[str, dict[str, str]]) -> None:
    tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id="parent-uuid-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )

    intent_oid = "1" * 40
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": intent_oid})
    assert tx.state == tx_mod.STATE_WRITE_STARTED

    tx, effect = tx_mod.transition(tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "Provider rejected write with 503"})
    assert tx.state == tx_mod.STATE_RECOVERY_REQUIRED
    assert effect.action == "escalate_recovery"
    assert tx.failure["stage"] == "post_send"


def test_prepare_rollback_requires_activation_barrier(base_context: dict[str, dict[str, str]]) -> None:
    parent_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=9,
        parent_transaction_id="g8",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content={"manifest_digest": "parent-manifest"},
        artifact={"artifact_id": 888, "archive_sha256": "parent-art"},
    )
    parent_tx = make_durable(parent_tx)

    failed_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id=parent_tx.transaction_id,
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": "2" * 40})
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "timeout"})

    # Rollback without barrier evidence must fail
    with pytest.raises(tx_mod.TransactionError, match="activation barrier evidence is required"):
        tx_mod.prepare_rollback(
            failed_transaction=failed_tx,
            parent_durable_transaction=parent_tx,
            generation=11,
            controller=base_context["controller"],
            owner=base_context["owner"],
            barrier_evidence={},
        )


def test_prepare_rollback_rejects_non_durable_source(base_context: dict[str, dict[str, str]]) -> None:
    parent_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=9,
        parent_transaction_id="g8",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    failed_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id=parent_tx.transaction_id,
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "pre-send failure"})

    with pytest.raises(tx_mod.TransactionError, match="durable transaction"):
        tx_mod.prepare_rollback(
            failed_transaction=failed_tx,
            parent_durable_transaction=parent_tx,
            generation=11,
            controller=base_context["controller"],
            owner=base_context["owner"],
            barrier_evidence={},
        )


def test_prepare_rollback_requires_advancing_generation(base_context: dict[str, dict[str, str]]) -> None:
    parent_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=9,
        parent_transaction_id="g8",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    parent_tx = make_durable(parent_tx)
    failed_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id=parent_tx.transaction_id,
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "pre-send failure"})

    with pytest.raises(tx_mod.TransactionError, match="generation must advance"):
        tx_mod.prepare_rollback(
            failed_transaction=failed_tx,
            parent_durable_transaction=parent_tx,
            generation=10,
            controller=base_context["controller"],
            owner=base_context["owner"],
            barrier_evidence={},
        )


def test_prepare_rollback_rejects_nonterminal_provider(base_context: dict[str, dict[str, str]]) -> None:
    parent_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=9,
        parent_transaction_id="g8",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    parent_tx = make_durable(parent_tx)
    failed_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id=parent_tx.transaction_id,
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": "2" * 40})
    with pytest.raises(tx_mod.TransactionError, match="Affirmative"):
        tx_mod.prepare_rollback(
            failed_transaction=failed_tx,
            parent_durable_transaction=parent_tx,
            generation=11,
            controller=base_context["controller"],
            owner=base_context["owner"],
            barrier_evidence={
                "provider_status": "in_progress",
                "quiescence_observed": False,
                "deployment_id": failed_tx.write["write_id"],
            },
        )


def test_rollback_lifecycle_happy_path(base_context: dict[str, dict[str, str]]) -> None:
    parent_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=9,
        parent_transaction_id="g8",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content={"manifest_digest": "parent-manifest-123"},
        artifact={"artifact_id": 888, "archive_sha256": "parent-art-123"},
    )
    parent_tx = make_durable(parent_tx)

    failed_tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id=parent_tx.transaction_id,
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": "3" * 40})
    failed_tx, _ = tx_mod.transition(failed_tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "timeout"})

    # Prepare rollback
    rb_tx, effect = tx_mod.prepare_rollback(
        failed_transaction=failed_tx,
        parent_durable_transaction=parent_tx,
        generation=11,
        controller=base_context["controller"],
        owner=base_context["owner"],
        barrier_evidence={
            "provider_status": "canceled",
            "quiescence_observed": True,
            "provider_deployment_absent": True,
            "artifact_id": failed_tx.artifact["artifact_id"],
            "pages_build_version": failed_tx.write["pages_build_version"],
        },
    )

    assert rb_tx.state == tx_mod.STATE_ROLLBACK_WRITE_STARTED
    assert rb_tx.kind == tx_mod.KIND_ROLLBACK
    assert rb_tx.generation == 11
    assert rb_tx.recovery_of == failed_tx.transaction_id
    assert rb_tx.restore_source["manifest_digest"] == "parent-manifest-123"
    assert rb_tx.desired["payload"]["content_digest"] == "parent-manifest-123"
    assert rb_tx.desired["payload"]["recovery_of"] == failed_tx.transaction_id
    assert effect.action == "create_deployment"
    assert effect.data["artifact_id"] == 888

    # Acknowledge rollback write
    rb_tx, effect = tx_mod.transition(rb_tx, tx_mod.EVENT_ACKNOWLEDGE_WRITE, {"id": "rb-dep-1", "status": "SUCCESS"})
    assert rb_tx.state == tx_mod.STATE_WRITE_ACKNOWLEDGED
    assert effect.action == "probe_endpoints"

    # Verify rollback probes
    rb_tx, effect = tx_mod.transition(
        rb_tx,
        tx_mod.EVENT_VERIFY_ROLLBACK,
        {"observation_digest": "rb-obs-999", "attestation": receipt_for(rb_tx, "rb-obs-999")},
    )
    assert rb_tx.state == tx_mod.STATE_ROLLBACK_VERIFIED
    assert effect.action == "commit_rollback"

    # Commit rollback durable
    rb_tx, effect = tx_mod.transition(rb_tx, tx_mod.EVENT_COMMIT_ROLLBACK)
    assert rb_tx.state == tx_mod.STATE_ROLLBACK_DURABLE
    assert effect.action == "advance_durable_head"


def _recovery_required_promotion(base_context: dict[str, dict[str, str]]) -> tx_mod.Transaction:
    tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=6,
        parent_transaction_id="parent-uuid-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_START_WRITE, {"intent_commit_oid": "1" * 40})
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "poll loop misreported terminal status"})
    assert tx.state == tx_mod.STATE_RECOVERY_REQUIRED
    assert tx.failure["stage"] == "post_send"
    return tx


def test_recovery_required_reconciles_forward_to_durable(base_context: dict[str, dict[str, str]]) -> None:
    tx = _recovery_required_promotion(base_context)
    obs_digest = "obs" * 20

    tx, effect = tx_mod.transition(
        tx,
        tx_mod.EVENT_VERIFY_SUCCESS,
        {
            "observation_digest": obs_digest,
            "pages_deployment_id": "a" * 40,
            "pages_deployment_status": "succeed",
            "attestation": receipt_for(tx, obs_digest),
        },
    )
    assert tx.state == tx_mod.STATE_EXTERNALLY_VERIFIED
    assert effect.action == "commit_durable"
    assert tx.verification["reconciled_from"] == tx_mod.STATE_RECOVERY_REQUIRED
    assert tx.verification["pages_deployment_id"] == "a" * 40
    assert tx.verification["pages_deployment_status"] == "succeed"
    assert tx.failure["stage"] == "post_send"

    tx, effect = tx_mod.transition(tx, tx_mod.EVENT_COMMIT_DURABLE)
    assert tx.state == tx_mod.STATE_DURABLE
    assert effect.action == "advance_durable_head"


def test_recovery_reconciliation_requires_succeed_status(base_context: dict[str, dict[str, str]]) -> None:
    tx = _recovery_required_promotion(base_context)
    obs_digest = "obs" * 20
    with pytest.raises(tx_mod.TransactionError, match="Pages deployment status of 'succeed'"):
        tx_mod.transition(
            tx,
            tx_mod.EVENT_VERIFY_SUCCESS,
            {
                "observation_digest": obs_digest,
                "pages_deployment_id": "a" * 40,
                "pages_deployment_status": "deployment_failed",
                "attestation": receipt_for(tx, obs_digest),
            },
        )


def test_recovery_reconciliation_rejects_mismatched_deployment_id(
    base_context: dict[str, dict[str, str]],
) -> None:
    tx = _recovery_required_promotion(base_context)
    obs_digest = "obs" * 20
    with pytest.raises(tx_mod.TransactionError, match="bound to this transaction's controller SHA"):
        tx_mod.transition(
            tx,
            tx_mod.EVENT_VERIFY_SUCCESS,
            {
                "observation_digest": obs_digest,
                "pages_deployment_id": "b" * 40,
                "pages_deployment_status": "succeed",
                "attestation": receipt_for(tx, obs_digest),
            },
        )


def test_recovery_reconciliation_rejects_missing_deployment_id(
    base_context: dict[str, dict[str, str]],
) -> None:
    tx = _recovery_required_promotion(base_context)
    obs_digest = "obs" * 20
    with pytest.raises(tx_mod.TransactionError, match="bound to this transaction's controller SHA"):
        tx_mod.transition(
            tx,
            tx_mod.EVENT_VERIFY_SUCCESS,
            {
                "observation_digest": obs_digest,
                "pages_deployment_status": "succeed",
                "attestation": receipt_for(tx, obs_digest),
            },
        )


def test_recovery_reconciliation_requires_controller_workflow_sha(
    base_context: dict[str, dict[str, str]],
) -> None:
    ctx = {**base_context, "controller": {**base_context["controller"], "workflow_sha": ""}}
    tx = _recovery_required_promotion(ctx)
    obs_digest = "obs" * 20
    with pytest.raises(tx_mod.TransactionError, match="requires the transaction's controller workflow SHA"):
        tx_mod.transition(
            tx,
            tx_mod.EVENT_VERIFY_SUCCESS,
            {
                "observation_digest": obs_digest,
                "pages_deployment_id": "a" * 40,
                "pages_deployment_status": "succeed",
                "attestation": receipt_for(tx, obs_digest),
            },
        )


def test_recovery_reconciliation_rejects_pre_send_failure(base_context: dict[str, dict[str, str]]) -> None:
    tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=6,
        parent_transaction_id="parent-uuid-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    tx, _ = tx_mod.transition(tx, tx_mod.EVENT_FAIL_WRITE, {"reason": "OIDC denied before send"})
    assert tx.state == tx_mod.STATE_RECOVERY_REQUIRED
    assert tx.failure["stage"] == "pre_send"

    with pytest.raises(tx_mod.TransactionError, match="post-send failure with a landed provider write"):
        tx_mod.transition(
            tx,
            tx_mod.EVENT_VERIFY_SUCCESS,
            {
                "observation_digest": "obs" * 20,
                "pages_deployment_id": "a" * 40,
                "pages_deployment_status": "succeed",
                "attestation": receipt_for(tx, "obs" * 20),
            },
        )


def test_recovery_required_still_allows_mark_terminal(base_context: dict[str, dict[str, str]]) -> None:
    tx = _recovery_required_promotion(base_context)
    tx, effect = tx_mod.transition(tx, tx_mod.EVENT_MARK_TERMINAL, {"reason": "operator abandoned generation"})
    assert tx.state == tx_mod.STATE_TERMINAL_FAILURE
    assert effect.action == "terminal_stop"


@pytest.mark.parametrize("kind", [tx_mod.KIND_ROLLBACK, tx_mod.KIND_LEGACY_RECOVERY])
def test_recovery_reconciliation_is_restricted_to_promotions(
    base_context: dict[str, dict[str, str]], kind: str
) -> None:
    """A non-promotion in recovery-required must not be reconciled forward: neither
    kind admits externally-verified, so the journal would reject the written state."""
    tx = dataclasses.replace(_recovery_required_promotion(base_context), kind=kind)
    obs_digest = "obs" * 20

    with pytest.raises(tx_mod.TransactionError, match="applies only to promotions"):
        tx_mod.transition(
            tx,
            tx_mod.EVENT_VERIFY_SUCCESS,
            {
                "observation_digest": obs_digest,
                "pages_deployment_id": "a" * 40,
                "pages_deployment_status": "succeed",
                "attestation": receipt_for(tx, obs_digest),
            },
        )


def test_invalid_state_transition_raises_error(base_context: dict[str, dict[str, str]]) -> None:
    tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=10,
        parent_transaction_id="parent-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )

    with pytest.raises(tx_mod.TransactionError, match="Invalid transition"):
        tx_mod.transition(tx, tx_mod.EVENT_COMMIT_DURABLE)


def test_transition_start_write_with_explicit_pages_build_version(base_context: dict[str, dict[str, str]]) -> None:
    tx, _ = tx_mod.prepare_promotion(
        target=base_context["target"],
        generation=2,
        parent_transaction_id="parent-uuid-001",
        approval=base_context["approval"],
        controller=base_context["controller"],
        owner=base_context["owner"],
        content=base_context["content"],
        artifact=base_context["artifact"],
    )
    intent_oid = "1" * 40
    wire_sha = "2" * 40
    tx, effect = tx_mod.transition(
        tx,
        tx_mod.EVENT_START_WRITE,
        {"intent_commit_oid": intent_oid, "pages_build_version": wire_sha},
    )
    assert tx.state == tx_mod.STATE_WRITE_STARTED
    assert effect.action == "create_deployment"
    assert effect.data["pages_build_version"] == wire_sha
    assert tx.write["intent_commit_oid"] == intent_oid
    assert tx.write["pages_build_version"] == wire_sha
