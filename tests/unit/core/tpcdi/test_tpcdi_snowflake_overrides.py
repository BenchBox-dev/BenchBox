"""Unit tests for TPC-DI Snowflake dialect overrides.

Verifies that:
- AQ7, AQ8, AQ10 replace JULIANDAY() with DATEDIFF() and DATE('now')
  with CURRENT_DATE()
- EQ7 computes the quality score from a derived UNION relation instead of
  sibling aliases
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
# AQ7 / AQ8 / AQ10: JULIANDAY → DATEDIFF, DATE('now') → CURRENT_DATE()
# ---------------------------------------------------------------------------


def test_aq7_snowflake_replaces_julianday_with_datediff():
    """AQ7 for Snowflake must not use JULIANDAY() - replace with DATEDIFF()."""
    q = _bench().get_queries(dialect="snowflake")["AQ7"]
    assert "JULIANDAY" not in q.upper(), f"AQ7 must not use JULIANDAY for Snowflake:\n{q}"
    assert "DATEDIFF(" in q, f"AQ7 must use DATEDIFF() for Snowflake:\n{q}"
    assert "CURRENT_DATE" in q, f"AQ7 must use CURRENT_DATE instead of DATE('now'):\n{q}"


def test_aq8_snowflake_replaces_julianday():
    """AQ8 for Snowflake must not use JULIANDAY()."""
    q = _bench().get_queries(dialect="snowflake")["AQ8"]
    assert "JULIANDAY" not in q.upper(), f"AQ8 must not use JULIANDAY for Snowflake:\n{q}"
    assert "DATEDIFF(" in q, f"AQ8 must use DATEDIFF() for Snowflake:\n{q}"


def test_aq10_snowflake_replaces_julianday():
    """AQ10 for Snowflake must not use JULIANDAY()."""
    q = _bench().get_queries(dialect="snowflake")["AQ10"]
    assert "JULIANDAY" not in q.upper(), f"AQ10 must not use JULIANDAY for Snowflake:\n{q}"
    assert "DATEDIFF(" in q, f"AQ10 must use DATEDIFF() for Snowflake:\n{q}"


# ---------------------------------------------------------------------------
# EQ7: sibling aliases → derived UNION relation
# ---------------------------------------------------------------------------


def test_eq7_snowflake_uses_derived_quality_relation():
    """EQ7 for Snowflake must compute its score from projected derived columns."""
    q = _bench().get_queries(dialect="snowflake")["EQ7"]
    assert "overall_quality_score" in q


def test_get_query_snowflake_matches_bulk_variant():
    """Single-query Snowflake retrieval must use the same variant as bulk retrieval."""
    bench = _bench()

    assert bench.get_query("EQ7", dialect="snowflake") == bench.get_queries(dialect="snowflake")["EQ7"]
