#!/usr/bin/env python3
"""Single state authority and Git journal CAS on the publication metadata ref.

Manages reading, preparing, and fast-forward compare-and-set updates on the
`publication` Git ref under the `publication/transaction-state/` subtree.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.publication.transaction import (
    KIND_LEGACY_RECOVERY,
    KIND_PROMOTION,
    KIND_ROLLBACK,
    OBJECT_TYPE,
    SCHEMA_VERSION,
    STATE_DURABLE,
    STATE_EXTERNALLY_VERIFIED,
    STATE_PREPARED,
    STATE_RECOVERY_REQUIRED,
    STATE_ROLLBACK_DURABLE,
    STATE_ROLLBACK_VERIFIED,
    STATE_ROLLBACK_WRITE_STARTED,
    STATE_TERMINAL_FAILURE,
    STATE_WRITE_ACKNOWLEDGED,
    STATE_WRITE_STARTED,
    VALID_KINDS,
    VALID_STATES,
    Transaction,
    canonical_json,
)

JOURNAL_OBJECT_TYPE = "publication-journal"
JOURNAL_SCHEMA_VERSION = 1
SUBTREE_PATH = "publication/transaction-state"
DEFAULT_REF = "publication"

KIND_STATES = {
    KIND_PROMOTION: {
        STATE_PREPARED,
        STATE_WRITE_STARTED,
        STATE_WRITE_ACKNOWLEDGED,
        STATE_EXTERNALLY_VERIFIED,
        STATE_DURABLE,
        STATE_RECOVERY_REQUIRED,
        STATE_TERMINAL_FAILURE,
    },
    KIND_ROLLBACK: {
        STATE_ROLLBACK_WRITE_STARTED,
        STATE_WRITE_ACKNOWLEDGED,
        STATE_ROLLBACK_VERIFIED,
        STATE_ROLLBACK_DURABLE,
        STATE_TERMINAL_FAILURE,
    },
    KIND_LEGACY_RECOVERY: {STATE_RECOVERY_REQUIRED, STATE_TERMINAL_FAILURE},
}


class JournalError(Exception):
    """Base exception for journal operations."""


class CasConflictError(JournalError):
    """Raised when an atomic CAS update fails due to a competing commit."""


class CorruptJournalError(JournalError):
    """Raised when journal state is missing or malformed."""


@dataclass(frozen=True)
class JournalState:
    target: dict[str, str]
    next_generation: int
    active_transaction_id: str | None
    durable_transaction_id: str | None
    write_block: str | None
    policy_digest: str
    tip_commit_oid: str
    object_type: str = JOURNAL_OBJECT_TYPE
    journal_schema_version: int = JOURNAL_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise JournalError(f"git {' '.join(args)} failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.strip()


def read_journal_state(repo_path: Path, ref: str = DEFAULT_REF) -> JournalState:
    """Read the current journal state.json directly from the given Git ref."""
    try:
        tip_oid = _run_git(["rev-parse", f"refs/heads/{ref}"], cwd=repo_path)
    except JournalError as e:
        raise CorruptJournalError(f"Cannot resolve journal ref '{ref}': {e}") from e

    state_path = f"{ref}:{SUBTREE_PATH}/state.json"
    try:
        content = _run_git(["cat-file", "-p", state_path], cwd=repo_path)
        data = json.loads(content)
    except Exception as e:
        raise CorruptJournalError(f"Missing or invalid state.json at {state_path}: {e}") from e

    if data.get("object_type") != JOURNAL_OBJECT_TYPE:
        raise CorruptJournalError(
            f"Invalid journal object_type: expected '{JOURNAL_OBJECT_TYPE}', got '{data.get('object_type')}'"
        )
    if data.get("journal_schema_version") != JOURNAL_SCHEMA_VERSION:
        raise CorruptJournalError(
            f"Unsupported journal schema version: expected {JOURNAL_SCHEMA_VERSION}, got {data.get('journal_schema_version')}"
        )

    return JournalState(
        target=data["target"],
        next_generation=data["next_generation"],
        active_transaction_id=data.get("active_transaction_id"),
        durable_transaction_id=data.get("durable_transaction_id"),
        write_block=data.get("write_block"),
        policy_digest=data["policy_digest"],
        tip_commit_oid=tip_oid,
        object_type=data["object_type"],
        journal_schema_version=data["journal_schema_version"],
    )


def read_transaction(repo_path: Path, tx_id: str, ref: str = DEFAULT_REF) -> Transaction:
    """Read a canonical transaction object directly from the journal ref."""
    tx_path = f"{ref}:{SUBTREE_PATH}/transactions/{tx_id}.json"
    try:
        content = _run_git(["cat-file", "-p", tx_path], cwd=repo_path)
        data = json.loads(content)
        if data.get("object_type") != OBJECT_TYPE:
            raise CorruptJournalError(f"Invalid transaction object_type: {data.get('object_type')!r}")
        if data.get("transaction_schema_version") != SCHEMA_VERSION:
            raise CorruptJournalError(
                f"Unsupported transaction schema version: {data.get('transaction_schema_version')!r}"
            )
        if data.get("state") not in VALID_STATES:
            raise CorruptJournalError(f"Invalid transaction state: {data.get('state')!r}")
        kind = data.get("kind")
        if kind not in VALID_KINDS:
            raise CorruptJournalError(f"Invalid transaction kind: {kind!r}")
        if data["state"] not in KIND_STATES[kind]:
            raise CorruptJournalError(f"Invalid state {data['state']!r} for transaction kind {kind!r}")
        if kind == KIND_ROLLBACK and not isinstance(data.get("restore_source"), dict):
            raise CorruptJournalError("Rollback transaction requires restore_source data")
        return Transaction(**data)
    except Exception as e:
        raise JournalError(f"Failed to read transaction '{tx_id}' at {tx_path}: {e}") from e


def write_journal_update(
    repo_path: Path,
    expected_parent_oid: str,
    new_state: JournalState,
    transaction: Transaction | None = None,
    ref: str = DEFAULT_REF,
    commit_message: str | None = None,
) -> tuple[JournalState, str]:
    """Atomically commit and fast-forward CAS a journal state update."""
    with tempfile.NamedTemporaryFile(delete=False) as tmp_idx:
        index_file = tmp_idx.name

    env = dict(os.environ, GIT_INDEX_FILE=index_file)
    try:
        # 1. Initialize temporary index from parent commit tree
        _run_git(["read-tree", expected_parent_oid], cwd=repo_path, env=env)

        # 2. Write state.json blob
        state_data = new_state.to_dict()
        state_data.pop("tip_commit_oid", None)
        state_bytes = canonical_json(state_data).encode("utf-8")

        p_state = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=repo_path,
            input=state_bytes,
            capture_output=True,
            check=True,
        )
        state_blob_oid = p_state.stdout.strip().decode()

        _run_git(
            ["update-index", "--add", "--cacheinfo", "100644", state_blob_oid, f"{SUBTREE_PATH}/state.json"],
            cwd=repo_path,
            env=env,
        )

        # 3. Write transaction blob if provided
        if transaction is not None:
            tx_bytes = canonical_json(transaction.to_dict()).encode("utf-8")
            p_tx = subprocess.run(
                ["git", "hash-object", "-w", "--stdin"],
                cwd=repo_path,
                input=tx_bytes,
                capture_output=True,
                check=True,
            )
            tx_blob_oid = p_tx.stdout.strip().decode()
            _run_git(
                [
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    "100644",
                    tx_blob_oid,
                    f"{SUBTREE_PATH}/transactions/{transaction.transaction_id}.json",
                ],
                cwd=repo_path,
                env=env,
            )

        # 4. Write new tree
        tree_oid = _run_git(["write-tree"], cwd=repo_path, env=env)

        # 5. Create commit pointing to expected_parent_oid
        msg = commit_message or f"journal: advance state to gen {new_state.next_generation}"
        commit_oid = _run_git(
            ["commit-tree", tree_oid, "-p", expected_parent_oid, "-m", msg],
            cwd=repo_path,
        )

        # 6. Atomically reserve the shared ref on the remote authority.
        p_update = subprocess.run(
            [
                "git",
                "push",
                "origin",
                f"{commit_oid}:refs/heads/{ref}",
                f"--force-with-lease=refs/heads/{ref}:{expected_parent_oid}",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if p_update.returncode != 0:
            if not resolve_timeout_or_recheck(repo_path, commit_oid, ref=ref):
                raise CasConflictError(
                    f"CAS update on remote ref '{ref}' failed (expected {expected_parent_oid}): {p_update.stderr.strip()}"
                )
        _run_git(["update-ref", f"refs/heads/{ref}", commit_oid], cwd=repo_path)

        updated_state = JournalState(
            target=new_state.target,
            next_generation=new_state.next_generation,
            active_transaction_id=new_state.active_transaction_id,
            durable_transaction_id=new_state.durable_transaction_id,
            write_block=new_state.write_block,
            policy_digest=new_state.policy_digest,
            tip_commit_oid=commit_oid,
            object_type=new_state.object_type,
            journal_schema_version=new_state.journal_schema_version,
        )
        return updated_state, commit_oid

    finally:
        if os.path.exists(index_file):
            try:
                os.unlink(index_file)
            except OSError:
                pass


def init_genesis_journal(
    repo_path: Path,
    target: dict[str, str],
    genesis_transaction: Transaction,
    base_commit_oid: str,
    ref: str = DEFAULT_REF,
) -> tuple[JournalState, str]:
    """Initialize a fresh publication journal at genesis referencing an attested known-good transaction."""
    init_state = JournalState(
        target=target,
        next_generation=genesis_transaction.generation + 1,
        active_transaction_id=None,
        durable_transaction_id=genesis_transaction.transaction_id,
        write_block=None,
        policy_digest="genesis",
        tip_commit_oid=base_commit_oid,
    )
    return write_journal_update(
        repo_path=repo_path,
        expected_parent_oid=base_commit_oid,
        new_state=init_state,
        transaction=genesis_transaction,
        ref=ref,
        commit_message=f"journal: initialize genesis at generation {genesis_transaction.generation}",
    )


def resolve_timeout_or_recheck(repo_path: Path, proposed_commit_oid: str, ref: str = DEFAULT_REF) -> bool:
    """Resolve an ambiguous network or API timeout by re-checking whether the proposed commit won."""
    try:
        _run_git(["fetch", "--no-tags", "origin", f"refs/heads/{ref}"], cwd=repo_path)
        current_oid = _run_git(["rev-parse", "FETCH_HEAD"], cwd=repo_path)
        return (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", proposed_commit_oid, current_oid],
                cwd=repo_path,
                check=False,
            ).returncode
            == 0
        )
    except Exception:
        return False
