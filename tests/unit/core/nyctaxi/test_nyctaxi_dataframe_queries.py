"""Unit tests for NYC Taxi DataFrame query implementations.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

from benchbox.core.dataframe.query import QueryCategory

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


ALL_QUERY_IDS = [f"Q{i}" for i in range(1, 26)]


class TestNYCTaxiQueryRegistry:
    """Tests for NYC Taxi DataFrame query registry."""

    def test_registry_imports_successfully(self):
        """Test that the registry can be imported."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        assert len(NYCTAXI_DATAFRAME_QUERIES) > 0
        assert hasattr(NYCTAXI_DATAFRAME_QUERIES, "get_query_ids")

    def test_registry_has_25_queries(self):
        """Test that all 25 NYC Taxi queries are registered."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        queries = NYCTAXI_DATAFRAME_QUERIES.get_all_queries()
        assert len(queries) == 25

    def test_registry_benchmark_name(self):
        """Test that registry has correct benchmark name."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        assert NYCTAXI_DATAFRAME_QUERIES.benchmark == "nyctaxi"

    def test_get_query_by_id(self):
        """Test getting a query by ID."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        query = get_nyctaxi_query("Q1")
        assert query is not None
        assert query.query_id == "Q1"

    def test_get_nonexistent_query(self):
        """Test getting a query that doesn't exist."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        query = get_nyctaxi_query("Q99")
        assert query is None

    def test_list_queries(self):
        """Test listing all queries."""
        from benchbox.core.nyctaxi.dataframe_queries import list_nyctaxi_queries

        queries = list_nyctaxi_queries()
        assert len(queries) == 25

    @pytest.mark.parametrize("query_id", ALL_QUERY_IDS)
    def test_all_queries_registered(self, query_id):
        """Test that each NYC Taxi query is registered."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        query = get_nyctaxi_query(query_id)
        assert query is not None, f"Query {query_id} should be registered"

    def test_queries_have_both_implementations(self):
        """Test that all queries have both expression and pandas implementations."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        for query in NYCTAXI_DATAFRAME_QUERIES.get_all_queries():
            assert query.expression_impl is not None, f"{query.query_id} missing expression impl"
            assert query.pandas_impl is not None, f"{query.query_id} missing pandas impl"

    def test_all_queries_callable(self):
        """Test that all query implementations are callable."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        for query in NYCTAXI_DATAFRAME_QUERIES.get_all_queries():
            assert callable(query.expression_impl), f"{query.query_id} expression_impl not callable"
            assert callable(query.pandas_impl), f"{query.query_id} pandas_impl not callable"

    def test_query_descriptions_not_empty(self):
        """Test that all queries have descriptions."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        for query in NYCTAXI_DATAFRAME_QUERIES.get_all_queries():
            assert query.description, f"{query.query_id} missing description"
            assert len(query.description) > 10, f"{query.query_id} description too short"

    def test_query_names_not_empty(self):
        """Test that all queries have names."""
        from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES

        for query in NYCTAXI_DATAFRAME_QUERIES.get_all_queries():
            assert query.query_name, f"{query.query_id} missing query_name"


