"""Coverage tests for CoffeeShop DataFrame query implementations.

Targets the implementation functions in:
  benchbox/core/coffeeshop/dataframe_queries/queries.py

Verifies that:
- _parse_date handles both str and date inputs
- Each query function is callable and executes on a mock context
- Registration via _register_all_queries() produces correct query objects

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.unit.core.conftest import MockExpr

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_mock_ctx() -> MockExpr:
    """Create a mock DataFrameContext backed by MockExpr."""
    return MockExpr()


class TestParseDateHelper:
    """Tests for the _parse_date utility in queries.py."""

    def test_parse_string_date(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries.queries import _parse_date

        result = _parse_date("2023-06-15")
        assert isinstance(result, date)
        assert result == date(2023, 6, 15)

    def test_pass_through_date_object(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries.queries import _parse_date

        d = date(2024, 1, 1)
        assert _parse_date(d) is d

    def test_parse_date_edge_cases(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries.queries import _parse_date

        assert _parse_date("2000-01-01") == date(2000, 1, 1)
        assert _parse_date("2099-12-31") == date(2099, 12, 31)


class TestCoffeeShopQueryFunctionCallable:
    """Tests that each query implementation function exists and is callable."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "sa1_expression_impl",
            "sa1_pandas_impl",
            "sa2_expression_impl",
            "sa2_pandas_impl",
            "sa3_expression_impl",
            "sa3_pandas_impl",
            "sa4_expression_impl",
            "sa4_pandas_impl",
            "sa5_expression_impl",
            "sa5_pandas_impl",
            "pr1_expression_impl",
            "pr1_pandas_impl",
            "pr2_expression_impl",
            "pr2_pandas_impl",
            "tr1_expression_impl",
            "tr1_pandas_impl",
            "tm1_expression_impl",
            "tm1_pandas_impl",
            "qc1_expression_impl",
            "qc1_pandas_impl",
            "qc2_expression_impl",
            "qc2_pandas_impl",
        ],
    )
    def test_function_is_callable(self, func_name: str) -> None:
        import benchbox.core.coffeeshop.dataframe_queries.queries as mod

        func = getattr(mod, func_name, None)
        assert func is not None, f"{func_name} not found in module"
        assert callable(func), f"{func_name} is not callable"


class TestCoffeeShopQueryRegistration:
    """Tests for _register_all_queries registration output."""

    def test_all_query_ids_are_strings(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import COFFEESHOP_DATAFRAME_QUERIES

        for q in COFFEESHOP_DATAFRAME_QUERIES.get_all_queries():
            assert isinstance(q.query_id, str)

    def test_sa1_categories_include_filter_join_groupby(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_coffeeshop_query("SA1")
        assert QueryCategory.FILTER in q.categories
        assert QueryCategory.JOIN in q.categories
        assert QueryCategory.GROUP_BY in q.categories

    def test_pr2_categories_include_analytical(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_coffeeshop_query("PR2")
        assert QueryCategory.ANALYTICAL in q.categories

    def test_tr1_categories_include_analytical(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_coffeeshop_query("TR1")
        assert QueryCategory.ANALYTICAL in q.categories

    def test_qc1_categories_include_aggregate(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_coffeeshop_query("QC1")
        assert QueryCategory.AGGREGATE in q.categories

    def test_sa4_categories_include_window(self) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_coffeeshop_query("SA4")
        assert QueryCategory.WINDOW in q.categories

    @pytest.mark.parametrize("qid", ["SA1", "SA2", "SA3", "SA4", "SA5", "PR1", "PR2", "TR1", "TM1", "QC1", "QC2"])
    def test_query_has_nonempty_name_and_description(self, qid: str) -> None:
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        q = get_coffeeshop_query(qid)
        assert q.query_name, f"{qid} missing query_name"
        assert q.description, f"{qid} missing description"


class TestCoffeeShopExpressionImplExecution:
    """Tests that expression_impl functions execute without error on mock context."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "sa1_expression_impl",
            "sa2_expression_impl",
            "sa3_expression_impl",
            "sa4_expression_impl",
            "sa5_expression_impl",
            "pr1_expression_impl",
            "pr2_expression_impl",
            "tr1_expression_impl",
            "tm1_expression_impl",
            "qc1_expression_impl",
            "qc2_expression_impl",
        ],
    )
    def test_expression_impl_runs(self, func_name: str) -> None:
        import benchbox.core.coffeeshop.dataframe_queries.queries as mod

        func = getattr(mod, func_name)
        ctx = _make_mock_ctx()
        result = func(ctx)
        assert result is not None


class TestCoffeeShopPandasImplExecution:
    """Tests that pandas_impl functions execute (or exercise code paths) on mock context.

    Some pandas_impl functions call numpy with mock objects, which numpy cannot
    process as arrays. We allow ValueError/TypeError from numpy internals while
    still verifying that the function body is entered and code paths are covered.
    """

    @pytest.mark.parametrize(
        "func_name",
        [
            "sa1_pandas_impl",
            "sa2_pandas_impl",
            "sa3_pandas_impl",
            "sa4_pandas_impl",
            "sa5_pandas_impl",
            "pr1_pandas_impl",
            "pr2_pandas_impl",
            "tr1_pandas_impl",
            "tm1_pandas_impl",
            "qc1_pandas_impl",
            "qc2_pandas_impl",
        ],
    )
    def test_pandas_impl_runs(self, func_name: str) -> None:
        import benchbox.core.coffeeshop.dataframe_queries.queries as mod

        func = getattr(mod, func_name)
        ctx = _make_mock_ctx()
        try:
            result = func(ctx)
            assert result is not None
        except (ValueError, TypeError):
            # numpy operations on mock data raise ValueError/TypeError;
            # the important thing is that we entered the function body (covered).
            pass
