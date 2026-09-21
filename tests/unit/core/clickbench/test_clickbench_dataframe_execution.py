"""Execution tests for ClickBench DataFrame query implementations.

Runs every registered ClickBench query (Q1-Q43) on both backends against a
small deterministic ``hits`` fixture and asserts the backends agree. The
fixture holds ten rows so no query's LIMIT truncates tied groups: with no
truncation both backends return the same groups and an order-insensitive
comparison is exact (the production tie-aware comparator in the
cross-surface gate covers the truncated case on real data).

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

try:
    import pandas as pd
    import polars as pl

    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

    DEPS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    pl = None  # type: ignore[assignment]
    PolarsDataFrameAdapter = None  # type: ignore[assignment]
    DEPS_AVAILABLE = False

pytestmark.append(pytest.mark.skipif(not DEPS_AVAILABLE, reason="pandas/polars not installed"))

ALL_QUERY_IDS = [f"Q{i}" for i in range(1, 44)]


class _PandasContext:
    """Minimal pandas-family context used by ClickBench pandas implementations."""

    def __init__(self, tables: dict[str, Any]) -> None:
        self._tables = tables

    def get_table(self, name: str) -> Any:
        return self._tables[name.lower()]


def _make_hits() -> Any:
    """Ten deterministic rows covering every filter/derive column the queries use."""
    base = datetime(2013, 7, 5, 12, 0, 0)
    rows = range(10)
    return pd.DataFrame(
        {
            "WatchID": [i + 1 for i in rows],
            "CounterID": [62] * 10,
            "EventDate": [date(2013, 7, 5)] * 10,
            "EventTime": [base.replace(hour=i, minute=i) for i in rows],
            "UserID": [1000 + (i % 5) for i in rows],
            "URL": [f"http://www.google.com/search?q={i}" if i % 2 == 0 else f"http://example.com/p{i}" for i in rows],
            "Title": [f"Google result {i}" if i % 2 == 0 else f"Page {i}" for i in rows],
            "SearchPhrase": [f"phrase {i % 3}" if i % 2 == 0 else "" for i in rows],
            "SearchEngineID": [(i % 3) + 1 for i in rows],
            "AdvEngineID": [0 if i % 3 == 0 else (i % 4) + 1 for i in rows],
            "RegionID": [(i % 4) + 1 for i in rows],
            "MobilePhone": [1 if i % 4 == 0 else 0 for i in rows],
            "MobilePhoneModel": ["Pixel" if i % 4 == 0 else "" for i in rows],
            "ClientIP": [(1 << 24) + i for i in rows],
            "URLHash": [2868770270353813622 if i == 0 else 1000 + i for i in rows],
            "RefererHash": [3594120000172545465 if i == 1 else 2000 + i for i in rows],
            "TraficSourceID": [-1 if i % 3 == 0 else (6 if i % 3 == 1 else 1) for i in rows],
            "Referer": [f"http://referer{i}.com" for i in rows],
            "IsRefresh": [0] * 10,
            "IsLink": [1 if i % 2 == 0 else 0 for i in rows],
            "IsDownload": [0] * 10,
            "DontCountHits": [0] * 10,
            "ResolutionWidth": [1920 if i % 2 == 0 else 1366 for i in rows],
            "WindowClientWidth": [1920 - i for i in rows],
            "WindowClientHeight": [1080 - i for i in rows],
        }
    )


def _to_pandas_result(result: Any) -> Any:
    """Normalize an expression/pandas query result to pandas."""
    if hasattr(result, "collect"):
        result = result.collect()
    if isinstance(result, pl.DataFrame):
        return result.to_pandas()
    if isinstance(result, pd.DataFrame):
        return result.copy()
    raise TypeError(f"Unsupported result type: {type(result)!r}")


def _normalized(frame: Any) -> Any:
    """Order-insensitive frame: datetime-likes as strings, rows fully sorted."""
    frame = frame.copy()
    for column in frame.columns:
        values = frame[column]
        if pd.api.types.is_datetime64_any_dtype(values) or (
            len(frame) and isinstance(values.iloc[0], (date, datetime))
        ):
            frame[column] = values.astype(str)
    return frame.sort_values(by=list(frame.columns)).reset_index(drop=True)


class TestClickBenchQueryExecution:
    """Every ClickBench query executes on both backends with identical results."""

    @pytest.fixture(scope="class")
    def hits(self):
        return _make_hits()

    @pytest.fixture(scope="class")
    def expr_ctx(self, hits):
        adapter = PolarsDataFrameAdapter()
        ctx = adapter.create_context()
        ctx.register_table("hits", pl.from_pandas(hits).lazy())
        return ctx

    @pytest.fixture(scope="class")
    def pandas_ctx(self, hits):
        return _PandasContext({"hits": hits})

    @pytest.mark.parametrize("query_id", ALL_QUERY_IDS)
    def test_backends_agree(self, query_id, expr_ctx, pandas_ctx):
        from benchbox.core.clickbench.dataframe_queries import get_clickbench_query

        query = get_clickbench_query(query_id)
        assert query is not None

        expr_result = _normalized(_to_pandas_result(query.expression_impl(expr_ctx)))
        pandas_result = _normalized(_to_pandas_result(query.pandas_impl(pandas_ctx)))

        assert expr_result.columns.tolist() == pandas_result.columns.tolist()
        pd.testing.assert_frame_equal(expr_result, pandas_result, check_dtype=False)

    def test_q1_counts_all_rows(self, expr_ctx, pandas_ctx):
        from benchbox.core.clickbench.dataframe_queries import get_clickbench_query

        query = get_clickbench_query("Q1")
        assert _to_pandas_result(query.expression_impl(expr_ctx))["count"].tolist() == [10]
        assert _to_pandas_result(query.pandas_impl(pandas_ctx))["count"].tolist() == [10]

    def test_q4_average_user_id(self, expr_ctx, pandas_ctx):
        from benchbox.core.clickbench.dataframe_queries import get_clickbench_query

        query = get_clickbench_query("Q4")
        assert _to_pandas_result(query.expression_impl(expr_ctx))["avg_user_id"].tolist() == [1002.0]
        assert _to_pandas_result(query.pandas_impl(pandas_ctx))["avg_user_id"].tolist() == [1002.0]

    def test_q5_unique_users(self, expr_ctx, pandas_ctx):
        from benchbox.core.clickbench.dataframe_queries import get_clickbench_query

        query = get_clickbench_query("Q5")
        assert _to_pandas_result(query.expression_impl(expr_ctx))["uniq_users"].tolist() == [5]
        assert _to_pandas_result(query.pandas_impl(pandas_ctx))["uniq_users"].tolist() == [5]
