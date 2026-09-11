"""Unit and contract tests for the publication transaction executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from scripts.publication import journal, transaction
from scripts.publication.transaction import (
    KIND_PROMOTION,
    KIND_ROLLBACK,
    STATE_DURABLE,
    STATE_EXTERNALLY_VERIFIED,
    STATE_PREPARED,
    STATE_RECOVERY_REQUIRED,
    STATE_ROLLBACK_DURABLE,
    STATE_ROLLBACK_VERIFIED,
    STATE_ROLLBACK_WRITE_STARTED,
    STATE_WRITE_ACKNOWLEDGED,
    STATE_WRITE_STARTED,
    Transaction,
    TransactionError,
    canonical_json,
)
from scripts.publication.transaction_executor import (
    authenticate_approval_record,
    cmd_acknowledge_write,
    cmd_authenticate_approval,
    cmd_finalize,
    cmd_prepare,
    cmd_reconcile,
    cmd_record_failure,
    cmd_record_prepared,
    cmd_record_verification,
    cmd_resume,
    cmd_start_write,
    fetch_pages_deployment_status,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def test_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a Git repository with remote and publication branch for journal CAS testing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@benchbox.dev"], cwd=repo, check=True)

    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)

    subprocess.run(["git", "branch", "publication"], cwd=repo, check=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main", "publication"], cwd=repo, check=True, capture_output=True)

    # Initialize genesis journal state
    target = {
        "repository": "BenchBox-dev/BenchBox",
        "environment": "github-pages",
        "url": "https://benchbox.dev",
    }
    genesis_tx, _ = transaction.prepare_promotion(
        target=target,
        generation=1,
        parent_transaction_id=None,
        approval={"permit_sha256": "genesis", "approver": "maintainer"},
        controller={"workflow_path": "release.yml", "workflow_sha": "0" * 40},
        owner={"run_id": "1", "epoch": "0"},
        content={"manifest_digest": "g" * 64},
        artifact={"artifact_id": 1, "archive_sha256": "g_art" * 16},
        transaction_id="genesis-tx-0001",
    )
    attestation = {"observation_digest": "genesis-observation"}
    durable_genesis = Transaction(**{**genesis_tx.to_dict(), "state": STATE_DURABLE, "attestation": attestation})
    monkeypatch.setattr(transaction, "validate_live_receipt", lambda current, payload: attestation)
    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    journal.init_genesis_journal(
        repo_path=repo,
        target=target,
        genesis_transaction=durable_genesis,
        base_commit_oid=base_oid,
        ref="publication",
    )
    return repo


def test_prepare_promotion_generates_canonical_permit(test_repo: Path, tmp_path: Path) -> None:
    output_permit = tmp_path / "permit.json"
    output_tx = tmp_path / "tx.json"

    args = argparse.Namespace(
        kind=KIND_PROMOTION,
        target_repo="BenchBox-dev/BenchBox",
        target_env="github-pages",
        target_url="https://benchbox.dev",
        develop_sha="1" * 40,
        published_results_sha="2" * 40,
        candidate_manifest_digest="a" * 64,
        candidate_artifact_id="12345",
        candidate_archive_sha256="b" * 64,
        restore_transaction_id=None,
        failed_transaction_id=None,
        barrier_evidence=None,
        transaction_id="test-tx-001",
        workflow_path=".github/workflows/publication-transaction.yml",
        workflow_sha="3" * 40,
        writer_run_id="999",
        ref="publication",
        repo_path=str(test_repo),
        output_permit=str(output_permit),
        output_tx=str(output_tx),
    )

    rc = cmd_prepare(args)
    assert rc == 0
    assert output_permit.is_file()
    assert output_tx.is_file()

    permit = json.loads(output_permit.read_text(encoding="utf-8"))
    assert permit["transaction_id"] == "test-tx-001"
    assert permit["generation"] == 2
    assert permit["parent_transaction_id"] == "genesis-tx-0001"
    assert permit["kind"] == KIND_PROMOTION

    tx = json.loads(output_tx.read_text(encoding="utf-8"))
    assert tx["state"] == STATE_PREPARED


def test_prepare_rejects_candidate_parent_that_moved(test_repo: Path, tmp_path: Path) -> None:
    args = argparse.Namespace(
        kind=KIND_PROMOTION,
        target_repo="BenchBox-dev/BenchBox",
        target_env="github-pages",
        target_url="https://benchbox.dev",
        develop_sha="1" * 40,
        published_results_sha="2" * 40,
        candidate_manifest_digest="a" * 64,
        candidate_artifact_id="12345",
        candidate_archive_sha256="b" * 64,
        candidate_site_tree_sha256="c" * 64,
        candidate_parent_sha="d" * 40,
        candidate_parent_generation="1",
        restore_transaction_id=None,
        failed_transaction_id=None,
        barrier_evidence=None,
        transaction_id="test-tx-stale-parent",
        workflow_path=".github/workflows/publication-transaction.yml",
        workflow_sha="3" * 40,
        writer_run_id="999",
        ref="publication",
        repo_path=str(test_repo),
        output_permit=str(tmp_path / "permit.json"),
        output_tx=str(tmp_path / "tx.json"),
    )

    with pytest.raises(TransactionError, match="current durable publication head"):
        cmd_prepare(args)


def test_resume_only_reissues_permit_for_active_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = {
        "repository": "BenchBox-dev/BenchBox",
        "environment": "github-pages",
        "url": "https://benchbox.dev",
    }
    tx = Transaction(
        transaction_id="rollback-resume-1",
        target=target,
        kind=KIND_ROLLBACK,
        generation=3,
        parent_transaction_id="durable-1",
        recovery_of="failed-1",
        restore_source={"parent_transaction_id": "durable-1"},
        approval={},
        controller={"workflow_sha": "a" * 40},
        owner={"run_id": "watchdog-1", "epoch": "3"},
        content={"manifest_digest": "m" * 64},
        desired={"digest": "d" * 64},
        artifact={"artifact_id": 123, "archive_sha256": "s" * 64},
        state=STATE_ROLLBACK_WRITE_STARTED,
    )
    state = journal.JournalState(
        target=target,
        next_generation=4,
        active_transaction_id=tx.transaction_id,
        durable_transaction_id="durable-1",
        write_block=None,
        policy_digest="p" * 64,
        tip_commit_oid="tip-1",
    )
    monkeypatch.setattr(journal, "read_journal_state", lambda *args, **kwargs: state)
    monkeypatch.setattr(journal, "read_transaction", lambda *args, **kwargs: tx)

    permit_path = tmp_path / "permit.json"
    tx_path = tmp_path / "tx.json"
    rc = cmd_resume(
        argparse.Namespace(
            transaction_id=tx.transaction_id,
            ref="publication",
            repo_path=str(tmp_path),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )

    assert rc == 0
    permit = json.loads(permit_path.read_text(encoding="utf-8"))
    assert permit["transaction_id"] == tx.transaction_id
    assert permit["kind"] == KIND_ROLLBACK
    assert permit["restore_transaction_id"] == "durable-1"
    assert permit["artifact_id"] == 123
    assert permit["artifact_archive_sha256"] == "s" * 64
    assert "permit_sha256" not in permit
    assert json.loads(tx_path.read_text(encoding="utf-8"))["state"] == STATE_ROLLBACK_WRITE_STARTED


def test_authenticate_approval_enforces_run_attempt_and_environment(tmp_path: Path) -> None:
    permit = {"transaction_id": "tx-1", "generation": 2, "target": {"url": "https://benchbox.dev"}}
    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()

    valid_simulated = {
        "state": "approved",
        "environment": {"name": "github-pages"},
        "comment": f"publication-approval:{permit_digest}",
        "user": {"id": 42, "login": "maintainer"},
    }

    # 1. Valid approval succeeds
    record = authenticate_approval_record(
        permit=permit,
        run_id="100",
        run_attempt=1,
        repo="BenchBox-dev/BenchBox",
        simulated_approval=valid_simulated,
    )
    assert record["authenticated"] is True
    assert record["approver_login"] == "maintainer"
    assert record["permit_sha256"] == permit_digest

    # 2. Defect D5 / Section 5: Run attempt > 1 must fail
    with pytest.raises(TransactionError, match="attempt 2 > 1 is forbidden"):
        authenticate_approval_record(
            permit=permit,
            run_id="100",
            run_attempt=2,
            repo="BenchBox-dev/BenchBox",
            simulated_approval=valid_simulated,
        )

    # 3. Comments are audit data, not a second authentication channel.
    no_comment = {key: value for key, value in valid_simulated.items() if key != "comment"}
    assert (
        authenticate_approval_record(
            permit=permit,
            run_id="100",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            simulated_approval=no_comment,
        )["authenticated"]
        is True
    )

    # 4. Wrong environment must fail
    bad_env_simulated = {**valid_simulated, "environment": {"name": "staging"}}
    with pytest.raises(TransactionError, match="Approval authentication failed"):
        authenticate_approval_record(
            permit=permit,
            run_id="100",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            simulated_approval=bad_env_simulated,
        )


def test_full_promotion_lifecycle_and_cas(test_repo: Path, tmp_path: Path) -> None:
    permit_path = tmp_path / "permit.json"
    tx_path = tmp_path / "tx.json"
    approval_path = tmp_path / "approval.json"
    provider_resp_path = tmp_path / "provider.json"
    probe_report_path = tmp_path / "probe.json"

    # Step 1: Prepare
    cmd_prepare(
        argparse.Namespace(
            kind=KIND_PROMOTION,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="1" * 40,
            published_results_sha="2" * 40,
            candidate_manifest_digest="a" * 64,
            candidate_artifact_id="12345",
            candidate_archive_sha256="b" * 64,
            restore_transaction_id=None,
            failed_transaction_id=None,
            barrier_evidence=None,
            transaction_id="tx-lifecycle-1",
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="3" * 40,
            writer_run_id="101",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )

    permit = json.loads(permit_path.read_text(encoding="utf-8"))
    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()

    # Step 2: Authenticate approval
    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id="101",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / "sim.json",
                    {
                        "state": "approved",
                        "environment": {"name": "github-pages"},
                        "comment": f"publication-approval:{permit_digest}",
                        "user": {"id": 1, "login": "joe"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )

    # Step 3: Record prepared
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    tx = journal.read_transaction(test_repo, "tx-lifecycle-1", ref="publication")
    assert tx.state == STATE_PREPARED

    # Step 4: Start write
    cmd_start_write(
        argparse.Namespace(
            transaction_id="tx-lifecycle-1",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    tx = journal.read_transaction(test_repo, "tx-lifecycle-1", ref="publication")
    assert tx.state == STATE_WRITE_STARTED
    assert tx.write and tx.write.get("pages_build_version")

    # Step 5: Acknowledge write
    _write_temp_json(
        provider_resp_path,
        {
            "id": "pages-dep-100",
            "status_url": "https://api.github.com/pages/status/100",
            "status": "SUCCESS",
            "page_url": "https://benchbox.dev",
        },
    )
    cmd_acknowledge_write(
        argparse.Namespace(
            transaction_id="tx-lifecycle-1",
            provider_response=str(provider_resp_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    tx = journal.read_transaction(test_repo, "tx-lifecycle-1", ref="publication")
    assert tx.state == STATE_WRITE_ACKNOWLEDGED

    # Step 6: Record verification
    _write_temp_json(
        probe_report_path,
        {
            "success": True,
            "routes": [{"url": "/", "status": 200, "ok": True}],
        },
    )
    cmd_record_verification(
        argparse.Namespace(
            transaction_id="tx-lifecycle-1",
            probe_report=str(probe_report_path),
            attestation=None,
            challenge="challenge-123",
            verifier_sha="v" * 40,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    tx = journal.read_transaction(test_repo, "tx-lifecycle-1", ref="publication")
    assert tx.state == STATE_EXTERNALLY_VERIFIED

    # Step 7: Finalize
    cmd_finalize(
        argparse.Namespace(
            transaction_id="tx-lifecycle-1",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    tx = journal.read_transaction(test_repo, "tx-lifecycle-1", ref="publication")
    assert tx.state == STATE_DURABLE

    state = journal.read_journal_state(test_repo, ref="publication")
    assert state.durable_transaction_id == "tx-lifecycle-1"
    assert state.active_transaction_id is None
    assert state.next_generation == 3


def test_defect_d1_and_d2_falsifying_contracts(test_repo: Path, tmp_path: Path) -> None:
    """Falsifying tests for D1 (one builder, restored desired/receipt link, reject old desired JSON)

    and D2 (unique write correlation, replay rejection).
    """
    permit_path = tmp_path / "p.json"
    tx_path = tmp_path / "t.json"
    approval_path = tmp_path / "a.json"
    provider_resp_path = tmp_path / "prov.json"
    probe_report_path = tmp_path / "probe.json"

    # Step 1: Promote A (generation 2)
    _execute_simple_promotion(test_repo, tmp_path, tx_id="tx-A", gen=2, candidate_digest="1" * 64)
    state = journal.read_journal_state(test_repo, ref="publication")
    assert state.durable_transaction_id == "tx-A"

    # Step 2: Attempt B (generation 3) -> fails at verification
    cmd_prepare(
        argparse.Namespace(
            kind=KIND_PROMOTION,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="b" * 40,
            published_results_sha="b" * 40,
            candidate_manifest_digest="2" * 64,
            candidate_artifact_id="222",
            candidate_archive_sha256="2" * 64,
            restore_transaction_id=None,
            failed_transaction_id=None,
            barrier_evidence=None,
            transaction_id="tx-B",
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="b" * 40,
            writer_run_id="202",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )
    permit_b = json.loads(permit_path.read_text(encoding="utf-8"))
    permit_b_digest = hashlib.sha256(canonical_json(permit_b).encode("utf-8")).hexdigest()

    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id="202",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / "sim_b.json",
                    {
                        "state": "approved",
                        "environment": {"name": "github-pages"},
                        "comment": f"publication-approval:{permit_b_digest}",
                        "user": {"id": 1, "login": "joe"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_start_write(
        argparse.Namespace(
            transaction_id="tx-B",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    _write_temp_json(
        provider_resp_path,
        {"id": "dep-B", "status_url": "https://api.github.com/pages/status/B", "status": "SUCCESS"},
    )
    cmd_acknowledge_write(
        argparse.Namespace(
            transaction_id="tx-B",
            provider_response=str(provider_resp_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )

    # Verification fails on B -> record-failure escalates to RECOVERY_REQUIRED
    cmd_record_failure(
        argparse.Namespace(
            transaction_id="tx-B",
            code="PROBE_TIMEOUT",
            stage="verification",
            reason="Endpoint returned 503",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    tx_b = journal.read_transaction(test_repo, "tx-B", ref="publication")
    assert tx_b.state == STATE_RECOVERY_REQUIRED

    # D2 test: Same workflow commit writes different artifact; replaying first ACK on second must reject
    with pytest.raises(TransactionError):
        transaction.transition(tx_b, transaction.EVENT_START_WRITE, payload={})

    # Step 3: Restore A via rollback (generation 4)
    barrier_evidence_path = tmp_path / "barrier.json"
    _write_temp_json(
        barrier_evidence_path,
        {
            "deployment_id": "dep-B",
            "provider_status": "CANCELED",
            "quiescence_observed": True,
        },
    )
    cmd_prepare(
        argparse.Namespace(
            kind=KIND_ROLLBACK,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="b" * 40,
            published_results_sha="b" * 40,
            candidate_manifest_digest="",
            candidate_artifact_id=None,
            candidate_archive_sha256="",
            restore_transaction_id="tx-A",
            failed_transaction_id="tx-B",
            barrier_evidence=str(barrier_evidence_path),
            transaction_id="tx-rollback-A",
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="b" * 40,
            writer_run_id="203",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )
    permit_rb = json.loads(permit_path.read_text(encoding="utf-8"))
    assert permit_rb["generation"] == 4
    assert permit_rb["parent_transaction_id"] == "tx-A"
    assert permit_rb["content_digest"] == "1" * 64

    # Execute rollback steps
    permit_rb_digest = hashlib.sha256(canonical_json(permit_rb).encode("utf-8")).hexdigest()
    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id="203",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / "sim_rb.json",
                    {
                        "state": "approved",
                        "environment": {"name": "github-pages"},
                        "comment": f"publication-approval:{permit_rb_digest}",
                        "user": {"id": 1, "login": "joe"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    _write_temp_json(
        provider_resp_path,
        {"id": "dep-RB-A", "status_url": "https://api.github.com/pages/status/RBA", "status": "SUCCESS"},
    )
    cmd_acknowledge_write(
        argparse.Namespace(
            transaction_id="tx-rollback-A",
            provider_response=str(provider_resp_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    _write_temp_json(probe_report_path, {"success": True, "routes": [{"url": "/", "ok": True}]})
    cmd_record_verification(
        argparse.Namespace(
            transaction_id="tx-rollback-A",
            probe_report=str(probe_report_path),
            attestation=None,
            challenge="challenge-rb",
            verifier_sha="v" * 40,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_finalize(
        argparse.Namespace(
            transaction_id="tx-rollback-A",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )

    state = journal.read_journal_state(test_repo, ref="publication")
    assert state.durable_transaction_id == "tx-rollback-A"
    assert state.next_generation == 5

    # Step 4: Promote C (generation 5, parent=rollback-A)
    _execute_simple_promotion(test_repo, tmp_path, tx_id="tx-C", gen=5, candidate_digest="3" * 64)
    state = journal.read_journal_state(test_repo, ref="publication")
    assert state.durable_transaction_id == "tx-C"
    tx_c = journal.read_transaction(test_repo, "tx-C", ref="publication")
    assert tx_c.parent_transaction_id == "tx-rollback-A"


def _write_temp_json(path: Path, data: dict[str, Any]) -> Path:
    path.write_text(canonical_json(data) + "\n", encoding="utf-8")
    return path


def _execute_simple_promotion(test_repo: Path, tmp_path: Path, tx_id: str, gen: int, candidate_digest: str) -> None:
    permit_path = tmp_path / f"p_{tx_id}.json"
    tx_path = tmp_path / f"t_{tx_id}.json"
    approval_path = tmp_path / f"a_{tx_id}.json"
    prov_path = tmp_path / f"prov_{tx_id}.json"
    probe_path = tmp_path / f"probe_{tx_id}.json"

    cmd_prepare(
        argparse.Namespace(
            kind=KIND_PROMOTION,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="c" * 40,
            published_results_sha="c" * 40,
            candidate_manifest_digest=candidate_digest,
            candidate_artifact_id="111",
            candidate_archive_sha256=candidate_digest,
            restore_transaction_id=None,
            failed_transaction_id=None,
            barrier_evidence=None,
            transaction_id=tx_id,
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="c" * 40,
            writer_run_id=f"run-{tx_id}",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )
    permit = json.loads(permit_path.read_text(encoding="utf-8"))
    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()

    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id=f"run-{tx_id}",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / f"sim_{tx_id}.json",
                    {
                        "state": "approved",
                        "environment": {"name": "github-pages"},
                        "comment": f"publication-approval:{permit_digest}",
                        "user": {"id": 1, "login": "joe"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_start_write(
        argparse.Namespace(
            transaction_id=tx_id,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    _write_temp_json(prov_path, {"id": f"dep-{tx_id}", "status": "SUCCESS"})
    cmd_acknowledge_write(
        argparse.Namespace(
            transaction_id=tx_id,
            provider_response=str(prov_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    _write_temp_json(probe_path, {"success": True, "routes": [{"url": "/", "ok": True}]})
    cmd_record_verification(
        argparse.Namespace(
            transaction_id=tx_id,
            probe_report=str(probe_path),
            attestation=None,
            challenge="challenge",
            verifier_sha="v" * 40,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_finalize(
        argparse.Namespace(
            transaction_id=tx_id,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )


def test_cmd_start_write_with_explicit_pages_build_version(
    test_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """start-write CLI command records explicit pages_build_version and preserves intent OID."""
    tx_id = "tx-explicit-version"
    permit_path = tmp_path / f"p_{tx_id}.json"
    tx_path = tmp_path / f"t_{tx_id}.json"
    approval_path = tmp_path / f"a_{tx_id}.json"
    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))

    candidate_digest = "c" * 64
    cmd_prepare(
        argparse.Namespace(
            kind=KIND_PROMOTION,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="c" * 40,
            published_results_sha="c" * 40,
            candidate_manifest_digest=candidate_digest,
            candidate_artifact_id="111",
            candidate_archive_sha256=candidate_digest,
            candidate_site_tree_sha256="s" * 64,
            candidate_parent_sha="",
            candidate_parent_generation="",
            restore_transaction_id=None,
            failed_transaction_id=None,
            barrier_evidence=None,
            transaction_id=tx_id,
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="c" * 40,
            writer_run_id=f"run-{tx_id}",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )
    permit = json.loads(permit_path.read_text(encoding="utf-8"))
    permit_digest = hashlib.sha256(canonical_json(permit).encode("utf-8")).hexdigest()

    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id=f"run-{tx_id}",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / f"sim_{tx_id}.json",
                    {
                        "state": "approved",
                        "environment": {"name": "github-pages"},
                        "comment": f"publication-approval:{permit_digest}",
                        "user": {"id": 1, "login": "joe"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )

    wire_sha = "w" * 40
    cmd_start_write(
        argparse.Namespace(
            transaction_id=tx_id,
            ref="publication",
            repo_path=str(test_repo),
            pages_build_version=wire_sha,
            output_tx=str(tx_path),
        )
    )
    tx = journal.read_transaction(test_repo, tx_id, ref="publication")
    assert tx.state == STATE_WRITE_STARTED
    assert tx.write["pages_build_version"] == wire_sha
    assert tx.write["intent_commit_oid"] != wire_sha
    assert len(tx.write["intent_commit_oid"]) == 40

    # Verify GITHUB_OUTPUT contents
    output_text = github_output.read_text(encoding="utf-8")
    assert f"pages_build_version={wire_sha}" in output_text
    assert f"intent_commit_oid={tx.write['intent_commit_oid']}" in output_text


def test_fetch_pages_deployment_status_live(monkeypatch: pytest.MonkeyPatch) -> None:
    class MockResponse:
        def __init__(self, data: dict[str, Any]) -> None:
            self._raw = json.dumps(data).encode("utf-8")

        def read(self) -> bytes:
            return self._raw

        def __enter__(self) -> MockResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    recorded_requests: list[urllib.request.Request] = []

    def mock_urlopen(req: urllib.request.Request) -> MockResponse:
        recorded_requests.append(req)
        return MockResponse({"status": "succeed"})

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    status = fetch_pages_deployment_status(
        repo="BenchBox-dev/BenchBox",
        deployment_id="sha-1234",
        token="ghp_secret",
    )
    assert status == "succeed"
    assert len(recorded_requests) == 1
    req = recorded_requests[0]
    assert req.full_url == "https://api.github.com/repos/BenchBox-dev/BenchBox/pages/deployments/sha-1234"
    assert req.headers["Authorization"] == "Bearer ghp_secret"
    assert req.headers["Accept"] == "application/vnd.github+json"
    assert req.headers["User-agent"] == "benchbox-publication-transaction"


def test_fetch_pages_deployment_status_missing_token() -> None:
    with pytest.raises(TransactionError, match="GitHub token is required"):
        fetch_pages_deployment_status(
            repo="BenchBox-dev/BenchBox",
            deployment_id="sha-1234",
            token=None,
        )


def test_fetch_pages_deployment_status_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def mock_urlopen_err(req: urllib.request.Request) -> Any:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_err)
    with pytest.raises(TransactionError, match="Failed to fetch Pages deployment status"):
        fetch_pages_deployment_status(
            repo="BenchBox-dev/BenchBox",
            deployment_id="sha-1234",
            token="ghp_secret",
        )


def test_cmd_reconcile_happy_path(test_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    permit_path = tmp_path / "permit.json"
    tx_path = tmp_path / "tx.json"
    approval_path = tmp_path / "approval.json"
    tx_id = "tx-rec-1"

    cmd_prepare(
        argparse.Namespace(
            kind=KIND_PROMOTION,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="d" * 40,
            published_results_sha="p" * 40,
            candidate_manifest_digest="m" * 64,
            candidate_artifact_id="101",
            candidate_archive_sha256="a" * 64,
            candidate_site_tree_sha256="s" * 64,
            candidate_parent_sha="",
            candidate_parent_generation="",
            restore_transaction_id=None,
            failed_transaction_id=None,
            barrier_evidence=None,
            transaction_id=tx_id,
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="w" * 40,
            writer_run_id="501",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )
    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id="501",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / "sim.json",
                    {
                        "environments": [{"name": "github-pages"}],
                        "state": "approved",
                        "user": {"id": 1, "login": "test"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_start_write(
        argparse.Namespace(
            transaction_id=tx_id,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_record_failure(
        argparse.Namespace(
            transaction_id=tx_id,
            code="POST_SEND_FAILURE",
            stage="post_send",
            reason="Poll timeout",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )

    github_output = tmp_path / "github_output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_output))
    rec_tx_path = tmp_path / "rec_tx.json"

    rc = cmd_reconcile(
        argparse.Namespace(
            transaction_id=tx_id,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(rec_tx_path),
        )
    )
    assert rc == 0
    assert rec_tx_path.is_file()
    out_tx = json.loads(rec_tx_path.read_text(encoding="utf-8"))
    assert out_tx["state"] == STATE_RECOVERY_REQUIRED
    assert out_tx["failure"]["stage"] == "post_send"

    lines = github_output.read_text(encoding="utf-8").strip().splitlines()
    assert f"transaction_id={tx_id}" in lines
    assert "kind=promotion" in lines
    assert "candidate_artifact_id=101" in lines
    assert f"controller_sha={'w' * 40}" in lines


def test_cmd_reconcile_rejects_invalid(test_repo: Path) -> None:
    with pytest.raises(TransactionError, match="Only a promotion transaction in recovery-required"):
        cmd_reconcile(
            argparse.Namespace(
                transaction_id="genesis-tx-0001",
                ref="publication",
                repo_path=str(test_repo),
                output_tx=None,
            )
        )


def test_cmd_record_verification_live_fetch(test_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    permit_path = tmp_path / "permit.json"
    tx_path = tmp_path / "tx.json"
    approval_path = tmp_path / "approval.json"
    tx_id = "tx-verif-live"

    cmd_prepare(
        argparse.Namespace(
            kind=KIND_PROMOTION,
            target_repo="BenchBox-dev/BenchBox",
            target_env="github-pages",
            target_url="https://benchbox.dev",
            develop_sha="d" * 40,
            published_results_sha="p" * 40,
            candidate_manifest_digest="m" * 64,
            candidate_artifact_id="102",
            candidate_archive_sha256="a" * 64,
            candidate_site_tree_sha256="s" * 64,
            candidate_parent_sha="",
            candidate_parent_generation="",
            restore_transaction_id=None,
            failed_transaction_id=None,
            barrier_evidence=None,
            transaction_id=tx_id,
            workflow_path=".github/workflows/publication-transaction.yml",
            workflow_sha="c" * 40,
            writer_run_id="502",
            ref="publication",
            repo_path=str(test_repo),
            output_permit=str(permit_path),
            output_tx=str(tx_path),
        )
    )
    cmd_authenticate_approval(
        argparse.Namespace(
            permit=str(permit_path),
            run_id="502",
            run_attempt=1,
            repo="BenchBox-dev/BenchBox",
            github_token=None,
            simulated_approval=str(
                _write_temp_json(
                    tmp_path / "sim.json",
                    {
                        "environments": [{"name": "github-pages"}],
                        "state": "approved",
                        "user": {"id": 1, "login": "test"},
                    },
                )
            ),
            output_approval=str(approval_path),
        )
    )
    cmd_record_prepared(
        argparse.Namespace(
            permit=str(permit_path),
            approval=str(approval_path),
            tx=str(tx_path),
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_start_write(
        argparse.Namespace(
            transaction_id=tx_id,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    cmd_record_failure(
        argparse.Namespace(
            transaction_id=tx_id,
            code="POST_SEND_FAILURE",
            stage="post_send",
            reason="Poll timeout",
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )

    probe_path = tmp_path / "probe.json"
    _write_temp_json(probe_path, {"ok": True, "probes": [{"path": "/", "ok": True}]})

    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(TransactionError, match="GitHub token is required"):
        cmd_record_verification(
            argparse.Namespace(
                transaction_id=tx_id,
                probe_report=str(probe_path),
                attestation=None,
                challenge="challenge",
                verifier_sha="v" * 40,
                repo=None,
                github_token=None,
                pages_deployment_id=None,
                pages_deployment_status=None,
                simulated_pages_deployment_status=None,
                ref="publication",
                repo_path=str(test_repo),
                output_tx=str(tx_path),
            )
        )

    class MockResponse:
        def __init__(self, data: dict[str, Any]) -> None:
            self._raw = json.dumps(data).encode("utf-8")

        def read(self) -> bytes:
            return self._raw

        def __enter__(self) -> MockResponse:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr(urllib.request, "urlopen", lambda req: MockResponse({"status": "failed"}))
    with pytest.raises(TransactionError, match="Pages deployment status of 'succeed'"):
        cmd_record_verification(
            argparse.Namespace(
                transaction_id=tx_id,
                probe_report=str(probe_path),
                attestation=None,
                challenge="challenge",
                verifier_sha="v" * 40,
                repo=None,
                github_token="fake-token",
                pages_deployment_id=None,
                pages_deployment_status=None,
                simulated_pages_deployment_status=None,
                ref="publication",
                repo_path=str(test_repo),
                output_tx=str(tx_path),
            )
        )

    monkeypatch.setattr(urllib.request, "urlopen", lambda req: MockResponse({"status": "succeed"}))
    rc = cmd_record_verification(
        argparse.Namespace(
            transaction_id=tx_id,
            probe_report=str(probe_path),
            attestation=None,
            challenge="challenge",
            verifier_sha="v" * 40,
            repo=None,
            github_token="fake-token",
            pages_deployment_id=None,
            pages_deployment_status=None,
            simulated_pages_deployment_status=None,
            ref="publication",
            repo_path=str(test_repo),
            output_tx=str(tx_path),
        )
    )
    assert rc == 0
    updated = journal.read_transaction(test_repo, tx_id, ref="publication")
    assert updated.state == STATE_EXTERNALLY_VERIFIED
    assert updated.verification["pages_deployment_id"] == "c" * 40
    assert updated.verification["pages_deployment_status"] == "succeed"
    assert updated.verification["reconciled_from"] == STATE_RECOVERY_REQUIRED
