"""Core tests for Metadata Primitives benchmark functionality.

This module contains unit tests for:
- TestMetadataCatalogLoader: Tests for catalog YAML loading and validation
- TestMetadataPrimitivesQueryManager: Tests for query management and retrieval
- TestMetadataPrimitivesBenchmark: Tests for core benchmark functionality

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.metadata_primitives import (
    MetadataBenchmarkResult,
    MetadataPrimitivesBenchmark,
    MetadataPrimitivesQueryManager,
    MetadataQueryResult,
)
from benchbox.core.metadata_primitives.catalog import (
    MetadataCatalog,
    MetadataQuery,
    load_metadata_catalog,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestMetadataCatalogLoader:
    """Test Metadata Primitives catalog loading functionality."""

    def test_load_catalog(self):
        """Test that the catalog loads successfully."""
        catalog = load_metadata_catalog()
        assert isinstance(catalog, MetadataCatalog)
        assert catalog.version == 1
        assert len(catalog.queries) > 0

    def test_catalog_version(self):
        """Test that catalog has correct version."""
        catalog = load_metadata_catalog()
        assert catalog.version == 1

    def test_catalog_query_structure(self):
        """Test that queries have required fields."""
        catalog = load_metadata_catalog()

        for query_id, query in catalog.queries.items():
            assert isinstance(query, MetadataQuery)
            assert query.id == query_id
            assert len(query.id) > 0
            assert len(query.category) > 0
            assert len(query.sql.strip()) > 0

    def test_catalog_categories(self):
        """Test that expected categories exist."""
        catalog = load_metadata_catalog()

        categories = {q.category for q in catalog.queries.values()}
        expected_categories = {"schema", "column", "stats", "query"}
        assert expected_categories.issubset(categories)

    def test_query_variants(self):
        """Test that query variants are properly structured."""
        catalog = load_metadata_catalog()

        # Find a query with variants
        queries_with_variants = [q for q in catalog.queries.values() if q.variants]
        assert len(queries_with_variants) > 0

        for query in queries_with_variants:
            assert isinstance(query.variants, dict)
            for dialect, sql in query.variants.items():
                assert isinstance(dialect, str)
                assert len(sql.strip()) > 0

    def test_query_skip_on(self):
        """Test that skip_on lists are properly structured."""
        catalog = load_metadata_catalog()

        # Find queries with skip_on
        queries_with_skip = [q for q in catalog.queries.values() if q.skip_on]
        assert len(queries_with_skip) > 0

        for query in queries_with_skip:
            assert isinstance(query.skip_on, list)
            for dialect in query.skip_on:
                assert isinstance(dialect, str)
                assert len(dialect) > 0

    def test_large_catalog_column_count_guards_empty_catalog_division(self):
        """Column-count query should not divide by zero when no catalog tables exist."""
        query = load_metadata_catalog().queries["large_catalog_column_count"]

        assert "NULLIF(COUNT(DISTINCT table_name), 0)" in query.sql
        assert "nullIf(uniq(table), 0)" in query.variants["clickhouse"]


@pytest.mark.unit
class TestMetadataPrimitivesQueryManager:
    """Test Metadata Primitives query manager functionality."""

    def test_query_manager_initialization(self):
        """Test query manager initializes correctly."""
        manager = MetadataPrimitivesQueryManager()
        queries = manager.get_all_queries()
        assert len(queries) > 0
        assert isinstance(queries, dict)

    def test_catalog_version(self):
        """Test query manager exposes catalog version."""
        manager = MetadataPrimitivesQueryManager()
        assert manager.catalog_version == 1

    def test_get_query(self):
        """Test getting individual queries."""
        manager = MetadataPrimitivesQueryManager()

        # Test valid query
        query = manager.get_query("schema_list_tables")
        assert isinstance(query, str)
        assert "SELECT" in query.upper()
        assert "table_name" in query.lower()

    def test_get_query_invalid(self):
        """Test error handling for invalid query IDs."""
        manager = MetadataPrimitivesQueryManager()

        with pytest.raises(ValueError, match="Invalid query ID"):
            manager.get_query("invalid_query_id")

    def test_get_query_with_dialect_variant(self):
        """Test getting dialect-specific variants."""
        manager = MetadataPrimitivesQueryManager()

        # schema_list_tables has a clickhouse variant
        base_query = manager.get_query("schema_list_tables")
        clickhouse_query = manager.get_query("schema_list_tables", dialect="clickhouse")

        assert "system.tables" in clickhouse_query
        assert "information_schema" in base_query.lower()

    def test_get_query_skip_on(self):
        """Test that queries marked skip_on raise errors for skipped dialects."""
        manager = MetadataPrimitivesQueryManager()

        # schema_list_views is skipped on clickhouse
        with pytest.raises(ValueError, match="not supported on dialect"):
            manager.get_query("schema_list_views", dialect="clickhouse")

    def test_get_query_entry(self):
        """Test getting full query entry."""
        manager = MetadataPrimitivesQueryManager()

        entry = manager.get_query_entry("schema_list_tables")
        assert isinstance(entry, MetadataQuery)
        assert entry.id == "schema_list_tables"
        assert entry.category == "schema"

    def test_get_all_queries(self):
        """Test getting all queries."""
        manager = MetadataPrimitivesQueryManager()

        queries = manager.get_all_queries()
        assert isinstance(queries, dict)
        assert len(queries) > 0
        assert all(isinstance(v, str) for v in queries.values())

    def test_query_categories(self):
        """Test query category functionality."""
        manager = MetadataPrimitivesQueryManager()

        categories = manager.get_query_categories()
        assert "schema" in categories
        assert "column" in categories
        assert "stats" in categories
        assert "query" in categories

    def test_get_queries_by_category(self):
        """Test getting queries filtered by category."""
        manager = MetadataPrimitivesQueryManager()

        # Test schema category
        schema_queries = manager.get_queries_by_category("schema")
        assert len(schema_queries) > 0
        assert "schema_list_tables" in schema_queries

        # Test column category
        column_queries = manager.get_queries_by_category("column")
        assert len(column_queries) > 0
        assert "column_list_all" in column_queries

        # Test empty category
        empty_queries = manager.get_queries_by_category("nonexistent")
        assert len(empty_queries) == 0

    def test_get_queries_for_dialect(self):
        """Test getting all queries for a specific dialect."""
        manager = MetadataPrimitivesQueryManager()

        # Test DuckDB (should include most queries)
        duckdb_queries = manager.get_queries_for_dialect("duckdb")
        assert len(duckdb_queries) > 0

        # Test ClickHouse (some queries skipped)
        clickhouse_queries = manager.get_queries_for_dialect("clickhouse")
        assert len(clickhouse_queries) > 0
        # schema_list_views should not be in clickhouse queries
        assert "schema_list_views" not in clickhouse_queries


@pytest.mark.unit
class TestMetadataPrimitivesBenchmark:
    """Test Metadata Primitives benchmark functionality."""

    def test_benchmark_initialization(self):
        """Test benchmark initializes correctly."""
        benchmark = MetadataPrimitivesBenchmark()
        assert benchmark._name == "Metadata Primitives Benchmark"
        assert benchmark._version == "1.0"
        assert benchmark.query_manager is not None

    def test_benchmark_with_scale_factor(self):
        """Test benchmark accepts scale_factor for API compatibility."""
        benchmark = MetadataPrimitivesBenchmark(scale_factor=0.1)
        assert benchmark.scale_factor == 0.1

    def test_data_source_none(self):
        """Test that metadata primitives doesn't require data generation."""
        benchmark = MetadataPrimitivesBenchmark()
        assert benchmark.get_data_source_benchmark() is None

    def test_generate_data_empty(self):
        """Test that generate_data returns empty dict."""
        benchmark = MetadataPrimitivesBenchmark()
        result = benchmark.generate_data()
        assert result == {}

    def test_get_query(self):
        """Test getting queries from benchmark."""
        benchmark = MetadataPrimitivesBenchmark()

        # Test getting individual query
        query = benchmark.get_query("schema_list_tables")
        assert isinstance(query, str)
        assert "SELECT" in query.upper()

    def test_get_query_with_params_error(self):
        """Test that params are not supported."""
        benchmark = MetadataPrimitivesBenchmark()

        with pytest.raises(ValueError, match="don't accept parameters"):
            benchmark.get_query("schema_list_tables", params={"foo": "bar"})

    def test_get_queries(self):
        """Test getting all queries."""
        benchmark = MetadataPrimitivesBenchmark()

        queries = benchmark.get_queries()
        assert isinstance(queries, dict)
        assert len(queries) > 0

    def test_get_queries_with_dialect(self):
        """Test getting queries for specific dialect."""
        benchmark = MetadataPrimitivesBenchmark()

        # Should filter out unsupported queries
        clickhouse_queries = benchmark.get_queries(dialect="clickhouse")
        assert "schema_list_views" not in clickhouse_queries

    def test_get_queries_by_category(self):
        """Test getting queries by category."""
        benchmark = MetadataPrimitivesBenchmark()

        schema_queries = benchmark.get_queries_by_category("schema")
        assert len(schema_queries) > 0

        column_queries = benchmark.get_queries_by_category("column")
        assert len(column_queries) > 0

    def test_get_query_categories(self):
        """Test getting list of categories."""
        benchmark = MetadataPrimitivesBenchmark()

        categories = benchmark.get_query_categories()
        assert "schema" in categories
        assert "column" in categories
        assert "stats" in categories
        assert "query" in categories

    def test_invalid_query(self):
        """Test error handling for invalid queries."""
        benchmark = MetadataPrimitivesBenchmark()

        with pytest.raises(ValueError, match="Invalid query ID"):
            benchmark.get_query("invalid_query")


