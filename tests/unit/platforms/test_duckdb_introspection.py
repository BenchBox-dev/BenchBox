"""Tests for the DuckDB post-load introspector + the adapter upgrade wiring.

Exercises the REAL corroboration path against a live in-memory DuckDB catalog
(``duckdb_indexes()``): a corroborated tuned run reaches ``applied_verified``
with a receipt, an induced index-column mismatch downgrades to
``applied_unverified`` with a diff, and an introspection failure stays
``applied_unverified``. TODO ``tuning-introspection-receipts-20260716``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import duckdb
import pytest

from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    APPLIED_VERIFIED,
    PHASE_DDL,
    AppliedTuningLedger,
    recording_connection,
)
from benchbox.core.tuning.introspection import ABSENT, CORROBORATED, KIND_INDEX, corroborate
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.platforms.duckdb_introspection import DuckDBTuningIntrospector

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _con_with_indexes() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE LINEITEM(L_ORDERKEY INTEGER, L_LINENUMBER INTEGER, L_COMMENT VARCHAR)")
    con.execute("CREATE TABLE ORDERS(O_ORDERKEY INTEGER, O_CUSTKEY INTEGER)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_orders_sort ON ORDERS (O_ORDERKEY, O_CUSTKEY)")
    return con


def _ledger_for(*statements: str) -> AppliedTuningLedger:
    ledger = AppliedTuningLedger()
    for stmt in statements:
        ledger.record(stmt, PHASE_DDL)
    return ledger


# ---------------------------------------------------------------------------
# Introspector: real duckdb_indexes() reads.
# ---------------------------------------------------------------------------
class TestDuckDBIntrospector:
    def test_reads_indexes_as_structured_facts(self):
        con = _con_with_indexes()
        ledger = _ledger_for(
            "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)",
            "CREATE INDEX IF NOT EXISTS idx_orders_sort ON ORDERS (O_ORDERKEY, O_CUSTKEY)",
        )
        state = DuckDBTuningIntrospector().introspect(con, ledger)
        assert state.error is None
        by_table = {obj.table.lower(): obj for obj in state.objects if obj.kind == KIND_INDEX}
        assert by_table["lineitem"].columns == ("l_orderkey", "l_linenumber")
        assert by_table["orders"].columns == ("o_orderkey", "o_custkey")

    def test_bounded_to_ledger_tables(self):
        con = _con_with_indexes()
        con.execute("CREATE TABLE PART(P_PARTKEY INTEGER)")
        con.execute("CREATE INDEX idx_part_sort ON PART (P_PARTKEY)")
        # Ledger only touched LINEITEM -> PART's index is not surfaced.
        ledger = _ledger_for("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)")
        state = DuckDBTuningIntrospector().introspect(con, ledger)
        tables = {obj.table.lower() for obj in state.objects}
        assert "part" not in tables and "lineitem" in tables

    def test_non_fatal_on_bad_connection(self):
        class _Boom:
            def execute(self, *_a, **_k):
                raise RuntimeError("catalog exploded")

        state = DuckDBTuningIntrospector().introspect(_Boom(), _ledger_for("CREATE INDEX i ON T (a)"))
        assert state.error is not None
        assert state.objects == []


# ---------------------------------------------------------------------------
# End-to-end corroboration against the real catalog.
# ---------------------------------------------------------------------------
class TestCorroborateAgainstRealCatalog:
    def test_persisted_indexes_corroborate(self):
        con = _con_with_indexes()
        ledger = _ledger_for(
            "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)",
            "CREATE INDEX IF NOT EXISTS idx_orders_sort ON ORDERS (O_ORDERKEY, O_CUSTKEY)",
        )
        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(con, ledger))
        assert receipt.corroborated is True
        assert all(e.verdict == CORROBORATED for e in receipt.entries)

    def test_recording_connection_populates_then_corroborates(self):
        # Populate the ledger EXACTLY as apply_unified_tuning does (through the
        # recording connection), then corroborate against the same live catalog.
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE LINEITEM(L_ORDERKEY INTEGER, L_LINENUMBER INTEGER)")
        ledger = AppliedTuningLedger()
        rec = recording_connection(con, ledger, PHASE_DDL)
        rec.execute("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)")
        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(con, ledger))
        assert receipt.corroborated is True

    def test_induced_mismatch_downgrades_with_diff(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE LINEITEM(L_ORDERKEY INTEGER, L_LINENUMBER INTEGER)")
        con.execute("CREATE INDEX idx_lineitem_sort ON LINEITEM (L_ORDERKEY)")  # only (a)
        ledger = _ledger_for("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)")
        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(con, ledger))
        assert receipt.corroborated is False
        assert receipt.entries[0].diff is not None

    def test_dropped_index_is_absent(self):
        # An index the ledger recorded but that no longer exists (mirrors the
        # CTAS-sorted-ingestion drop of DuckDB's sort index) -> absent.
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE LINEITEM(L_ORDERKEY INTEGER, L_LINENUMBER INTEGER)")
        ledger = _ledger_for("CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)")
        receipt = corroborate(ledger, DuckDBTuningIntrospector().introspect(con, ledger))
        assert receipt.corroborated is False
        assert receipt.entries[0].verdict == ABSENT


# ---------------------------------------------------------------------------
# Adapter wiring: _corroborate_applied_ledger is the SOLE emitter of verified.
# ---------------------------------------------------------------------------
class TestAdapterUpgradeWiring:
    def test_adapter_upgrades_to_verified_only_via_corroboration(self):
        con = _con_with_indexes()
        adapter = DuckDBAdapter()
        adapter._applied_tuning_ledger = _ledger_for(
            "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)",
            "CREATE INDEX IF NOT EXISTS idx_orders_sort ON ORDERS (O_ORDERKEY, O_CUSTKEY)",
        )
        status, receipt = adapter._corroborate_applied_ledger(con, APPLIED_UNVERIFIED)
        assert status == APPLIED_VERIFIED
        assert receipt["corroborated"] is True
        assert receipt["summary"]["corroborated"] == 2

    def test_adapter_stays_unverified_on_mismatch(self):
        con = duckdb.connect(":memory:")
        con.execute("CREATE TABLE LINEITEM(L_ORDERKEY INTEGER, L_LINENUMBER INTEGER)")
        con.execute("CREATE INDEX idx_lineitem_sort ON LINEITEM (L_ORDERKEY)")
        adapter = DuckDBAdapter()
        adapter._applied_tuning_ledger = _ledger_for(
            "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)"
        )
        status, receipt = adapter._corroborate_applied_ledger(con, APPLIED_UNVERIFIED)
        assert status == APPLIED_UNVERIFIED
        assert receipt["corroborated"] is False

    def test_adapter_non_unverified_status_is_untouched(self):
        # noop/failed/not_applicable never get an introspection attempt.
        con = _con_with_indexes()
        adapter = DuckDBAdapter()
        adapter._applied_tuning_ledger = _ledger_for(
            "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)"
        )
        status, receipt = adapter._corroborate_applied_ledger(con, "noop")
        assert status == "noop"
        assert receipt is None

    def test_adapter_introspection_failure_stays_unverified(self):
        class _Boom:
            def execute(self, *_a, **_k):
                raise RuntimeError("boom")

        adapter = DuckDBAdapter()
        adapter._applied_tuning_ledger = _ledger_for(
            "CREATE INDEX IF NOT EXISTS idx_lineitem_sort ON LINEITEM (L_ORDERKEY, L_LINENUMBER)"
        )
        status, receipt = adapter._corroborate_applied_ledger(_Boom(), APPLIED_UNVERIFIED)
        assert status == APPLIED_UNVERIFIED
        # Receipt is produced and records the degradation reason.
        assert receipt is not None and receipt["corroborated"] is False

    def test_duckdb_adapter_exposes_introspector(self):
        assert isinstance(DuckDBAdapter().get_tuning_introspector(), DuckDBTuningIntrospector)
