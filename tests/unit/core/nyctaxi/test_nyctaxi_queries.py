"""Tests for NYC Taxi queries module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime

import pytest

from benchbox.core.nyctaxi.queries import QUERIES, NYCTaxiQueryManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueriesDefinition:
    """Tests for QUERIES dictionary."""

    def test_queries_not_empty(self):
        """Should have at least one query defined."""
        assert len(QUERIES) > 0, "QUERIES should not be empty"

    def test_all_queries_have_required_fields(self):
        """All queries should have required metadata fields."""
        required_fields = {"id", "name", "description", "category", "sql"}
        for query_id, query_def in QUERIES.items():
            missing = required_fields - set(query_def.keys())
            assert not missing, f"Query {query_id} missing fields: {missing}"

    def test_all_queries_have_unique_ids(self):
        """All queries should have unique numeric IDs."""
        ids = [qdef["id"] for qdef in QUERIES.values()]
        assert len(ids) == len(set(ids)), "Duplicate query IDs found"

    def test_all_queries_have_valid_categories(self):
        """All queries should have valid categories."""
        valid_categories = {
            "temporal",
            "geographic",
            "financial",
            "characteristics",
            "rates",
            "vendor",
            "complex",
            "point",
            "baseline",
        }
        for query_id, query_def in QUERIES.items():
            assert query_def["category"] in valid_categories, (
                f"Query {query_id} has invalid category: {query_def['category']}"
            )


class TestQueryCategories:
    """Tests for query categories."""

    def test_temporal_queries(self):
        """Should have temporal category queries."""
        temporal = [q for q, d in QUERIES.items() if d["category"] == "temporal"]
        assert len(temporal) >= 3

    def test_geographic_queries(self):
        """Should have geographic category queries."""
        geographic = [q for q, d in QUERIES.items() if d["category"] == "geographic"]
        assert len(geographic) >= 4

    def test_financial_queries(self):
        """Should have financial category queries."""
        financial = [q for q, d in QUERIES.items() if d["category"] == "financial"]
        assert len(financial) >= 3

    def test_complex_queries(self):
        """Should have complex category queries."""
        complex_queries = [q for q, d in QUERIES.items() if d["category"] == "complex"]
        assert len(complex_queries) >= 3


class TestNYCTaxiQueryManager:
    """Tests for NYCTaxiQueryManager class."""

    @pytest.fixture
    def manager(self, seed, start_date, end_date):
        """Create a query manager for testing."""
        return NYCTaxiQueryManager(
            start_date=start_date,
            end_date=end_date,
            seed=seed,
        )

    def test_init_default_dates(self, seed):
        """Should use default dates if not provided."""
        manager = NYCTaxiQueryManager(seed=seed)
        assert manager.start_date == datetime(2019, 1, 1)
        assert manager.end_date == datetime(2019, 12, 31)

    def test_init_custom_dates(self, start_date, end_date, seed):
        """Should accept custom dates."""
        manager = NYCTaxiQueryManager(
            start_date=start_date,
            end_date=end_date,
            seed=seed,
        )
        assert manager.start_date == start_date
        assert manager.end_date == end_date

    def test_get_query_returns_string(self, manager):
        """get_query should return a parameterized SQL string."""
        query = manager.get_query("trips-per-hour")
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "FROM trips" in query

    def test_get_query_fills_parameters(self, manager):
        """get_query should fill in date parameters."""
        query = manager.get_query("trips-per-hour")
        # Should not have unfilled placeholders
        assert "{" not in query
        assert "}" not in query
        # Should have actual date values
        assert "2019" in query

    def test_get_query_with_param_override(self, manager):
        """get_query should accept parameter overrides."""
        query = manager.get_query("zone-detail", params={"zone_id": 161})
        assert "161" in query

    def test_get_query_unknown_raises(self, manager):
        """get_query should raise ValueError for unknown query."""
        with pytest.raises(ValueError, match="Unknown query"):
            manager.get_query("nonexistent_query")

    def test_get_query_error_shows_available(self, manager):
        """Error message should list available queries."""
        with pytest.raises(ValueError) as exc_info:
            manager.get_query("bad_query")
        assert "trips-per-hour" in str(exc_info.value)

    def test_get_queries_returns_all(self, manager):
        """get_queries should return all queries."""
        queries = manager.get_queries()
        assert len(queries) == len(QUERIES)
        assert all(isinstance(q, str) for q in queries.values())

    def test_get_query_info(self, manager):
        """get_query_info should return query metadata."""
        info = manager.get_query_info("trips-per-hour")
        assert info["id"] == "1"
        assert info["category"] == "temporal"
        assert "description" in info

    def test_get_query_info_unknown_raises(self, manager):
        """get_query_info should raise for unknown query."""
        with pytest.raises(ValueError, match="Unknown query"):
            manager.get_query_info("unknown")

    def test_get_queries_by_category(self, manager):
        """get_queries_by_category should filter by category."""
        temporal = manager.get_queries_by_category("temporal")
        assert "trips-per-hour" in temporal
        # Verify all returned are actually temporal
        for qid in temporal:
            assert QUERIES[qid]["category"] == "temporal"

    def test_get_queries_by_category_empty(self, manager):
        """get_queries_by_category should return empty for unknown category."""
        result = manager.get_queries_by_category("nonexistent")
        assert result == []

    def test_get_categories(self):
        """get_categories should return all unique categories."""
        manager = NYCTaxiQueryManager()
        categories = manager.get_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0
        assert "temporal" in categories
        assert "geographic" in categories

    def test_get_query_count(self):
        """get_query_count should return total query count (Yellow-only default)."""
        manager = NYCTaxiQueryManager()
        count = manager.get_query_count()
        assert count == len(QUERIES)


class TestQueryParameterGeneration:
    """Tests for query parameter generation."""

    @pytest.fixture
    def manager(self, seed, start_date, end_date):
        """Create a query manager."""
        return NYCTaxiQueryManager(start_date=start_date, end_date=end_date, seed=seed)

    def test_date_params_within_dataset(self, manager):
        """Date parameters should be within dataset bounds."""
        for _ in range(10):
            query = manager.get_query("trips-per-hour")
            assert "2019" in query

    def test_zone_id_from_popular_zones(self, manager):
        """Zone ID should be from popular zones list."""
        query = manager.get_query("zone-detail")
        # Just verify it has a zone ID
        assert "pickup_location_id =" in query

    def test_reproducible_with_seed(self, start_date, end_date):
        """Same seed should produce same parameters."""
        manager1 = NYCTaxiQueryManager(start_date=start_date, end_date=end_date, seed=42)
        manager2 = NYCTaxiQueryManager(start_date=start_date, end_date=end_date, seed=42)

        query1 = manager1.get_query("trips-per-hour")
        query2 = manager2.get_query("trips-per-hour")
        assert query1 == query2


class TestQuerySQLValidity:
    """Tests that generated SQL is syntactically valid."""

    @pytest.fixture
    def manager(self, seed, start_date, end_date):
        """Create a query manager."""
        return NYCTaxiQueryManager(start_date=start_date, end_date=end_date, seed=seed)

    def test_all_queries_have_select(self, manager):
        """All queries should have SELECT clause."""
        for query_id in QUERIES:
            query = manager.get_query(query_id)
            assert "SELECT" in query.upper()

    def test_all_queries_have_from(self, manager):
        """All queries should have FROM clause."""
        for query_id in QUERIES:
            query = manager.get_query(query_id)
            assert "FROM" in query.upper()

    def test_temporal_queries_have_group_by(self, manager):
        """Temporal queries should have GROUP BY."""
        temporal_queries = [q for q, d in QUERIES.items() if d["category"] == "temporal"]
        for query_id in temporal_queries:
            query = manager.get_query(query_id)
            assert "GROUP BY" in query.upper()

    def test_geographic_queries_use_joins(self, manager):
        """Geographic queries should JOIN taxi_zones."""
        geographic_queries = [q for q, d in QUERIES.items() if d["category"] == "geographic"]
        for query_id in geographic_queries:
            query = manager.get_query(query_id)
            assert "JOIN" in query.upper() or "taxi_zones" in query.lower()
