"""Unit tests for TPC-DI PostgreSQL dialect rendering."""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _bench():
    from benchbox.core.tpcdi.benchmark import TPCDIBenchmark

    return TPCDIBenchmark(scale_factor=0.01)


def test_postgres_replaces_julianday_date_arithmetic() -> None:
    """PostgreSQL-family TPC-DI queries must not retain SQLite JULIANDAY calls."""
    queries = _bench().get_queries(dialect="postgres")

    for query_id in ("AQ7", "AQ8", "AQ10"):
        query = queries[query_id]
        assert "JULIANDAY" not in query.upper(), f"{query_id} retained JULIANDAY:\n{query}"
        assert "CAST(" in query and " AS DATE)" in query, f"{query_id} should use PostgreSQL date subtraction:\n{query}"


def test_postgres_renders_boolean_numeric_comparisons() -> None:
    """PostgreSQL does not compare boolean columns to integer literals."""
    queries = _bench().get_queries(dialect="postgres")
    rendered = "\n".join(queries.values())

    assert "IsCurrent = 1" not in rendered
    assert "IsCurrent = 0" not in rendered
    assert "TT_IS_SELL = 1" not in rendered
    assert "TT_IS_SELL = 0" not in rendered
    assert "IsCurrent IS TRUE" in rendered
    assert "TT_IS_SELL IS TRUE" in rendered
    assert "TT_IS_SELL IS FALSE" in rendered
    assert "HolidayFlag = 1" not in rendered
    assert "HolidayFlag = 0" not in rendered


def test_postgres_removes_same_select_alias_references() -> None:
    """PostgreSQL does not allow all same-level SELECT aliases in HAVING/ORDER BY peers."""
    queries = _bench().get_queries(dialect="postgres")

    assert "HAVING customer_count > 10" not in queries["A5"]
    assert "HAVING COUNT(DISTINCT c.SK_CustomerID) > 10" in queries["A5"]
    assert "CASE risk_profile" not in queries["AQ10"]
    assert "ORDER BY 15, total_trade_value DESC" in queries["AQ10"]
    assert "FROM (VALUES (0)) AS dummy" not in queries["EQ7"]
    assert "overall_quality_score" in queries["EQ7"]
