"""Unit tests for TPC-DS DataFrame query implementations.

Tests for:
- Query registry functionality
- Query parameter system
- Expression family implementations
- Pandas family implementations

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

from benchbox.core.dataframe.query import QueryCategory

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCDSQueryRegistry:
    """Tests for TPC-DS DataFrame query registry."""

    def test_registry_imports_successfully(self):
        """Test that the registry can be imported."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        assert TPCDS_DATAFRAME_QUERIES is not None

    def test_registry_has_queries(self):
        """Test that queries are registered."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        queries = TPCDS_DATAFRAME_QUERIES.get_all_queries()
        assert len(queries) > 0

    def test_get_query_by_id(self):
        """Test getting a query by ID."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q3")
        assert query is not None
        assert query.query_id == "Q3"

    def test_get_nonexistent_query(self):
        """Test getting a query that doesn't exist."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q999")
        assert query is None

    def test_list_queries(self):
        """Test listing all queries."""
        from benchbox.core.tpcds.dataframe_queries import list_tpcds_queries

        queries = list_tpcds_queries()
        assert len(queries) > 0
        assert all(QueryCategory.TPCDS in q.categories for q in queries)

    def test_simple_queries_registered(self):
        """Test that simple queries are registered."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        simple_queries = [
            "Q3",
            "Q7",
            "Q19",
            "Q25",
            "Q42",
            "Q43",
            "Q52",
            "Q53",
            "Q55",
            "Q63",
            "Q65",
            "Q68",
            "Q73",
            "Q79",
            "Q89",
            "Q96",
            "Q98",
        ]
        for qid in simple_queries:
            query = get_tpcds_query(qid)
            assert query is not None, f"Query {qid} should be registered"

    def test_moderate_queries_registered(self):
        """Test that moderate queries with CTEs/subqueries are registered."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        moderate_queries = ["Q1", "Q6", "Q12", "Q15", "Q20", "Q26", "Q32", "Q82", "Q92"]
        for qid in moderate_queries:
            query = get_tpcds_query(qid)
            assert query is not None, f"Query {qid} should be registered"

    def test_complex_queries_registered(self):
        """Test that complex queries with advanced patterns are registered."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        complex_queries = ["Q37", "Q46", "Q50", "Q72"]
        for qid in complex_queries:
            query = get_tpcds_query(qid)
            assert query is not None, f"Query {qid} should be registered"

    def test_queries_have_both_implementations(self):
        """Test that queries have both expression and pandas implementations."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        for query in TPCDS_DATAFRAME_QUERIES.get_all_queries():
            assert query.expression_impl is not None, f"{query.query_id} missing expression impl"
            assert query.pandas_impl is not None, f"{query.query_id} missing pandas impl"


class TestTPCDSParameters:
    """Tests for TPC-DS query parameters."""

    def test_get_parameters(self):
        """Test getting parameters for a query."""
        from benchbox.core.tpcds.dataframe_queries.parameters import get_parameters

        params = get_parameters(3)
        assert params.query_id == 3
        assert "month" in params.params
        assert "manufact_id" in params.params

    def test_get_all_parameters(self):
        """Test getting all parameters."""
        from benchbox.core.tpcds.dataframe_queries.parameters import get_all_parameters

        all_params = get_all_parameters()
        assert len(all_params) == 99

    def test_parameters_have_defaults(self):
        """Test that parameters have sensible defaults."""
        from benchbox.core.tpcds.dataframe_queries.parameters import get_parameters

        # Q42 parameters
        params = get_parameters(42)
        assert params.get("month") == 11
        assert params.get("year") == 2000

    def test_parameter_get_with_default(self):
        """Test getting parameter with default value."""
        from benchbox.core.tpcds.dataframe_queries.parameters import get_parameters

        params = get_parameters(1)
        assert params.get("nonexistent", "default") == "default"


class TestQ3Query:
    """Tests for TPC-DS Q3: Date/Item Brand Sales."""

    def test_q3_expression_impl_exists(self):
        """Test that Q3 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q3")
        assert callable(query.expression_impl)

    def test_q3_pandas_impl_exists(self):
        """Test that Q3 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q3")
        assert callable(query.pandas_impl)

    def test_q3_categories(self):
        """Test Q3 query categories."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q3")
        assert QueryCategory.JOIN in query.categories
        assert QueryCategory.AGGREGATE in query.categories
        assert QueryCategory.TPCDS in query.categories


