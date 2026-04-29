"""Test Read Primitives query manager variant retrieval functionality.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.query_catalog_base import QuerySkippedError
from benchbox.core.read_primitives.queries import ReadPrimitivesQueryManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueryManagerVariantRetrieval:
    """Test query manager get_query() with dialect-specific variants."""

    @pytest.fixture
    def mock_catalog_with_variants(self, monkeypatch, tmp_path):
        """Create a mock catalog with variant queries."""
        catalog_yaml = """
version: 1
queries:
  - id: query_base_only
    category: test
    sql: SELECT * FROM orders

  - id: query_with_duckdb_variant
    category: test
    sql: SELECT * FROM orders
    variants:
      duckdb: SELECT * FROM orders USING SAMPLE 10%

  - id: query_with_multiple_variants
    category: test
    sql: SELECT * FROM orders
    variants:
      duckdb: SELECT * FROM orders USING SAMPLE 10%
      bigquery: SELECT * FROM `orders` TABLESAMPLE SYSTEM (10 PERCENT)
      snowflake: SELECT * FROM orders SAMPLE (10)

  - id: query_skip_on_duckdb
    category: test
    sql: SELECT JSON_EXTRACT(data, '$.field') FROM table
    skip_on: [duckdb, sqlite]

  - id: query_with_variant_and_skip
    category: test
    sql: SELECT * FROM orders
    variants:
      bigquery: SELECT * FROM `orders`
    skip_on: [sqlite]
