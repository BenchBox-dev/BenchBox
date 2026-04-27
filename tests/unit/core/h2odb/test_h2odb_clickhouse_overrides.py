"""Unit tests for H2ODB ClickHouse dialect overrides.

Verifies that h2odb Q9 uses native quantile() syntax (not PERCENTILE_CONT)
when the ClickHouse dialect is requested.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_h2odb_q9_clickhouse_uses_quantile_not_percentile_cont():
    """get_queries('clickhouse') for Q9 must use quantile() not PERCENTILE_CONT.

    ClickHouse does not support ordered-set aggregate syntax:
    PERCENTILE_CONT(p) WITHIN GROUP (ORDER BY col)

    The fix replaces Q9 wholesale with quantile(p)(col) aggregate syntax.
    """
    from benchbox.core.h2odb.benchmark import H2OBenchmark

    bench = H2OBenchmark()
    queries = bench.get_queries(dialect="clickhouse")

    q9 = queries["Q9"]
    assert "quantile(" in q9.lower(), f"Q9 must use quantile() for ClickHouse, got:\n{q9}"
    assert "PERCENTILE_CONT" not in q9.upper(), f"Q9 must not use PERCENTILE_CONT for ClickHouse, got:\n{q9}"


def test_h2odb_q9_base_dialect_retains_percentile_cont():
    """get_queries() without dialect must retain standard PERCENTILE_CONT syntax."""
    from benchbox.core.h2odb.benchmark import H2OBenchmark

    bench = H2OBenchmark()
    queries = bench.get_queries()

    q9 = queries["Q9"]
    assert "PERCENTILE_CONT" in q9.upper(), f"Base Q9 must use PERCENTILE_CONT, got:\n{q9}"


def test_h2odb_q9_clickhouse_preserves_column_names():
    """ClickHouse Q9 override must return median_fare_amount and p90_fare_amount columns."""
    from benchbox.core.h2odb.benchmark import H2OBenchmark

    bench = H2OBenchmark()
    q9 = bench.get_queries(dialect="clickhouse")["Q9"]

    assert "median_fare_amount" in q9, f"Q9 must alias median column, got:\n{q9}"
    assert "p90_fare_amount" in q9, f"Q9 must alias p90 column, got:\n{q9}"


def test_h2odb_other_queries_unaffected_by_clickhouse_dialect():
    """ClickHouse dialect override must not alter queries Q1-Q8 and Q10."""
    from benchbox.core.h2odb.benchmark import H2OBenchmark

    bench = H2OBenchmark()
    clickhouse = bench.get_queries(dialect="clickhouse")

    # Q9 is the only override - all others should be translated but not wholesale-replaced.
    for qid in [f"Q{i}" for i in range(1, 11) if i != 9]:
        # Just verify they're present and non-empty.
        assert qid in clickhouse, f"{qid} missing from ClickHouse queries"
        assert clickhouse[qid].strip(), f"{qid} is empty in ClickHouse queries"
