"""Unit tests for DataFrameQuery and QueryRegistry.

Tests for:
- DataFrameQuery dataclass validation
- Query family support detection
- QueryRegistry management
- Query category filtering

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from typing import Any

import pytest

from benchbox.core.dataframe.query import (
    DataFrameQuery,
    QueryCategory,
    QueryRegistry,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Test implementations for queries
def sample_pandas_impl(ctx: Any) -> Any:
    """Sample Pandas-family implementation."""
    return ctx.get_table("orders")


def sample_expression_impl(ctx: Any) -> Any:
    """Sample Expression-family implementation."""
    return ctx.get_table("orders")


class TestQueryCategory:
    """Tests for QueryCategory enum."""

    def test_all_categories_exist(self):
        """Test that all expected categories are defined."""
        expected = {
            "scan",
            "projection",
            "filter",
            "sort",
            "aggregate",
            "group_by",
            "join",
            "multi_join",
            "subquery",
            "window",
            "analytical",
            "tpch",
            "tpcds",
        }
        actual = {c.value for c in QueryCategory}
        assert actual == expected

    def test_str_returns_value(self):
        """Test that str() returns the value."""
        assert str(QueryCategory.SCAN) == "scan"
        assert str(QueryCategory.GROUP_BY) == "group_by"
        assert str(QueryCategory.TPCH) == "tpch"


class TestDataFrameQuery:
    """Tests for DataFrameQuery dataclass."""

    def test_minimal_query_with_pandas_impl(self):
        """Test creating a query with only Pandas implementation."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
        )

        assert query.query_id == "Q1"
        assert query.query_name == "Test Query"
        assert query.has_pandas_impl()
        assert not query.has_expression_impl()

    def test_minimal_query_with_expression_impl(self):
        """Test creating a query with only Expression implementation."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            expression_impl=sample_expression_impl,
        )

        assert query.has_expression_impl()
        assert not query.has_pandas_impl()

    def test_query_with_both_implementations(self):
        """Test creating a query with both implementations."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
            expression_impl=sample_expression_impl,
        )

        assert query.has_pandas_impl()
        assert query.has_expression_impl()

    def test_query_requires_at_least_one_implementation(self):
        """Test that query must have at least one implementation."""
        with pytest.raises(ValueError, match="must have at least one implementation"):
            DataFrameQuery(
                query_id="Q1",
                query_name="Test Query",
                description="A test query",
            )

    def test_query_id_required(self):
        """Test that query_id is required."""
        with pytest.raises(ValueError, match="query_id cannot be empty"):
            DataFrameQuery(
                query_id="",
                query_name="Test Query",
                description="A test query",
                pandas_impl=sample_pandas_impl,
            )

    def test_query_name_required(self):
        """Test that query_name is required."""
        with pytest.raises(ValueError, match="query_name cannot be empty"):
            DataFrameQuery(
                query_id="Q1",
                query_name="",
                description="A test query",
                pandas_impl=sample_pandas_impl,
            )

    def test_query_with_categories(self):
        """Test creating a query with categories."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Aggregation Query",
            description="A groupby aggregation query",
            categories=[QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            pandas_impl=sample_pandas_impl,
        )

        assert query.in_category(QueryCategory.GROUP_BY)
        assert query.in_category(QueryCategory.AGGREGATE)
        assert not query.in_category(QueryCategory.JOIN)

    def test_query_with_sql_equivalent(self):
        """Test query with SQL equivalent for validation."""
        sql = "SELECT status, SUM(amount) FROM orders GROUP BY status"
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
            sql_equivalent=sql,
        )

        assert query.has_sql_equivalent()
        assert query.sql_equivalent == sql

    def test_query_with_expected_row_count(self):
        """Test query with expected row count."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
            expected_row_count=100,
            scale_factor_dependent=False,
        )

        assert query.expected_row_count == 100
        assert not query.scale_factor_dependent

    def test_query_with_skip_platforms(self):
        """Test query with skipped platforms."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
            expression_impl=sample_expression_impl,
            skip_platforms=["cudf", "vaex"],
        )

        assert query.supports_platform("pandas")
        assert not query.supports_platform("cudf")
        assert not query.supports_platform("vaex")

    def test_supports_platform_pandas_family(self):
        """Test supports_platform for Pandas family platforms."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
        )

        # Should support all Pandas family
        assert query.supports_platform("pandas")
        assert query.supports_platform("cudf")
        assert query.supports_platform("vaex")
        assert query.supports_platform("dask")

        # Should not support Expression family (no impl)
        assert not query.supports_platform("polars")
        assert not query.supports_platform("pyspark")

    def test_supports_platform_expression_family(self):
        """Test supports_platform for Expression family platforms."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            expression_impl=sample_expression_impl,
        )

        # Should support all Expression family
        assert query.supports_platform("polars")
        assert query.supports_platform("pyspark")
        assert query.supports_platform("datafusion")
        assert query.supports_platform("spark")

        # Should not support Pandas family (no impl)
        assert not query.supports_platform("pandas")

    def test_get_impl_for_family(self):
        """Test get_impl_for_family method."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
            expression_impl=sample_expression_impl,
        )

        assert query.get_impl_for_family("pandas") == sample_pandas_impl
        assert query.get_impl_for_family("expression") == sample_expression_impl

    def test_get_impl_for_family_invalid(self):
        """Test get_impl_for_family with invalid family."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
        )

        with pytest.raises(ValueError, match="Unknown family"):
            query.get_impl_for_family("invalid")

    def test_execute_calls_correct_impl(self):
        """Test that execute calls the correct implementation."""
        call_log = []

        def pandas_impl(ctx):
            call_log.append("pandas")
            return "pandas_result"

        def expression_impl(ctx):
            call_log.append("expression")
            return "expression_result"

        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=pandas_impl,
            expression_impl=expression_impl,
        )

        # Mock context
        class MockContext:
            pass

        ctx = MockContext()

        result = query.execute(ctx, "pandas")
        assert result == "pandas_result"
        assert call_log == ["pandas"]

        result = query.execute(ctx, "expression")
        assert result == "expression_result"
        assert call_log == ["pandas", "expression"]

    def test_execute_raises_for_missing_impl(self):
        """Test that execute raises for missing implementation."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
        )

        class MockContext:
            pass

        with pytest.raises(ValueError, match="has no expression implementation"):
            query.execute(MockContext(), "expression")

    def test_to_dict(self):
        """Test serialization to dictionary."""
        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            categories=[QueryCategory.AGGREGATE],
            pandas_impl=sample_pandas_impl,
            sql_equivalent="SELECT * FROM orders",
            expected_row_count=100,
            timeout_seconds=30.0,
            skip_platforms=["cudf"],
        )

        d = query.to_dict()

        assert d["query_id"] == "Q1"
        assert d["query_name"] == "Test Query"
        assert d["description"] == "A test query"
        assert d["categories"] == ["aggregate"]
        assert d["has_pandas_impl"] is True
        assert d["has_expression_impl"] is False
        assert d["sql_equivalent"] == "SELECT * FROM orders"
        assert d["expected_row_count"] == 100
        assert d["timeout_seconds"] == 30.0
        assert d["skip_platforms"] == ["cudf"]


