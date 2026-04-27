"""Unit tests for CoffeeShop ClickHouse dialect overrides.

Verifies that:
- SA4 replaces the nested window aggregate SUM(SUM()) OVER () with a CROSS JOIN subquery
- TM1 replaces EXTRACT(HOUR FROM order_time) with toHour(toDateTime(order_time))
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _bench():
    from benchbox.core.coffeeshop.benchmark import CoffeeShopBenchmark

    return CoffeeShopBenchmark()


# ---------------------------------------------------------------------------
# SA4: nested window aggregate → CROSS JOIN subquery
# ---------------------------------------------------------------------------


def test_sa4_clickhouse_avoids_nested_window_aggregate():
    """SA4 for ClickHouse must not use SUM(SUM()) OVER () - not supported in ClickHouse."""
    q = _bench().get_queries(dialect="clickhouse")["SA4"]
    assert "SUM(SUM(" not in q, f"Must not use nested window aggregate in ClickHouse SA4:\n{q}"


def test_sa4_clickhouse_preserves_revenue_share_column():
    """SA4 ClickHouse override must still produce a revenue_share column."""
    q = _bench().get_queries(dialect="clickhouse")["SA4"]
    assert "revenue_share" in q, f"SA4 ClickHouse must compute revenue_share:\n{q}"


def test_sa4_base_dialect_retains_window_aggregate():
    """Base SA4 must use the standard SUM(SUM()) OVER () pattern."""
    q = _bench().get_queries()["SA4"]
    assert "SUM(SUM(" in q, f"Base SA4 must use nested window aggregate:\n{q}"


# ---------------------------------------------------------------------------
# TM1: EXTRACT(HOUR FROM TIME) → toHour(toDateTime(...))
# ---------------------------------------------------------------------------


def test_tm1_clickhouse_uses_todatetime_wrapper():
    """TM1 for ClickHouse must wrap order_time in toDateTime() before toHour()."""
    q = _bench().get_queries(dialect="clickhouse")["TM1"]
    assert "toDateTime(" in q, f"TM1 must wrap order_time in toDateTime() for ClickHouse:\n{q}"
    assert "toHour(" in q, f"TM1 must use toHour() for ClickHouse:\n{q}"
    assert "EXTRACT" not in q.upper(), f"TM1 must not use EXTRACT for ClickHouse:\n{q}"


def test_tm1_clickhouse_preserves_day_part_categories():
    """TM1 ClickHouse override must retain Morning/Midday/Afternoon/Evening categories."""
    q = _bench().get_queries(dialect="clickhouse")["TM1"]
    for category in ("Morning", "Midday", "Afternoon", "Evening"):
        assert category in q, f"TM1 must include '{category}' day-part category:\n{q}"


def test_tm1_base_dialect_retains_extract():
    """Base TM1 must use EXTRACT(HOUR FROM order_time)."""
    q = _bench().get_queries()["TM1"]
    assert "EXTRACT" in q.upper(), f"Base TM1 must use EXTRACT(HOUR …):\n{q}"


# ---------------------------------------------------------------------------
# Other queries unaffected
# ---------------------------------------------------------------------------


def test_non_overridden_queries_present_in_clickhouse_dialect():
    """ClickHouse dialect must not drop or empty any non-overridden queries."""
    bench = _bench()
    base = bench.get_queries()
    clickhouse = bench.get_queries(dialect="clickhouse")

    for qid in base:
        if qid not in ("SA4", "TM1"):
            assert qid in clickhouse, f"{qid} missing from ClickHouse queries"
            assert clickhouse[qid].strip(), f"{qid} is empty in ClickHouse queries"
