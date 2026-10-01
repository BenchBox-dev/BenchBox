"""Regression coverage for SQL NULL semantics in the TPC-DS DataFrame implementations.

SQL orders NULLs last (the reference engine's default), keeps a NULL grouping key as its own
group, and treats NULLs as equal in INTERSECT and EXCEPT. Polars sorts NULLs first and does
not match NULL join keys, and pandas drops NULL grouping keys, so each had to be handled.
"""

from __future__ import annotations

from datetime import date

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

FAMILIES = ["expression", "pandas"]


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


def _rows(result):
    from benchbox.core.equivalence.dataframe_surface import materialize_rows

    return materialize_rows(result)


@pytest.mark.parametrize("family", FAMILIES)
def test_joined_aggregate_keeps_a_null_group_and_sorts_it_last(family):
    from benchbox.core.tpcds.dataframe_queries import queries

    spec = {
        "query_id": 15,
        "base": "t",
        "joins": [],
        "group_by": ["zip"],
        "aggs": [["total", "v", "sum"]],
        "sort_by": ["zip"],
    }
    ctx = _context(family, {"t": {"zip": ["b", None, "a", "b"], "v": [1.0, 5.0, 2.0, 3.0]}})
    engine = queries._joined_agg_expression_impl if family == "expression" else queries._joined_agg_pandas_impl

    assert _rows(engine(ctx, spec)) == [("a", 2.0), ("b", 4.0), (None, 5.0)]


@pytest.mark.parametrize("family", FAMILIES)
def test_q34_sorts_null_names_last_and_reports_them_as_none(family, monkeypatch):
    from benchbox.core.tpcds.dataframe_queries import queries

    monkeypatch.setattr(queries, "get_parameters", lambda _query_id: {"year": 1998})
    tickets = 15  # Q34 keeps tickets with 15 to 20 line items
    tables = {
        "store_sales": {
            "ss_sold_date_sk": [1] * (2 * tickets),
            "ss_store_sk": [1] * (2 * tickets),
            "ss_hdemo_sk": [1] * (2 * tickets),
            "ss_ticket_number": [100] * tickets + [200] * tickets,
            "ss_customer_sk": [1] * tickets + [2] * tickets,
        },
        "date_dim": {"d_date_sk": [1], "d_dom": [2], "d_year": [1998]},
        "store": {"s_store_sk": [1], "s_county": ["Williamson County"]},
        "household_demographics": {
            "hd_demo_sk": [1],
            "hd_buy_potential": [">10000"],
            "hd_vehicle_count": [1],
            "hd_dep_count": [2],
        },
        "customer": {
            "c_customer_sk": [1, 2],
            "c_last_name": ["Baker", None],
            "c_first_name": ["Andrew", None],
            "c_salutation": ["Dr.", None],
            "c_preferred_cust_flag": ["N", "Y"],
        },
    }
    ctx = _context(family, tables)
    impl = queries.q34_expression_impl if family == "expression" else queries.q34_pandas_impl

    assert _rows(impl(ctx)) == [
        ("Baker", "Andrew", "Dr.", "N", 100, tickets),
        (None, None, None, "Y", 200, tickets),
    ]


def _three_channel_tables(store, catalog, web):
    """Customers 1 (NULL names) and 2 ('Lee', 'Ann') buy on one date; customer 99 has no customer row."""
    return {
        "store_sales": {"ss_sold_date_sk": [1] * len(store), "ss_customer_sk": store},
        "catalog_sales": {"cs_sold_date_sk": [1] * len(catalog), "cs_bill_customer_sk": catalog},
        "web_sales": {"ws_sold_date_sk": [1] * len(web), "ws_bill_customer_sk": web},
        "date_dim": {"d_date_sk": [1], "d_date": [date(2000, 3, 1)], "d_month_seq": [1200]},
        "customer": {"c_customer_sk": [1, 2], "c_last_name": [None, "Lee"], "c_first_name": [None, "Ann"]},
    }


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize(
    "query_id, impl_name, store, catalog, web, expected",
    [
        # INTERSECT: the NULL-named customer is in all three channels and counts once.
        (38, "q38", [1, 2], [1], [1, 2], 1),
        # EXCEPT: the NULL-named customer is removed by the other channels; only customer 2 remains.
        (87, "q87", [1, 2], [1], [1], 1),
        # EXCEPT with nothing matching leaves both customers, including the NULL-named one.
        (87, "q87", [1, 2], [99], [99], 2),
    ],
)
def test_set_operations_treat_null_names_as_equal(
    family, query_id, impl_name, store, catalog, web, expected, monkeypatch
):
    from benchbox.core.tpcds.dataframe_queries import queries

    monkeypatch.setattr(queries, "get_parameters", lambda _query_id: {"dms": 1200})
    ctx = _context(family, _three_channel_tables(store, catalog, web))
    impl = getattr(queries, f"{impl_name}_{family}_impl")

    assert _rows(impl(ctx)) == [(expected,)]