class TestQueryRegistry:
    """Tests for QueryRegistry."""

    def create_sample_queries(self) -> list[DataFrameQuery]:
        """Create sample queries for testing."""
        return [
            DataFrameQuery(
                query_id="Q1",
                query_name="Query 1",
                description="First query",
                categories=[QueryCategory.SCAN],
                pandas_impl=sample_pandas_impl,
            ),
            DataFrameQuery(
                query_id="Q2",
                query_name="Query 2",
                description="Second query",
                categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
                pandas_impl=sample_pandas_impl,
                expression_impl=sample_expression_impl,
            ),
            DataFrameQuery(
                query_id="Q3",
                query_name="Query 3",
                description="Third query",
                categories=[QueryCategory.JOIN],
                expression_impl=sample_expression_impl,
            ),
        ]

    def test_register_and_get(self):
        """Test basic registration and retrieval."""
        registry = QueryRegistry(benchmark="Test")

        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
        )

        registry.register(query)

        assert registry.get("Q1") == query
        assert registry.get("Q2") is None

    def test_register_many(self):
        """Test registering multiple queries at once."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()

        registry.register_many(queries)

        assert len(registry) == 3
        assert "Q1" in registry
        assert "Q2" in registry
        assert "Q3" in registry

    def test_register_duplicate_raises(self):
        """Test that registering duplicate ID raises ValueError."""
        registry = QueryRegistry(benchmark="Test")

        query = DataFrameQuery(
            query_id="Q1",
            query_name="Test Query",
            description="A test query",
            pandas_impl=sample_pandas_impl,
        )

        registry.register(query)

        with pytest.raises(ValueError, match="already registered"):
            registry.register(query)

    def test_get_or_raise(self):
        """Test get_or_raise method."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        query = registry.get_or_raise("Q1")
        assert query.query_id == "Q1"

        with pytest.raises(KeyError, match="not found"):
            registry.get_or_raise("Q999")

    def test_get_all_queries_sorted(self):
        """Test that get_all_queries returns sorted list."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        all_queries = registry.get_all_queries()

        assert len(all_queries) == 3
        assert [q.query_id for q in all_queries] == ["Q1", "Q2", "Q3"]

    def test_get_query_ids(self):
        """Test get_query_ids returns sorted list."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        ids = registry.get_query_ids()

        assert ids == ["Q1", "Q2", "Q3"]

    def test_get_queries_by_category(self):
        """Test filtering queries by category."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        scan_queries = registry.get_queries_by_category(QueryCategory.SCAN)
        assert len(scan_queries) == 1
        assert scan_queries[0].query_id == "Q1"

        agg_queries = registry.get_queries_by_category(QueryCategory.AGGREGATE)
        assert len(agg_queries) == 1
        assert agg_queries[0].query_id == "Q2"

        join_queries = registry.get_queries_by_category(QueryCategory.JOIN)
        assert len(join_queries) == 1
        assert join_queries[0].query_id == "Q3"

        window_queries = registry.get_queries_by_category(QueryCategory.WINDOW)
        assert len(window_queries) == 0

    def test_get_queries_for_platform(self):
        """Test filtering queries by platform support."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        pandas_queries = registry.get_queries_for_platform("pandas")
        assert len(pandas_queries) == 2  # Q1 and Q2 have pandas impl
        assert {q.query_id for q in pandas_queries} == {"Q1", "Q2"}

        polars_queries = registry.get_queries_for_platform("polars")
        assert len(polars_queries) == 2  # Q2 and Q3 have expression impl
        assert {q.query_id for q in polars_queries} == {"Q2", "Q3"}

    def test_get_queries_for_family(self):
        """Test filtering queries by family."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        pandas_family = registry.get_queries_for_family("pandas")
        assert len(pandas_family) == 2
        assert {q.query_id for q in pandas_family} == {"Q1", "Q2"}

        expression_family = registry.get_queries_for_family("expression")
        assert len(expression_family) == 2
        assert {q.query_id for q in expression_family} == {"Q2", "Q3"}

    def test_get_queries_for_family_invalid(self):
        """Test get_queries_for_family with invalid family."""
        registry = QueryRegistry(benchmark="Test")

        with pytest.raises(ValueError, match="Unknown family"):
            registry.get_queries_for_family("invalid")

    def test_len(self):
        """Test __len__ method."""
        registry = QueryRegistry(benchmark="Test")
        assert len(registry) == 0

        queries = self.create_sample_queries()
        registry.register_many(queries)
        assert len(registry) == 3

    def test_contains(self):
        """Test __contains__ method."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        assert "Q1" in registry
        assert "Q2" in registry
        assert "Q999" not in registry

    def test_iter(self):
        """Test __iter__ method."""
        registry = QueryRegistry(benchmark="Test")
        queries = self.create_sample_queries()
        registry.register_many(queries)

        ids = list(registry)
        assert ids == ["Q1", "Q2", "Q3"]

    def test_benchmark_name_stored(self):
        """Test that benchmark name is stored."""
        registry = QueryRegistry(benchmark="TPC-H")
        assert registry.benchmark == "TPC-H"
