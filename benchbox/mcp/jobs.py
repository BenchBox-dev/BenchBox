"""Durable, tenant-owned benchmark jobs for remote stateless MCP."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import ToolAnnotations

from benchbox.core.benchmark_registry import get_all_benchmarks
from benchbox.mcp.schemas import MCPValidationError, validate_phases, validate_platform_options
from benchbox.mcp.security import (
    AUTHORIZATION_ERROR,
    JobLimits,
    Principal,
    TenantWorkspaceProvider,
    authenticated_principal,
)
from benchbox.mcp.tools.benchmark import (
    _execute_mcp_run_via_core,
    _resolve_mcp_mode_with_registry,
)
from benchbox.utils.clock import mono_time, utc_now

logger = logging.getLogger(__name__)

JOB_NOT_FOUND = -32005
JOB_NOT_READY = -32006
JOB_QUEUE_FULL = -32007
JOB_IDEMPOTENCY_CONFLICT = -32008


START_ANNOTATIONS = ToolAnnotations(
    title="Start benchmark job",
    read_only_hint=False,
    destructive_hint=False,
    idempotent_hint=False,
    open_world_hint=True,
)
READ_ANNOTATIONS = ToolAnnotations(
    title="Read benchmark job",
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
CANCEL_ANNOTATIONS = ToolAnnotations(
    title="Cancel benchmark job",
    read_only_hint=False,
    destructive_hint=True,
    idempotent_hint=True,
    open_world_hint=False,
)


# Leased attempts always hold database capacity. Unknown outcomes hold it until
# the fenced executor durably attests that its call has returned.
LEASED_STATES = ("running", "publishing")


@dataclass(frozen=True, slots=True)
class JobRecord:
    """One persisted benchmark job."""

    execution_id: str
    principal_id: str
    state: str
    request: dict[str, Any]
    idempotency_key: str | None
    attempts: int
    lease_owner: str | None
    lease_expires_at: float | None
    lease_version: int
    lease_generation: int
    cancel_requested: bool
    artifact_path: str | None
    error_code: str | None
    created_at: str
    updated_at: str
    completed_at: str | None
    unproven_owner: str | None = None
    quiesced_at: str | None = None


class DurableJobRepository:
    """SQLite job queue whose transitions are safe across worker processes."""

    def __init__(self, path: Path, limits: JobLimits):
        self.path = path
        self.limits = limits
        self._lease_observations: dict[str, tuple[str | None, int, float]] = {}
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            for attempt in range(100):
                try:
                    connection.execute("PRAGMA journal_mode = WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 99:
                        raise
                    time.sleep(0.01)
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS mcp_benchmark_jobs (
                    execution_id TEXT PRIMARY KEY,
                    principal_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (
                        state IN (
                            'queued', 'running', 'publishing', 'completed',
                            'failed', 'cancelled', 'unknown'
                        )
                    ),
                    request_json TEXT NOT NULL,
                    idempotency_key TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_owner TEXT,
                    lease_expires_at REAL,
                    lease_version INTEGER NOT NULL DEFAULT 1,
                    lease_generation INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    artifact_path TEXT,
                    error_code TEXT,
                    enqueue_sequence INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    unproven_owner TEXT,
                    quiesced_at TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS mcp_job_idempotency_idx
                    ON mcp_benchmark_jobs (principal_id, idempotency_key)
                    WHERE idempotency_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS mcp_job_queue_idx
                    ON mcp_benchmark_jobs (state, created_at);
                CREATE INDEX IF NOT EXISTS mcp_job_owner_idx
                    ON mcp_benchmark_jobs (principal_id, execution_id);
                CREATE TABLE IF NOT EXISTS mcp_job_claim_fairness (
                    principal_id TEXT PRIMARY KEY,
                    last_served_sequence INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS mcp_job_order (
                    name TEXT PRIMARY KEY,
                    value INTEGER NOT NULL
                );
                """
            )
            self._ensure_column(connection, "lease_version", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(connection, "lease_generation", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(connection, "unproven_owner", "TEXT")
            self._ensure_column(connection, "quiesced_at", "TEXT")
            self._ensure_column(connection, "enqueue_sequence", "INTEGER")
            connection.execute("UPDATE mcp_benchmark_jobs SET enqueue_sequence = rowid WHERE enqueue_sequence IS NULL")
            connection.execute(
                """
                INSERT INTO mcp_job_order (name, value)
                SELECT 'enqueue', COALESCE(MAX(enqueue_sequence), 0) FROM mcp_benchmark_jobs
                WHERE 1
                ON CONFLICT (name) DO UPDATE SET value = MAX(value, excluded.value)
                """
            )
            self._migrate_state_check(connection)

    @staticmethod
    def _ensure_column(connection: sqlite3.Connection, name: str, declaration: str) -> None:
        """Add one migration column, tolerating a concurrent initializer winner."""
        columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(mcp_benchmark_jobs)")}
        if name in columns:
            return
        try:
            connection.execute(f"ALTER TABLE mcp_benchmark_jobs ADD COLUMN {name} {declaration}")
        except sqlite3.OperationalError:
            columns = {str(row["name"]) for row in connection.execute("PRAGMA table_info(mcp_benchmark_jobs)")}
            if name not in columns:
                raise

    @staticmethod
    def _migrate_state_check(connection: sqlite3.Connection) -> None:
        """Widen the state CHECK on pre-unknown databases so recovery can record unknown outcomes."""
        try:
            stranded = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'mcp_benchmark_jobs_legacy'"
            ).fetchone()
            if stranded is not None:
                DurableJobRepository._resume_state_migration(connection)
                return
            definition = connection.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'mcp_benchmark_jobs'"
            ).fetchone()
            if definition is None or definition[0] is None or "'unknown'" in definition[0]:
                return
            DurableJobRepository._rebuild_state_table(connection)
        except sqlite3.OperationalError:
            if DurableJobRepository._migration_complete(connection):
                return  # A concurrent worker already migrated the shared database.
            raise

    @staticmethod
    def _migration_complete(connection: sqlite3.Connection) -> bool:
        """Check whether another initializer already finished the state migration."""
        stranded = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'mcp_benchmark_jobs_legacy'"
        ).fetchone()
        if stranded is not None:
            return False
        definition = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'mcp_benchmark_jobs'").fetchone()
        return definition is not None and definition[0] is not None and "'unknown'" in definition[0]

    @staticmethod
    def _resume_state_migration(connection: sqlite3.Connection) -> None:
        """Finish a state migration interrupted after the rename, in one transaction."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            DurableJobRepository._copy_legacy_jobs(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _rebuild_state_table(connection: sqlite3.Connection) -> None:
        """Rebuild the jobs table with the widened state CHECK, preserving rows by column name."""
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("ALTER TABLE mcp_benchmark_jobs RENAME TO mcp_benchmark_jobs_legacy")
            DurableJobRepository._copy_legacy_jobs(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    @staticmethod
    def _copy_legacy_jobs(connection: sqlite3.Connection) -> None:
        """Copy stranded legacy rows into the widened table and drop the legacy table."""
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS mcp_benchmark_jobs (
                execution_id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN (
                        'queued', 'running', 'publishing', 'completed',
                        'failed', 'cancelled', 'unknown'
                    )
                ),
                request_json TEXT NOT NULL,
                idempotency_key TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                lease_owner TEXT,
                lease_expires_at REAL,
                lease_version INTEGER NOT NULL DEFAULT 1,
                lease_generation INTEGER NOT NULL DEFAULT 0,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                artifact_path TEXT,
                error_code TEXT,
                enqueue_sequence INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                unproven_owner TEXT,
                quiesced_at TEXT
            )
            """
        )
        legacy_columns = [
            str(row["name"]) for row in connection.execute("PRAGMA table_info(mcp_benchmark_jobs_legacy)")
        ]
        names = ", ".join(legacy_columns)
        connection.execute(
            f"INSERT OR IGNORE INTO mcp_benchmark_jobs ({names}) SELECT {names} FROM mcp_benchmark_jobs_legacy"
        )
        connection.execute("DROP TABLE mcp_benchmark_jobs_legacy")
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS mcp_job_idempotency_idx"
            " ON mcp_benchmark_jobs (principal_id, idempotency_key) WHERE idempotency_key IS NOT NULL"
        )
        connection.execute("CREATE INDEX IF NOT EXISTS mcp_job_queue_idx ON mcp_benchmark_jobs (state, created_at)")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS mcp_job_owner_idx ON mcp_benchmark_jobs (principal_id, execution_id)"
        )

    @staticmethod
    def _record(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            execution_id=row["execution_id"],
            principal_id=row["principal_id"],
            state=row["state"],
            request=json.loads(row["request_json"]),
            idempotency_key=row["idempotency_key"],
            attempts=row["attempts"],
            lease_owner=row["lease_owner"],
            lease_expires_at=row["lease_expires_at"],
            lease_version=row["lease_version"],
            lease_generation=row["lease_generation"],
            cancel_requested=bool(row["cancel_requested"]),
            artifact_path=row["artifact_path"],
            error_code=row["error_code"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
            unproven_owner=row["unproven_owner"],
            quiesced_at=row["quiesced_at"],
        )

    @staticmethod
    def _next_order(connection: sqlite3.Connection, name: str) -> int:
        """Return a database-owned monotonic order value inside the caller's transaction."""
        connection.execute(
            "INSERT INTO mcp_job_order (name, value) VALUES (?, 0) ON CONFLICT (name) DO NOTHING",
            (name,),
        )
        row = connection.execute(
            "UPDATE mcp_job_order SET value = value + 1 WHERE name = ? RETURNING value",
            (name,),
        ).fetchone()
        assert row is not None
        return int(row[0])

    def submit(
        self,
        principal_id: str,
        request: Mapping[str, Any],
        *,
        idempotency_key: str | None = None,
    ) -> tuple[JobRecord, bool]:
        """Create a queued job, or return the principal's idempotent match.

        Submission bounds queued depth only: the global queue and the
        principal's own queued share. Running admission is enforced
        separately by :meth:`claim`, so new work can wait while outstanding
        attempts hold database capacity.
        """
        normalized_key = idempotency_key.strip() if idempotency_key is not None else None
        if normalized_key is not None and (not normalized_key or len(normalized_key) > 200):
            raise MCPError(-32602, "idempotency_key must contain 1 to 200 characters")
        now = utc_now().isoformat()
        execution_id = f"mcp_job_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if normalized_key is not None:
                existing = connection.execute(
                    "SELECT * FROM mcp_benchmark_jobs WHERE principal_id = ? AND idempotency_key = ?",
                    (principal_id, normalized_key),
                ).fetchone()
                if existing is not None:
                    if json.loads(existing["request_json"]) != dict(request):
                        connection.rollback()
                        raise MCPError(JOB_IDEMPOTENCY_CONFLICT, "Idempotency key was used for a different request")
                    connection.commit()
                    return self._record(existing), False
            queued_total = connection.execute(
                "SELECT COUNT(*) FROM mcp_benchmark_jobs WHERE state = 'queued'"
            ).fetchone()[0]
            if queued_total >= self.limits.queue_limit:
                connection.rollback()
                raise MCPError(JOB_QUEUE_FULL, "Benchmark job queue is full")
            queued_owned = connection.execute(
                "SELECT COUNT(*) FROM mcp_benchmark_jobs WHERE state = 'queued' AND principal_id = ?",
                (principal_id,),
            ).fetchone()[0]
            if queued_owned >= self.limits.max_queued_per_principal:
                connection.rollback()
                raise MCPError(JOB_QUEUE_FULL, "Benchmark job queue is full for this principal")
            connection.execute(
                """
                INSERT INTO mcp_benchmark_jobs (
                    execution_id, principal_id, state, request_json, idempotency_key,
                    enqueue_sequence, created_at, updated_at
                ) VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    execution_id,
                    principal_id,
                    json.dumps(dict(request), sort_keys=True),
                    normalized_key,
                    self._next_order(connection, "enqueue"),
                    now,
                    now,
                ),
            )
            row = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            connection.commit()
        assert row is not None
        return self._record(row), True

    def get_owned(self, execution_id: str, principal_id: str) -> JobRecord | None:
        """Return a job only when the caller owns it."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ? AND principal_id = ?",
                (execution_id, principal_id),
            ).fetchone()
        return self._record(row) if row is not None else None

    def get(self, execution_id: str) -> JobRecord | None:
        """Return a job for worker coordination, independent of tenant requests."""
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
        return self._record(row) if row is not None else None

    def claim(self, worker_id: str) -> JobRecord | None:
        """Transactionally lease one queued job under running capacity and fairness.

        Running admission is bounded globally and per principal over leased
        attempts plus unquiesced unknown work, so a lost
        lease keeps holding database capacity until a fenced transition
        proves quiescence. Among eligible principals the least-recently-served
        wins, and each principal's own oldest queued job wins, which keeps
        per-principal FIFO order while preventing a noisy principal from
        starving the rest.
        """
        now = utc_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            outstanding_total = connection.execute(
                """SELECT COUNT(*) FROM mcp_benchmark_jobs
                   WHERE state IN (?, ?) OR (state = 'unknown' AND quiesced_at IS NULL)""",
                LEASED_STATES,
            ).fetchone()[0]
            if outstanding_total >= self.limits.max_running:
                connection.commit()
                return None
            winner = connection.execute(
                """
                SELECT queued.principal_id AS principal_id,
                       MIN(queued.enqueue_sequence) AS oldest
                FROM mcp_benchmark_jobs AS queued
                WHERE queued.state = 'queued'
                  AND (
                      SELECT COUNT(*)
                      FROM mcp_benchmark_jobs AS active
                      WHERE (active.state IN (?, ?)
                             OR (active.state = 'unknown' AND active.quiesced_at IS NULL))
                        AND active.principal_id = queued.principal_id
                  ) < ?
                GROUP BY queued.principal_id
                ORDER BY
                    COALESCE(
                        (SELECT last_served_sequence FROM mcp_job_claim_fairness AS fair
                         WHERE fair.principal_id = queued.principal_id),
                        0
                    ),
                    MIN(queued.enqueue_sequence),
                    queued.principal_id
                LIMIT 1
                """,
                (*LEASED_STATES, self.limits.max_running_per_principal),
            ).fetchone()
            if winner is None:
                connection.commit()
                return None
            row = connection.execute(
                """
                SELECT * FROM mcp_benchmark_jobs
                WHERE state = 'queued' AND principal_id = ?
                ORDER BY enqueue_sequence, rowid LIMIT 1
                """,
                (winner["principal_id"],),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            execution_id = row["execution_id"]
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET state = 'running', attempts = attempts + 1, lease_owner = ?, lease_expires_at = ?,
                    lease_version = 2, lease_generation = lease_generation + 1,
                    unproven_owner = NULL, quiesced_at = NULL, updated_at = ?
                WHERE execution_id = ? AND state = 'queued'
                """,
                (worker_id, now.timestamp() + self.limits.lease_seconds, now.isoformat(), execution_id),
            ).rowcount
            if changed != 1:
                connection.rollback()
                return None
            connection.execute(
                """
                INSERT INTO mcp_job_claim_fairness (principal_id, last_served_sequence)
                VALUES (?, ?)
                ON CONFLICT (principal_id) DO UPDATE
                    SET last_served_sequence = excluded.last_served_sequence
                """,
                (winner["principal_id"], self._next_order(connection, "claim")),
            )
            claimed = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            connection.commit()
        assert claimed is not None
        return self._record(claimed)

    def renew(self, execution_id: str, worker_id: str) -> bool:
        """Renew a running or publishing lease owned by this worker.

        Ownership is the fence: renewal succeeds only while this worker still
        owns the lease, so a fenced worker learns it lost the lease and stops
        before publication. Lapse detection stays wall-clock free at this
        layer; expiry is decided by the recovery-side monotonic observation
        mechanism in :meth:`claim_expired`, never by comparing a wall-clock
        deadline here, so a host clock step cannot falsely evict a healthy
        attempt.
        """
        now = utc_now()
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET lease_expires_at = ?, lease_generation = lease_generation + 1, updated_at = ?
                WHERE execution_id = ? AND lease_owner = ? AND lease_version = 2
                  AND state IN ('running', 'publishing')
                """,
                (
                    now.timestamp() + self.limits.lease_seconds,
                    now.isoformat(),
                    execution_id,
                    worker_id,
                ),
            ).rowcount
        return changed == 1

    def begin_publication(self, execution_id: str, worker_id: str) -> bool:
        """Fence stale/cancelled workers before they publish an artifact."""
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs SET state = 'publishing', updated_at = ?
                WHERE execution_id = ? AND state = 'running' AND lease_owner = ?
                  AND cancel_requested = 0
                """,
                (utc_now().isoformat(), execution_id, worker_id),
            ).rowcount
        return changed == 1

    def complete(
        self,
        execution_id: str,
        worker_id: str,
        artifact_path: Path,
        *,
        publish: Callable[[], None] | None = None,
    ) -> bool:
        """Mark complete only after the worker has durably published the artifact."""
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                """SELECT state FROM mcp_benchmark_jobs
                   WHERE execution_id = ? AND state = 'publishing' AND lease_owner = ?
                     AND cancel_requested = 0""",
                (execution_id, worker_id),
            ).fetchone()
            if current is None:
                connection.rollback()
                return False
            if publish is not None:
                publish()
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET state = 'completed', artifact_path = ?, lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?, completed_at = ?
                WHERE execution_id = ? AND state = 'publishing' AND lease_owner = ?
                """,
                (str(artifact_path), now, now, execution_id, worker_id),
            ).rowcount
            connection.commit()
        return changed == 1

    def fail_attempt(self, execution_id: str, worker_id: str, error_code: str, *, retryable: bool = True) -> str | None:
        """Retry an owned failure when budget remains, otherwise fail terminally.

        Only the lease owner may report, and only while it still owns the lease,
        so a requeue here is safe: the reporting attempt already finished and
        cannot still be executing database work. Expiry recovery without such a
        report must use :meth:`recover`, which records ``unknown`` instead.
        """
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ? AND lease_owner = ?",
                (execution_id, worker_id),
            ).fetchone()
            if row is None or row["state"] not in {"running", "publishing"}:
                connection.rollback()
                return None
            cancelled = bool(row["cancel_requested"])
            retry = retryable and not cancelled and row["attempts"] < self.limits.max_attempts
            if retry:
                queued_total = connection.execute(
                    "SELECT COUNT(*) FROM mcp_benchmark_jobs WHERE state = 'queued'"
                ).fetchone()[0]
                queued_owned = connection.execute(
                    "SELECT COUNT(*) FROM mcp_benchmark_jobs WHERE state = 'queued' AND principal_id = ?",
                    (row["principal_id"],),
                ).fetchone()[0]
                retry = queued_total < self.limits.queue_limit and queued_owned < self.limits.max_queued_per_principal
                if not retry:
                    error_code = "retry_queue_full"
            next_state = "queued" if retry else ("cancelled" if cancelled else "failed")
            completed_at = None if retry else now
            connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET state = ?, lease_owner = NULL, lease_expires_at = NULL, error_code = ?,
                    lease_version = 1, lease_generation = 0, updated_at = ?, completed_at = ?
                WHERE execution_id = ? AND lease_owner = ?
                """,
                (next_state, error_code[:80], now, completed_at, execution_id, worker_id),
            )
            connection.commit()
        return next_state

    def mark_unknown_outstanding(self, execution_id: str, worker_id: str) -> bool:
        """Quarantine an owned job whose serialized result reports live work."""
        now = utc_now().isoformat()
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET state = 'unknown', lease_owner = NULL, lease_expires_at = NULL,
                    lease_version = 1, lease_generation = 0,
                    unproven_owner = ?, quiesced_at = NULL,
                    error_code = 'outstanding_work', updated_at = ?, completed_at = ?
                WHERE execution_id = ? AND lease_owner = ?
                  AND state IN ('running', 'publishing')
                """,
                (worker_id, now, now, execution_id, worker_id),
            ).rowcount
        return changed == 1

    def cancel(self, execution_id: str, principal_id: str) -> tuple[JobRecord, str] | None:
        """Cancel an owned job and report how the request was honored.

        Returns the current record with one of ``accepted`` (queued work
        cancelled immediately), ``requested`` (the running attempt will stop at
        the next safe boundary), or ``too_late`` (publication already committed
        or the job is otherwise terminal, so nothing can be revoked). Returns
        ``None`` when the job does not belong to the principal.
        """
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ? AND principal_id = ?",
                (execution_id, principal_id),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            if row["state"] == "queued":
                connection.execute(
                    """
                    UPDATE mcp_benchmark_jobs SET state = 'cancelled', cancel_requested = 1,
                        updated_at = ?, completed_at = ? WHERE execution_id = ?
                    """,
                    (now, now, execution_id),
                )
                outcome = "accepted"
            elif row["state"] == "running":
                connection.execute(
                    "UPDATE mcp_benchmark_jobs SET cancel_requested = 1, updated_at = ? WHERE execution_id = ?",
                    (now, execution_id),
                )
                outcome = "requested"
            else:
                outcome = "too_late"
            updated = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ?", (execution_id,)
            ).fetchone()
            connection.commit()
        assert updated is not None
        return self._record(updated), outcome

    def claim_expired(self, recovery_owner: str) -> JobRecord | None:
        """Transactionally fence and return the oldest expired lease."""
        observed_at = mono_time()
        wall_now = utc_now().timestamp()
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM mcp_benchmark_jobs
                WHERE state IN ('running', 'publishing')
                ORDER BY created_at
                """,
            ).fetchall()
        active_ids = {str(row["execution_id"]) for row in rows}
        self._lease_observations = {
            execution_id: observation
            for execution_id, observation in self._lease_observations.items()
            if execution_id in active_ids
        }
        candidate: sqlite3.Row | None = None
        for row in rows:
            if int(row["lease_version"]) == 1:
                if row["lease_expires_at"] is not None and float(row["lease_expires_at"]) <= wall_now:
                    candidate = row
                    break
                continue
            identity = (row["lease_owner"], int(row["lease_generation"]))
            observation = self._lease_observations.get(row["execution_id"])
            if observation is None or observation[:2] != identity:
                self._lease_observations[row["execution_id"]] = (*identity, observed_at)
                continue
            if observed_at - observation[2] >= self.limits.lease_seconds:
                candidate = row
                break
        if candidate is None:
            return None
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if int(candidate["lease_version"]) == 1:
                changed = connection.execute(
                    """UPDATE mcp_benchmark_jobs
                       SET lease_owner = ?, lease_expires_at = ?, lease_version = 2,
                           lease_generation = lease_generation + 1,
                           unproven_owner = COALESCE(unproven_owner, ?), updated_at = ?
                       WHERE execution_id = ? AND lease_owner = ? AND lease_version = 1
                         AND lease_expires_at <= ? AND state IN ('running', 'publishing')""",
                    (
                        recovery_owner,
                        wall_now + self.limits.lease_seconds,
                        candidate["lease_owner"],
                        utc_now().isoformat(),
                        candidate["execution_id"],
                        candidate["lease_owner"],
                        wall_now,
                    ),
                ).rowcount
            else:
                changed = connection.execute(
                    """UPDATE mcp_benchmark_jobs
                       SET lease_owner = ?, lease_expires_at = ?, lease_version = 2,
                           lease_generation = lease_generation + 1,
                           unproven_owner = COALESCE(unproven_owner, ?), updated_at = ?
                       WHERE execution_id = ? AND lease_owner = ? AND lease_version = 2
                         AND lease_generation = ? AND state IN ('running', 'publishing')""",
                    (
                        recovery_owner,
                        wall_now + self.limits.lease_seconds,
                        candidate["lease_owner"],
                        utc_now().isoformat(),
                        candidate["execution_id"],
                        candidate["lease_owner"],
                        candidate["lease_generation"],
                    ),
                ).rowcount
            if changed != 1:
                connection.rollback()
                return None
            fenced = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ?", (candidate["execution_id"],)
            ).fetchone()
            connection.commit()
        self._lease_observations.pop(candidate["execution_id"], None)
        assert fenced is not None
        return self._record(fenced)

    def recover(self, job: JobRecord, *, published_artifact: Path | None = None) -> str | None:
        """Recover one expired lease without allowing duplicate completion.

        The publication commit point can be completed from a durable artifact.
        Every other unreported expiry becomes ``unknown`` until the displaced
        worker separately attests quiescence. The proof may arrive just before
        or after recovery wins the fence. Cancellation and an exhausted
        attempt budget prove nothing about termination, so an
        unreported expired attempt records the terminal ``unknown`` outcome
        even on its final attempt: the job is never claimed again and an
        operator must inspect before resubmitting with a new idempotency key.
        """
        now = utc_now().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT * FROM mcp_benchmark_jobs WHERE execution_id = ?", (job.execution_id,)
            ).fetchone()
            if (
                current is None
                or current["state"] not in {"running", "publishing"}
                or current["lease_owner"] != job.lease_owner
            ):
                connection.rollback()
                return None
            if current["state"] == "publishing" and published_artifact is not None and published_artifact.is_file():
                next_state = "completed"
                artifact = str(published_artifact)
                error_code = None
                completed_at = now
            else:
                next_state = "unknown"
                artifact = None
                error_code = "cancellation_unconfirmed" if bool(current["cancel_requested"]) else "unknown_outcome"
                completed_at = now
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET state = ?, artifact_path = ?, lease_owner = NULL, lease_expires_at = NULL,
                    lease_version = 1, lease_generation = 0,
                    error_code = ?, updated_at = ?, completed_at = ?
                WHERE execution_id = ? AND lease_owner = ?
                """,
                (
                    next_state,
                    artifact,
                    error_code,
                    now,
                    completed_at,
                    job.execution_id,
                    job.lease_owner,
                ),
            ).rowcount
            if changed != 1:
                connection.rollback()
                return None
            connection.commit()
        return next_state

    def attest_quiescence(self, execution_id: str, worker_id: str) -> bool:
        """Record that an executor returned, releasing capacity if it becomes unknown.

        The recovery transition records the displaced lease owner. Only that
        owner can attest that the synchronous database call has returned. The
        outcome remains unknown; the attestation proves only that the old
        attempt can no longer produce external effects.
        """
        now = utc_now().isoformat()
        with self._connect() as connection:
            changed = connection.execute(
                """
                UPDATE mcp_benchmark_jobs
                SET quiesced_at = ?, unproven_owner = ?, updated_at = ?
                WHERE execution_id = ? AND quiesced_at IS NULL
                  AND (
                      (state = 'unknown' AND unproven_owner = ?)
                      OR (state IN ('running', 'publishing') AND lease_owner = ?)
                      OR (state IN ('running', 'publishing') AND unproven_owner = ?)
                  )
                """,
                (now, worker_id, now, execution_id, worker_id, worker_id, worker_id),
            ).rowcount
        return changed == 1

    def expired_terminal(self) -> list[JobRecord]:
        """Return terminal jobs whose retention period has elapsed."""
        cutoff = utc_now().timestamp() - self.limits.retention_seconds
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM mcp_benchmark_jobs
                WHERE (state IN (?, ?, ?)
                       OR (state = 'unknown' AND quiesced_at IS NOT NULL))
                  AND completed_at IS NOT NULL AND unixepoch(completed_at) <= ?
                """,
                ("completed", "failed", "cancelled", cutoff),
            ).fetchall()
        return [self._record(row) for row in rows]

    def delete_terminal(self, execution_id: str) -> bool:
        """Delete terminal metadata only after owned artifact cleanup succeeds."""
        with self._connect() as connection:
            changed = connection.execute(
                """
                DELETE FROM mcp_benchmark_jobs
                WHERE execution_id = ? AND (
                    state IN (?, ?, ?)
                    OR (state = 'unknown' AND quiesced_at IS NOT NULL)
                )
                """,
                (execution_id, "completed", "failed", "cancelled"),
            ).rowcount
        return changed == 1

    def capacity_summary(self) -> dict[str, Any]:
        """Report durable row counts against running capacity for operators.

        Row counts and capacity usage are separated: ``outstanding`` jobs
        (leased attempts plus work whose lease was lost without proof of
        termination) hold database capacity until a fenced transition
        releases them. ``quarantined`` names every unproven job with the
        reason it still holds capacity.
        """
        with self._connect() as connection:
            state_rows = connection.execute(
                "SELECT state, COUNT(*) AS total FROM mcp_benchmark_jobs GROUP BY state"
            ).fetchall()
            principal_rows = connection.execute(
                """
                SELECT principal_id,
                       SUM(CASE WHEN state = 'queued' THEN 1 ELSE 0 END) AS queued,
                       SUM(CASE WHEN state IN (?, ?)
                                     OR (state = 'unknown' AND quiesced_at IS NULL)
                                THEN 1 ELSE 0 END) AS outstanding
                FROM mcp_benchmark_jobs
                GROUP BY principal_id
                """,
                LEASED_STATES,
            ).fetchall()
            quarantined_rows = connection.execute(
                """
                SELECT execution_id, principal_id, error_code, updated_at
                FROM mcp_benchmark_jobs
                WHERE state = 'unknown' AND quiesced_at IS NULL
                ORDER BY updated_at, execution_id
                """
            ).fetchall()
        states = {str(row["state"]): int(row["total"]) for row in state_rows}
        outstanding = sum(int(row["outstanding"] or 0) for row in principal_rows)
        return {
            "limits": {
                "queue_limit": self.limits.queue_limit,
                "max_queued_per_principal": self.limits.max_queued_per_principal,
                "max_running": self.limits.max_running,
                "max_running_per_principal": self.limits.max_running_per_principal,
            },
            "queued": states.get("queued", 0),
            "outstanding": outstanding,
            "states": states,
            "quarantined": [
                {
                    "execution_id": str(row["execution_id"]),
                    "principal_id": str(row["principal_id"]),
                    "reason": str(row["error_code"] or "unknown_outcome"),
                    "since": str(row["updated_at"]),
                }
                for row in quarantined_rows
            ],
            "per_principal": {
                str(row["principal_id"]): {
                    "queued": int(row["queued"] or 0),
                    "outstanding": int(row["outstanding"] or 0),
                }
                for row in principal_rows
            },
        }


BenchmarkExecutor = Callable[[JobRecord, Path], dict[str, Any]]


def _response_has_outstanding_work(value: object) -> bool:
    """Return whether a serialized core result says work may still be running."""
    if isinstance(value, Mapping):
        outstanding = value.get("outstanding_stream_ids")
        if isinstance(outstanding, (list, tuple)) and bool(outstanding):
            return True
        if value.get("cleanup_state") == "outstanding":
            return True
        return any(_response_has_outstanding_work(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_response_has_outstanding_work(item) for item in value)
    return False


class DurableJobWorker:
    """Lease and execute durable jobs for one HTTP worker process."""

    def __init__(
        self,
        repository: DurableJobRepository,
        workspaces: TenantWorkspaceProvider,
        *,
        executor: BenchmarkExecutor | None = None,
        worker_id: str | None = None,
    ):
        self.repository = repository
        self.workspaces = workspaces
        self.executor = executor or self._execute_benchmark
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex}"
        self._next_retention_check = 0.0

    def _job_paths(self, job: JobRecord) -> tuple[Path, Path, Path]:
        workspace = self.workspaces.paths_for_principal_id(job.principal_id)
        jobs_root = workspace.root / "jobs"
        staging = jobs_root / ".staging" / f"{job.execution_id}-{job.attempts}"
        final_dir = jobs_root / job.execution_id
        return staging, final_dir, final_dir / "response.json"

    @staticmethod
    def _execute_benchmark(job: JobRecord, staging: Path) -> dict[str, Any]:
        """Execute a durable job via the shared core run service.

        This is the one-engine adoption for the worker path: instead of
        calling the MCP-private ``_run_benchmark_impl`` helper chain, the
        worker builds surface-neutral configs and delegates to
        ``benchbox.core.run_service.execute_run`` with a surface-injected
        ``AdapterFactory`` and ``SilentVerbosity``. Lease/fencing,
        idempotency and ``staging→os.replace`` publication remain in
        ``DurableJobWorker._run_job`` and are untouched.
        """
        from benchbox.mcp.errors import ErrorCode, make_error, make_not_found_error

        request = job.request
        platform = str(request["platform"])
        benchmark = str(request["benchmark"])
        scale_factor = float(request.get("scale_factor", 0.01))
        queries = request.get("queries")
        phases = request.get("phases")
        mode = request.get("mode")
        capture_plans = bool(request.get("capture_plans", False))
        link_probe = bool(request.get("link_probe", True))
        platform_options = request.get("platform_options")
        results_dir = staging
        execution_id = job.execution_id
        anonymize = True
        start_time = __import__("benchbox.utils.clock", fromlist=["mono_time"]).mono_time()

        # Re-admission: durable store is re-read, so validate again.
        try:
            from benchbox.mcp.schemas import validate_platform_options

            normalized_platform_options = validate_platform_options(platform, platform_options)
        except Exception as exc:
            from benchbox.mcp.errors import ErrorCode, make_error

            resp = make_error(ErrorCode.VALIDATION_ERROR, str(exc), details={"platform": platform})
            resp["execution_id"] = execution_id
            resp["status"] = "failed"
            return resp

        try:
            from benchbox.mcp.schemas import validate_phases

            phases = validate_phases(phases)
        except Exception as exc:
            from benchbox.core.constants import VALID_PHASES
            from benchbox.mcp.errors import ErrorCode, make_error

            resp = make_error(
                ErrorCode.VALIDATION_INVALID_PHASE, str(exc), details={"valid_phases": list(VALID_PHASES)}
            )
            resp["execution_id"] = execution_id
            resp["status"] = "failed"
            return resp

        resolved_mode, mode_error = _resolve_mcp_mode_with_registry(platform, mode)
        if mode_error:
            mode_error["execution_id"] = execution_id
            mode_error["status"] = "failed"
            return mode_error
        from benchbox.core.benchmark_registry import get_public_benchmark_class

        all_benchmarks = get_all_benchmarks()
        benchmark_lower = benchmark.lower()
        if benchmark_lower not in all_benchmarks:
            from benchbox.mcp.errors import make_not_found_error

            response = make_not_found_error("benchmark", benchmark, available=list(all_benchmarks.keys()))
            response["execution_id"] = execution_id
            response["status"] = "failed"
            return response
        benchmark_class = get_public_benchmark_class(benchmark_lower)
        if benchmark_class is None:
            from benchbox.mcp.errors import ErrorCode, make_error

            response = make_error(
                ErrorCode.DEPENDENCY_MISSING,
                f"Benchmark '{benchmark}' requires additional dependencies",
                details={"benchmark": benchmark},
            )
            response["execution_id"] = execution_id
            response["status"] = "failed"
            return response

        phases_list = (
            ["generate"]
            if resolved_mode == "data_only"
            else [phase.strip() for phase in (phases or "load,power").split(",")]
        )
        return _execute_mcp_run_via_core(
            platform=platform,
            benchmark=benchmark_lower,
            benchmark_class=benchmark_class,
            scale_factor=scale_factor,
            queries=queries,
            phases=phases_list,
            resolved_mode=resolved_mode,
            capture_plans=capture_plans,
            link_probe=link_probe,
            normalized_platform_options=normalized_platform_options,
            results_dir=results_dir,
            execution_id=execution_id,
            start_time=start_time,
            anonymize=anonymize,
        )

    async def run(self) -> None:
        """Continuously recover and execute shared queued work."""
        while True:
            await anyio.to_thread.run_sync(self.recover_expired)
            if mono_time() >= self._next_retention_check:
                await anyio.to_thread.run_sync(self.purge_expired)
                self._next_retention_check = mono_time() + min(60.0, self.repository.limits.retention_seconds)
            job = await anyio.to_thread.run_sync(self.repository.claim, self.worker_id)
            if job is None:
                await anyio.sleep(self.repository.limits.poll_seconds)
                continue
            await self._run_job(job)

    def recover_expired(self) -> None:
        """Fence expired leases and finalize only what the old attempt proved.

        Attempts that may still be executing are recorded ``unknown`` and never
        retried automatically; see :meth:`DurableJobRepository.recover`.
        """
        while True:
            recovery_owner = f"{self.worker_id}:recovery:{uuid.uuid4().hex}"
            job = self.repository.claim_expired(recovery_owner)
            if job is None:
                return
            staging, final_dir, response_path = self._job_paths(job)
            marker = final_dir / ".published"
            published = response_path if marker.is_file() and response_path.is_file() else None
            if job.state == "publishing" and published is None:
                shutil.rmtree(final_dir, ignore_errors=True)
            shutil.rmtree(staging, ignore_errors=True)
            self.repository.recover(job, published_artifact=published)

    async def _run_job(self, job: JobRecord) -> None:
        gate = await anyio.to_thread.run_sync(self.repository.get, job.execution_id)
        if gate is None or gate.lease_owner != self.worker_id or gate.state != "running":
            await anyio.to_thread.run_sync(self.repository.attest_quiescence, job.execution_id, self.worker_id)
            return  # Fenced or finalized before starting; recovery owns the outcome.
        if gate.cancel_requested:
            await anyio.to_thread.run_sync(self.repository.fail_attempt, job.execution_id, self.worker_id, "cancelled")
            return
        staging, final_dir, response_path = self._job_paths(job)
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir(parents=True, exist_ok=False)
        lease_lost = anyio.Event()
        try:
            execution_error: Exception | None = None
            response: dict[str, Any] | None = None
            executor_quiescent = True
            async with anyio.create_task_group() as task_group:
                task_group.start_soon(self._heartbeat, job.execution_id, lease_lost)
                try:
                    try:
                        response = await anyio.to_thread.run_sync(self.executor, job, staging)
                    except Exception as exc:
                        execution_error = exc
                    if execution_error is None:
                        assert response is not None
                        executor_quiescent = not _response_has_outstanding_work(response)
                        if not executor_quiescent:
                            await anyio.to_thread.run_sync(
                                self.repository.mark_unknown_outstanding,
                                job.execution_id,
                                self.worker_id,
                            )
                            shutil.rmtree(staging, ignore_errors=True)
                            return
                        if response.get("status") == "failed":
                            await anyio.to_thread.run_sync(
                                lambda: self.repository.fail_attempt(
                                    job.execution_id, self.worker_id, "benchmark_rejected", retryable=False
                                )
                            )
                            shutil.rmtree(staging, ignore_errors=True)
                            return
                        current = await anyio.to_thread.run_sync(self.repository.get, job.execution_id)
                        if current is None or current.cancel_requested:
                            await anyio.to_thread.run_sync(
                                self.repository.fail_attempt, job.execution_id, self.worker_id, "cancelled"
                            )
                            shutil.rmtree(staging, ignore_errors=True)
                            return
                        if lease_lost.is_set():
                            # The lease lapsed mid-execution; recovery owns the
                            # outcome. Never publish or report from a stale attempt.
                            shutil.rmtree(staging, ignore_errors=True)
                            return
                        if not await anyio.to_thread.run_sync(
                            self.repository.begin_publication, job.execution_id, self.worker_id
                        ):
                            shutil.rmtree(staging, ignore_errors=True)
                            return
                        final_result = self._rewrite_result_paths(response, staging, final_dir)
                        published = await anyio.to_thread.run_sync(
                            self._publish_artifact, job, final_result, staging, final_dir, response_path
                        )
                        if not published:
                            shutil.rmtree(staging, ignore_errors=True)
                finally:
                    task_group.cancel_scope.cancel()
                    # The synchronous executor has returned. If recovery fenced
                    # this attempt meanwhile, record the distinct durable proof
                    # that it can no longer produce external effects.
                    if executor_quiescent:
                        with anyio.CancelScope(shield=True):
                            await anyio.to_thread.run_sync(
                                self.repository.attest_quiescence, job.execution_id, self.worker_id
                            )
            if execution_error is not None:
                raise execution_error
        except BaseException as exc:
            shutil.rmtree(staging, ignore_errors=True)
            if isinstance(exc, anyio.get_cancelled_exc_class()):
                raise
            if (final_dir / ".published").is_file() and response_path.is_file():
                # The artifact crossed the durable publication boundary. Leave
                # it in publishing for lease recovery rather than re-executing.
                await anyio.to_thread.run_sync(
                    self.repository.complete, job.execution_id, self.worker_id, response_path
                )
                return
            if lease_lost.is_set():
                # The lease lapsed before the failure was reported; recovery
                # owns the outcome, so a stale attempt must not requeue.
                return
            logger.error("Durable MCP benchmark failed (%s)", type(exc).__name__)
            await anyio.to_thread.run_sync(
                self.repository.fail_attempt, job.execution_id, self.worker_id, type(exc).__name__
            )

    async def _heartbeat(self, execution_id: str, lease_lost: anyio.Event) -> None:
        interval = max(0.05, min(self.repository.limits.lease_seconds / 3, 30.0))
        while True:
            await anyio.sleep(interval)
            if not await anyio.to_thread.run_sync(self.repository.renew, execution_id, self.worker_id):
                lease_lost.set()
                return

    def _publish_artifact(
        self,
        job: JobRecord,
        response: dict[str, Any],
        staging: Path,
        final_dir: Path,
        response_path: Path,
    ) -> bool:
        """Flush and atomically publish while the database fence remains owned."""
        (staging / "response.json").write_text(json.dumps(response, sort_keys=True), encoding="utf-8")
        (staging / ".published").write_text(job.execution_id, encoding="ascii")
        self._sync_tree(staging)

        def publish() -> None:
            os.replace(staging, final_dir)
            self._sync_path(final_dir.parent)

        return self.repository.complete(
            job.execution_id,
            self.worker_id,
            response_path,
            publish=publish,
        )

    @staticmethod
    def _rewrite_result_paths(response: dict[str, Any], staging: Path, final_dir: Path) -> dict[str, Any]:
        metadata = response.get("mcp_metadata")
        if isinstance(metadata, dict):
            result_file = metadata.get("result_file")
            if isinstance(result_file, str):
                try:
                    relative = Path(result_file).relative_to(staging)
                except ValueError:
                    metadata["result_file"] = None
                else:
                    metadata["result_file"] = str(final_dir / relative)
        data_generation = response.get("data_generation")
        if isinstance(data_generation, dict) and isinstance(data_generation.get("data_path"), str):
            try:
                relative = Path(data_generation["data_path"]).relative_to(staging)
            except ValueError:
                data_generation["data_path"] = None
            else:
                data_generation["data_path"] = str(final_dir / relative)
        return response

    @staticmethod
    def _sync_path(path: Path) -> None:
        """Flush a file or directory before a durable state transition.

        Directory metadata is flushed where supported (POSIX); on Windows
        directory ``fsync`` is skipped because opening directories with
        ``os.open`` is not supported.
        """
        if path.is_dir() and sys.platform == "win32":
            return
        # Windows' ``FlushFileBuffers`` requires a write-capable handle.  Keep
        # read-only handles on POSIX so directory metadata remains flushable.
        flags = os.O_RDWR if sys.platform == "win32" else os.O_RDONLY
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @classmethod
    def _sync_tree(cls, root: Path) -> None:
        """Flush every staged file and directory before atomic publication."""
        for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            cls._sync_path(path)
        cls._sync_path(root)

    def purge_expired(self) -> None:
        """Delete retained artifacts only inside their persisted tenant workspace."""
        for job in self.repository.expired_terminal():
            if job.artifact_path is not None:
                workspace = self.workspaces.paths_for_principal_id(job.principal_id)
                artifact = Path(job.artifact_path)
                try:
                    artifact.resolve().relative_to(workspace.root)
                except ValueError:
                    logger.error("Refused to purge an MCP artifact outside its tenant workspace")
                    continue
                shutil.rmtree(artifact.parent, ignore_errors=True)
                if artifact.parent.exists():
                    logger.error("Could not purge an expired MCP job artifact")
                    continue
            self.repository.delete_terminal(job.execution_id)


@dataclass(frozen=True, slots=True)
class DurableJobRuntime:
    """Repository and worker lifecycle attached only to remote servers."""

    repository: DurableJobRepository
    worker: DurableJobWorker

    @classmethod
    def create(cls, state_db: Path, limits: JobLimits, workspaces: TenantWorkspaceProvider) -> DurableJobRuntime:
        repository = DurableJobRepository(state_db, limits)
        return cls(repository=repository, worker=DurableJobWorker(repository, workspaces))

    @asynccontextmanager
    async def lifespan(self, _server: MCPServer):
        """Run the background queue consumer for this server process."""
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(self.worker.run)
            try:
                yield self
            finally:
                task_group.cancel_scope.cancel()


def _owned_job(repository: DurableJobRepository, execution_id: str, principal: Principal) -> JobRecord:
    job = repository.get_owned(execution_id, principal.principal_id)
    if job is None:
        raise MCPError(JOB_NOT_FOUND, "Benchmark job not found")
    return job


def _public_status(job: JobRecord) -> dict[str, Any]:
    status: dict[str, Any] = {
        "execution_id": job.execution_id,
        "status": job.state,
        "attempts": job.attempts,
        "cancel_requested": job.cancel_requested,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "completed_at": job.completed_at,
        "error_code": job.error_code,
    }
    if job.state == "unknown":
        status["outcome_note"] = (
            "A prior attempt lost its lease and may still have executed database work. "
            "Inspect the target before resubmitting with a new idempotency key."
        )
    return status


def register_durable_job_tools(mcp: MCPServer, runtime: DurableJobRuntime) -> None:
    """Register remote-only durable benchmark job tools."""

    @mcp.tool(annotations=START_ANNOTATIONS)
    async def start_benchmark(
        platform: str,
        benchmark: str,
        scale_factor: float = 0.01,
        queries: str | None = None,
        phases: str | None = None,
        mode: str | None = None,
        capture_plans: bool = False,
        link_probe: bool = True,
        platform_options: dict[str, object] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Queue a tenant-owned benchmark and immediately return its durable handle."""
        principal = authenticated_principal()
        try:
            normalized_platform_options = validate_platform_options(platform, platform_options)
            phases = validate_phases(phases)
        except MCPValidationError as exc:
            raise MCPError(-32602, str(exc)) from exc
        request = {
            "platform": platform,
            "benchmark": benchmark,
            "scale_factor": scale_factor,
            "queries": queries,
            "phases": phases,
            "mode": mode,
            "capture_plans": capture_plans,
            "link_probe": link_probe,
        }
        if normalized_platform_options:
            request["platform_options"] = normalized_platform_options
        job, created = await anyio.to_thread.run_sync(
            lambda: runtime.repository.submit(principal.principal_id, request, idempotency_key=idempotency_key)
        )
        return {**_public_status(job), "created": created}

    @mcp.tool(annotations=READ_ANNOTATIONS)
    async def get_benchmark_status(execution_id: str) -> dict[str, Any]:
        """Read the status of a benchmark job owned by the current principal."""
        principal = authenticated_principal()
        job = await anyio.to_thread.run_sync(_owned_job, runtime.repository, execution_id, principal)
        return _public_status(job)

    @mcp.tool(annotations=READ_ANNOTATIONS)
    async def get_benchmark_capacity() -> dict[str, Any]:
        """Report queue depth and running capacity without exposing other tenants.

        Global row counts are aggregates only; the per-principal slice and
        the quarantined job list are restricted to the current principal.
        """
        principal = authenticated_principal()
        summary = await anyio.to_thread.run_sync(runtime.repository.capacity_summary)
        owned = summary["per_principal"].get(principal.principal_id, {"queued": 0, "outstanding": 0})
        return {
            "limits": summary["limits"],
            "queued": summary["queued"],
            "outstanding": summary["outstanding"],
            "states": summary["states"],
            "owned": owned,
            "quarantined": [
                {key: entry[key] for key in ("execution_id", "reason", "since")}
                for entry in summary["quarantined"]
                if entry["principal_id"] == principal.principal_id
            ],
        }

    @mcp.tool(annotations=READ_ANNOTATIONS)
    async def get_benchmark_result(execution_id: str) -> dict[str, Any]:
        """Return a completed owned result without exposing another tenant's paths."""
        principal = authenticated_principal()
        job = await anyio.to_thread.run_sync(_owned_job, runtime.repository, execution_id, principal)
        if job.state != "completed" or job.artifact_path is None:
            raise MCPError(JOB_NOT_READY, f"Benchmark job is not complete (status: {job.state})")
        artifact = Path(job.artifact_path)
        workspace = runtime.worker.workspaces.paths_for(principal)
        try:
            artifact.resolve(strict=True).relative_to(workspace.root)
        except (OSError, ValueError) as exc:
            raise MCPError(AUTHORIZATION_ERROR, "Benchmark artifact is unavailable") from exc
        try:
            payload = json.loads(artifact.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise MCPError(JOB_NOT_READY, "Benchmark artifact is unavailable") from exc
        if not isinstance(payload, dict):
            raise MCPError(JOB_NOT_READY, "Benchmark artifact is invalid")
        return payload

    @mcp.tool(annotations=CANCEL_ANNOTATIONS)
    async def cancel_benchmark(execution_id: str) -> dict[str, Any]:
        """Cancel queued work, request cancellation at the next safe boundary, or report it is too late."""
        principal = authenticated_principal()
        outcome = await anyio.to_thread.run_sync(runtime.repository.cancel, execution_id, principal.principal_id)
        if outcome is None:
            raise MCPError(JOB_NOT_FOUND, "Benchmark job not found")
        job, cancel_outcome = outcome
        return {**_public_status(job), "cancel_outcome": cancel_outcome}


__all__ = [
    "LEASED_STATES",
    "DurableJobRepository",
    "DurableJobRuntime",
    "DurableJobWorker",
    "JobRecord",
    "register_durable_job_tools",
]
