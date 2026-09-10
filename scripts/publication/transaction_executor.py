#!/usr/bin/env python3
"""Canonical CLI and execution engine for publication transactions.

Drives the transactional publication lifecycle:
- prepare: validates candidate bytes or restore source, queries journal, generates canonical permit
- authenticate-approval: validates the protected GitHub environment approval
- record-prepared: atomically reserves generation and commits 'prepared' state to the journal via CAS
- start-write: creates unique intent commit OID, records 'write-started' in journal
- acknowledge-write: records provider deployment outcome in journal ('write-acknowledged')
- record-verification: records probe results and attestation ('externally-verified')
- finalize: atomically advances durable head to 'durable'
- record-failure: escalates transaction to 'recovery-required' or 'terminal-failure'
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.publication import journal, transaction
from scripts.publication.transaction import (
    EVENT_ACKNOWLEDGE_WRITE,
    EVENT_COMMIT_DURABLE,
    EVENT_COMMIT_ROLLBACK,
    EVENT_FAIL_VERIFICATION,
    EVENT_FAIL_WRITE,
    EVENT_START_WRITE,
    EVENT_VERIFY_ROLLBACK,
    EVENT_VERIFY_SUCCESS,
    KIND_LEGACY_RECOVERY,
    KIND_PROMOTION,
    KIND_ROLLBACK,
    STATE_PREPARED,
    STATE_RECOVERY_REQUIRED,
    STATE_ROLLBACK_WRITE_STARTED,
    STATE_TERMINAL_FAILURE,
    Transaction,
    TransactionError,
    canonical_json,
)

WATCHDOG_MAX_AGE_MINUTES = 10


def _load_json(path: Path | str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object at {path}")
    return data


def _write_json(path: Path | str, data: dict[str, Any]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(canonical_json(data) + "\n")


# ---------------------------------------------------------------------------
# 1. Prepare
# ---------------------------------------------------------------------------


def cmd_prepare(args: argparse.Namespace) -> int:  # noqa: C901
    repo_path = Path(args.repo_path).resolve()
    target = {
        "repository": args.target_repo,
        "environment": args.target_env,
        "url": args.target_url,
    }

    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    if journal_state.write_block:
        raise TransactionError(f"Journal has active write block: {journal_state.write_block}")
    if args.kind == KIND_PROMOTION and journal_state.active_transaction_id:
        raise TransactionError(
            f"Cannot prepare promotion: active transaction already exists: {journal_state.active_transaction_id}"
        )
    if args.kind == KIND_ROLLBACK:
        if not args.failed_transaction_id:
            raise TransactionError("failed_transaction_id is required for rollback preparation")
        if journal_state.active_transaction_id != args.failed_transaction_id:
            raise TransactionError(
                f"Cannot prepare rollback: active transaction {journal_state.active_transaction_id} "
                f"does not match failed transaction {args.failed_transaction_id}"
            )

    generation = journal_state.next_generation
    parent_tx_id = journal_state.durable_transaction_id
    tx_id = args.transaction_id or str(uuid.uuid4())
    nonce = uuid.uuid4().hex
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    writer_run_id = args.writer_run_id or os.environ.get("GITHUB_RUN_ID", "local-run")
    owner_epoch = str(generation)

    controller = {
        "repository": args.target_repo,
        "workflow_path": args.workflow_path,
        "workflow_sha": args.workflow_sha or os.environ.get("GITHUB_SHA", "0" * 40),
        "run_id": writer_run_id,
        "run_attempt": int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
    }
    owner = {
        "run_id": writer_run_id,
        "run_attempt": controller["run_attempt"],
        "epoch": owner_epoch,
    }

    if args.kind == KIND_PROMOTION:
        candidate_parent_sha = getattr(args, "candidate_parent_sha", "") or ""
        candidate_parent_generation = getattr(args, "candidate_parent_generation", "") or ""
        if bool(candidate_parent_sha) != bool(candidate_parent_generation):
            raise TransactionError("candidate parent SHA and generation must be supplied together")
        if candidate_parent_generation:
            try:
                candidate_parent_generation_int = int(candidate_parent_generation)
            except ValueError as exc:
                raise TransactionError("candidate parent generation must be a positive integer") from exc
            if candidate_parent_generation_int <= 0:
                raise TransactionError("candidate parent generation must be a positive integer")
            if generation <= 1:
                raise TransactionError("genesis promotion cannot declare a parent")
            if not parent_tx_id:
                raise TransactionError("candidate declares a parent but the journal has no durable transaction")
            parent_tx = journal.read_transaction(repo_path, parent_tx_id, ref=args.ref)
            parent_source_sha = str(
                (parent_tx.attestation or {}).get("source_commit") or parent_tx.content.get("develop_sha") or ""
            )
            if candidate_parent_sha != parent_source_sha or candidate_parent_generation_int != parent_tx.generation:
                raise TransactionError("candidate parent does not match the current durable publication head")
        content = {
            "manifest_digest": args.candidate_manifest_digest,
            "develop_sha": args.develop_sha,
            "published_results_sha": args.published_results_sha,
        }
        if candidate_parent_sha:
            content["parent_sha"] = candidate_parent_sha
            content["parent_generation"] = candidate_parent_generation_int
        artifact = {
            "artifact_id": int(args.candidate_artifact_id) if args.candidate_artifact_id else None,
            "archive_sha256": getattr(args, "candidate_archive_sha256", "") or None,
            "site_tree_sha256": getattr(args, "candidate_site_tree_sha256", "") or None,
        }
        tx, _ = transaction.prepare_promotion(
            target=target,
            generation=generation,
            parent_transaction_id=parent_tx_id,
            approval={},  # Filled upon approval authentication
            controller=controller,
            owner=owner,
            content=content,
            artifact=artifact,
            transaction_id=tx_id,
        )
    elif args.kind == KIND_ROLLBACK:
        if not args.failed_transaction_id:
            raise TransactionError("failed_transaction_id is required for rollback preparation")
        if not args.restore_transaction_id:
            raise TransactionError("restore_transaction_id is required for rollback preparation")

        failed_tx = journal.read_transaction(repo_path, args.failed_transaction_id, ref=args.ref)
        parent_tx = journal.read_transaction(repo_path, args.restore_transaction_id, ref=args.ref)

        barrier_evidence = _load_json(args.barrier_evidence) if args.barrier_evidence else {}
        tx, _ = transaction.prepare_rollback(
            failed_transaction=failed_tx,
            parent_durable_transaction=parent_tx,
            generation=generation,
            controller=controller,
            owner=owner,
            barrier_evidence=barrier_evidence,
            transaction_id=tx_id,
        )
    else:
        raise TransactionError(f"Unsupported transaction kind: {args.kind}")

    permit = {
        "transaction_id": tx.transaction_id,
        "target": target,
        "kind": tx.kind,
        "generation": tx.generation,
        "parent_transaction_id": tx.parent_transaction_id,
        "content_digest": tx.content.get("manifest_digest"),
        "candidate_run_id": getattr(args, "candidate_run_id", None),
        "candidate_artifact_id": tx.artifact.get("artifact_id"),
        "candidate_archive_sha256": tx.artifact.get("archive_sha256"),
        "candidate_site_tree_sha256": tx.artifact.get("site_tree_sha256"),
        "desired_digest": tx.desired.get("digest"),
        "expected_parent_oid": journal_state.tip_commit_oid,
        "expected_journal_revision": journal_state.tip_commit_oid,
        "policy_digest": journal_state.policy_digest,
        "controller_sha": controller["workflow_sha"],
        "writer_run_id": writer_run_id,
        "owner_epoch": owner_epoch,
        "expiry": expiry,
        "nonce": nonce,
    }
    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()

    if args.output_permit:
        _write_json(args.output_permit, permit)
    if args.output_tx:
        _write_json(args.output_tx, tx.to_dict())

    # Emit output variables for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"permit_sha256={permit_digest}\n")
            f.write(f"transaction_id={tx.transaction_id}\n")
            f.write(f"generation={tx.generation}\n")
            if tx.content.get("manifest_digest") is not None:
                f.write(f"candidate_manifest_digest={tx.content['manifest_digest']}\n")
            if tx.artifact.get("artifact_id") is not None:
                f.write(f"artifact_id={tx.artifact['artifact_id']}\n")
            if tx.artifact.get("archive_sha256") is not None:
                f.write(f"candidate_archive_sha256={tx.artifact['archive_sha256']}\n")
            if tx.artifact.get("site_tree_sha256") is not None:
                f.write(f"candidate_site_tree_sha256={tx.artifact['site_tree_sha256']}\n")

    print(f"Prepared {tx.kind} transaction {tx.transaction_id} (gen {tx.generation})")
    print(f"Permit SHA-256: {permit_digest}")
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    """Create a permit for a prepared rollback after operator reconciliation."""
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    tx = journal.read_transaction(repo_path, args.transaction_id, ref=args.ref)
    if tx.kind != KIND_ROLLBACK or tx.state != STATE_ROLLBACK_WRITE_STARTED:
        raise TransactionError("Only a rollback-write-started transaction can be resumed")
    if journal_state.active_transaction_id != tx.transaction_id:
        raise TransactionError("Rollback transaction is not the active journal transaction")
    permit = {
        "transaction_id": tx.transaction_id,
        "target": tx.target,
        "kind": tx.kind,
        "generation": tx.generation,
        "parent_transaction_id": tx.parent_transaction_id,
        "restore_transaction_id": (tx.restore_source or {}).get("parent_transaction_id"),
        "content_digest": tx.content.get("manifest_digest"),
        "artifact_id": tx.artifact.get("artifact_id"),
        "artifact_archive_sha256": tx.artifact.get("archive_sha256"),
        "desired_digest": tx.desired.get("digest"),
        "expected_parent_oid": journal_state.tip_commit_oid,
        "expected_journal_revision": journal_state.tip_commit_oid,
        "policy_digest": journal_state.policy_digest,
        "controller_sha": tx.controller.get("workflow_sha"),
        "writer_run_id": tx.owner.get("run_id"),
        "owner_epoch": tx.owner.get("epoch"),
        "expiry": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "nonce": uuid.uuid4().hex,
    }
    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()
    _write_json(args.output_permit, permit)
    _write_json(args.output_tx, tx.to_dict())
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as output:
            output.write(f"permit_sha256={permit_digest}\n")
            output.write(f"transaction_id={tx.transaction_id}\n")
            output.write(f"generation={tx.generation}\n")
            output.write(f"artifact_id={tx.artifact.get('artifact_id') or ''}\n")
    print(f"Resumed rollback transaction {tx.transaction_id}")
    return 0


# ---------------------------------------------------------------------------
# 2. Authenticate Approval
# ---------------------------------------------------------------------------


def authenticate_approval_record(
    permit: dict[str, Any],
    run_id: str,
    run_attempt: int,
    repo: str,
    token: str | None = None,
    simulated_approval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Authenticate maintainer approval for the given permit and run."""
    # Defect D5 / Section 5: Run attempt > 1 is strictly forbidden
    if run_attempt > 1:
        raise TransactionError(
            f"Writer run attempt {run_attempt} > 1 is forbidden: "
            "GitHub approval objects do not bind run attempt, so attempts > 1 cannot be authenticated."
        )

    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()
    if simulated_approval is not None:
        approvals = [simulated_approval]
    else:
        if not token:
            raise TransactionError("GitHub token is required to authenticate approval via API")
        url = f"https://api.github.com/repos/{repo}/actions/runs/{run_id}/approvals"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "benchbox-publication-transaction",
            },
        )
        try:
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise TransactionError(f"Failed to fetch workflow run approvals: {e}") from e

        approvals = data if isinstance(data, list) else data.get("approvals", [])

    matched = None
    for app in approvals:
        env = app.get("environments", [{}])[0] if app.get("environments") else app.get("environment", {})
        env_name = env.get("name") if isinstance(env, dict) else str(env)
        state = app.get("state", "").lower()
        if env_name == "github-pages" and state == "approved":
            matched = app
            break

    if not matched:
        raise TransactionError(
            f"Approval authentication failed: no approval found on run {run_id} "
            "for protected environment 'github-pages'"
        )

    user = matched.get("user") or {}
    return {
        "authenticated": True,
        "permit_sha256": permit_digest,
        "approver_id": user.get("id"),
        "approver_login": user.get("login"),
        "environment": "github-pages",
        "state": "approved",
        "comment": matched.get("comment"),
        "authenticated_at": datetime.now(timezone.utc).isoformat(),
    }


