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
    PHASE_DDL,
    PHASE_SESSION,
    AppliedTuningLedger,
)
from benchbox.core.tuning.introspection import KIND_PARTITION_KEY, KIND_SORT_KEY, corroborate
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
        # Documented limitation: ClickHouse's key DDL runs outside the ledger, so
        # the ledger's OPTIMIZE (maintenance) + SET (transient) statements are
        # non-blocking and there is nothing catalog-backed to earn verification.
        # The observed keys still surface in the receipt as evidence.
        rows = [("lineitem", "l_orderkey, l_linenumber", "")]
        ledger = _optimize_ledger()
        receipt = corroborate(ledger, ClickHouseTuningIntrospector().introspect(_FakeCHConnection(rows), ledger))
        assert receipt.corroborated is False
        assert receipt.summary["verifiable_total"] == 0
        assert any(o.kind == KIND_SORT_KEY for o in receipt.observed)