@pytest.mark.unit
class TestMetadataQueryResult:
    """Test MetadataQueryResult dataclass."""

    def test_result_creation(self):
        """Test creating a result object."""
        result = MetadataQueryResult(
            query_id="schema_list_tables",
            category="schema",
            execution_time_ms=10.5,
            row_count=100,
            success=True,
        )
        assert result.query_id == "schema_list_tables"
        assert result.category == "schema"
        assert result.execution_time_ms == 10.5
        assert result.row_count == 100
        assert result.success is True
        assert result.error is None

    def test_result_with_error(self):
        """Test creating a result with error."""
        result = MetadataQueryResult(
            query_id="schema_list_tables",
            category="schema",
            execution_time_ms=5.0,
            row_count=0,
            success=False,
            error="Query failed",
        )
        assert result.success is False
        assert result.error == "Query failed"


@pytest.mark.unit
class TestMetadataBenchmarkResult:
    """Test MetadataBenchmarkResult dataclass."""

    def test_result_creation(self):
        """Test creating a benchmark result object."""
        result = MetadataBenchmarkResult()
        assert result.total_queries == 0
        assert result.successful_queries == 0
        assert result.failed_queries == 0
        assert result.total_time_ms == 0.0
        assert result.results == []
        assert result.category_summary == {}

    def test_result_with_data(self):
        """Test benchmark result with populated data."""
        query_results = [
            MetadataQueryResult(
                query_id="q1",
                category="schema",
                execution_time_ms=10.0,
                row_count=5,
                success=True,
            ),
            MetadataQueryResult(
                query_id="q2",
                category="column",
                execution_time_ms=15.0,
                row_count=10,
                success=True,
            ),
        ]

        result = MetadataBenchmarkResult(
            total_queries=2,
            successful_queries=2,
            failed_queries=0,
            total_time_ms=25.0,
            results=query_results,
            category_summary={
                "schema": {"total_queries": 1, "successful": 1},
                "column": {"total_queries": 1, "successful": 1},
            },
        )

        assert result.total_queries == 2
        assert result.successful_queries == 2
        assert len(result.results) == 2
        assert "schema" in result.category_summary


