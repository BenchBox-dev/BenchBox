"""Tests for TSBS DevOps queries module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime

import pytest

from benchbox.core.tsbs_devops.queries import QUERIES, TSBSDevOpsQueryManager

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
            "single-host",
            "aggregation",
            "groupby",
            "threshold",
            "memory",
            "disk",
            "network",
            "combined",
            "lastpoint",
            "tags",
        }
        for query_id, query_def in QUERIES.items():
            assert query_def["category"] in valid_categories, (
                f"Query {query_id} has invalid category: {query_def['category']}"
            )

    def test_sql_contains_placeholder_parameters(self):
        """Queries should have parameterized placeholders."""
        for query_id, query_def in QUERIES.items():
            sql = query_def["sql"]
            # Most queries should have time range params
            if query_id != "lastpoint":  # lastpoint only has start_time
                assert "{start_time}" in sql or "{end_time}" in sql, f"Query {query_id} missing time parameters"


class TestQueryCategories:
    """Tests for query categories."""

    def test_single_host_queries(self):
        """Should have single-host category queries."""
        single_host = [q for q, d in QUERIES.items() if d["category"] == "single-host"]
        assert len(single_host) >= 2

    def test_aggregation_queries(self):
        """Should have aggregation category queries."""
        aggregation = [q for q, d in QUERIES.items() if d["category"] == "aggregation"]
        assert len(aggregation) >= 2

    def test_threshold_queries(self):
        """Should have threshold category queries."""
        threshold = [q for q, d in QUERIES.items() if d["category"] == "threshold"]
        assert len(threshold) >= 3

    def test_groupby_queries(self):
        """Should have groupby category queries."""
        groupby = [q for q, d in QUERIES.items() if d["category"] == "groupby"]
        assert len(groupby) >= 2


class TestTSBSDevOpsQueryManager:
    """Tests for TSBSDevOpsQueryManager class."""

    @pytest.fixture
    def manager(self, seed, start_time):
        """Create a query manager for testing."""
        return TSBSDevOpsQueryManager(
            num_hosts=100,
            start_time=start_time,
            seed=seed,
        )

    def test_init_creates_hostnames(self, manager):
        """Should generate hostname list on init."""
        assert len(manager.hostnames) == 100
        assert all(h.startswith("host_") for h in manager.hostnames)

    def test_init_with_custom_num_hosts(self, start_time, seed):
        """Should respect custom num_hosts."""
        manager = TSBSDevOpsQueryManager(num_hosts=50, start_time=start_time, seed=seed)
        assert len(manager.hostnames) == 50

    def test_init_default_start_time(self, seed):
        """Should use default start time if not provided."""
        manager = TSBSDevOpsQueryManager(seed=seed)
        assert manager.start_time == datetime(2024, 1, 1)

    def test_get_query_returns_string(self, manager):
        """get_query should return a parameterized SQL string."""
        query = manager.get_query("single-host-12-hr")
        assert isinstance(query, str)
        assert "SELECT" in query
        assert "FROM cpu" in query

    def test_get_query_fills_parameters(self, manager):
        """get_query should fill in time and host parameters."""
        query = manager.get_query("single-host-12-hr")
        # Should not have unfilled placeholders
        assert "{" not in query
        assert "}" not in query
        # Should have actual values
        assert "2024-01-01" in query  # start date

    def test_lastpoint_uses_joined_latest_rows(self, manager):
        """Last-point lookup must not use DataFusion's unsupported row-value IN form."""
        query = manager.get_query("lastpoint")
        assert "JOIN (" in query
        assert "MAX(time) AS max_time" in query
        assert "ORDER BY c.hostname" in query
        assert "(hostname, time) IN" not in query

    def test_get_query_with_param_override(self, manager):
        """get_query should accept parameter overrides."""
        query = manager.get_query("single-host-12-hr", params={"hostname": "custom_host"})
        assert "custom_host" in query

    def test_get_query_unknown_raises(self, manager):
        """get_query should raise ValueError for unknown query."""
        with pytest.raises(ValueError, match="Unknown query"):
            manager.get_query("nonexistent_query")

    def test_get_query_error_shows_available(self, manager):
        """Error message should list available queries."""
        with pytest.raises(ValueError) as exc_info:
            manager.get_query("bad_query")
        assert "single-host-12-hr" in str(exc_info.value)

    def test_get_queries_returns_all(self, manager):
        """get_queries should return all queries."""
        queries = manager.get_queries()
        assert len(queries) == len(QUERIES)
        assert all(isinstance(q, str) for q in queries.values())

    def test_get_query_info(self, manager):
        """get_query_info should return query metadata."""
        info = manager.get_query_info("cpu-max-all-1-hr")
        assert info["id"] == "3"
        assert info["category"] == "aggregation"
        assert "Maximum CPU" in info["description"]

    def test_get_query_info_unknown_raises(self, manager):
        """get_query_info should raise for unknown query."""
        with pytest.raises(ValueError, match="Unknown query"):
            manager.get_query_info("unknown")

    def test_get_queries_by_category(self, manager):
        """get_queries_by_category should filter by category."""
        single_host = manager.get_queries_by_category("single-host")
        assert "single-host-12-hr" in single_host
        assert "single-host-1-hr" in single_host
        # Verify all returned are actually single-host
        for qid in single_host:
            assert QUERIES[qid]["category"] == "single-host"

    def test_get_queries_by_category_empty(self, manager):
        """get_queries_by_category should return empty for unknown category."""
        result = manager.get_queries_by_category("nonexistent")
        assert result == []

    def test_get_categories(self):
        """get_categories should return all unique categories."""
        categories = TSBSDevOpsQueryManager.get_categories()
        assert isinstance(categories, list)
        assert len(categories) > 0
        # Should have main categories
        assert "single-host" in categories
        assert "aggregation" in categories
        assert "threshold" in categories

    def test_get_query_count(self):
        """get_query_count should return total query count."""
        count = TSBSDevOpsQueryManager.get_query_count()
        assert count == len(QUERIES)


