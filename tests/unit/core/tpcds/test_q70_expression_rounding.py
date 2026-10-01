"""Regression coverage for TPC-DS Q70 totals on the expression (Polars) DataFrame family.

``ss_net_profit`` is a two-decimal DECIMAL in SQL, so the rollup totals are exact. Float
sums are not: 0.1 + 0.2 is 0.30000000000000004. Unrounded totals can order differently
from the SQL result when they are compared, so the expression impl rounds them to the
source scale, as the pandas impl already does.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _q70_tables():
    # One state, two counties. Profits whose float sums are not exactly representable.
    return {
        "store_sales": {
            "ss_sold_date_sk": [1, 1, 1],
            "ss_store_sk": [1, 1, 2],
            "ss_net_profit": [0.1, 0.2, 0.7],
        },
        "date_dim": {"d_date_sk": [1], "d_month_seq": [1200]},
        "store": {"s_store_sk": [1, 2], "s_state": ["TN", "TN"], "s_county": ["A", "B"]},
    }


def test_q70_expression_totals_are_rounded_to_the_decimal_scale(monkeypatch):
    pl = pytest.importorskip("polars")

    from benchbox.core.equivalence.dataframe_surface import materialize_rows
    from benchbox.core.tpcds.dataframe_queries import queries
    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

    monkeypatch.setattr(queries, "get_parameters", lambda _query_id: {"dms": 1200})
    ctx = PolarsDataFrameAdapter().create_context()
    for name, data in _q70_tables().items():
        ctx.register_table(name, pl.DataFrame(data).lazy())

    rows = materialize_rows(queries.q70_expression_impl(ctx))

    totals = [row[0] for row in rows]
    assert totals, "Q70 returned no rows"
    assert all(total == round(total, 2) for total in totals), totals
    assert 0.3 in totals  # county A: 0.1 + 0.2 must be exactly 0.3, not 0.30000000000000004
