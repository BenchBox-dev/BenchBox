"""Unit tests for TPC-DI ClickHouse dialect overrides.

Verifies that:
- AQ6 replaces the nested window aggregate SUM(SUM()) OVER () with a CROSS JOIN total
- AQ7, AQ8, AQ10 replace JULIANDAY() with dateDiff() and DATE('now') with today()
- EQ7 computes the quality score from a derived UNION relation instead of sibling aliases
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


@pytest.mark.parametrize("query_id", ["AQ7", "AQ8", "AQ10", "EQ7"])
def test_get_query_clickhouse_matches_bulk_variant(query_id):
    """Single-query ClickHouse retrieval must use the same variant as bulk retrieval."""
    bench = _bench()

    assert bench.get_query(query_id, dialect="clickhouse") == bench.get_queries(dialect="clickhouse")[query_id]


def test_get_query_clickhouse_preserves_parameter_substitution():
    """Single-query ClickHouse variants must retain caller-supplied parameters."""
    q = _bench().get_query(
        "AQ10",
        params={
            "start_year": 2020,
            "large_trade_threshold": 1234.5,
            "large_trade_count_threshold": 7,
            "same_day_trade_threshold": 2,
            "limit_rows": 11,
        },
        dialect="clickhouse",
    )

    assert "2020" in q
    assert "1234.5" in q
    assert "> 7 THEN" in q
    assert "> 2 THEN" in q
    assert "LIMIT 11" in q


def test_get_query_clickhouse_eq7_preserves_parameter_substitution():
    """The derived EQ7 variant must retain caller-supplied quality thresholds."""
    q = _bench().get_query(
        "EQ7",
        params={
            "excellent_quality_threshold": 99.0,
            "good_quality_threshold": 88.0,
            "acceptable_quality_threshold": 77.0,
        },
        dialect="clickhouse",
    )

    assert ") >= 99.0 THEN" in q
    assert ") >= 88.0 THEN" in q
    assert ") >= 77.0 THEN" in q


# ---------------------------------------------------------------------------
# EQ7: sibling aliases → derived UNION relation
# ---------------------------------------------------------------------------


def test_eq7_clickhouse_uses_derived_quality_relation():
    """EQ7 for ClickHouse must compute its score from projected derived columns."""
    import re

    q = _bench().get_queries(dialect="clickhouse")["EQ7"]
    assert "quality_metrics" in q
    assert not re.search(r"FROM\s+VALUES", q, re.IGNORECASE)
    assert "overall_quality_score" in q


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
