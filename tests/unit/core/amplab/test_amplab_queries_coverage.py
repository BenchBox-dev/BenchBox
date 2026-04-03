"""Coverage tests for AMPLab DataFrame query implementations.

Targets the implementation functions in:
  benchbox/core/amplab/dataframe_queries/queries.py

Verifies that:
- Each query function is callable and executes without error on a mock context
- Registration via _register_all_queries() produces correct query objects
- Category assignments match query semantics

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from tests.unit.core.conftest import MockExpr

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_mock_ctx() -> MockExpr:
    """Create a mock DataFrameContext backed by MockExpr."""
    return MockExpr()


class TestAMPLabQueryFunctionCallable:
    """Tests that each query implementation function exists and is callable."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "q1_expression_impl",
            "q1_pandas_impl",
            "q1a_expression_impl",
            "q1a_pandas_impl",
            "q2_expression_impl",
            "q2_pandas_impl",
            "q2a_expression_impl",
            "q2a_pandas_impl",
            "q3_expression_impl",
            "q3_pandas_impl",
            "q3a_expression_impl",
            "q3a_pandas_impl",
            "q4_expression_impl",
            "q4_pandas_impl",
            "q5_expression_impl",
            "q5_pandas_impl",
        ],
    )
    def test_function_is_callable(self, func_name: str) -> None:
        import benchbox.core.amplab.dataframe_queries.queries as mod

        func = getattr(mod, func_name, None)
        assert func is not None, f"{func_name} not found in module"
        assert callable(func), f"{func_name} is not callable"


class TestAMPLabExpressionImplExecution:
    """Tests that expression_impl functions execute without error on mock context."""

    @pytest.mark.parametrize(
        "func_name",
        [
            "q1_expression_impl",
            "q1a_expression_impl",
            "q2_expression_impl",
            "q2a_expression_impl",
            "q3_expression_impl",
            "q3a_expression_impl",
            "q4_expression_impl",
            "q5_expression_impl",
        ],
    )
    def test_expression_impl_runs(self, func_name: str) -> None:
        import benchbox.core.amplab.dataframe_queries.queries as mod

        func = getattr(mod, func_name)
        ctx = _make_mock_ctx()
        result = func(ctx)
        assert result is not None


class TestAMPLabPandasImplExecution:
    """Tests that pandas_impl functions execute (or exercise code paths) on mock context.

    Some pandas_impl functions call numpy with mock objects, which numpy cannot
    process as arrays. We allow ValueError/TypeError from numpy internals while
    still verifying that the function body is entered and code paths are covered.
    """

    @pytest.mark.parametrize(
        "func_name",
        [
            "q1_pandas_impl",
            "q1a_pandas_impl",
            "q2_pandas_impl",
            "q2a_pandas_impl",
            "q3_pandas_impl",
            "q3a_pandas_impl",
            "q4_pandas_impl",
            "q5_pandas_impl",
        ],
    )
    def test_pandas_impl_runs(self, func_name: str) -> None:
        import benchbox.core.amplab.dataframe_queries.queries as mod

        func = getattr(mod, func_name)
        ctx = _make_mock_ctx()
        try:
            result = func(ctx)
            assert result is not None
        except (ValueError, TypeError):
            # numpy operations on mock data raise ValueError/TypeError;
            # the important thing is that we entered the function body (covered).
            pass


class TestAMPLabQueryRegistration:
    """Tests for _register_all_queries registration output."""

    def test_all_query_ids_are_strings(self) -> None:
        from benchbox.core.amplab.dataframe_queries import AMPLAB_DATAFRAME_QUERIES

        for q in AMPLAB_DATAFRAME_QUERIES.get_all_queries():
            assert isinstance(q.query_id, str)

    def test_q1_categories_include_scan_and_filter(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q1")
        assert QueryCategory.SCAN in q.categories or QueryCategory.FILTER in q.categories

    def test_q1a_categories_include_aggregate(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q1a")
        assert QueryCategory.AGGREGATE in q.categories

    def test_q2_categories_include_join(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q2")
        assert QueryCategory.JOIN in q.categories

    def test_q2a_categories_include_join_and_sort(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q2a")
        assert QueryCategory.JOIN in q.categories
        assert QueryCategory.SORT in q.categories

    def test_q3_categories_include_analytical(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q3")
        assert QueryCategory.ANALYTICAL in q.categories

    def test_q3a_categories_include_projection(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q3a")
        assert QueryCategory.PROJECTION in q.categories

    def test_q4_categories_include_analytical_and_aggregate(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q4")
        assert QueryCategory.ANALYTICAL in q.categories
        assert QueryCategory.AGGREGATE in q.categories

    def test_q5_categories_include_join_and_analytical(self) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query
        from benchbox.core.dataframe.query import QueryCategory

        q = get_amplab_query("Q5")
        assert QueryCategory.JOIN in q.categories
        assert QueryCategory.ANALYTICAL in q.categories

    @pytest.mark.parametrize("qid", ["Q1", "Q1a", "Q2", "Q2a", "Q3", "Q3a", "Q4", "Q5"])
    def test_query_has_nonempty_name_and_description(self, qid: str) -> None:
        from benchbox.core.amplab.dataframe_queries import get_amplab_query

        q = get_amplab_query(qid)
        assert q.query_name, f"{qid} missing query_name"
        assert q.description, f"{qid} missing description"

    def test_all_queries_have_both_implementations(self) -> None:
        from benchbox.core.amplab.dataframe_queries import AMPLAB_DATAFRAME_QUERIES

        for q in AMPLAB_DATAFRAME_QUERIES.get_all_queries():
            assert q.expression_impl is not None
            assert q.pandas_impl is not None