class TestQ42Query:
    """Tests for TPC-DS Q42: Date/Item Category Sales."""

    def test_q42_expression_impl_exists(self):
        """Test that Q42 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q42")
        assert callable(query.expression_impl)

    def test_q42_pandas_impl_exists(self):
        """Test that Q42 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q42")
        assert callable(query.pandas_impl)


class TestQ52Query:
    """Tests for TPC-DS Q52: Date/Brand Extended Sales."""

    def test_q52_expression_impl_exists(self):
        """Test that Q52 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q52")
        assert query.expression_impl is not None

    def test_q52_pandas_impl_exists(self):
        """Test that Q52 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q52")
        assert query.pandas_impl is not None


class TestQ55Query:
    """Tests for TPC-DS Q55: Brand Manager Sales."""

    def test_q55_expression_impl_exists(self):
        """Test that Q55 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q55")
        assert query.expression_impl is not None

    def test_q55_pandas_impl_exists(self):
        """Test that Q55 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q55")
        assert query.pandas_impl is not None


class TestQ19Query:
    """Tests for TPC-DS Q19: Store Sales Item/Customer Analysis."""

    def test_q19_expression_impl_exists(self):
        """Test that Q19 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q19")
        assert query.expression_impl is not None

    def test_q19_pandas_impl_exists(self):
        """Test that Q19 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q19")
        assert query.pandas_impl is not None

    def test_q19_is_multi_join(self):
        """Test that Q19 is categorized as multi-join."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q19")
        assert QueryCategory.MULTI_JOIN in query.categories


class TestQ43Query:
    """Tests for TPC-DS Q43: Store Sales Day Analysis."""

    def test_q43_expression_impl_exists(self):
        """Test that Q43 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q43")
        assert query.expression_impl is not None

    def test_q43_pandas_impl_exists(self):
        """Test that Q43 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q43")
        assert query.pandas_impl is not None


class TestQ96Query:
    """Tests for TPC-DS Q96: Store Sales Time Count."""

    def test_q96_expression_impl_exists(self):
        """Test that Q96 expression implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q96")
        assert query.expression_impl is not None

    def test_q96_pandas_impl_exists(self):
        """Test that Q96 pandas implementation exists."""
        from benchbox.core.tpcds.dataframe_queries import get_tpcds_query

        query = get_tpcds_query("Q96")
        assert query.pandas_impl is not None


class TestQueryIntegration:
    """Integration tests for TPC-DS DataFrame queries."""

    def test_all_queries_callable(self):
        """Test that all query implementations are callable."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        for query in TPCDS_DATAFRAME_QUERIES.get_all_queries():
            assert callable(query.expression_impl), f"{query.query_id} expression_impl not callable"
            assert callable(query.pandas_impl), f"{query.query_id} pandas_impl not callable"

    def test_registry_benchmark(self):
        """Test that registry has correct benchmark name."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        assert TPCDS_DATAFRAME_QUERIES.benchmark == "tpcds"

    def test_query_descriptions_not_empty(self):
        """Test that all queries have descriptions."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        for query in TPCDS_DATAFRAME_QUERIES.get_all_queries():
            assert query.description, f"{query.query_id} missing description"
            assert len(query.description) > 10, f"{query.query_id} description too short"

    def test_query_names_not_empty(self):
        """Test that all queries have names."""
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        for query in TPCDS_DATAFRAME_QUERIES.get_all_queries():
            assert query.query_name, f"{query.query_id} missing query_name"
