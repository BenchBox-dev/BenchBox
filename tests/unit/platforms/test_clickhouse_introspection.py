"""Tests for the ClickHouse post-load introspector.

Uses a fake connection returning ``system.tables`` rows (no live ClickHouse):
the introspector reports ``sorting_key`` / ``partition_key`` as structured
facts, bounded to the ledger's tables and non-fatal on failure. TODO
``tuning-introspection-receipts-20260716``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tuning.applied_ledger import (
    APPLIED_UNVERIFIED,
    APPLIED_VERIFIED,
    PHASE_DDL,
    PHASE_SESSION,
    AppliedTuningLedger,
)
from benchbox.core.tuning.interface import TableTuning, TuningColumn, UnifiedTuningConfiguration
from benchbox.core.tuning.introspection import KIND_PARTITION_KEY, KIND_SORT_KEY, corroborate
from benchbox.platforms.clickhouse.adapter import ClickHouseAdapter
from benchbox.platforms.clickhouse.introspection import ClickHouseTuningIntrospector

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class _FakeCHConnection:
    """Returns canned ``system.tables`` rows; records the query it received."""

    def __init__(self, rows, fail: bool = False):
        self._rows = rows
        self._fail = fail
        self.queries: list[str] = []

    def execute(self, query, *args, **kwargs):
        self.queries.append(str(query))
        if self._fail:
            raise RuntimeError("system.tables unavailable")
        return self._rows


def _optimize_ledger() -> AppliedTuningLedger:
    # A realistic ClickHouse tuning ledger: OPTIMIZE (maintenance) + session SETs.
    ledger = AppliedTuningLedger()
    ledger.record("OPTIMIZE TABLE lineitem", PHASE_DDL)
    ledger.record("SET max_threads = 4", PHASE_SESSION)
    return ledger


class TestClickHouseIntrospector:
    def test_reports_sort_and_partition_keys(self):
        rows = [("lineitem", "l_orderkey, l_linenumber", "toYYYYMM(l_shipdate)")]
        state = ClickHouseTuningIntrospector().introspect(_FakeCHConnection(rows), _optimize_ledger())
        assert state.error is None
        kinds = {obj.kind: obj for obj in state.objects}
        assert kinds[KIND_SORT_KEY].columns == ("l_orderkey", "l_linenumber")
        assert kinds[KIND_PARTITION_KEY].table == "lineitem"

    def test_query_uses_structured_catalog_not_show_create(self):
        conn = _FakeCHConnection([("lineitem", "l_orderkey", "")])
        ClickHouseTuningIntrospector().introspect(conn, _optimize_ledger())
        assert conn.queries, "introspector must issue a catalog query"
        q = conn.queries[0].lower()
        assert "system.tables" in q and "show create" not in q

    def test_bounded_to_ledger_tables(self):
        rows = [
            ("lineitem", "l_orderkey", ""),
            ("nation", "n_nationkey", ""),  # not in ledger
        ]
        state = ClickHouseTuningIntrospector().introspect(_FakeCHConnection(rows), _optimize_ledger())
        tables = {obj.table for obj in state.objects}
        assert tables == {"lineitem"}

    def test_non_fatal_on_query_failure(self):
        state = ClickHouseTuningIntrospector().introspect(_FakeCHConnection([], fail=True), _optimize_ledger())
        assert state.error is not None
        assert state.objects == []

    def test_optimize_ledger_reports_keys_but_stays_unverified(self):
        # A ClickHouse ledger carrying only OPTIMIZE (maintenance) + SET
        # (transient) statements is non-blocking and has nothing catalog-backed
        # to earn verification. The observed keys still surface as evidence.
        # (The tuned sort key IS folded into the ledger separately -- see
        # TestTunedSortKeyFold below.)
        rows = [("lineitem", "l_orderkey, l_linenumber", "")]
        ledger = _optimize_ledger()
        receipt = corroborate(ledger, ClickHouseTuningIntrospector().introspect(_FakeCHConnection(rows), ledger))
        assert receipt.corroborated is False
        assert receipt.summary["verifiable_total"] == 0
        assert any(o.kind == KIND_SORT_KEY for o in receipt.observed)


def _sorted_tuning_config() -> UnifiedTuningConfiguration:
    config = UnifiedTuningConfiguration()
    config.table_tunings["LINEITEM"] = TableTuning(
        table_name="LINEITEM",
        sorting=[
            TuningColumn(name="l_orderkey", type="INTEGER", order=1),
            TuningColumn(name="l_linenumber", type="INTEGER", order=2),
        ],
    )
    return config


class TestTunedSortKeyFold:
    """The tuned MergeTree ORDER BY is folded into the applied ledger so it can
    corroborate against ``system.tables.sorting_key`` and earn verification.
    """

    def _tuned_adapter(self) -> ClickHouseAdapter:
        adapter = ClickHouseAdapter()
        adapter.tuning_enabled = True
        adapter._applied_tuning_ledger = AppliedTuningLedger()
        adapter._applied_layout_operations = []
        return adapter

    def test_tuned_order_by_records_sort_key_op(self):
        adapter = self._tuned_adapter()
        tunings = _sorted_tuning_config().table_tunings
        original = "CREATE TABLE lineitem (l_orderkey INTEGER, l_linenumber INTEGER, l_comment VARCHAR)"
        optimized = adapter._optimize_table_definition(original, tunings, nullable_columns=set())
        assert "ORDER BY (l_orderkey, l_linenumber)" in optimized

        adapter._record_tuned_sort_key_op(original, optimized, "lineitem", tunings)
        ops = [op for op in adapter._applied_layout_operations if op["mechanism"] == "sort_key"]
        assert len(ops) == 1
        assert ops[0]["phase"] == PHASE_DDL and ops[0]["table"] == "lineitem"

    def test_full_flow_reaches_applied_verified(self):
        adapter = self._tuned_adapter()
        tunings = _sorted_tuning_config().table_tunings
        original = "CREATE TABLE lineitem (l_orderkey INTEGER, l_linenumber INTEGER, l_comment VARCHAR)"
        optimized = adapter._optimize_table_definition(original, tunings, nullable_columns=set())
        adapter._record_tuned_sort_key_op(original, optimized, "lineitem", tunings)
        adapter._fold_layout_operations_into_ledger()

        conn = _FakeCHConnection([("lineitem", "l_orderkey, l_linenumber", "")])
        status, receipt = adapter._corroborate_applied_ledger(conn, APPLIED_UNVERIFIED)
        assert status == APPLIED_VERIFIED
        assert receipt["corroborated"] is True

    def test_baseline_order_by_not_recorded(self):
        # An untuned table (not in the tuning config) gets only the
        # engine-mandatory baseline ORDER BY, which is NOT tuning -> not recorded.
        adapter = self._tuned_adapter()
        tunings = _sorted_tuning_config().table_tunings
        original = "CREATE TABLE nation (n_nationkey INTEGER PRIMARY KEY, n_name VARCHAR)"
        optimized = adapter._optimize_table_definition(original, tunings, nullable_columns=set())
        adapter._record_tuned_sort_key_op(original, optimized, "nation", tunings)
        assert not [op for op in adapter._applied_layout_operations if op["mechanism"] == "sort_key"]

    def test_no_record_when_tuning_disabled(self):
        adapter = self._tuned_adapter()
        adapter.tuning_enabled = False
        tunings = _sorted_tuning_config().table_tunings
        original = "CREATE TABLE lineitem (l_orderkey INTEGER, l_linenumber INTEGER)"
        adapter._record_tuned_sort_key_op(original, original, "lineitem", tunings)
        assert adapter._applied_layout_operations == []