def cmd_authenticate_approval(args: argparse.Namespace) -> int:
    permit = _load_json(args.permit)
    simulated = _load_json(args.simulated_approval) if args.simulated_approval else None
    token = args.github_token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")

    record = authenticate_approval_record(
        permit=permit,
        run_id=args.run_id or os.environ.get("GITHUB_RUN_ID", "1"),
        run_attempt=int(args.run_attempt or os.environ.get("GITHUB_RUN_ATTEMPT", "1")),
        repo=args.repo or os.environ.get("GITHUB_REPOSITORY", "BenchBox-dev/BenchBox"),
        token=token,
        simulated_approval=simulated,
    )

    if args.output_approval:
        _write_json(args.output_approval, record)

    print(f"Approval authenticated successfully for permit {record['permit_sha256']}")
    print(f"Approver: {record['approver_login']} (ID: {record['approver_id']})")
    return 0


# ---------------------------------------------------------------------------
# 3. Record Prepared
# ---------------------------------------------------------------------------


def cmd_record_prepared(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    permit = _load_json(args.permit)
    approval = _load_json(args.approval)

    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    if journal_state.tip_commit_oid != permit["expected_parent_oid"]:
        raise journal.CasConflictError(
            f"Journal revision moved: expected {permit['expected_parent_oid']}, found {journal_state.tip_commit_oid}"
        )

    tx_data = _load_json(args.tx)
    tx_data["approval"] = approval
    if tx_data.get("kind") != KIND_ROLLBACK:
        tx_data["state"] = STATE_PREPARED
    tx = Transaction(**tx_data)

    new_state = journal.JournalState(
        target=journal_state.target,
        next_generation=max(journal_state.next_generation, tx.generation + 1),
        active_transaction_id=tx.transaction_id,
        durable_transaction_id=journal_state.durable_transaction_id,
        write_block=journal_state.write_block,
        policy_digest=journal_state.policy_digest,
        tip_commit_oid=journal_state.tip_commit_oid,
    )

    updated_state, commit_oid = journal.write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=journal_state.tip_commit_oid,
        new_state=new_state,
        transaction=tx,
        ref=args.ref,
        commit_message=f"transaction: reserve gen {tx.generation} ({tx.transaction_id}) in prepared state",
    )

    if args.output_tx:
        _write_json(args.output_tx, tx.to_dict())

    print(f"Committed prepared transaction {tx.transaction_id} at commit {commit_oid}")
    return 0


