"""Unit tests for TPC-DI ClickHouse dialect overrides.

Verifies that:
- AQ6 replaces the nested window aggregate SUM(SUM()) OVER () with a CROSS JOIN total
- AQ7, AQ8, AQ10 replace JULIANDAY() with dateDiff() and DATE('now') with today()
- EQ7 replaces FROM (VALUES (0)) with FROM (SELECT 0)
- EQ3 flattens the spurious double-nested COUNT scalar subquery
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _bench():
    from benchbox.core.tpcdi.benchmark import TPCDIBenchmark

    return TPCDIBenchmark()


# ---------------------------------------------------------------------------
# AQ6: nested window aggregate → CROSS JOIN subquery
# ---------------------------------------------------------------------------


def test_aq6_clickhouse_avoids_nested_window_aggregate():
    """AQ6 for ClickHouse must not use SUM(SUM()) OVER () - not supported in ClickHouse."""
    q = _bench().get_queries(dialect="clickhouse")["AQ6"]
    assert "SUM(SUM(" not in q, f"Must not use nested window aggregate in ClickHouse AQ6:\n{q}"


def test_aq6_clickhouse_uses_cross_join_total():
    """AQ6 ClickHouse override must compute grand total via CROSS JOIN."""
    q = _bench().get_queries(dialect="clickhouse")["AQ6"]
    assert "grand_totals" in q, f"AQ6 must use CROSS JOIN grand_totals subquery:\n{q}"
    assert "sector_market_share_pct" in q, f"AQ6 must compute sector_market_share_pct:\n{q}"


def test_aq6_base_dialect_retains_window_aggregate():
    """Base AQ6 must use the standard SUM(SUM()) OVER () pattern."""
    q = _bench().get_queries()["AQ6"]
    assert "SUM(SUM(" in q, f"Base AQ6 must use nested window aggregate:\n{q}"


# ---------------------------------------------------------------------------
# AQ7 / AQ8 / AQ10: JULIANDAY → dateDiff, DATE('now') → today()
# ---------------------------------------------------------------------------


def test_aq7_clickhouse_replaces_julianday_with_datediff():
    """AQ7 for ClickHouse must not use JULIANDAY() - replace with dateDiff()."""
    q = _bench().get_queries(dialect="clickhouse")["AQ7"]
    assert "JULIANDAY" not in q.upper(), f"AQ7 must not use JULIANDAY for ClickHouse:\n{q}"
    assert "dateDiff(" in q, f"AQ7 must use dateDiff() for ClickHouse:\n{q}"
    assert "today()" in q, f"AQ7 must use today() instead of DATE('now') for ClickHouse:\n{q}"


def test_aq7_base_dialect_retains_julianday():
    """Base AQ7 must use JULIANDAY() (SQLite)."""
    q = _bench().get_queries()["AQ7"]
    assert "JULIANDAY" in q.upper(), f"Base AQ7 must use JULIANDAY:\n{q}"


def test_aq8_clickhouse_replaces_julianday():
    """AQ8 for ClickHouse must not use JULIANDAY()."""
    q = _bench().get_queries(dialect="clickhouse")["AQ8"]
    assert "JULIANDAY" not in q.upper(), f"AQ8 must not use JULIANDAY for ClickHouse:\n{q}"
    assert "dateDiff(" in q, f"AQ8 must use dateDiff() for ClickHouse:\n{q}"


def test_aq10_clickhouse_replaces_julianday():
    """AQ10 for ClickHouse must not use JULIANDAY()."""
    q = _bench().get_queries(dialect="clickhouse")["AQ10"]
    assert "JULIANDAY" not in q.upper(), f"AQ10 must not use JULIANDAY for ClickHouse:\n{q}"
    assert "dateDiff(" in q, f"AQ10 must use dateDiff() for ClickHouse:\n{q}"


# ---------------------------------------------------------------------------
# EQ7: VALUES (0) → SELECT 0
# ---------------------------------------------------------------------------


def test_eq7_clickhouse_replaces_values_dummy():
    """EQ7 for ClickHouse must replace FROM (VALUES (0)) with FROM (SELECT 0)."""
    import re

    q = _bench().get_queries(dialect="clickhouse")["EQ7"]
    assert not re.search(r"FROM\s+VALUES", q, re.IGNORECASE), f"EQ7 must not use FROM VALUES for ClickHouse:\n{q}"
    assert "SELECT 0" in q, f"EQ7 must use SELECT 0 dummy row for ClickHouse:\n{q}"


def test_eq7_base_dialect_retains_values():
    """Base EQ7 must use FROM (VALUES (0)) as dummy."""
    q = _bench().get_queries()["EQ7"]
    assert "VALUES" in q.upper(), f"Base EQ7 must use VALUES dummy row:\n{q}"


# ---------------------------------------------------------------------------
# EQ3: double-nested COUNT → flat COUNT
# ---------------------------------------------------------------------------


def test_eq3_clickhouse_flattens_nested_count():
    """EQ3 for ClickHouse must flatten (SELECT COUNT(*) FROM (SELECT COUNT(*) ...)) to direct COUNT."""
    import re

    q = _bench().get_queries(dialect="clickhouse")["EQ3"]
    # The double-nesting pattern must be gone
    assert not re.search(r"SELECT\s+COUNT\s*\(\s*\*\s*\)\s+FROM\s+\(\s*(?:/\*|--)", q, re.IGNORECASE), (
        f"EQ3 must not have double-nested COUNT scalar subquery for ClickHouse:\n{q[:500]}"
    )
    # Direct COUNT subquery must be present
    assert re.search(r"COUNT\(\*\)\s+FROM\s+DimCustomer\s+WHERE\s+BatchID", q, re.IGNORECASE), (
        f"EQ3 must have flat COUNT(*) FROM DimCustomer for ClickHouse:\n{q[:500]}"
    )


# ---------------------------------------------------------------------------
# Other queries unaffected
# ---------------------------------------------------------------------------


def test_non_overridden_queries_present_in_clickhouse_dialect():
    """ClickHouse dialect must not drop or empty any queries."""
    bench = _bench()
    base = bench.get_queries()
    clickhouse = bench.get_queries(dialect="clickhouse")

    for qid in base:
        assert qid in clickhouse, f"{qid} missing from ClickHouse queries"
        assert clickhouse[qid].strip(), f"{qid} is empty in ClickHouse queries"
