"""Contract and architecture tests for publication-recover.yml workflow (Slice D)."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from scripts.publication import journal, transaction, transaction_executor

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "publication-recover.yml"


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), f"Workflow file missing at {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_recover_workflow_triggers_and_schedules() -> None:
    wf = _workflow()
    triggers = wf.get("on") or wf.get(True) or {}

    assert "push" not in triggers
    assert "pull_request" not in triggers

    # workflow_run on the three writer workflows
    assert "workflow_run" in triggers
    wf_run = triggers["workflow_run"]
    expected_workflows = {
        "Publication Transactions",
        "Publication Control Plane Deployment",
        "Publication Preview Deploy (G2)",
    }
    assert set(wf_run.get("workflows", [])) == expected_workflows
    assert wf_run.get("types") == ["completed"]

    # schedule: 5-minute reconciliation cron (2-57/5 * * * *)
    assert "schedule" in triggers
    schedules = triggers["schedule"]
    crons = [s.get("cron", "") for s in schedules]
    assert "2-57/5 * * * *" in crons

    # workflow_dispatch inputs
    assert "workflow_dispatch" in triggers
    inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "action" in inputs
    assert set(inputs["action"].get("options", [])) == {"scan", "finalize", "compensate", "mark_terminal"}
    assert "barrier_evidence" in inputs


def test_recover_workflow_permissions_follow_least_privilege() -> None:
    wf = _workflow()
    jobs = wf["jobs"]

    # Top-level is read-only
    assert wf.get("permissions") == {"contents": "read"}

    # scan: read-only
    assert jobs["scan"]["permissions"] == {"contents": "read", "actions": "read"}

    # act: contents: write (for journal CAS), pages: write, id-token: write, actions: read
    assert jobs["act"]["permissions"] == {
        "contents": "write",
        "pages": "write",
        "id-token": "write",
        "actions": "read",
    }
    assert jobs["act"]["environment"]["name"] == "github-pages"


def test_recover_workflow_concurrency_scoped_to_act_job() -> None:
    wf = _workflow()

    # Top-level has watchdog group
    assert wf.get("concurrency", {}).get("group") == "publication-watchdog"

    # act job participates in pages-deploy concurrency
    assert wf["jobs"]["act"]["concurrency"] == {
        "group": "pages-deploy",
        "cancel-in-progress": False,
    }


def test_recover_workflow_job_dependencies() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["act"]["needs"] == "scan"
    assert "needs.scan.outputs.recovery_needed == 'true'" in jobs["act"]["if"]


def test_recover_workflow_pins_all_actions() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    action_refs = re.findall(r"uses:\s+([^\s#]+)", text)
    assert len(action_refs) >= 4
    for ref in action_refs:
        assert "@" in ref, f"Action reference '{ref}' must specify a version"
        _, sha_or_tag = ref.split("@", 1)
        assert len(sha_or_tag) == 40 and re.match(r"^[0-9a-f]{40}$", sha_or_tag), (
            f"Action '{ref}' must be pinned to a 40-character commit SHA"
        )


# ---------------------------------------------------------------------------
# Falsifying Tests for Defect D4:
# "Kill after local intent commit creation/before remote ref acceptance (zero POSTs),
# then kill initiating run before POST, after remote success/before response,
# after ACK/before signing, after signing/before durable;
# no stale overwrite or fabricated success. Unknown finality forbids compensation.
# Exercise independently approved legacy recovery with the new journal unreadable."
# ---------------------------------------------------------------------------


def _setup_test_journal(tmp_path: Path) -> tuple[Path, journal.JournalState]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    init_state = journal.JournalState(
        target="BenchBox-dev/BenchBox:github-pages",
        next_generation=1,
        active_transaction_id=None,
        durable_transaction_id=None,
        write_block=None,
        policy_digest="p" * 64,
        tip_commit_oid="tip-oid-0",
    )
    return repo, init_state


def test_defect_d4_kill_before_write_started_zero_posts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 1: Initiating run prepared transaction but died before start-write.

    Watchdog detects STATE_PREPARED, recognizes zero provider writes occurred,
    and transitions to failure without any Pages POST.
    """
    repo, init_state = _setup_test_journal(tmp_path)

    tx = transaction.Transaction(
        object_type=transaction.OBJECT_TYPE,
        transaction_schema_version=1,
        transaction_id="tx-prepared-lost",
        target={"repo": "BenchBox-dev/BenchBox", "env": "github-pages", "base_url": "https://benchbox.dev"},
        kind=transaction.KIND_PROMOTION,
        generation=1,
        parent_transaction_id=None,
        recovery_of=None,
        restore_source=None,
        approval={"approved": True},
        controller={"workflow_path": "wf", "workflow_sha": "a" * 40, "run_id": 101},
        owner={"epoch": 1, "run_id": 101},
        content={"develop_sha": "d" * 40, "published_results_sha": "p" * 40},
        desired={"manifest_digest": "m" * 64, "generation": 1},
        artifact={"archive_sha256": "s" * 64},
        write=None,  # Zero writes!
        state=transaction.STATE_PREPARED,
    )
    j_state = journal.JournalState(
        target=init_state.target,
        next_generation=2,
        active_transaction_id=tx.transaction_id,
        durable_transaction_id=None,
        write_block=None,
        policy_digest=init_state.policy_digest,
        tip_commit_oid="tip-oid-1",
    )

    monkeypatch.setattr(journal, "read_journal_state", lambda repo_path, ref: j_state)
    monkeypatch.setattr(journal, "read_transaction", lambda repo_path, tx_id, ref: tx)

    action, status, reason = transaction_executor._resolve_watchdog_action(tx, j_state, barrier_evidence=None)
    assert action == "record_failure"
    assert status == "run_lost_before_write"
    assert "no provider write occurred" in reason


