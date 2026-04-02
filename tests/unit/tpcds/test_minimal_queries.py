"""Minimal TPC-DS queries tests for query manager interface.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.tpcds.queries import TPCDSQueryManager


@pytest.fixture(autouse=True)
def fake_dsqgen(monkeypatch):
    """Stub out dsqgen dependency with deterministic SQL."""

    class FakeDSQGen:
        def generate(self, query_id, **_):
            return f"SELECT {query_id} AS q{query_id}"

        def generate_with_parameters(self, query_id, parameters, **_):
            return f"SELECT {query_id} /* params:{parameters} */"

        def get_query_variations(self, query_id):
            base = str(query_id)
            return [base, f"{base}a"]

        def validate_query_id(self, query_id):
            try:
                value = int(query_id)
            except (TypeError, ValueError):
                return False
            return 1 <= value <= 99

    monkeypatch.setattr("benchbox.core.tpcds.queries.DSQGenBinary", lambda: FakeDSQGen())


# Mark all tests in this file as unit tests and skip if TPC-DS binaries unavailable
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCDSQueryManagerMinimal:
    """Test minimal TPC-DS query manager interface."""

    def test_queries_initialization(self):
        """Test query manager can be initialized."""
        queries = TPCDSQueryManager()
        assert queries.dsqgen is not None, "dsqgen should be set after initialization"
        assert queries.get_query(1) is not None, "Should be able to retrieve query 1"

    def test_get_query_basic(self):
        """Test getting processed queries."""
        queries = TPCDSQueryManager()

        query = queries.get_query(1)
        assert isinstance(query, str)
        assert len(query) > 0

        # Should contain SQL content
        query_lower = query.lower()
        assert "select" in query_lower or "with" in query_lower

    def test_get_query_multiple(self):
        """Test getting multiple queries."""
        queries = TPCDSQueryManager()

        query1 = queries.get_query(1)
        query2 = queries.get_query(2)
        query99 = queries.get_query(99)

        assert isinstance(query1, str)
        assert isinstance(query2, str)
        assert isinstance(query99, str)

        # Queries should be different
        assert query1 != query2
        assert query1 != query99

    def test_get_query_error_handling(self):
        """Test query error handling."""
        queries = TPCDSQueryManager()

        # Test invalid query IDs
        with pytest.raises(ValueError):
            queries.get_query(0)

        with pytest.raises(ValueError):
            queries.get_query(100)

        with pytest.raises(ValueError):
            queries.get_query(-1)

        with pytest.raises(ValueError):
            queries.get_query(999)

    def test_get_all_queries(self):
        """Test getting all queries."""
        queries = TPCDSQueryManager()

        all_queries = queries.get_all_queries()
        assert isinstance(all_queries, dict)
        assert len(all_queries) > 0

        # Should have numeric keys
        for query_id in all_queries:
            assert isinstance(query_id, int)
            assert 1 <= query_id <= 99

        # Should have string queries
        for query in all_queries.values():
            assert isinstance(query, str)
            assert len(query) > 0

    def test_query_with_parameters(self):
        """Test getting queries with parameters."""
        queries = TPCDSQueryManager()

        # Test with seed
        query_with_seed = queries.get_query(1, seed=42)
        assert isinstance(query_with_seed, str)
        assert len(query_with_seed) > 0

        # Test with scale factor
        query_with_scale = queries.get_query(1, scale_factor=2.0)
        assert isinstance(query_with_scale, str)
        assert len(query_with_scale) > 0

        # Test with both
        query_with_both = queries.get_query(1, seed=42, scale_factor=2.0)
        assert isinstance(query_with_both, str)
        assert len(query_with_both) > 0

    def test_available_queries_completeness(self):
        """Test that queries are available."""
        queries = TPCDSQueryManager()

        all_queries = queries.get_all_queries()

        # TPC-DS should have many queries
        assert len(all_queries) > 90  # Most queries should be available

        # Test some key queries
        for query_id in [1, 2, 3, 10, 50, 99]:
            assert query_id in all_queries

    def test_query_content_validation(self):
        """Test query content validation."""
        queries = TPCDSQueryManager()

        # Test a few specific queries
        for query_id in [1, 2, 3, 10, 50, 99]:
            query = queries.get_query(query_id)

            # Should be non-empty
            assert len(query.strip()) > 0

            # Should contain SQL-like content
            query_lower = query.lower()
            has_sql = any(
                keyword in query_lower
                for keyword in [
                    "select",
                    "with",
                    "from",
                    "where",
                    "group by",
                    "order by",
                ]
            )
            assert has_sql, f"Query {query_id} doesn't contain SQL keywords"

    def test_query_consistency(self):
        """Test query consistency across calls."""
        queries = TPCDSQueryManager()

        # Get same query multiple times
        query1_call1 = queries.get_query(1)
        query1_call2 = queries.get_query(1)
        query1_call3 = queries.get_query(1)

        # Should be identical (without seed)
        assert query1_call1 == query1_call2
        assert query1_call1 == query1_call3

    def test_queries_interface_independence(self):
        """Test queries interface works independently."""
        queries1 = TPCDSQueryManager()
        queries2 = TPCDSQueryManager()

        # Both should work independently
        query1_q1 = queries1.get_query(1)
        query1_q2 = queries2.get_query(1)

        assert query1_q1 == query1_q2

        # Should be able to get different queries
        query2_q1 = queries1.get_query(2)
        query2_q2 = queries2.get_query(2)

        assert query2_q1 == query2_q2
        assert query1_q1 != query2_q1

    def test_multiple_instances_match_behavior(self):
        """Independent manager instances should behave consistently."""
        queries_a = TPCDSQueryManager()
        queries_b = TPCDSQueryManager()

        assert type(queries_a) == type(queries_b)
        assert queries_a.get_query(1) == queries_b.get_query(1)
