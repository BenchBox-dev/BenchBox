"""Applied-tuning ledger: what the execution path actually ran.

Per tuning-ADR-001 (``docs/development/tuning-adr-001-trust-and-hash-semantics.md``)
and TODO ``tuning-applied-ledger-and-validation-status-20260712``.

Today the bundle records *intent as fact*: ``tunings_applied`` is the requested
config's ``to_dict()`` and ``validation_status="APPLIED"`` certifies only that a
metadata-table INSERT succeeded. This module records what the adapter *actually
executed* -- each tuning-relevant statement (DDL clauses, post-load statements,
session SETs) appended as it runs -- and derives an honest ``validation_status``
from that observation.

Two invariants (must-preserve from the TODO):

* **Produced by the execution path, never reconstructed from config.** The
  ledger is populated as statements execute; there is no path that rebuilds it
  from the requested ``UnifiedTuningConfiguration``.
* **Capture never breaks a run.** Every record/derive call degrades to a no-op
  on error (the degradation is logged, the benchmark continues).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# validation_status vocabulary (ADR-001, honest semantics)
#
# Execution-derived, all-lowercase. Replaces the metadata-write proxy where
# "APPLIED" meant only "a metadata INSERT succeeded". Documented mapping:
#
#   not_applicable      tuning disabled, or no effective configuration
#   noop                tuning requested but the execution path ran no
#                       statement (deliberate base no-op adapter, or a config
#                       that renders to nothing on this platform)
#   applied_unverified  >= 1 tuning statement executed successfully;
#                       self-attested, NOT yet corroborated by introspection
#   applied_verified    executed AND corroborated by a post-load
#                       schema-introspection receipt. RESERVED: only
#                       tuning-introspection-receipts-20260716 may emit it,
#                       via corroboration -- never the ledger alone.
#   failed              tuning was attempted but every statement failed / the
#                       apply path raised
#
# Metadata-persistence failure is NO LONGER a tuning status: the old
# FAILED_TO_SAVE is downgraded to the separate ``tuning_metadata_saved`` flag,
# a non-alarming persistence note (benign for read-only / in-memory runs).
NOT_APPLICABLE = "not_applicable"
NOOP = "noop"
APPLIED_UNVERIFIED = "applied_unverified"
APPLIED_VERIFIED = "applied_verified"
FAILED = "failed"

# BenchmarkResults dataclass default (pre-run, before any derivation).
NOT_VALIDATED = "not_validated"

#: The full reviewed vocabulary. Pinned by
#: ``tests/unit/core/tuning/test_validation_status_vocabulary.py`` -- adding or
#: renaming a status must be a conscious edit there.
TUNING_STATUS_VOCABULARY = frozenset(
    {
        NOT_APPLICABLE,
        NOOP,
        APPLIED_UNVERIFIED,
        APPLIED_VERIFIED,
        FAILED,
        NOT_VALIDATED,
    }
)

#: Legacy (pre-ledger) -> new status, for bundle back-compat readers. Note the
#: metadata-write proxy collapses: both old "APPLIED" and old "FAILED_TO_SAVE"
#: mean "a statement was executed" under the new model, so both map to
#: ``applied_unverified`` (the metadata outcome moves to ``tuning_metadata_saved``).
LEGACY_STATUS_MAP = {
    "NOT_APPLICABLE": NOT_APPLICABLE,
    "APPLIED": APPLIED_UNVERIFIED,
    "FAILED_TO_SAVE": APPLIED_UNVERIFIED,
    "NOT_VALIDATED": NOT_VALIDATED,
}

# Statement outcome tokens.
EXECUTED = "executed"
STATEMENT_FAILED = "failed"

# Statement phases (ordered chronology in the run).
PHASE_DDL = "ddl"
PHASE_POST_LOAD = "post_load"
PHASE_SESSION = "session"

# Read-only statement prefixes the recorder must NOT log: adapters run readbacks
# through the same wrapped connection (e.g. ClickHouse's
# validate_session_cache_control issues `SELECT ... FROM system.settings` to
# confirm a SET took effect). Those are verification queries, not applied
# tuning, so recording them would pollute the ledger and the physical hash.
# Conservative allowlist-by-exclusion: only skip unambiguous readbacks. NOTE
# `PRAGMA` is deliberately absent -- DuckDB tuning uses `PRAGMA threads=4` etc.,
# which ARE applied statements.
_READBACK_PREFIXES = ("select", "show", "describe", "desc ", "explain", "values ")


def _is_recordable_statement(statement: Any) -> bool:
    """Whether *statement* is an applied tuning statement worth recording.

    Returns ``False`` for read-only verification queries (SELECT/SHOW/...), which
    adapters issue through the same connection to confirm applied settings.
    Defaults to ``True`` on any uncertainty so a real tuning statement is never
    silently dropped.
    """
    try:
        text = str(statement).lstrip().lstrip("(").lstrip().lower()
    except Exception:  # pragma: no cover - defensive; never drop on uncertainty
        return True
    return not text.startswith(_READBACK_PREFIXES)


@dataclass
class AppliedStatement:
    """One tuning-relevant statement the adapter actually executed."""

    statement: str
    phase: str
    status: str = EXECUTED  # EXECUTED | STATEMENT_FAILED
    mechanism: str | None = None
    table: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "statement": self.statement,
            "phase": self.phase,
            "status": self.status,
        }
        if self.mechanism:
            payload["mechanism"] = self.mechanism
        if self.table:
            payload["table"] = self.table
        if self.error:
            payload["error"] = self.error
        return payload


@dataclass
class DroppedIntent:
    """A requested tuning intent that was NOT rendered to a statement.

    Capability-filtered, unmapped, or log-only intents (review finding R4): the
    ledger knows what was requested but not executed, so we surface it rather
    than silently dropping it.
    """

    intent: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"intent": self.intent, "reason": self.reason}


@dataclass
class AppliedTuningLedger:
    """Ordered record of executed tuning statements + dropped intents.

    Mutated in place by the execution path via :meth:`record` /
    :meth:`record_dropped`; read back once at result-construction time for the
    honest status, the applied-ledger hash, and the bundle companion.
    """

    statements: list[AppliedStatement] = field(default_factory=list)
    dropped: list[DroppedIntent] = field(default_factory=list)

    # -- population (execution path) ---------------------------------------
    def record(
        self,
        statement: str,
        phase: str,
        *,
        status: str = EXECUTED,
        mechanism: str | None = None,
        table: str | None = None,
        error: Any | None = None,
    ) -> None:
        """Append one executed/failed statement. Never raises."""
        try:
            self.statements.append(
                AppliedStatement(
                    statement=str(statement),
                    phase=phase,
                    status=status,
                    mechanism=mechanism,
                    table=table,
                    error=(str(error) if error is not None else None),
                )
            )
        except Exception as exc:  # capture must never break a run
            logger.debug("applied-ledger record degraded: %s", exc)

    def record_dropped(self, intent: str, reason: str) -> None:
        """Append one requested-but-not-rendered intent. Never raises."""
        try:
            self.dropped.append(DroppedIntent(intent=str(intent), reason=str(reason)))
        except Exception as exc:
            logger.debug("applied-ledger dropped-record degraded: %s", exc)

    # -- read back (result construction) -----------------------------------
    @property
    def executed_statements(self) -> list[AppliedStatement]:
        return [s for s in self.statements if s.status == EXECUTED]

    def overall_status(self, *, tuning_enabled: bool, has_config: bool) -> str:
        """Derive the honest ``validation_status`` from what actually ran.

        Note this never returns ``applied_verified`` -- verification requires a
        corroborating introspection receipt supplied by a separate code path
        (tuning-introspection-receipts-20260716), never the ledger alone.
        """
        if not tuning_enabled or not has_config:
            return NOT_APPLICABLE
        if any(s.status == EXECUTED for s in self.statements):
            return APPLIED_UNVERIFIED
        if self.statements:  # statements attempted, all failed
            return FAILED
        return NOOP

    def applied_ledger_hash(self) -> str | None:
        """SHA-256 over the ORDERED executed statements (physical identity).

        Mirrors ``UnifiedTuningConfiguration.get_configuration_hash`` canonical
        form (``sort_keys`` + compact separators), but over an ordered *list*:
        list order is preserved (``sort_keys`` only orders each record's keys),
        so statement chronology is part of the identity. ``None`` when nothing
        executed (there is no physical layout to identify).
        """
        executed = [s.to_dict() for s in self.executed_statements]
        if not executed:
            return None
        payload = json.dumps(executed, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_payload(
        self,
        *,
        status: str,
        receipt: dict[str, Any] | None = None,
        drift_check: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The ``.applied.json`` companion payload.

        ``receipt`` (when supplied) is the post-load introspection receipt
        (``benchbox.core.tuning.introspection.IntrospectionReceipt.to_payload``)
        that corroborated the ledger against the live catalog. It rides inside
        this companion rather than in a separate file. A ``receipt`` is present
        only when the run status was ``applied_unverified`` and introspection was
        attempted; the ``applied_verified`` status it may carry is derived solely
        from that receipt's corroboration, never from the ledger alone.

        ``drift_check`` (when supplied) is the rerun tuning drift-validation
        result (``MetadataValidationResult.to_payload``) computed when a reused
        database's persisted tuning metadata is validated against the expected
        configuration. It rides in this same companion per the ADR-001 addendum
        (drift-validation bundle routing); it is descriptive, never a source of
        ``applied_verified``.
        """
        payload: dict[str, Any] = {
            "status": status,
            "applied_ledger_hash": self.applied_ledger_hash(),
            "statements": [s.to_dict() for s in self.statements],
            "dropped": [d.to_dict() for d in self.dropped],
        }
        if receipt is not None:
            payload["receipt"] = receipt
        if drift_check is not None:
            payload["drift_check"] = drift_check
        return payload

    def is_empty(self) -> bool:
        return not self.statements and not self.dropped


class RecordingConnection:
    """Transparent proxy that records executed statements into a ledger.

    Wraps a real DB connection: ``execute`` and ``cursor().execute`` are
    recorded (SQL text + phase + executed/failed), everything else delegates
    unchanged. Wrapping never changes control flow -- the real result is
    returned and exceptions re-raise after being recorded, so an adapter's own
    try/except around a statement behaves exactly as before.

    Only ever wraps the connection handed to the tuning-apply /
    session-configuration path, so it sees only tuning-relevant statements.
    """

    __slots__ = ("_conn", "_ledger", "_phase")

    def __init__(self, connection: Any, ledger: AppliedTuningLedger, phase: str) -> None:
        object.__setattr__(self, "_conn", connection)
        object.__setattr__(self, "_ledger", ledger)
        object.__setattr__(self, "_phase", phase)

    # -- recorded surface ---------------------------------------------------
    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        return self._run(self._conn.execute, statement, args, kwargs)

    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        return _RecordingCursor(self._conn.cursor(*args, **kwargs), self._ledger, self._phase)

    def _run(self, fn: Any, statement: Any, args: tuple, kwargs: dict) -> Any:
        record = _is_recordable_statement(statement)
        try:
            result = fn(statement, *args, **kwargs)
        except Exception as exc:
            if record:
                self._ledger.record(statement, self._phase, status=STATEMENT_FAILED, error=exc)
            raise
        if record:
            self._ledger.record(statement, self._phase, status=EXECUTED)
        return result

    # -- transparency -------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._conn, name, value)

    def __enter__(self) -> Any:
        self._conn.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        return self._conn.__exit__(*exc_info)

    @property
    def raw_connection(self) -> Any:
        """The underlying real connection (for callers that need the C object)."""
        return self._conn


class _RecordingCursor:
    """Cursor proxy mirroring :class:`RecordingConnection` for ``cursor.execute``."""

    __slots__ = ("_cur", "_ledger", "_phase")

    def __init__(self, cursor: Any, ledger: AppliedTuningLedger, phase: str) -> None:
        object.__setattr__(self, "_cur", cursor)
        object.__setattr__(self, "_ledger", ledger)
        object.__setattr__(self, "_phase", phase)

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> Any:
        record = _is_recordable_statement(statement)
        try:
            result = self._cur.execute(statement, *args, **kwargs)
        except Exception as exc:
            if record:
                self._ledger.record(statement, self._phase, status=STATEMENT_FAILED, error=exc)
            raise
        if record:
            self._ledger.record(statement, self._phase, status=EXECUTED)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cur, name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._cur, name, value)

    def __iter__(self) -> Any:
        return iter(self._cur)

    def __enter__(self) -> Any:
        self._cur.__enter__()
        return self

    def __exit__(self, *exc_info: Any) -> Any:
        return self._cur.__exit__(*exc_info)


def recording_connection(connection: Any, ledger: AppliedTuningLedger | None, phase: str) -> Any:
    """Wrap *connection* for capture, degrading to the raw connection on error.

    Returns the unwrapped connection when *ledger* is ``None`` or wrapping is
    not possible, so a capture failure can never break statement execution.
    """
    if ledger is None:
        return connection
    try:
        return RecordingConnection(connection, ledger, phase)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("applied-ledger connection wrap degraded: %s", exc)
        return connection