"""
        catalog_file = tmp_path / "queries.yaml"
        catalog_file.write_text(catalog_yaml)

        import importlib.resources

        class MockPath:
            def __init__(self, path):
                self.path = path

            def joinpath(self, name):
                return self.path / name

            def open(self, *args, **kwargs):
                return open(self.path / "queries.yaml", *args, **kwargs)

        monkeypatch.setattr(importlib.resources, "files", lambda pkg: MockPath(tmp_path))

    def test_get_query_without_dialect_returns_base(self, mock_catalog_with_variants):
        """Test get_query() without dialect returns base SQL."""
        manager = ReadPrimitivesQueryManager()

        query = manager.get_query("query_with_duckdb_variant")
        assert query == "SELECT * FROM orders"
        assert "USING SAMPLE" not in query

    def test_get_query_with_matching_variant_returns_variant(self, mock_catalog_with_variants):
        """Test get_query() with matching dialect returns variant SQL."""
        manager = ReadPrimitivesQueryManager()

        query = manager.get_query("query_with_duckdb_variant", dialect="duckdb")
        assert "USING SAMPLE 10%" in query

    def test_get_query_with_non_matching_variant_returns_base(self, mock_catalog_with_variants):
        """Test get_query() with non-matching dialect returns base SQL."""
        manager = ReadPrimitivesQueryManager()

        # Query has duckdb variant but request bigquery
        query = manager.get_query("query_with_duckdb_variant", dialect="bigquery")
        assert query == "SELECT * FROM orders"
        assert "USING SAMPLE" not in query

    def test_get_query_with_multiple_variants_returns_correct_one(self, mock_catalog_with_variants):
        """Test get_query() returns correct variant when multiple exist."""
        manager = ReadPrimitivesQueryManager()

        duckdb_query = manager.get_query("query_with_multiple_variants", dialect="duckdb")
        assert "USING SAMPLE" in duckdb_query

        bigquery_query = manager.get_query("query_with_multiple_variants", dialect="bigquery")
        assert "TABLESAMPLE SYSTEM" in bigquery_query

        snowflake_query = manager.get_query("query_with_multiple_variants", dialect="snowflake")
        assert "SAMPLE (10)" in snowflake_query

    def test_get_query_skip_on_raises_query_skipped_error(self, mock_catalog_with_variants):
        """Test get_query() raises QuerySkippedError for skip_on dialects."""
        manager = ReadPrimitivesQueryManager()

        with pytest.raises(QuerySkippedError) as exc_info:
            manager.get_query("query_skip_on_duckdb", dialect="duckdb")

        assert "not supported on dialect" in str(exc_info.value)
        assert "duckdb" in str(exc_info.value).lower()

    def test_get_query_skip_on_with_different_dialect_works(self, mock_catalog_with_variants):
        """Test get_query() works if dialect not in skip_on list."""
        manager = ReadPrimitivesQueryManager()

        # Query skips duckdb and sqlite, but bigquery should work
        query = manager.get_query("query_skip_on_duckdb", dialect="bigquery")
        assert "JSON_EXTRACT" in query

    def test_get_query_dialect_case_insensitive(self, mock_catalog_with_variants):
        """Test get_query() dialect matching is case-insensitive."""
        manager = ReadPrimitivesQueryManager()

        # All these should return the DuckDB variant
        query1 = manager.get_query("query_with_duckdb_variant", dialect="duckdb")
        query2 = manager.get_query("query_with_duckdb_variant", dialect="DuckDB")
        query3 = manager.get_query("query_with_duckdb_variant", dialect="DUCKDB")

        assert query1 == query2 == query3
        assert "USING SAMPLE" in query1

    def test_get_query_skip_on_case_insensitive(self, mock_catalog_with_variants):
        """Test skip_on matching is case-insensitive."""
        manager = ReadPrimitivesQueryManager()

        # All these should raise ValueError
        with pytest.raises(ValueError):
            manager.get_query("query_skip_on_duckdb", dialect="duckdb")

        with pytest.raises(ValueError):
            manager.get_query("query_skip_on_duckdb", dialect="DuckDB")

        with pytest.raises(ValueError):
            manager.get_query("query_skip_on_duckdb", dialect="DUCKDB")

    def test_get_query_base_only_query_with_dialect(self, mock_catalog_with_variants):
        """Test get_query() with dialect on query with no variants returns base."""
        manager = ReadPrimitivesQueryManager()

        query = manager.get_query("query_base_only", dialect="duckdb")
        assert query == "SELECT * FROM orders"

    def test_get_query_invalid_query_id_raises_valueerror(self, mock_catalog_with_variants):
        """Test get_query() with invalid query ID raises ValueError."""
        manager = ReadPrimitivesQueryManager()

        with pytest.raises(ValueError) as exc_info:
            manager.get_query("nonexistent_query_id")

        assert "Invalid query ID" in str(exc_info.value)

    def test_get_query_variant_with_skip_both_present(self, mock_catalog_with_variants):
        """Test query can have both variant and skip_on."""
        manager = ReadPrimitivesQueryManager()

        # Should raise ValueError for sqlite (in skip_on)
        with pytest.raises(ValueError):
            manager.get_query("query_with_variant_and_skip", dialect="sqlite")

        # Should return variant for bigquery
        query = manager.get_query("query_with_variant_and_skip", dialect="bigquery")
        assert "`orders`" in query

        # Should return base for other dialects
        query = manager.get_query("query_with_variant_and_skip", dialect="duckdb")
        assert query == "SELECT * FROM orders"


class TestQueryManagerVariantIntegration:
    """Integration tests for query manager with actual catalog."""

    def test_actual_catalog_variant_lookup_works(self):
        """Test that actual catalog supports dialect variant lookup."""
        manager = ReadPrimitivesQueryManager()

        for query_id in ["map_construction", "map_access", "map_keys_values"]:
            query = manager.get_query(query_id, dialect="datafusion")
            assert "MAP(" in query.upper()
            assert "MAP_FROM_ENTRIES" not in query.upper()

        with pytest.raises(ValueError, match="not supported on dialect"):
            manager.get_query("array_distinct", dialect="datafusion")

    def test_actual_catalog_datafusion_rewrites_for_known_failures(self):
        """DataFusion should use variants for known unsupported base functions."""
        manager = ReadPrimitivesQueryManager()

        intrinsic = manager.get_query("intrinsic_to_date", dialect="datafusion")
        assert "TO_DATE('1995-03-15')" in intrinsic.upper()

        max_by = manager.get_query("max_by_simple", dialect="datafusion")
        assert "ROW_NUMBER()" in max_by.upper()
        assert "MAX_BY" not in max_by.upper()

    def test_actual_catalog_datafusion_skips_unsupported_json_queries(self):
        """DataFusion should explicitly skip JSON queries with no SQL-function support."""
        manager = ReadPrimitivesQueryManager()

        for query_id in ["json_extract_simple", "json_extract_nested", "json_aggregates"]:
            with pytest.raises(ValueError, match="not supported on dialect"):
                manager.get_query(query_id, dialect="datafusion")

    def test_query_manager_initialized_successfully(self):
        """Test query manager initializes with actual catalog."""
        manager = ReadPrimitivesQueryManager()

        # Should have loaded catalog successfully
        assert manager.catalog_version >= 1

        # Should have entries
        all_queries = manager.get_all_queries()
        assert len(all_queries) > 100  # Should have 109 queries

    def test_get_query_with_none_dialect_returns_base(self):
        """Test get_query() with dialect=None returns base query."""
        manager = ReadPrimitivesQueryManager()

        all_queries = manager.get_all_queries()
        first_query_id = list(all_queries.keys())[0]

        query1 = manager.get_query(first_query_id, dialect=None)
        query2 = manager.get_query(first_query_id)

        # Both should return the same base query
        assert query1 == query2
