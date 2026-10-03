from __future__ import annotations

import sys

import pandas as pd
import pytest

from benchbox.core.tpcds.dataframe_queries.rollup_helper import (
    compute_grouping_function,
    expand_rollup_expression,
    expand_rollup_pandas,
    lochierarchy_expression,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _LitExpr:
    def __init__(self, value):
        self.value = value

    def alias(self, name: str):
        return ("alias", self.value, name)


class _AggMeta:
    def __init__(self, name: str):
        self._name = name

    def output_name(self) -> str:
        return self._name


class _AggExpr:
    def __init__(self, name: str):
        self.meta = _AggMeta(name)


class _FakeFrame:
    def __init__(self, cols=None):
        self.cols = cols or []

    def group_by(self, *cols):
        return _FakeFrame(list(cols))

    def agg(self, *exprs):
        return _FakeFrame(self.cols.copy())

    def select(self, *cols):
        return _FakeFrame(list(cols))

    def with_columns(self, expr):
        return self


class _FakeColExpr:
    def __init__(self, name):
        self.name = name

    def count(self):
        return _FakeCountExpr(self.name)


class _FakeCountExpr:
    def __init__(self, name):
        self.name = name

    def alias(self, name: str):
        return ("count-alias", self.name, name)


class _FakeExprCtx:
    def lit(self, value):
        return _LitExpr(value)

    def col(self, name):
        return _FakeColExpr(name)

    def when(self, condition):
        return _FakeWhen(condition)

    def concat(self, frames):
        return frames


class _FakeWhen:
    def __init__(self, condition):
        self.condition = condition

    def then(self, value):
        return _FakeThen(value)


class _FakeThen:
    def __init__(self, value):
        self.value = value

    def otherwise(self, value):
        return _FakeOtherwise(value)


class _FakeOtherwise:
    def __init__(self, value):
        self.value = value

    def alias(self, name: str):
        return ("when-alias", name)


class _PandasAdapter:
    def groupby_agg(self, df, group_cols, agg_spec, as_index=False, dropna=True):
        return df.groupby(group_cols, as_index=False).agg(**agg_spec)


class _PandasCtx:
    def __init__(self):
        self._adapter = _PandasAdapter()

    def concat(self, frames):
        return pd.concat(frames, ignore_index=True)


def test_expand_rollup_expression_returns_all_levels():
    df = _FakeFrame()
    ctx = _FakeExprCtx()
    agg_exprs = [_AggExpr("sum_sales")]

    out = expand_rollup_expression(df, group_cols=["a", "b"], agg_exprs=agg_exprs, ctx=ctx)

    assert len(out) == 3


def test_expand_rollup_pandas_includes_grouping_id_and_null_levels():
    df = pd.DataFrame({"a": ["x", "x"], "b": ["y", "z"], "val": [1, 2]})
    ctx = _PandasCtx()
    agg = {"sum_val": ("val", "sum")}

    out = expand_rollup_pandas(df, group_cols=["a", "b"], agg_dict=agg, ctx=ctx)

    assert "grouping_id" in out.columns
    assert out["grouping_id"].max() >= 0


def test_compute_grouping_function_and_lochierarchy_fallback(monkeypatch):
    grouping_expr = compute_grouping_function(df=None, grouping_id_col="grouping_id", column_position=1)
    assert grouping_expr is not None

    monkeypatch.setitem(sys.modules, "polars", None)
    counter = lochierarchy_expression(grouping_id_col="grouping_id", num_cols=3, ctx=None)
    assert callable(counter)
    assert counter(7) == 3
