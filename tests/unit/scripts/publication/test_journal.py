"""Unit tests for publication metadata Git journal CAS module (scripts/publication/journal.py)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.publication import journal as journal_mod, transaction as tx_mod

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def valid_receipt_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tx_mod, "validate_live_receipt_contract", lambda receipt: [])


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Create a temporary initialized Git repository with an initial commit."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@benchbox.dev"], cwd=repo, check=True)

    # Initial commit on main
    (repo / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)

    # Branch publication off main
    subprocess.run(["git", "branch", "publication"], cwd=repo, check=True)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=repo, check=True)
    subprocess.run(["git", "push", "origin", "main", "publication"], cwd=repo, check=True, capture_output=True)
    return repo


@pytest.fixture
def genesis_tx() -> tx_mod.Transaction:
    tx, _ = tx_mod.prepare_promotion(
        target={"repository": "BenchBox-dev/BenchBox", "environment": "github-pages", "url": "https://benchbox.dev"},
        generation=1,
        parent_transaction_id=None,
        approval={"permit_sha256": "genesis-permit", "approver": "maintainer"},
        controller={"workflow_path": "release.yml", "workflow_sha": "0" * 40},
        owner={"run_id": "1", "epoch": "0"},
        content={"manifest_digest": "g" * 64},
        artifact={"artifact_id": 1, "archive_sha256": "g_art" * 16},
        transaction_id="genesis-tx-0001",
    )
    # Mark as durable genesis
    attestation = {
        "target": tx.target,
        "generation": tx.generation,
        "manifest_digest": tx.content["manifest_digest"],
        "artifact_digest": tx.artifact["archive_sha256"],
        "observation_digest": "genesis-observation",
    }
    return tx_mod.Transaction(**{**tx.to_dict(), "state": tx_mod.STATE_DURABLE, "attestation": attestation})


def test_init_genesis_and_read(git_repo: Path, genesis_tx: tx_mod.Transaction) -> None:
    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    target = {"repository": "BenchBox-dev/BenchBox", "environment": "github-pages", "url": "https://benchbox.dev"}
    state, commit_oid = journal_mod.init_genesis_journal(
        repo_path=git_repo,
        target=target,
        genesis_transaction=genesis_tx,
        base_commit_oid=base_oid,
        ref="publication",
    )

    assert state.next_generation == 2
    assert state.durable_transaction_id == "genesis-tx-0001"
    assert state.active_transaction_id is None
    assert state.tip_commit_oid == commit_oid

    # Read state back
    loaded_state = journal_mod.read_journal_state(git_repo, ref="publication")
    assert loaded_state.next_generation == 2
    assert loaded_state.durable_transaction_id == "genesis-tx-0001"
    assert loaded_state.tip_commit_oid == commit_oid

    # Read transaction back
    loaded_tx = journal_mod.read_transaction(git_repo, "genesis-tx-0001", ref="publication")
    assert loaded_tx.transaction_id == "genesis-tx-0001"
    assert loaded_tx.generation == 1
    assert loaded_tx.state == tx_mod.STATE_DURABLE


def test_write_journal_update_happy_path(git_repo: Path, genesis_tx: tx_mod.Transaction) -> None:
    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    target = {"repository": "BenchBox-dev/BenchBox", "environment": "github-pages", "url": "https://benchbox.dev"}
    state, genesis_commit_oid = journal_mod.init_genesis_journal(
        repo_path=git_repo,
        target=target,
        genesis_transaction=genesis_tx,
        base_commit_oid=base_oid,
        ref="publication",
    )

    # Next transaction
    tx2, _ = tx_mod.prepare_promotion(
        target=target,
        generation=2,
        parent_transaction_id=genesis_tx.transaction_id,
        approval={"permit_sha256": "permit-2", "approver": "maintainer"},
        controller={"workflow_path": "tx.yml", "workflow_sha": "1" * 40},
        owner={"run_id": "2", "epoch": "1"},
        content={"manifest_digest": "m2" * 32},
        artifact={"artifact_id": 2, "archive_sha256": "art2" * 16},
        transaction_id="tx-0002",
    )

    new_state = journal_mod.JournalState(
        target=target,
        next_generation=3,
        active_transaction_id="tx-0002",
        durable_transaction_id=genesis_tx.transaction_id,
        write_block=None,
        policy_digest="p2",
        tip_commit_oid=genesis_commit_oid,
    )

    updated_state, new_commit_oid = journal_mod.write_journal_update(
        repo_path=git_repo,
        expected_parent_oid=genesis_commit_oid,
        new_state=new_state,
        transaction=tx2,
        ref="publication",
    )

    assert updated_state.next_generation == 3
    assert updated_state.active_transaction_id == "tx-0002"
    assert updated_state.tip_commit_oid == new_commit_oid

    # Verify both transactions are readable
    t1 = journal_mod.read_transaction(git_repo, "genesis-tx-0001", ref="publication")
    t2 = journal_mod.read_transaction(git_repo, "tx-0002", ref="publication")
    assert t1.transaction_id == "genesis-tx-0001"
    assert t2.transaction_id == "tx-0002"

    identity = subprocess.run(
        ["git", "show", "-s", "--format=%an <%ae>", new_commit_oid],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert identity == "BenchBox Publication Controller <publication-controller@benchbox.dev>"


def test_cas_conflict_detection(git_repo: Path, genesis_tx: tx_mod.Transaction) -> None:
    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    target = {"repository": "BenchBox-dev/BenchBox", "environment": "github-pages", "url": "https://benchbox.dev"}
    state, genesis_commit_oid = journal_mod.init_genesis_journal(
        repo_path=git_repo,
        target=target,
        genesis_transaction=genesis_tx,
        base_commit_oid=base_oid,
        ref="publication",
    )

    # Writer 1 prepares an update
    state_writer_1 = journal_mod.JournalState(
        target=target,
        next_generation=3,
        active_transaction_id="tx-w1",
        durable_transaction_id=genesis_tx.transaction_id,
        write_block=None,
        policy_digest="p-w1",
        tip_commit_oid=genesis_commit_oid,
    )
    # Writer 2 also prepares from the same genesis_commit_oid
    state_writer_2 = journal_mod.JournalState(
        target=target,
        next_generation=3,
        active_transaction_id="tx-w2",
        durable_transaction_id=genesis_tx.transaction_id,
        write_block=None,
        policy_digest="p-w2",
        tip_commit_oid=genesis_commit_oid,
    )

    # Writer 1 commits first
    _, w1_commit = journal_mod.write_journal_update(
        repo_path=git_repo,
        expected_parent_oid=genesis_commit_oid,
        new_state=state_writer_1,
        ref="publication",
    )

    # Writer 2 attempts to commit using old parent -> MUST fail with CasConflictError
    with pytest.raises(journal_mod.CasConflictError, match="CAS update on remote ref 'publication' failed"):
        journal_mod.write_journal_update(
            repo_path=git_repo,
            expected_parent_oid=genesis_commit_oid,
            new_state=state_writer_2,
            ref="publication",
        )


def test_ambiguous_push_failure_reconciles_remote_success(
    git_repo: Path, genesis_tx: tx_mod.Transaction, monkeypatch: pytest.MonkeyPatch
) -> None:
    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    state = journal_mod.JournalState(
        target={"repository": "BenchBox-dev/BenchBox", "environment": "github-pages"},
        next_generation=2,
        active_transaction_id=genesis_tx.transaction_id,
        durable_transaction_id=None,
        write_block=None,
        policy_digest="policy",
        tip_commit_oid=base_oid,
    )
    original_run = subprocess.run

    def lose_push_response(args, *positional, **kwargs):
        result = original_run(args, *positional, **kwargs)
        if args[:2] == ["git", "push"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="connection closed after update")
        return result

    monkeypatch.setattr(journal_mod.subprocess, "run", lose_push_response)
    updated, commit_oid = journal_mod.write_journal_update(
        repo_path=git_repo,
        expected_parent_oid=base_oid,
        new_state=state,
        transaction=genesis_tx,
        ref="publication",
    )

    assert updated.tip_commit_oid == commit_oid
    assert journal_mod.resolve_timeout_or_recheck(git_repo, commit_oid, ref="publication") is True


def test_timeout_resolution(git_repo: Path, genesis_tx: tx_mod.Transaction, tmp_path: Path) -> None:
    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    target = {"repository": "BenchBox-dev/BenchBox", "environment": "github-pages", "url": "https://benchbox.dev"}
    _, commit_oid = journal_mod.init_genesis_journal(
        repo_path=git_repo,
        target=target,
        genesis_transaction=genesis_tx,
        base_commit_oid=base_oid,
        ref="publication",
    )

    assert journal_mod.resolve_timeout_or_recheck(git_repo, commit_oid, ref="publication") is True
    remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    other_repo = tmp_path / "other"
    subprocess.run(["git", "clone", remote, str(other_repo)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=other_repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=other_repo, check=True)
    subprocess.run(["git", "checkout", "publication"], cwd=other_repo, check=True, capture_output=True)
    tree_oid = subprocess.run(
        ["git", "show", "-s", "--format=%T", commit_oid],
        cwd=other_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    descendant_oid = subprocess.run(
        ["git", "commit-tree", tree_oid, "-p", commit_oid, "-m", "later journal update"],
        cwd=other_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "push",
            "origin",
            f"{descendant_oid}:refs/heads/publication",
            f"--force-with-lease=refs/heads/publication:{commit_oid}",
        ],
        cwd=other_repo,
        check=True,
        capture_output=True,
    )
    assert journal_mod.resolve_timeout_or_recheck(git_repo, commit_oid, ref="publication") is True
    assert journal_mod.resolve_timeout_or_recheck(git_repo, "nonexistent-sha", ref="publication") is False


def test_corrupt_journal_fails_closed(git_repo: Path) -> None:
    # On empty/uninitialized publication branch, read fails closed
    with pytest.raises(journal_mod.CorruptJournalError, match="Missing or invalid state.json"):
        journal_mod.read_journal_state(git_repo, ref="publication")


@pytest.mark.parametrize(
    "field,value",
    [
        ("object_type", "wrong"),
        ("transaction_schema_version", 99),
        ("state", "invented"),
        ("kind", "invented"),
        ("kind", tx_mod.KIND_ROLLBACK),
    ],
)
def test_read_transaction_rejects_invalid_contract(monkeypatch: pytest.MonkeyPatch, field: str, value: object) -> None:
    data = {
        "object_type": tx_mod.OBJECT_TYPE,
        "transaction_schema_version": tx_mod.SCHEMA_VERSION,
        "state": tx_mod.STATE_PREPARED,
        "kind": tx_mod.KIND_PROMOTION,
    }
    data[field] = value
    monkeypatch.setattr(journal_mod, "_run_git", lambda *args, **kwargs: json.dumps(data))
    with pytest.raises(journal_mod.JournalError):
        journal_mod.read_transaction(Path("."), "bad")


def test_historical_durable_transaction_reads_without_stale_receipt_error(
    git_repo: Path, genesis_tx: tx_mod.Transaction, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historical durable transactions in the journal must not fail read due to wall-clock receipt age."""
    from scripts.publication.reconciliation import validate_live_receipt_contract as real_validate

    # Restore the real validator to test real contract validation
    monkeypatch.setattr(tx_mod, "validate_live_receipt_contract", real_validate)
    monkeypatch.setattr("scripts.publication.reconciliation.verify_live_receipt_signature", lambda r: (True, None))

    base_oid = subprocess.run(
        ["git", "rev-parse", "refs/heads/publication"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    target = {"repository": "BenchBox-dev/BenchBox", "environment": "github-pages", "url": "https://benchbox.dev"}
    genesis_tx.attestation.update(
        {
            "schema_version": 2,
            "receipt_id": "live-genesis-test",
            "timestamp": "2026-08-01T00:00:00Z",
            "develop_sha": "0" * 40,
            "published_results_sha": "0" * 40,
            "artifact": {"archive_sha256": genesis_tx.artifact["archive_sha256"]},
            "artifacts": {"pages_assembly": {"digest": genesis_tx.artifact["archive_sha256"]}},
            "observation_origin": "github-actions:publication-verify",
            "nonce": "test-nonce",
            "freshness_window": "24h",
            "attestor": "github-actions:publication-deploy",
            "signature": "mock-sig",
            "status": "BUILT",
            "target": "benchbox.dev",
            "routes": [
                {"path": "/", "status_code": 200, "ok": True, "sha256": "abc"},
                {"path": "/docs/", "status_code": 200, "ok": True, "sha256": "abc"},
                {"path": "/results/", "status_code": 200, "ok": True, "sha256": "abc"},
                {"path": "/results/data/results.duckdb", "status_code": 200, "ok": True, "sha256": "abc"},
            ],
        }
    )

    state, commit_oid = journal_mod.init_genesis_journal(
        repo_path=git_repo,
        target=target,
        genesis_transaction=genesis_tx,
        base_commit_oid=base_oid,
        ref="publication",
    )
    loaded = journal_mod.read_transaction(git_repo, state.durable_transaction_id, ref="publication")
    assert loaded.transaction_id == genesis_tx.transaction_id