class TestNYCTaxiQueryCategories:
    """Tests for NYC Taxi query category assignments."""

    def test_temporal_queries_have_analytical(self):
        """Test that Q1-Q4 have ANALYTICAL category."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        for i in range(1, 5):
            query = get_nyctaxi_query(f"Q{i}")
            assert QueryCategory.ANALYTICAL in query.categories, f"Q{i} should have ANALYTICAL"

    def test_geographic_queries_have_join(self):
        """Test that Q5-Q8 have JOIN or MULTI_JOIN category."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        for i in range(5, 9):
            query = get_nyctaxi_query(f"Q{i}")
            assert QueryCategory.JOIN in query.categories or QueryCategory.MULTI_JOIN in query.categories, (
                f"Q{i} should have JOIN or MULTI_JOIN"
            )

    def test_financial_queries_have_aggregate(self):
        """Test that Q9-Q12 have AGGREGATE category."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        for i in range(9, 13):
            query = get_nyctaxi_query(f"Q{i}")
            assert QueryCategory.AGGREGATE in query.categories, f"Q{i} should have AGGREGATE"

    def test_complex_queries_have_analytical(self):
        """Test that Q19-Q22 have ANALYTICAL category."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        for i in range(19, 23):
            query = get_nyctaxi_query(f"Q{i}")
            assert QueryCategory.ANALYTICAL in query.categories, f"Q{i} should have ANALYTICAL"

    def test_point_queries_have_filter_and_aggregate(self):
        """Test that point queries Q23-Q24 have FILTER and AGGREGATE."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        for i in [23, 24]:
            query = get_nyctaxi_query(f"Q{i}")
            assert QueryCategory.FILTER in query.categories, f"Q{i} should have FILTER"
            assert QueryCategory.AGGREGATE in query.categories, f"Q{i} should have AGGREGATE"

    def test_baseline_scan_query(self):
        """Test that Q25 has SCAN category."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        query = get_nyctaxi_query("Q25")
        assert QueryCategory.SCAN in query.categories, "Q25 should have SCAN"

    def test_double_join_query(self):
        """Test that Q7 has MULTI_JOIN category."""
        from benchbox.core.nyctaxi.dataframe_queries import get_nyctaxi_query

        query = get_nyctaxi_query("Q7")
        assert QueryCategory.MULTI_JOIN in query.categories, "Q7 should have MULTI_JOIN"


class TestNYCTaxiParameters:
    """Tests for NYC Taxi query parameters."""

    def test_all_queries_have_parameters(self):
        """Test that all 25 queries have parameter entries."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import NYCTAXI_DEFAULT_PARAMS

        assert len(NYCTAXI_DEFAULT_PARAMS) == 25

    @pytest.mark.parametrize("query_id", ALL_QUERY_IDS)
    def test_parameter_entries_exist(self, query_id):
        """Test that each query has a parameter entry."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import NYCTAXI_DEFAULT_PARAMS

        assert query_id in NYCTAXI_DEFAULT_PARAMS, f"Missing parameters for {query_id}"

    def test_date_range_parameters(self):
        """Test that date-range queries have start_date and end_date."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import NYCTAXI_DEFAULT_PARAMS

        for qid in [f"Q{i}" for i in range(1, 25)]:
            params = NYCTAXI_DEFAULT_PARAMS[qid]
            assert "start_date" in params, f"{qid} missing start_date"
            assert "end_date" in params, f"{qid} missing end_date"

    def test_q24_has_zone_id(self):
        """Test that Q24 has a zone_id parameter."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import NYCTAXI_DEFAULT_PARAMS

        assert "zone_id" in NYCTAXI_DEFAULT_PARAMS["Q24"]
        assert NYCTAXI_DEFAULT_PARAMS["Q24"]["zone_id"] == 132

    def test_q25_has_no_parameters(self):
        """Test that Q25 has empty parameters (full scan)."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import NYCTAXI_DEFAULT_PARAMS

        assert NYCTAXI_DEFAULT_PARAMS["Q25"] == {}

    def test_get_parameters_returns_container(self):
        """Test that get_parameters returns NYCTaxiParameters."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import NYCTaxiParameters, get_parameters

        result = get_parameters("Q1")
        assert isinstance(result, NYCTaxiParameters)
        assert result.query_id == "Q1"

    def test_get_parameters_with_defaults(self):
        """Test that NYCTaxiParameters.get works with defaults."""
        from benchbox.core.nyctaxi.dataframe_queries.parameters import get_parameters

        result = get_parameters("Q1")
        assert result.get("start_date") == "2019-01-01"
        assert result.get("nonexistent", "fallback") == "fallback"


class TestNYCTaxiBenchmarkRegistry:
    """Tests for NYC Taxi DataFrame support in benchmark registry."""

    def test_nyctaxi_supports_dataframe(self):
        """Test that NYC Taxi is marked as supporting DataFrames."""
        from benchbox.core.benchmark_registry import get_benchmark_metadata

        meta = get_benchmark_metadata("nyctaxi")
        assert meta is not None
        assert meta.get("supports_dataframe") is True
