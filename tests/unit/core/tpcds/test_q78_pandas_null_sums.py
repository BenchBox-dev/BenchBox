"""Regression coverage for Q78's pandas channel sums.

SQL ``SUM`` over inputs that are all NULL is NULL, not 0. The pandas implementation aggregates
with the vectorized ``sum`` and ``count`` and masks empty groups, so check that a group with only
NULL inputs stays NULL, a group with some NULL inputs sums the rest, and a plain sum is unchanged.
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_q78_pandas_keeps_all_null_sums_null(monkeypatch):
    import pandas as pd

    from benchbox.core.equivalence.dataframe_surface import materialize_rows
    from benchbox.core.tpcds.dataframe_queries import queries
    from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter

    monkeypatch.setattr(queries, "get_parameters", lambda _query_id: {"year": 2000})
    tables = {
        # Two tickets for item 1 and customer 1: wholesale cost is NULL in both (all-NULL group),
        # sales price is NULL in one (partial group), quantity is complete.
        "store_sales": {
            "ss_ticket_number": [1, 2],
            "ss_item_sk": [1, 1],
            "ss_customer_sk": [1, 1],
            "ss_sold_date_sk": [1, 1],
            "ss_quantity": [2, 3],
            "ss_wholesale_cost": [None, None],
            "ss_sales_price": [1.0, None],
        },
        "store_returns": {"sr_ticket_number": [99], "sr_item_sk": [99], "sr_returned_date_sk": [1]},
        "web_sales": {
            "ws_order_number": [10],
            "ws_item_sk": [1],
            "ws_bill_customer_sk": [1],
            "ws_sold_date_sk": [1],
            "ws_quantity": [5],
            "ws_wholesale_cost": [4.0],
            "ws_sales_price": [6.0],
        },
        "web_returns": {"wr_order_number": [99], "wr_item_sk": [99], "wr_returned_date_sk": [1]},
        # A different item, so the catalog channel does not match the store group.
        "catalog_sales": {
            "cs_order_number": [20],
            "cs_item_sk": [2],
            "cs_bill_customer_sk": [1],
            "cs_sold_date_sk": [1],
            "cs_quantity": [1],
            "cs_wholesale_cost": [1.0],
            "cs_sales_price": [1.0],
        },
        "catalog_returns": {"cr_order_number": [99], "cr_item_sk": [99], "cr_returned_date_sk": [1]},
        "date_dim": {"d_date_sk": [1], "d_year": [2000]},
    }
    ctx = PandasDataFrameAdapter().create_context()
    for name, data in tables.items():
        ctx.register_table(name, pd.DataFrame(data))

    rows = materialize_rows(queries.q78_pandas_impl(ctx))

    # (year, item, customer, ratio, store_qty, store_wholesale_cost, store_sales_price, other qty/cost/price)
    assert rows == [(2000, 1, 1, 1.0, 5, None, 1.0, 5.0, 4.0, 6.0)]
