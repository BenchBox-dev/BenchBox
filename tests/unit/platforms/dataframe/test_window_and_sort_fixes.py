"""Regression tests for Polars window helpers and the UnifiedExpr.desc() sort marker.

These guard three shared-platform bugs surfaced during the read_primitives
cross-surface burn-down:

* ``window_lag``/``window_lead`` shifted in the frame's current order and then
  re-sorted the shifted values (wrong); they must sort by the window ORDER BY
  first, then shift.
* ``window_ntile`` used ``ceil(rank*n/count)``, which does not match SQL NTILE's
  even bucket distribution.
* ``UnifiedExpr.desc()`` returned a value-reordering expression on Polars instead
  of a descending sort marker, so ``.sort(a, b.desc())`` sorted ascending.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

pl = pytest.importorskip("polars", reason="Polars not installed")

from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter
from benchbox.platforms.dataframe.unified_frame import UnifiedExpr, UnifiedLazyFrame

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_window_lag_sorts_before_shifting():
    adapter = PolarsDataFrameAdapter()
    df = pl.DataFrame({"g": [1, 1, 1], "o": [3, 1, 2], "v": [30, 10, 20]})
    expr = adapter.window_lag("v", 1, partition_by=["g"], order_by=[("o", True)])
    out = df.with_columns(expr.alias("lag")).sort(["g", "o"])
    # Ordered by o: 10, 20, 30 -> lag is None, 10, 20.
    assert out["lag"].to_list() == [None, 10, 20]


def test_window_lead_sorts_before_shifting():
    adapter = PolarsDataFrameAdapter()
    df = pl.DataFrame({"g": [1, 1, 1], "o": [3, 1, 2], "v": [30, 10, 20]})
    expr = adapter.window_lead("v", 1, partition_by=["g"], order_by=[("o", True)])
    out = df.with_columns(expr.alias("lead")).sort(["g", "o"])
    assert out["lead"].to_list() == [20, 30, None]


def test_window_ntile_even_distribution():
    adapter = PolarsDataFrameAdapter()
    # NTILE(3) over 5 rows -> bucket sizes [2, 2, 1].
    df = pl.DataFrame({"o": [10, 20, 30, 40, 50]})
    expr = adapter.window_ntile(3, order_by=[("o", True)])
    out = df.with_columns(expr.alias("nt")).sort("o")
    assert out["nt"].to_list() == [1, 1, 2, 2, 3]


def test_window_ntile_partition_smaller_than_n():
    adapter = PolarsDataFrameAdapter()
    # NTILE(4) over a 2-row partition -> [1, 2] (no divide-by-zero).
    df = pl.DataFrame({"o": [10, 20]})
    expr = adapter.window_ntile(4, order_by=[("o", True)])
    out = df.with_columns(expr.alias("nt")).sort("o")
    assert out["nt"].to_list() == [1, 2]


def test_unified_sort_desc_marker_is_descending():
    adapter = PolarsDataFrameAdapter()
    lf = UnifiedLazyFrame(pl.DataFrame({"a": [1, 1, 2], "b": [1, 3, 2]}).lazy(), adapter)
    out = lf.sort(UnifiedExpr(pl.col("a")), UnifiedExpr(pl.col("b")).desc()).native.collect()
    # a ascending, b DESCENDING within a.
    assert out.select("a", "b").rows() == [(1, 3), (1, 1), (2, 2)]