@pytest.mark.unit
class TestQueryContentValidation:
    """Test that queries contain expected SQL content."""

    def test_schema_queries_content(self):
        """Test schema discovery queries have expected content."""
        manager = MetadataPrimitivesQueryManager()

        # List tables query should reference information_schema.tables
        query = manager.get_query("schema_list_tables")
        assert "table_name" in query.lower()
        assert "table_type" in query.lower()

    def test_column_queries_content(self):
        """Test column introspection queries have expected content."""
        manager = MetadataPrimitivesQueryManager()

        # Column list query should reference columns
        query = manager.get_query("column_list_all")
        assert "column_name" in query.lower()
        assert "data_type" in query.lower()

    def test_stats_queries_content(self):
        """Test statistics queries have expected content."""
        manager = MetadataPrimitivesQueryManager()

        # Stats query should aggregate counts
        query = manager.get_query("stats_column_count_summary")
        assert "count" in query.lower()

    def test_query_introspection_content(self):
        """Test query introspection queries have expected content."""
        manager = MetadataPrimitivesQueryManager()

        # Explain query should have EXPLAIN
        query = manager.get_query("query_explain_simple")
        assert "explain" in query.lower() or "select" in query.lower()


@pytest.mark.unit
class TestDialectVariants:
    """Test dialect-specific query variants."""

    def test_clickhouse_variants_use_system_tables(self):
        """Test ClickHouse variants use system.* tables."""
        manager = MetadataPrimitivesQueryManager()

        clickhouse_queries = manager.get_queries_for_dialect("clickhouse")

        # At least some queries should reference system tables
        has_system_tables = False
        for sql in clickhouse_queries.values():
            if "system." in sql:
                has_system_tables = True
                break
        assert has_system_tables

    def test_duckdb_variants(self):
        """Test DuckDB-specific variants."""
        manager = MetadataPrimitivesQueryManager()

        # schema_list_views has a DuckDB variant using duckdb_views()
        duckdb_query = manager.get_query("schema_list_views", dialect="duckdb")
        assert "duckdb_views()" in duckdb_query

    def test_base_query_unchanged_without_variant(self):
        """Test base query returned when no variant exists."""
        manager = MetadataPrimitivesQueryManager()

        base_query = manager.get_query("schema_list_schemata")
        duckdb_query = manager.get_query("schema_list_schemata", dialect="duckdb")

        # Without a DuckDB variant, should return base query
        assert base_query == duckdb_query