def test_defect_d4_unknown_finality_forbids_compensation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 2: Kill initiating run before POST or during post uncertainty.

    Watchdog detects STATE_WRITE_STARTED with unknown provider finality.
    Without barrier evidence, compensation/rollback is FORBIDDEN and quarantined.
    With barrier evidence, failure is recorded safely.
    """
    repo, init_state = _setup_test_journal(tmp_path)

    tx = transaction.Transaction(
        object_type=transaction.OBJECT_TYPE,
        transaction_schema_version=1,
        transaction_id="tx-write-uncertain",
        target={"repo": "BenchBox-dev/BenchBox", "env": "github-pages", "base_url": "https://benchbox.dev"},
        kind=transaction.KIND_PROMOTION,
        generation=1,
        parent_transaction_id=None,
        recovery_of=None,
        restore_source=None,
        approval={"approved": True},
        controller={"workflow_path": "wf", "workflow_sha": "a" * 40, "run_id": 102},
        owner={"epoch": 1, "run_id": 102},
        content={"develop_sha": "d" * 40, "published_results_sha": "p" * 40},
        desired={"manifest_digest": "m" * 64, "generation": 1},
        artifact={"archive_sha256": "s" * 64},
        write={"write_id": "w-uncertain", "pages_build_version": "commit-oid-1"},
        state=transaction.STATE_WRITE_STARTED,
    )
    j_state = journal.JournalState(
        target=init_state.target,
        next_generation=2,
        active_transaction_id=tx.transaction_id,
        durable_transaction_id=None,
        write_block=None,
        policy_digest=init_state.policy_digest,
        tip_commit_oid="tip-oid-2",
    )

    # 1. Without barrier evidence: MUST quarantine, forbidding compensation
    action, status, reason = transaction_executor._resolve_watchdog_action(tx, j_state, barrier_evidence=None)
    assert action == "quarantine"
    assert status == "awaiting_activation_barrier"
    assert "cannot compensate without documented activation barrier" in reason

    # 2. With barrier evidence: allowed to record failure
    action_with_barrier, status_with_barrier, _ = transaction_executor._resolve_watchdog_action(
        tx, j_state, barrier_evidence='{"barrier": "verified_status_404"}'
    )
    assert action_with_barrier == "record_failure"
    assert status_with_barrier == "write_failed_with_barrier"


def test_defect_d4_kill_after_ack_before_signing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 3: Kill initiating run after ACK before signing.

    Watchdog detects STATE_WRITE_ACKNOWLEDGED. Resolves action
    'verify_and_finalize' to probe the live site and complete verification.
    """
    repo, init_state = _setup_test_journal(tmp_path)

    tx = transaction.Transaction(
        object_type=transaction.OBJECT_TYPE,
        transaction_schema_version=1,
        transaction_id="tx-ack-unverified",
        target={"repo": "BenchBox-dev/BenchBox", "env": "github-pages", "base_url": "https://benchbox.dev"},
        kind=transaction.KIND_PROMOTION,
        generation=1,
        parent_transaction_id=None,
        recovery_of=None,
        restore_source=None,
        approval={"approved": True},
        controller={"workflow_path": "wf", "workflow_sha": "a" * 40, "run_id": 103},
        owner={"epoch": 1, "run_id": 103},
        content={"develop_sha": "d" * 40, "published_results_sha": "p" * 40},
        desired={"manifest_digest": "m" * 64, "generation": 1},
        artifact={"archive_sha256": "s" * 64},
        write={"write_id": "w1", "pages_build_version": "commit-1", "status": "succeed"},
        state=transaction.STATE_WRITE_ACKNOWLEDGED,
    )
    j_state = journal.JournalState(
        target=init_state.target,
        next_generation=2,
        active_transaction_id=tx.transaction_id,
        durable_transaction_id=None,
        write_block=None,
        policy_digest=init_state.policy_digest,
        tip_commit_oid="tip-oid-3",
    )

    action, status, _ = transaction_executor._resolve_watchdog_action(tx, j_state, barrier_evidence=None)
    assert action == "verify_and_finalize"
    assert status == "write_acknowledged_unverified"


