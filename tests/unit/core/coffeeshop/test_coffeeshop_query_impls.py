"""Tests for CoffeeShop DataFrame query implementations.

Calls every expression_impl and pandas_impl function with a mock DataFrameContext
so that the query body lines are covered.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Expr:
    """Minimal expression stub that supports comparison and chaining operators."""

    def __gt__(self, other):
        return _Expr()

    def __ge__(self, other):
        return _Expr()

    def __lt__(self, other):
        return _Expr()

    def __le__(self, other):
        return _Expr()

    def __ne__(self, other):  # type: ignore[override]
        return _Expr()

    def __and__(self, other):
        return _Expr()

    def __or__(self, other):
        return _Expr()

    def __getitem__(self, key):
        return _Expr()

    def __getattr__(self, name):
        return _Expr()

    def __call__(self, *args, **kwargs):
        return _Expr()

    def __truediv__(self, other):
        return _Expr()

    def __floordiv__(self, other):
        return _Expr()

    def __add__(self, other):
        return _Expr()

    def __sub__(self, other):
        return _Expr()

    def __mul__(self, other):
        return _Expr()


class _DataFrame:
    """Minimal DataFrame stub that supports fluent method chaining and comparison."""

    def __gt__(self, other):
        return _DataFrame()

    def __ge__(self, other):
        return _DataFrame()

    def __lt__(self, other):
        return _DataFrame()

    def __le__(self, other):
        return _DataFrame()

    def __and__(self, other):
        return _DataFrame()

    def __or__(self, other):
        return _DataFrame()

    def __getattr__(self, name):
        return _DataFrame()

    def __getitem__(self, key):
        return _DataFrame()

    def __call__(self, *args, **kwargs):
        return _DataFrame()

    def __truediv__(self, other):
        return _DataFrame()

    def __floordiv__(self, other):
        return _DataFrame()

    def __add__(self, other):
        return _DataFrame()

    def __sub__(self, other):
        return _DataFrame()

    def __mul__(self, other):
        return _DataFrame()

    def __len__(self):
        return 10

    def __iter__(self):
        return iter([])

    def scalar(self):
        return 100.0


def _mock_ctx():
    """Return a mock DataFrameContext with expression and DataFrame stubs."""
    ctx = MagicMock()
    ctx.col.side_effect = lambda *a, **kw: _Expr()
    ctx.lit.side_effect = lambda *a, **kw: _Expr()
    ctx.when.side_effect = lambda *a, **kw: _Expr()
    ctx.get_table.side_effect = lambda *a, **kw: _DataFrame()
    return ctx


def _pandas_ctx():
    """Return a mock DataFrameContext backed by minimal pandas DataFrames."""
    from datetime import datetime

    order_lines = pd.DataFrame(
        {
            "order_id": [1, 1, 2, 2],
            "order_date": pd.to_datetime(["2023-01-10", "2023-01-10", "2023-01-15", "2024-06-01"]),
            "location_record_id": [1, 1, 2, 2],
            "product_record_id": [10, 20, 10, 20],
            "total_price": [5.0, 3.0, 8.0, 4.0],
            "quantity": [1, 2, 1, 1],
            "unit_price": [5.0, 3.0, 8.0, 4.0],
            "order_time": pd.to_datetime(
                ["2023-01-10 08:00", "2023-01-10 12:00", "2023-01-15 16:00", "2024-06-01 20:00"]
            ),
        }
    )
    dim_locations = pd.DataFrame(
        {
            "record_id": [1, 2],
            "region": ["South", "North"],
            "location_id": [101, 102],
            "city": ["Atlanta", "Boston"],
            "state": ["GA", "MA"],
        }
    )
    dim_products = pd.DataFrame(
        {
            "record_id": [10, 20],
            "subcategory": ["Coffee", "Tea"],
            "product_name": ["Espresso", "Green Tea"],
            "name": ["Espresso", "Green Tea"],
            "product_id": [1001, 1002],
            "from_date": pd.to_datetime(["2022-01-01", "2022-01-01"]),
            "to_date": pd.to_datetime(["2025-12-31", "2025-12-31"]),
        }
    )

    tables = {
        "order_lines": order_lines,
        "dim_locations": dim_locations,
        "dim_products": dim_products,
    }

    ctx = MagicMock()
    ctx.get_table.side_effect = lambda name: tables[name]
    return ctx


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------


def test_parse_date_from_string():
    from benchbox.core.coffeeshop.dataframe_queries.queries import _parse_date

    result = _parse_date("2023-01-15")
    assert result == date(2023, 1, 15)


def test_parse_date_from_date_object():
    from benchbox.core.coffeeshop.dataframe_queries.queries import _parse_date

    d = date(2023, 6, 1)
    assert _parse_date(d) is d


# ---------------------------------------------------------------------------
# SA1
# ---------------------------------------------------------------------------


def test_sa1_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa1_expression_impl

    ctx = _mock_ctx()
    result = sa1_expression_impl(ctx)
    assert result is not None


def test_sa1_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa1_pandas_impl

    ctx = _pandas_ctx()
    result = sa1_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# SA2
# ---------------------------------------------------------------------------


def test_sa2_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa2_expression_impl

    ctx = _mock_ctx()
    result = sa2_expression_impl(ctx)
    assert result is not None


def test_sa2_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa2_pandas_impl

    ctx = _mock_ctx()
    result = sa2_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# SA3
# ---------------------------------------------------------------------------


def test_sa3_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa3_expression_impl

    ctx = _mock_ctx()
    result = sa3_expression_impl(ctx)
    assert result is not None


def test_sa3_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa3_pandas_impl

    ctx = _pandas_ctx()
    result = sa3_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# SA4 - uses .scalar()
# ---------------------------------------------------------------------------


def test_sa4_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa4_expression_impl

    ctx = _mock_ctx()
    result = sa4_expression_impl(ctx)
    assert result is not None


def test_sa4_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa4_pandas_impl

    ctx = _pandas_ctx()
    result = sa4_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# SA5
# ---------------------------------------------------------------------------


def test_sa5_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa5_expression_impl

    ctx = _mock_ctx()
    result = sa5_expression_impl(ctx)
    assert result is not None


def test_sa5_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import sa5_pandas_impl

    ctx = _mock_ctx()
    result = sa5_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# PR1
# ---------------------------------------------------------------------------


def test_pr1_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import pr1_expression_impl

    ctx = _mock_ctx()
    result = pr1_expression_impl(ctx)
    assert result is not None


def test_pr1_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import pr1_pandas_impl

    ctx = _mock_ctx()
    result = pr1_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# PR2
# ---------------------------------------------------------------------------


def test_pr2_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import pr2_expression_impl

    ctx = _mock_ctx()
    result = pr2_expression_impl(ctx)
    assert result is not None


def test_pr2_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import pr2_pandas_impl

    ctx = _pandas_ctx()
    result = pr2_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# TR1
# ---------------------------------------------------------------------------


def test_tr1_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import tr1_expression_impl

    ctx = _mock_ctx()
    result = tr1_expression_impl(ctx)
    assert result is not None


def test_tr1_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import tr1_pandas_impl

    ctx = _pandas_ctx()
    result = tr1_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# TM1
# ---------------------------------------------------------------------------


def test_tm1_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import tm1_expression_impl

    ctx = _mock_ctx()
    result = tm1_expression_impl(ctx)
    assert result is not None


def test_tm1_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import tm1_pandas_impl

    ctx = _pandas_ctx()
    result = tm1_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# QC1
# ---------------------------------------------------------------------------


def test_qc1_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import qc1_expression_impl

    ctx = _mock_ctx()
    result = qc1_expression_impl(ctx)
    assert result is not None


def test_qc1_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import qc1_pandas_impl

    ctx = _pandas_ctx()
    result = qc1_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# QC2
# ---------------------------------------------------------------------------


def test_qc2_expression_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import qc2_expression_impl

    ctx = _mock_ctx()
    result = qc2_expression_impl(ctx)
    assert result is not None


def test_qc2_pandas_impl():
    from benchbox.core.coffeeshop.dataframe_queries.queries import qc2_pandas_impl

    ctx = _pandas_ctx()
    result = qc2_pandas_impl(ctx)
    assert result is not None


# ---------------------------------------------------------------------------
# Registration completeness
# ---------------------------------------------------------------------------


def test_all_11_queries_registered_with_callable_impls():
    from benchbox.core.coffeeshop.dataframe_queries import COFFEESHOP_DATAFRAME_QUERIES

    queries = COFFEESHOP_DATAFRAME_QUERIES.get_all_queries()
    assert len(queries) == 11
    for q in queries:
        assert callable(q.expression_impl), f"{q.query_id} expression_impl not callable"
        assert callable(q.pandas_impl), f"{q.query_id} pandas_impl not callable"
        assert q.query_id, "query_id must not be empty"
        assert q.description, f"{q.query_id} description must not be empty"