# ---------------------------------------------------------------------------
# 4. Start Write
# ---------------------------------------------------------------------------


def cmd_start_write(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    tx = journal.read_transaction(repo_path, args.transaction_id, ref=args.ref)

    if tx.state not in (STATE_PREPARED, STATE_ROLLBACK_WRITE_STARTED):
        raise TransactionError(f"Cannot start write from state {tx.state}")

    # Create a unique write-intent commit on the repository. The intent OID
    # stays a journal-internal correlator: the provider resolves
    # pages_build_version as a commit, so the workflow sends the run's
    # pushed source SHA on the wire instead (an unpushed intent OID makes
    # the provider reject the create request).
    msg = f"write-intent: transaction {tx.transaction_id} gen {tx.generation}"
    tree_oid = subprocess.run(
        ["git", "rev-parse", f"{journal_state.tip_commit_oid}^{{tree}}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    intent_env = dict(os.environ)
    intent_env.setdefault("GIT_AUTHOR_NAME", "BenchBox Publication Controller")
    intent_env.setdefault("GIT_AUTHOR_EMAIL", "publication-controller@benchbox.dev")
    intent_env.setdefault("GIT_COMMITTER_NAME", "BenchBox Publication Controller")
    intent_env.setdefault("GIT_COMMITTER_EMAIL", "publication-controller@benchbox.dev")
    intent_commit_oid = subprocess.run(
        ["git", "commit-tree", tree_oid, "-p", journal_state.tip_commit_oid, "-m", msg],
        cwd=repo_path,
        env=intent_env,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    pages_build_version = getattr(args, "pages_build_version", None) or intent_commit_oid

    if tx.kind == KIND_ROLLBACK:
        updated_tx = replace(
            tx,
            write={
                "write_id": tx.transaction_id,
                "intent_commit_oid": intent_commit_oid,
                "pages_build_version": pages_build_version,
                "status": "in_flight",
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    else:
        updated_tx, _ = transaction.transition(
            tx,
            EVENT_START_WRITE,
            payload={
                "intent_commit_oid": intent_commit_oid,
                "pages_build_version": pages_build_version,
                "write_id": tx.transaction_id,
            },
        )

    updated_state, commit_oid = journal.write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=journal_state.tip_commit_oid,
        new_state=journal_state,
        transaction=updated_tx,
        ref=args.ref,
        commit_message=f"transaction: start write {tx.transaction_id} with intent {intent_commit_oid[:8]}",
    )

    # Emit output for GitHub Actions
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as f:
            f.write(f"pages_build_version={pages_build_version}\n")
            f.write(f"intent_commit_oid={intent_commit_oid}\n")
            f.write(f"write_id={tx.transaction_id}\n")

    if args.output_tx:
        _write_json(args.output_tx, updated_tx.to_dict())

    print(
        f"Started write for {tx.transaction_id}: intent={intent_commit_oid} pages_build_version={pages_build_version}"
    )
    return 0


# ---------------------------------------------------------------------------
# 5. Acknowledge Write
# ---------------------------------------------------------------------------


def cmd_acknowledge_write(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    tx = journal.read_transaction(repo_path, args.transaction_id, ref=args.ref)

    provider_data = _load_json(args.provider_response)
    updated_tx, effect = transaction.transition(tx, EVENT_ACKNOWLEDGE_WRITE, payload=provider_data)

    updated_state, commit_oid = journal.write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=journal_state.tip_commit_oid,
        new_state=journal_state,
        transaction=updated_tx,
        ref=args.ref,
        commit_message=f"transaction: acknowledge write {tx.transaction_id} provider_id={provider_data.get('id')}",
    )

    if args.output_tx:
        _write_json(args.output_tx, updated_tx.to_dict())

    print(f"Acknowledged write for {tx.transaction_id}: provider_id={provider_data.get('id')}")
    return 0


# ---------------------------------------------------------------------------
# 6. Record Verification
# ---------------------------------------------------------------------------


def cmd_record_verification(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    tx = journal.read_transaction(repo_path, args.transaction_id, ref=args.ref)

    probe_report = _load_json(args.probe_report)
    obs_digest = hashlib.sha256(canonical_json(probe_report).encode("utf-8")).hexdigest()

    attestation = _load_json(args.attestation) if args.attestation else None

    event_type = EVENT_VERIFY_ROLLBACK if tx.kind == KIND_ROLLBACK else EVENT_VERIFY_SUCCESS
    updated_tx, effect = transaction.transition(
        tx,
        event_type,
        payload={
            "observation_digest": obs_digest,
            "challenge": args.challenge or "challenge-ok",
            "verifier_sha": args.verifier_sha or os.environ.get("GITHUB_SHA", "0" * 40),
            "attestation": attestation,
        },
    )

    updated_state, commit_oid = journal.write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=journal_state.tip_commit_oid,
        new_state=journal_state,
        transaction=updated_tx,
        ref=args.ref,
        commit_message=f"transaction: record verification success for {tx.transaction_id}",
    )

    if args.output_tx:
        _write_json(args.output_tx, updated_tx.to_dict())

    print(f"Recorded verification for {tx.transaction_id}: state={updated_tx.state}")
    return 0


# ---------------------------------------------------------------------------
# 7. Finalize Durable
# ---------------------------------------------------------------------------


def cmd_finalize(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    tx = journal.read_transaction(repo_path, args.transaction_id, ref=args.ref)

    event_type = EVENT_COMMIT_ROLLBACK if tx.kind == KIND_ROLLBACK else EVENT_COMMIT_DURABLE
    updated_tx, effect = transaction.transition(tx, event_type)

    new_state = journal.JournalState(
        target=journal_state.target,
        next_generation=tx.generation + 1,
        active_transaction_id=None,
        durable_transaction_id=tx.transaction_id,
        write_block=None,
        policy_digest=journal_state.policy_digest,
        tip_commit_oid=journal_state.tip_commit_oid,
    )

    updated_state, commit_oid = journal.write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=journal_state.tip_commit_oid,
        new_state=new_state,
        transaction=updated_tx,
        ref=args.ref,
        commit_message=f"transaction: advance durable head to {tx.transaction_id} (gen {tx.generation})",
    )

    if args.output_tx:
        _write_json(args.output_tx, updated_tx.to_dict())

    print(f"Finalized transaction {tx.transaction_id} as durable head at gen {tx.generation}")
    return 0


# ---------------------------------------------------------------------------
# 8. Record Failure / Escalation
# ---------------------------------------------------------------------------


def cmd_record_failure(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)
    tx = journal.read_transaction(repo_path, args.transaction_id, ref=args.ref)

    event_type = EVENT_FAIL_VERIFICATION if args.stage == "verification" else EVENT_FAIL_WRITE
    updated_tx, effect = transaction.transition(
        tx,
        event_type,
        payload={"code": args.code, "stage": args.stage, "reason": args.reason},
    )

    new_state = journal.JournalState(
        target=journal_state.target,
        next_generation=journal_state.next_generation,
        active_transaction_id=updated_tx.transaction_id if updated_tx.state == STATE_RECOVERY_REQUIRED else None,
        durable_transaction_id=journal_state.durable_transaction_id,
        write_block=args.reason if updated_tx.state == STATE_TERMINAL_FAILURE else None,
        policy_digest=journal_state.policy_digest,
        tip_commit_oid=journal_state.tip_commit_oid,
    )

    updated_state, commit_oid = journal.write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=journal_state.tip_commit_oid,
        new_state=new_state,
        transaction=updated_tx,
        ref=args.ref,
        commit_message=f"transaction: record {updated_tx.state} for {tx.transaction_id}: {args.code}",
    )

    if args.output_tx:
        _write_json(args.output_tx, updated_tx.to_dict())

    print(f"Recorded failure for {tx.transaction_id}: state={updated_tx.state} code={args.code}")
    return 0


def _transaction_age_seconds(tx: transaction.Transaction) -> float | None:
    """Return the age of the durable transaction event when it is parseable."""
    timestamp = tx.event.get("timestamp") if isinstance(tx.event, dict) else None
    if not timestamp:
        return None
    try:
        created = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - created).total_seconds())


def _resolve_watchdog_action(
    tx: transaction.Transaction,
    journal_state: journal.JournalState,
    barrier_evidence: str | None,
) -> tuple[str, str, str]:
    """Resolve (action, status, reason) for active transaction during watchdog scan."""
    age_seconds = _transaction_age_seconds(tx)
    if age_seconds is not None and age_seconds > WATCHDOG_MAX_AGE_MINUTES * 60:
        return (
            "alert",
            "stale_transaction",
            f"Active transaction is {age_seconds / 60:.1f} minutes old; operator reconciliation is required.",
        )
    if tx.state == STATE_PREPARED:
        return (
            "record_failure",
            "run_lost_before_write",
            "Initiating run completed or was lost before starting write; no provider write occurred.",
        )
    if tx.state == transaction.STATE_WRITE_STARTED:
        if barrier_evidence:
            return (
                "record_failure",
                "write_failed_with_barrier",
                "Provider write failed or lost; provider activation barrier verified.",
            )
        return (
            "quarantine",
            "awaiting_activation_barrier",
            "Write started but provider status unknown; cannot compensate without documented activation barrier.",
        )
    if tx.state == transaction.STATE_WRITE_ACKNOWLEDGED:
        return (
            "verify_and_finalize",
            "write_acknowledged_unverified",
            "Provider write succeeded; external verification needed to advance durable head.",
        )
    if tx.state == STATE_ROLLBACK_WRITE_STARTED:
        return (
            "operator_reconcile",
            "rollback_write_pending",
            "Rollback transaction is prepared; an operator must reconcile it through the protected writer.",
        )
    if tx.state in (transaction.STATE_EXTERNALLY_VERIFIED, transaction.STATE_ROLLBACK_VERIFIED):
        return (
            "finalize",
            "verified_unfinalized",
            "Transaction verified; ready for durable CAS advance.",
        )
    if tx.state == STATE_RECOVERY_REQUIRED:
        if not barrier_evidence:
            return (
                "quarantine",
                "awaiting_activation_barrier",
                "Recovery required but awaiting activation barrier evidence.",
            )
        return (
            "operator_restore",
            "ready_for_operator",
            "Recovery required; provider finality evidence is present and an operator must start restoration.",
        )
    if tx.state == STATE_TERMINAL_FAILURE:
        return (
            "none",
            "terminal_failure",
            f"Journal blocked under terminal failure: {journal_state.write_block}",
        )
    return ("none", "unknown_state", f"Unknown transaction state: {tx.state}")


def cmd_watchdog_scan(args: argparse.Namespace) -> int:
    repo_path = Path(args.repo_path).resolve()
    journal_state = journal.read_journal_state(repo_path, ref=args.ref)

    if not journal_state or not journal_state.active_transaction_id:
        report = {
            "status": "idle",
            "recovery_needed": False,
            "action": "none",
            "active_transaction_id": None,
            "state": None,
            "message": "Journal is idle; no in-flight active transaction.",
        }
        if args.output_json:
            _write_json(args.output_json, report)
        print(json.dumps(report, indent=2))
        return 0

    tx_id = journal_state.active_transaction_id
    tx = journal.read_transaction(repo_path, tx_id, ref=args.ref)
    if not tx:
        report = {
            "status": "corrupt_journal",
            "recovery_needed": True,
            "action": "mark_terminal",
            "active_transaction_id": tx_id,
            "state": None,
            "message": f"Active transaction {tx_id} declared in state.json but missing from transactions/",
        }
        if args.output_json:
            _write_json(args.output_json, report)
        print(json.dumps(report, indent=2))
        return 1

    if tx.state == STATE_PREPARED and str(args.trigger_run_id or "") != str(tx.owner.get("run_id", "")):
        action, status, reason = (
            "quarantine",
            "awaiting_owner_run_completion",
            "Prepared transaction owner run has not been confirmed complete.",
        )
    else:
        action, status, reason = _resolve_watchdog_action(tx, journal_state, args.barrier_evidence)
    recovery_needed = tx.state != STATE_TERMINAL_FAILURE

    report = {
        "status": status,
        "recovery_needed": recovery_needed,
        "action": action,
        "active_transaction_id": tx.transaction_id,
        "state": tx.state,
        "kind": tx.kind,
        "reason": reason,
        "age_seconds": _transaction_age_seconds(tx),
    }

    if args.output_json:
        _write_json(args.output_json, report)
    print(json.dumps(report, indent=2))
    return 0


# ---------------------------------------------------------------------------
# Main CLI Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # prepare
    p_prep = sub.add_parser("prepare", help="Prepare a transaction permit")
    p_prep.add_argument("--kind", choices=[KIND_PROMOTION, KIND_ROLLBACK, KIND_LEGACY_RECOVERY], default=KIND_PROMOTION)
    p_prep.add_argument("--target-repo", default="BenchBox-dev/BenchBox")
    p_prep.add_argument("--target-env", default="github-pages")
    p_prep.add_argument("--target-url", default="https://benchbox.dev")
    p_prep.add_argument("--develop-sha", default="0" * 40)
    p_prep.add_argument("--published-results-sha", default="0" * 40)
    p_prep.add_argument("--candidate-manifest-digest", default="0" * 64)
    p_prep.add_argument("--candidate-artifact-id", default=None)
    p_prep.add_argument("--candidate-archive-sha256", default="")
    p_prep.add_argument("--candidate-site-tree-sha256", default="")
    p_prep.add_argument("--candidate-parent-sha", default="")
    p_prep.add_argument("--candidate-parent-generation", default="")
    p_prep.add_argument("--restore-transaction-id", default=None)
    p_prep.add_argument("--failed-transaction-id", default=None)
    p_prep.add_argument("--barrier-evidence", default=None)
    p_prep.add_argument("--transaction-id", default=None)
    p_prep.add_argument("--workflow-path", default=".github/workflows/publication-transaction.yml")
    p_prep.add_argument("--workflow-sha", default=None)
    p_prep.add_argument("--writer-run-id", default=None)
    p_prep.add_argument("--ref", default=journal.DEFAULT_REF)
    p_prep.add_argument("--repo-path", default=".")
    p_prep.add_argument("--output-permit", default=None)
    p_prep.add_argument("--output-tx", default=None)
    p_prep.set_defaults(func=cmd_prepare)

    # authenticate-approval
    p_auth = sub.add_parser("authenticate-approval", help="Authenticate GitHub environment approval")
    p_auth.add_argument("--permit", required=True)
    p_auth.add_argument("--run-id", default=None)
    p_auth.add_argument("--run-attempt", type=int, default=None)
    p_auth.add_argument("--repo", default=None)
    p_auth.add_argument("--github-token", default=None)
    p_auth.add_argument("--simulated-approval", default=None)
    p_auth.add_argument("--output-approval", default=None)
    p_auth.set_defaults(func=cmd_authenticate_approval)

    # record-prepared
    p_rec_prep = sub.add_parser("record-prepared", help="Record prepared transaction in journal")
    p_rec_prep.add_argument("--permit", required=True)
    p_rec_prep.add_argument("--approval", required=True)
    p_rec_prep.add_argument("--tx", required=True)
    p_rec_prep.add_argument("--ref", default=journal.DEFAULT_REF)
    p_rec_prep.add_argument("--repo-path", default=".")
    p_rec_prep.add_argument("--output-tx", default=None)
    p_rec_prep.set_defaults(func=cmd_record_prepared)

    # start-write
    p_start = sub.add_parser("start-write", help="Record write-started in journal")
    p_start.add_argument("--transaction-id", required=True)
    p_start.add_argument("--ref", default=journal.DEFAULT_REF)
    p_start.add_argument("--repo-path", default=".")
    p_start.add_argument(
        "--pages-build-version",
        default=None,
        help="Wire pages_build_version sent to provider (defaults to intent_commit_oid)",
    )
    p_start.add_argument("--output-tx", default=None)
    p_start.set_defaults(func=cmd_start_write)

    # acknowledge-write
    p_ack = sub.add_parser("acknowledge-write", help="Record write-acknowledged in journal")
    p_ack.add_argument("--transaction-id", required=True)
    p_ack.add_argument("--provider-response", required=True)
    p_ack.add_argument("--ref", default=journal.DEFAULT_REF)
    p_ack.add_argument("--repo-path", default=".")
    p_ack.add_argument("--output-tx", default=None)
    p_ack.set_defaults(func=cmd_acknowledge_write)

    # record-verification
    p_ver = sub.add_parser("record-verification", help="Record externally-verified in journal")
    p_ver.add_argument("--transaction-id", required=True)
    p_ver.add_argument("--probe-report", required=True)
    p_ver.add_argument("--attestation", default=None)
    p_ver.add_argument("--challenge", default=None)
    p_ver.add_argument("--verifier-sha", default=None)
    p_ver.add_argument("--ref", default=journal.DEFAULT_REF)
    p_ver.add_argument("--repo-path", default=".")
    p_ver.add_argument("--output-tx", default=None)
    p_ver.set_defaults(func=cmd_record_verification)

    # finalize
    p_fin = sub.add_parser("finalize", help="Advance durable head in journal")
    p_fin.add_argument("--transaction-id", required=True)
    p_fin.add_argument("--ref", default=journal.DEFAULT_REF)
    p_fin.add_argument("--repo-path", default=".")
    p_fin.add_argument("--output-tx", default=None)
    p_fin.set_defaults(func=cmd_finalize)

    # record-failure
    p_fail = sub.add_parser("record-failure", help="Record failure in journal")
    p_fail.add_argument("--transaction-id", required=True)
    p_fail.add_argument("--code", required=True)
    p_fail.add_argument("--stage", required=True)
    p_fail.add_argument("--reason", required=True)
    p_fail.add_argument("--ref", default=journal.DEFAULT_REF)
    p_fail.add_argument("--repo-path", default=".")
    p_fail.add_argument("--output-tx", default=None)
    p_fail.set_defaults(func=cmd_record_failure)

    # watchdog-scan
    p_watch = sub.add_parser("watchdog-scan", help="Scan journal state without changing it")
    p_watch.add_argument("--repo-path", default=".")
    p_watch.add_argument("--ref", default=journal.DEFAULT_REF)
    p_watch.add_argument("--base-url", default="https://benchbox.dev")
    p_watch.add_argument("--barrier-evidence", default=None)
    p_watch.add_argument("--trigger-run-id", default=None)
    p_watch.add_argument("--output-json", default=None)
    p_watch.set_defaults(func=cmd_watchdog_scan)

    # resume an operator-reconciled rollback
    p_resume = sub.add_parser("resume", help="Create a permit for a prepared rollback")
    p_resume.add_argument("--transaction-id", required=True)
    p_resume.add_argument("--ref", default=journal.DEFAULT_REF)
    p_resume.add_argument("--repo-path", default=".")
    p_resume.add_argument("--output-permit", required=True)
    p_resume.add_argument("--output-tx", required=True)
    p_resume.set_defaults(func=cmd_resume)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
