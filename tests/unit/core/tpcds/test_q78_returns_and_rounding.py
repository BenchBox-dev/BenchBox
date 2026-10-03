"""Regression coverage for Q78's returns anti-join and ratio rounding on both DataFrame families.

The SQL keeps a sale when ``sr_ticket_number IS NULL`` after a left join to the returns table, so a
return whose ``sr_returned_date_sk`` is NULL still removes the sale. Testing the date instead keeps
that sale. The SQL ``ROUND`` also rounds a half up (30 / 48 = 0.625 gives 0.63), where Polars and
pandas round it to even (0.62).
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

FAMILIES = ["expression", "pandas"]


def _tables():
    return {
        # Item 1 sells 30 and is not returned; item 2 sells 5 and its ticket was returned with a NULL date.
        "store_sales": {
            "ss_ticket_number": [1, 2],
            "ss_item_sk": [1, 2],
            "ss_customer_sk": [1, 1],
            "ss_sold_date_sk": [1, 1],
            "ss_quantity": [30, 5],
            "ss_wholesale_cost": [10.0, 1.0],
            "ss_sales_price": [11.0, 1.0],
        },
        "store_returns": {"sr_ticket_number": [2, 99], "sr_item_sk": [2, 99], "sr_returned_date_sk": [None, 1]},
        "web_sales": {
            "ws_order_number": [10, 11],
            "ws_item_sk": [1, 2],
            "ws_bill_customer_sk": [1, 1],
            "ws_sold_date_sk": [1, 1],
            "ws_quantity": [48, 5],
            "ws_wholesale_cost": [4.0, 1.0],
            "ws_sales_price": [6.0, 1.0],
        },
        "web_returns": {"wr_order_number": [99], "wr_item_sk": [99], "wr_returned_date_sk": [1]},
        "catalog_sales": {
            "cs_order_number": [20],
            "cs_item_sk": [3],
            "cs_bill_customer_sk": [9],
            "cs_sold_date_sk": [1],
            "cs_quantity": [1],
            "cs_wholesale_cost": [1.0],
            "cs_sales_price": [1.0],
        },
        "catalog_returns": {"cr_order_number": [99], "cr_item_sk": [99], "cr_returned_date_sk": [1]},
        "date_dim": {"d_date_sk": [1], "d_year": [2000]},
    }


def _context(family, tables):
    if family == "expression":
        pl = pytest.importorskip("polars")
        from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

        ctx = PolarsDataFrameAdapter().create_context()
        for name, data in tables.items():
            ctx.register_table(name, pl.DataFrame(data).lazy())
    else:
        import pandas as pd

        from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter

        ctx = PandasDataFrameAdapter().create_context()
        for name, data in tables.items():
            ctx.register_table(name, pd.DataFrame(data))
    return ctx


@pytest.mark.parametrize("family", FAMILIES)
def test_q78_drops_a_returned_sale_even_when_the_return_date_is_null_and_rounds_halves_up(family, monkeypatch):
    from benchbox.core.equivalence.dataframe_surface import materialize_rows
    from benchbox.core.tpcds.dataframe_queries import queries

    monkeypatch.setattr(queries, "get_parameters", lambda _query_id: {"year": 2000})
    impl = queries.q78_expression_impl if family == "expression" else queries.q78_pandas_impl

    rows = materialize_rows(impl(_context(family, _tables())))

    # (year, item, customer, ratio, store_qty, store_wholesale_cost, store_sales_price, other qty/cost/price)
    assert rows == [(2000, 1, 1, 0.63, 30, 10.0, 11.0, 48, 4.0, 6.0)]