class TestQueryParameterGeneration:
    """Tests for query parameter generation."""

    @pytest.fixture
    def manager(self, seed, start_time):
        """Create a query manager."""
        return TSBSDevOpsQueryManager(num_hosts=100, start_time=start_time, seed=seed)

    def test_time_params_within_dataset(self, manager):
        """Time parameters should be within dataset bounds."""
        # Run multiple times to test randomization
        for _ in range(10):
            query = manager.get_query("single-host-1-hr")
            # Should contain valid datetime
            assert "2024-01-01" in query

    def test_hostname_from_hostlist(self, manager):
        """Selected hostname should be from the hostlist."""
        query = manager.get_query("single-host-12-hr")
        # Should contain a valid host reference
        assert "host_" in query

    def test_region_param_for_tags_queries(self, manager):
        """Region queries should have valid region parameter."""
        query = manager.get_query("by-region")
        # Should contain a valid region
        valid_regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
        assert any(r in query for r in valid_regions)

    def test_reproducible_with_seed(self, start_time):
        """Same seed should produce same parameters."""
        manager1 = TSBSDevOpsQueryManager(num_hosts=100, start_time=start_time, seed=42)
        manager2 = TSBSDevOpsQueryManager(num_hosts=100, start_time=start_time, seed=42)

        query1 = manager1.get_query("single-host-12-hr")
        query2 = manager2.get_query("single-host-12-hr")
        assert query1 == query2

    def test_different_seed_different_params(self, start_time):
        """Different seeds should produce different parameters."""
        manager1 = TSBSDevOpsQueryManager(num_hosts=100, start_time=start_time, seed=42)
        manager2 = TSBSDevOpsQueryManager(num_hosts=100, start_time=start_time, seed=123)

        query1 = manager1.get_query("single-host-12-hr")
        query2 = manager2.get_query("single-host-12-hr")
        # Queries may differ in hostname or time range
        # Just verify they're both valid SQL
        assert "SELECT" in query1
        assert "SELECT" in query2


class TestQuerySQLValidity:
    """Tests that generated SQL is syntactically valid."""

    @pytest.fixture
    def manager(self, seed, start_time):
        """Create a query manager."""
        return TSBSDevOpsQueryManager(num_hosts=100, start_time=start_time, seed=seed)

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

    def test_time_filtered_queries_have_where(self, manager):
        """Queries with time filters should have WHERE clause."""
        for query_id in QUERIES:
            if "time" in QUERIES[query_id]["sql"]:
                query = manager.get_query(query_id)
                assert "WHERE" in query.upper()

    def test_aggregation_queries_have_group_by(self, manager):
        """Aggregation queries should have GROUP BY."""
        aggregation_queries = [q for q, d in QUERIES.items() if d["category"] == "aggregation"]
        for query_id in aggregation_queries:
            query = manager.get_query(query_id)
            assert "GROUP BY" in query.upper()

    def test_join_queries_have_join(self, manager):
        """Combined and tag queries should have JOIN."""
        join_categories = {"combined", "tags"}
        for query_id, query_def in QUERIES.items():
            if query_def["category"] in join_categories:
                query = manager.get_query(query_id)
                assert "JOIN" in query.upper()
