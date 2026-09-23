"""SQL<->DataFrame correspondence decision for TPC-DS OBT: abandon.

The DataFrame registry holds OBT-native analytic queries (``Q1`` ..
``Q17``: ``obt_row_count``, ``obt_channel_distribution``, ...) whose
``sql_equivalent`` statements target the single ``tpcds_sales_returns_obt``
table. The SQL surface holds 89 converted TPC-DS queries numbered in the
TPC-DS domain (1..99 sparse). The ``Q1``-style labels collide
cosmetically -- DataFrame ``Q1`` is an OBT row count, not TPC-DS query 1
-- so no clean SQL<->DataFrame correspondence is achievable without
renumbering or re-scoping one side. This locks the abandon verdict and
the facts forcing it: tpcds_obt is a poor cross-surface gate candidate
as long as the two numbering domains stay disjoint. Gating itself is out
of scope here.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_dataframe_side_is_obt_native() -> None:
    """Every DF query is OBT-native, not a TPC-DS query number."""
    from benchbox.core.tpcds_obt.dataframe_queries import get_dataframe_queries

    queries = get_dataframe_queries()
    assert len(queries) == 17
    assert {str(q.query_id) for q in queries} == {f"Q{n}" for n in range(1, 18)}
    queries = sorted(queries, key=lambda q: int(str(q.query_id)[1:]))
    for query in queries:
        assert str(query.query_name).startswith("obt_"), query.query_id
        assert "tpcds_sales_returns_obt" in str(query.sql_equivalent), query.query_id
    # Pin the collision: DF Q1 is an OBT row count, not TPC-DS query 1.
    assert queries[0].query_name == "obt_row_count"


def test_sql_side_is_tpcds_numbered() -> None:
    """The SQL surface spans the TPC-DS numbering domain, far beyond Q1-Q17."""
    from benchbox.core.tpcds_obt.queries import CONVERTIBLE_QUERY_IDS

    assert len(CONVERTIBLE_QUERY_IDS) == 89
    assert max(CONVERTIBLE_QUERY_IDS) > 17
    assert set(range(1, 18)) <= set(CONVERTIBLE_QUERY_IDS)


def test_no_clean_correspondence() -> None:
    """Abandon verdict: the two id domains denote different things."""
    from benchbox.core.tpcds_obt.dataframe_queries import get_dataframe_queries
    from benchbox.core.tpcds_obt.queries import CONVERTIBLE_QUERY_IDS

    df_names = {str(q.query_name) for q in get_dataframe_queries()}
    # No DF query names a TPC-DS query; no SQL id names an OBT analytic.
    assert not {f"q{n}" for n in CONVERTIBLE_QUERY_IDS} & {n.lower() for n in df_names}