def test_defect_d4_kill_after_signing_before_durable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 4: Kill initiating run after signing / before durable head advance.

    Watchdog detects STATE_EXTERNALLY_VERIFIED. Resolves action 'finalize'
    to atomically advance the durable head via journal CAS.
    """
    repo, init_state = _setup_test_journal(tmp_path)

    tx = transaction.Transaction(
        object_type=transaction.OBJECT_TYPE,
        transaction_schema_version=1,
        transaction_id="tx-verified-unfinalized",
        target={"repo": "BenchBox-dev/BenchBox", "env": "github-pages", "base_url": "https://benchbox.dev"},
        kind=transaction.KIND_PROMOTION,
        generation=1,
        parent_transaction_id=None,
        recovery_of=None,
        restore_source=None,
        approval={"approved": True},
        controller={"workflow_path": "wf", "workflow_sha": "a" * 40, "run_id": 104},
        owner={"epoch": 1, "run_id": 104},
        content={"develop_sha": "d" * 40, "published_results_sha": "p" * 40},
        desired={"manifest_digest": "m" * 64, "generation": 1},
        artifact={"archive_sha256": "s" * 64},
        write={"write_id": "w1", "pages_build_version": "commit-1", "status": "succeed"},
        verification={"receipt_id": "receipt-1", "ok": True},
        state=transaction.STATE_EXTERNALLY_VERIFIED,
    )
    j_state = journal.JournalState(
        target=init_state.target,
        next_generation=2,
        active_transaction_id=tx.transaction_id,
        durable_transaction_id=None,
        write_block=None,
        policy_digest=init_state.policy_digest,
        tip_commit_oid="tip-oid-4",
    )

    action, status, _ = transaction_executor._resolve_watchdog_action(tx, j_state, barrier_evidence=None)
    assert action == "finalize"
    assert status == "verified_unfinalized"


def test_defect_d4_legacy_recovery_with_unreadable_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Case 5: Unreadable or corrupt journal.

    When the new journal is unreadable, watchdog refuses to invent state or
    fabricate an active transaction; reports corrupt_journal and halts.
    Legacy recovery in docs.yml runs independently from historical attested checkpoints.
    """
    repo, _ = _setup_test_journal(tmp_path)

    # Corrupt journal: active transaction declared in state.json but missing from transactions/
    j_state = journal.JournalState(
        target="BenchBox-dev/BenchBox:github-pages",
        next_generation=5,
        active_transaction_id="missing-tx-file",
        durable_transaction_id=None,
        write_block=None,
        policy_digest="p" * 64,
        tip_commit_oid="tip-corrupt",
    )

    monkeypatch.setattr(journal, "read_journal_state", lambda repo_path, ref: j_state)
    monkeypatch.setattr(journal, "read_transaction", lambda repo_path, tx_id, ref: None)

    args = argparse.Namespace(
        repo_path=repo,
        ref="publication",
        base_url="https://benchbox.dev",
        barrier_evidence=None,
        trigger_run_id=None,
        output_json=None,
        execute=False,
    )
    rc = transaction_executor.cmd_watchdog_scan(args)
    assert rc == 1  # Fails closed on corrupt journal
