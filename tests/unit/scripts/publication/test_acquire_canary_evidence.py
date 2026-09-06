"""Unit tests for acquire_canary_evidence.py."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.publication import acquire_canary_evidence, journal, transaction

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_acquire_from_journal_extracts_manifest_and_receipts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()

    # Create dummy journal with durable transaction
    tx = transaction.Transaction(
        object_type=transaction.OBJECT_TYPE,
        transaction_schema_version=1,
        transaction_id="durable-tx-123",
        target={"repo": "BenchBox-dev/BenchBox", "env": "github-pages", "base_url": "https://benchbox.dev"},
        kind=transaction.KIND_PROMOTION,
        generation=1,
        parent_transaction_id=None,
        recovery_of=None,
        restore_source=None,
        approval={"approved": True},
        controller={"workflow_path": "wf", "workflow_sha": "a" * 40, "run_id": 100},
        owner={"epoch": 1, "run_id": 100},
        content={"develop_sha": "d" * 40, "published_results_sha": "p" * 40},
        desired={"manifest_digest": "m" * 64, "generation": 1},
        artifact={"archive_sha256": "s" * 64},
        write={"write_id": "w1", "pages_build_version": "commit-1", "status": "succeed"},
        verification={"receipt_id": "receipt-1", "timestamp": "2026-09-05T00:00:00Z"},
        certification=None,
        state=transaction.STATE_DURABLE,
        event={},
        failure=None,
        attestation={"key_id": "k1", "signature": "sig1"},
    )

    out_dir = tmp_path / "evidence"

    # Mock journal functions
    j_state = journal.JournalState(
        target="BenchBox-dev/BenchBox:github-pages",
        next_generation=2,
        active_transaction_id=None,
        durable_transaction_id="durable-tx-123",
        write_block=None,
        policy_digest="p" * 64,
        tip_commit_oid="tip-oid",
    )

    monkeypatch.setattr(journal, "read_journal_state", lambda repo_path, ref: j_state)
    monkeypatch.setattr(journal, "read_transaction", lambda repo_path, tx_id, ref: tx)

    summary = acquire_canary_evidence.acquire(
        repository="BenchBox-dev/BenchBox",
        output_dir=out_dir,
        repo_path=repo,
        allow_unavailable=False,
    )
    assert summary["source"] == "journal"
    assert summary["durable_transaction_id"] == "durable-tx-123"
    assert (out_dir / "desired-manifest.json").is_file()
    assert (out_dir / "reconciliation" / "deployment-receipt.json").is_file()
    assert (out_dir / "reconciliation" / "live-receipt.json").is_file()


def test_acquire_fails_closed_when_evidence_unavailable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    out_dir = tmp_path / "evidence"

    monkeypatch.setattr(journal, "read_journal_state", lambda repo_path, ref: None)
    monkeypatch.setattr(acquire_canary_evidence, "acquire_from_github", lambda repo, out: None)

    with pytest.raises(acquire_canary_evidence.EvidenceUnavailable):
        acquire_canary_evidence.acquire(
            repository="BenchBox-dev/BenchBox",
            output_dir=out_dir,
            repo_path=repo,
            allow_unavailable=False,
        )


def test_acquire_allow_unavailable_records_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    out_dir = tmp_path / "evidence"

    monkeypatch.setattr(journal, "read_journal_state", lambda repo_path, ref: None)
    monkeypatch.setattr(acquire_canary_evidence, "acquire_from_github", lambda repo, out: None)

    status = acquire_canary_evidence.acquire(
        repository="BenchBox-dev/BenchBox",
        output_dir=out_dir,
        repo_path=repo,
        allow_unavailable=True,
    )
    assert status["available"] is False
    assert (out_dir / "evidence-status.json").is_file()
    data = json.loads((out_dir / "evidence-status.json").read_text(encoding="utf-8"))
    assert data["available"] is False
