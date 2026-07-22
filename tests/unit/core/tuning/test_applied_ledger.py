"""Unit tests for the applied-tuning ledger.

Covers ``benchbox.core.tuning.applied_ledger`` (TODO
``tuning-applied-ledger-and-validation-status-20260712`` / tuning-ADR-001): the
honest, execution-derived ``validation_status`` vocabulary, the physical-
identity ``applied_ledger_hash`` (determinism + order-sensitivity),
``record_dropped``, and the recording-connection proxy that captures exactly
what a connection actually executed.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    APPLIED_VERIFIED,
    EXECUTED,
    FAILED,
    NOOP,
    NOT_APPLICABLE,
    PHASE_DDL,
    PHASE_SESSION,
    STATEMENT_FAILED,
    AppliedTuningLedger,
    recording_connection,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Fakes: minimal connection surfaces the recording proxy wraps.
# ---------------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, sink: list[str], fail_on: str | None = None) -> None:
        self._sink = sink
        self._fail_on = fail_on

    def execute(self, statement, *args, **kwargs):
        if self._fail_on is not None and self._fail_on in str(statement):
            raise RuntimeError("boom")
        self._sink.append(str(statement))
        return f"cursor-result::{statement}"

    def close(self) -> None:  # pragma: no cover - transparency check
        return None


class _FakeConnection:
    """Records every statement it actually executes (via execute + cursor)."""

    def __init__(self, fail_on: str | None = None) -> None:
        self.executed: list[str] = []
        self._fail_on = fail_on

    def execute(self, statement, *args, **kwargs):
        if self._fail_on is not None and self._fail_on in str(statement):
            raise RuntimeError("boom")
        self.executed.append(str(statement))
        return f"result::{statement}"

    def cursor(self, *args, **kwargs):
        return _FakeCursor(self.executed, fail_on=self._fail_on)

    # A non-recorded passthrough attribute, to prove transparency.
    def rollback(self) -> str:
        return "rolled-back"


# ---------------------------------------------------------------------------
# Status derivation
# ---------------------------------------------------------------------------
class TestStatusDerivation:
    def test_not_applicable_when_tuning_disabled(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX x", PHASE_DDL)  # even with a statement
        assert ledger.overall_status(tuning_enabled=False, has_config=True) == NOT_APPLICABLE

    def test_not_applicable_when_no_config(self) -> None:
        ledger = AppliedTuningLedger()
        assert ledger.overall_status(tuning_enabled=True, has_config=False) == NOT_APPLICABLE

    def test_noop_when_enabled_but_nothing_executed(self) -> None:
        ledger = AppliedTuningLedger()
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == NOOP

    def test_applied_unverified_when_a_statement_executed(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX idx_lineitem_sort ON LINEITEM (l_orderkey)", PHASE_DDL)
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == APPLIED_UNVERIFIED

    def test_failed_when_every_statement_failed(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX bad", PHASE_DDL, status=STATEMENT_FAILED, error="nope")
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == FAILED

    def test_one_success_among_failures_is_applied_unverified(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX bad", PHASE_DDL, status=STATEMENT_FAILED, error="nope")
        ledger.record("CREATE INDEX good ON t (a)", PHASE_DDL)
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == APPLIED_UNVERIFIED

    def test_overall_status_never_returns_applied_verified(self) -> None:
        # applied_verified is RESERVED: it requires an introspection receipt from
        # a separate code path and must never be derived from the ledger alone.
        ledger = AppliedTuningLedger()
        ledger.record("SET a=1", PHASE_SESSION)
        assert ledger.overall_status(tuning_enabled=True, has_config=True) != APPLIED_VERIFIED

    def test_noop_platform_never_reports_applied(self) -> None:
        # A deliberately no-op apply path (base-class no-op adapter) executes
        # nothing on the wrapped connection, so status is noop, never applied.
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        _ = recording_connection(conn, ledger, PHASE_DDL)
        # ... apply path decides to run no statement at all.
        assert conn.executed == []
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == NOOP

    def test_metadata_persistence_failure_is_not_an_alarming_status(self) -> None:
        # tuning_metadata_saved (a persistence note) is NOT an input to the
        # status: a run whose statements executed stays applied_unverified even
        # if a later metadata INSERT failed. The ledger never yields "failed"
        # for a benign persistence problem.
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX idx ON t (a)", PHASE_DDL)
        status = ledger.overall_status(tuning_enabled=True, has_config=True)
        assert status == APPLIED_UNVERIFIED
        assert status != FAILED


# ---------------------------------------------------------------------------
# Hashing: determinism + order-sensitivity
# ---------------------------------------------------------------------------
class TestAppliedLedgerHash:
    def test_none_when_nothing_executed(self) -> None:
        assert AppliedTuningLedger().applied_ledger_hash() is None

    def test_none_when_only_failed_statements(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX bad", PHASE_DDL, status=STATEMENT_FAILED, error="nope")
        assert ledger.applied_ledger_hash() is None

    def test_deterministic_for_identical_executed_sequences(self) -> None:
        a = AppliedTuningLedger()
        b = AppliedTuningLedger()
        for statement in ("CREATE INDEX i1 ON t (a)", "CREATE INDEX i2 ON t (b)"):
            a.record(statement, PHASE_DDL)
            b.record(statement, PHASE_DDL)
        assert a.applied_ledger_hash() == b.applied_ledger_hash()
        assert a.applied_ledger_hash() is not None

    def test_order_sensitive(self) -> None:
        forward = AppliedTuningLedger()
        forward.record("CREATE INDEX i1 ON t (a)", PHASE_DDL)
        forward.record("CREATE INDEX i2 ON t (b)", PHASE_DDL)

        reverse = AppliedTuningLedger()
        reverse.record("CREATE INDEX i2 ON t (b)", PHASE_DDL)
        reverse.record("CREATE INDEX i1 ON t (a)", PHASE_DDL)

        assert forward.applied_ledger_hash() != reverse.applied_ledger_hash()

    def test_failed_statements_excluded_from_hash(self) -> None:
        # A trailing failed statement must not change the physical identity of
        # what actually applied.
        clean = AppliedTuningLedger()
        clean.record("CREATE INDEX i1 ON t (a)", PHASE_DDL)

        with_failure = AppliedTuningLedger()
        with_failure.record("CREATE INDEX i1 ON t (a)", PHASE_DDL)
        with_failure.record("CREATE INDEX bad", PHASE_DDL, status=STATEMENT_FAILED, error="nope")

        assert clean.applied_ledger_hash() == with_failure.applied_ledger_hash()


# ---------------------------------------------------------------------------
# Dropped intents
# ---------------------------------------------------------------------------
class TestDroppedIntents:
    def test_record_dropped_appears_in_payload(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record_dropped("partitioning:LINEITEM", "handled at data-loading time")
        payload = ledger.to_payload(status=NOOP)
        assert payload["dropped"] == [{"intent": "partitioning:LINEITEM", "reason": "handled at data-loading time"}]

    def test_dropped_intent_does_not_count_as_executed(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record_dropped("distribution:ORDERS", "single-node")
        # A dropped intent is not an executed statement -> still noop.
        assert ledger.overall_status(tuning_enabled=True, has_config=True) == NOOP
        assert ledger.applied_ledger_hash() is None

    def test_to_payload_shape(self) -> None:
        ledger = AppliedTuningLedger()
        ledger.record("CREATE INDEX i ON t (a)", PHASE_DDL, mechanism="index", table="t")
        payload = ledger.to_payload(status=APPLIED_UNVERIFIED)
        assert set(payload) == {"status", "applied_ledger_hash", "statements", "dropped"}
        assert payload["status"] == APPLIED_UNVERIFIED
        assert payload["applied_ledger_hash"] == ledger.applied_ledger_hash()
        assert payload["statements"][0]["mechanism"] == "index"
        assert payload["statements"][0]["table"] == "t"
        assert payload["statements"][0]["status"] == EXECUTED


# ---------------------------------------------------------------------------
# Recording-connection harness (the w5 harness): captured == actually executed.
# ---------------------------------------------------------------------------
class TestRecordingConnectionHarness:
    def test_captured_statements_match_what_the_connection_ran(self) -> None:
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        wrapped = recording_connection(conn, ledger, PHASE_DDL)

        statements = [
            "CREATE INDEX idx_lineitem_sort ON LINEITEM (l_orderkey)",
            "CREATE INDEX idx_orders_cluster ON ORDERS (o_custkey)",
        ]
        results = [wrapped.execute(sql) for sql in statements]

        # The real results are returned unchanged (control flow preserved).
        assert results == [f"result::{sql}" for sql in statements]
        # The ledger's captured statements EXACTLY match what the fake ran.
        assert conn.executed == statements
        assert [s.statement for s in ledger.executed_statements] == statements
        assert all(s.phase == PHASE_DDL and s.status == EXECUTED for s in ledger.executed_statements)

    def test_cursor_execute_is_captured(self) -> None:
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        wrapped = recording_connection(conn, ledger, PHASE_SESSION)

        cursor = wrapped.cursor()
        cursor.execute("SET query_timeout = 30")

        assert conn.executed == ["SET query_timeout = 30"]
        assert [s.statement for s in ledger.executed_statements] == ["SET query_timeout = 30"]
        assert ledger.statements[0].phase == PHASE_SESSION

    def test_failed_execute_is_recorded_then_reraised(self) -> None:
        ledger = AppliedTuningLedger()
        conn = _FakeConnection(fail_on="CREATE INDEX bad")
        wrapped = recording_connection(conn, ledger, PHASE_DDL)

        with pytest.raises(RuntimeError):
            wrapped.execute("CREATE INDEX bad ON t (a)")

        # The connection never appended it (it raised), but the ledger recorded
        # the attempt as failed -- capture happens around the real call.
        assert conn.executed == []
        assert len(ledger.statements) == 1
        assert ledger.statements[0].status == STATEMENT_FAILED
        assert ledger.statements[0].error is not None
        assert ledger.executed_statements == []

    def test_none_ledger_returns_raw_connection_unwrapped(self) -> None:
        conn = _FakeConnection()
        assert recording_connection(conn, None, PHASE_DDL) is conn

    def test_non_execute_attributes_delegate_transparently(self) -> None:
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        wrapped = recording_connection(conn, ledger, PHASE_DDL)
        # Passthrough method is delegated and does not touch the ledger.
        assert wrapped.rollback() == "rolled-back"
        assert ledger.is_empty()

    def test_readback_select_executes_but_is_not_recorded(self) -> None:
        # Adapters run verification readbacks through the same wrapped connection
        # (e.g. ClickHouse's validate_session_cache_control issues
        # `SELECT ... FROM system.settings` to confirm a SET took effect). Those
        # must still execute and return, but must NOT pollute the ledger/hash as
        # applied tuning.
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        wrapped = recording_connection(conn, ledger, PHASE_SESSION)

        result = wrapped.execute("SELECT name, value FROM system.settings WHERE name = 'x'")

        assert result.startswith("result::")  # really executed on the connection
        assert conn.executed == ["SELECT name, value FROM system.settings WHERE name = 'x'"]
        assert ledger.is_empty()  # but not recorded as applied tuning

    def test_only_mutating_statement_recorded_when_interleaved_with_readback(self) -> None:
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        wrapped = recording_connection(conn, ledger, PHASE_SESSION)

        wrapped.execute("SET max_threads = 8")
        wrapped.execute("SELECT value FROM system.settings WHERE name = 'max_threads'")

        # Both really ran on the connection...
        assert conn.executed == [
            "SET max_threads = 8",
            "SELECT value FROM system.settings WHERE name = 'max_threads'",
        ]
        # ...but only the SET is recorded as applied tuning.
        assert [s.statement for s in ledger.statements] == ["SET max_threads = 8"]

    def test_cursor_readback_is_not_recorded(self) -> None:
        ledger = AppliedTuningLedger()
        conn = _FakeConnection()
        cursor = recording_connection(conn, ledger, PHASE_SESSION).cursor()

        cursor.execute("SHOW VARIABLES LIKE 'max_threads'")

        assert conn.executed == ["SHOW VARIABLES LIKE 'max_threads'"]
        assert ledger.is_empty()
