"""Unit tests for Read Primitives DataFrame queries.

Tests the DataFrame implementations of Read Primitives benchmark queries
for both expression-family and pandas-family platforms.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.dataframe.query import QueryCategory, QueryRegistry
from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark
from benchbox.core.read_primitives.dataframe_queries import (
    REGISTRY,
    SKIP_FOR_DATAFRAME,
    SKIP_FOR_EXPRESSION_FAMILY,
    get_dataframe_queries,
    get_skip_for_dataframe,
    get_skip_for_expression_family,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryRegistry:
    """Test the Read Primitives DataFrame query registry."""

    def test_registry_is_query_registry(self):
        """Registry should be a QueryRegistry instance."""
        assert isinstance(REGISTRY, QueryRegistry)
        assert REGISTRY.benchmark == "Read Primitives"

    def test_registry_has_queries(self):
        """Registry should contain queries."""
        assert len(REGISTRY) > 0, "Registry should contain at least one query"

    def test_get_dataframe_queries_returns_registry(self):
        """get_dataframe_queries should return the registry."""
        registry = get_dataframe_queries()
        assert registry is REGISTRY

    def test_all_queries_have_both_implementations(self):
        """All registered queries should have both expression and pandas implementations."""
        for query in REGISTRY.get_all_queries():
            assert query.has_expression_impl(), f"Query {query.query_id} missing expression_impl"
            assert query.has_pandas_impl(), f"Query {query.query_id} missing pandas_impl"

    def test_all_queries_have_valid_categories(self):
        """All registered queries should have at least one valid category."""
        for query in REGISTRY.get_all_queries():
            assert len(query.categories) > 0, f"Query {query.query_id} has no categories"
            for category in query.categories:
                assert isinstance(category, QueryCategory), (
                    f"Query {query.query_id} has invalid category type: {type(category)}"
                )


class TestSkipLists:
    """Test the skip/exclusion lists."""

    def test_skip_for_dataframe_contains_correlated_subqueries(self):
        """SKIP_FOR_DATAFRAME contains the correlated-subquery + PySpark-only-aggregate skip set."""
        # 3 correlated-subquery queries + 2 PySpark-only approximate-aggregate
        # queries (array-quantile and frequency-based top-K). The HLL distinct
        # pair (`approx_count_distinct_*`) and `approx_quantile_groupby` now
        # have DataFrame impls. Some pandas-family engines use exact
        # fallbacks where their API has no matching sketch aggregate.
        assert len(SKIP_FOR_DATAFRAME) == 5, f"Should have 5 skip entries, got {len(SKIP_FOR_DATAFRAME)}"

    def test_skip_for_dataframe_has_expected_queries(self):
        """SKIP_FOR_DATAFRAME contains correlated subqueries and PySpark-only approximate-aggregates."""
        expected = {
            "optimizer_exists_to_semijoin",  # Correlated EXISTS
            "optimizer_in_to_exists",  # Correlated IN
            "optimizer_scalar_subquery_flattening",  # Correlated scalar subquery
            "approx_quantiles_array",  # PySpark-only at the DataFrame layer
            "approx_top_k_lineitem",  # PySpark 4.1+ only at the DataFrame layer
        }
        assert set(SKIP_FOR_DATAFRAME) == expected, (
            f"Skip list should contain correlated-subquery + PySpark-only approximate-aggregates. "
            f"Expected: {expected}, got: {set(SKIP_FOR_DATAFRAME)}"
        )

    def test_get_skip_for_dataframe_returns_copy(self):
        """get_skip_for_dataframe should return a copy, not the original list."""
        result = get_skip_for_dataframe()
        assert result == SKIP_FOR_DATAFRAME
        assert result is not SKIP_FOR_DATAFRAME

    def test_skip_for_expression_family_is_empty(self):
        """SKIP_FOR_EXPRESSION_FAMILY is empty - platform-specific skips are in SKIP_FOR_POLARS etc."""
        assert isinstance(SKIP_FOR_EXPRESSION_FAMILY, list)
        assert len(SKIP_FOR_EXPRESSION_FAMILY) == 0, (
            f"SKIP_FOR_EXPRESSION_FAMILY should be empty, got {SKIP_FOR_EXPRESSION_FAMILY}"
        )

    def test_skip_for_expression_family_all_in_registry(self):
        """All queries in SKIP_FOR_EXPRESSION_FAMILY must exist in the registry."""
        registry_ids = {q.query_id for q in REGISTRY.get_all_queries()}
        for query_id in SKIP_FOR_EXPRESSION_FAMILY:
            assert query_id in registry_ids, (
                f"Skip list entry '{query_id}' not found in registry. Was it renamed or removed?"
            )

    def test_skip_for_expression_family_no_overlap_with_dataframe(self):
        """SKIP_FOR_EXPRESSION_FAMILY should not overlap with SKIP_FOR_DATAFRAME."""
        overlap = set(SKIP_FOR_EXPRESSION_FAMILY) & set(SKIP_FOR_DATAFRAME)
        assert not overlap, (
            f"Queries in both skip lists (redundant): {overlap}. "
            f"Move to SKIP_FOR_DATAFRAME if they should be skipped for all platforms."
        )

    def test_get_skip_for_expression_family_returns_copy(self):
        """get_skip_for_expression_family should return a copy, not the original list."""
        result = get_skip_for_expression_family()
        assert result == SKIP_FOR_EXPRESSION_FAMILY
        assert result is not SKIP_FOR_EXPRESSION_FAMILY

    def test_skip_lists_have_no_duplicates(self):
        """Neither skip list should contain duplicate entries."""
        assert len(SKIP_FOR_DATAFRAME) == len(set(SKIP_FOR_DATAFRAME)), "SKIP_FOR_DATAFRAME has duplicates"
        assert len(SKIP_FOR_EXPRESSION_FAMILY) == len(set(SKIP_FOR_EXPRESSION_FAMILY)), (
            "SKIP_FOR_EXPRESSION_FAMILY has duplicates"
        )


class TestBenchmarkIntegration:
    """Test integration with ReadPrimitivesBenchmark class."""

    def test_benchmark_has_get_dataframe_queries_method(self):
        """ReadPrimitivesBenchmark should have get_dataframe_queries method."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        assert hasattr(benchmark, "get_dataframe_queries")

    def test_benchmark_get_dataframe_queries_returns_registry(self):
        """Benchmark.get_dataframe_queries should return the registry."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        registry = benchmark.get_dataframe_queries()
        assert isinstance(registry, QueryRegistry)
        assert registry is REGISTRY

    def test_benchmark_has_get_dataframe_skip_queries_method(self):
        """ReadPrimitivesBenchmark should have get_dataframe_skip_queries method."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        assert hasattr(benchmark, "get_dataframe_skip_queries")

    def test_benchmark_get_dataframe_skip_queries_returns_list(self):
        """Benchmark.get_dataframe_skip_queries should return skip list."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        skip_list = benchmark.get_dataframe_skip_queries()
        assert isinstance(skip_list, list)
        # 3 correlated-subquery queries + 2 PySpark-only approximate-aggregate
        # queries (array-quantile and frequency-based top-K).
        assert len(skip_list) == 5

    def test_benchmark_has_get_expression_family_skip_queries_method(self):
        """ReadPrimitivesBenchmark should have get_expression_family_skip_queries method."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        assert hasattr(benchmark, "get_expression_family_skip_queries")

    def test_benchmark_get_expression_family_skip_queries_returns_list(self):
        """Benchmark.get_expression_family_skip_queries should return empty list."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        skip_list = benchmark.get_expression_family_skip_queries()
        assert isinstance(skip_list, list)
        assert len(skip_list) == 0  # Platform-specific skips moved to SKIP_FOR_POLARS etc.

    def test_benchmark_get_expression_family_skip_queries_matches_constant(self):
        """Benchmark method should return same queries as the module constant."""
        benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
        skip_list = benchmark.get_expression_family_skip_queries()
        assert set(skip_list) == set(SKIP_FOR_EXPRESSION_FAMILY)


class TestQueryCategories:
    """Test query categorization."""

    def test_has_aggregation_queries(self):
        """Registry should have aggregation queries."""
        agg_queries = REGISTRY.get_queries_by_category(QueryCategory.AGGREGATE)
        assert len(agg_queries) > 0

    def test_has_filter_queries(self):
        """Registry should have filter queries."""
        filter_queries = REGISTRY.get_queries_by_category(QueryCategory.FILTER)
        assert len(filter_queries) > 0

    def test_has_sort_queries(self):
        """Registry should have sort queries."""
        sort_queries = REGISTRY.get_queries_by_category(QueryCategory.SORT)
        assert len(sort_queries) > 0

    def test_has_window_queries(self):
        """Registry should have window queries."""
        window_queries = REGISTRY.get_queries_by_category(QueryCategory.WINDOW)
        assert len(window_queries) > 0

    def test_has_join_queries(self):
        """Registry should have join queries."""
        join_queries = REGISTRY.get_queries_by_category(QueryCategory.JOIN)
        assert len(join_queries) > 0


class TestPlatformSupport:
    """Test platform support for queries."""

    def test_all_queries_support_polars(self):
        """All queries should support Polars (expression family)."""
        for query in REGISTRY.get_all_queries():
            assert query.supports_platform("polars"), f"Query {query.query_id} should support Polars"

    def test_all_queries_support_pandas(self):
        """All queries should support Pandas (pandas family)."""
        for query in REGISTRY.get_all_queries():
            assert query.supports_platform("pandas"), f"Query {query.query_id} should support Pandas"

    def test_all_queries_support_pyspark(self):
        """All queries should support PySpark (expression family)."""
        for query in REGISTRY.get_all_queries():
            assert query.supports_platform("pyspark"), f"Query {query.query_id} should support PySpark"


class TestQueryMetadata:
    """Test query metadata."""

    def test_all_queries_have_query_id(self):
        """All queries should have a non-empty query_id."""
        for query in REGISTRY.get_all_queries():
            assert query.query_id, "Query should have a query_id"
            assert isinstance(query.query_id, str)

    def test_all_queries_have_query_name(self):
        """All queries should have a non-empty query_name."""
        for query in REGISTRY.get_all_queries():
            assert query.query_name, f"Query {query.query_id} should have a query_name"

    def test_all_queries_have_description(self):
        """All queries should have a non-empty description."""
        for query in REGISTRY.get_all_queries():
            assert query.description, f"Query {query.query_id} should have a description"

    def test_query_ids_are_unique(self):
        """All query IDs should be unique."""
        query_ids = REGISTRY.get_query_ids()
        assert len(query_ids) == len(set(query_ids)), "Query IDs should be unique"


class TestSqlDataframeParity:
    """Test that SQL catalog and DataFrame registry stay in sync."""

    def test_all_dataframe_queries_have_sql_counterpart(self):
        """Every DataFrame query (minus SKIP_FOR_DATAFRAME) should have a SQL catalog entry."""
        from benchbox.core.read_primitives.queries import ReadPrimitivesQueryManager

        sql_ids = set(ReadPrimitivesQueryManager().get_all_queries().keys())
        df_ids = {q.query_id for q in REGISTRY.get_all_queries()}
        skip_ids = set(SKIP_FOR_DATAFRAME)

        # DataFrame queries that should have SQL counterparts
        df_expected_in_sql = df_ids - skip_ids
        missing_sql = df_expected_in_sql - sql_ids
        assert not missing_sql, (
            f"DataFrame queries without SQL catalog counterpart: {sorted(missing_sql)}. "
            f"Add SQL entries to catalog/queries.yaml to maintain parity."
        )

    def test_all_sql_queries_have_dataframe_counterpart(self):
        """Every SQL query (minus optimizer/SQL-only) should have a DataFrame registry entry."""
        from benchbox.core.read_primitives.queries import ReadPrimitivesQueryManager

        sql_ids = set(ReadPrimitivesQueryManager().get_all_queries().keys())
        df_ids = {q.query_id for q in REGISTRY.get_all_queries()}
        skip_ids = set(SKIP_FOR_DATAFRAME)

        # SQL queries that should have DataFrame counterparts (excluding skipped)
        sql_expected_in_df = sql_ids - skip_ids
        missing_df = sql_expected_in_df - df_ids
        assert not missing_df, (
            f"SQL queries without DataFrame registry counterpart: {sorted(missing_df)}. "
            f"Add DataFrame implementations to dataframe_queries.py or add to SKIP_FOR_DATAFRAME."
        )


class TestQueryImplementationSignatures:
    """Test that query implementations have correct signatures."""

    def test_expression_impls_are_callable(self):
        """All expression implementations should be callable."""
        for query in REGISTRY.get_all_queries():
            impl = query.expression_impl
            assert callable(impl), f"Query {query.query_id} expression_impl should be callable"

    def test_pandas_impls_are_callable(self):
        """All pandas implementations should be callable."""
        for query in REGISTRY.get_all_queries():
            impl = query.pandas_impl
            assert callable(impl), f"Query {query.query_id} pandas_impl should be callable"
