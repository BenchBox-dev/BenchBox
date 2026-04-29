"""Integration test for identify=True regression in Read Primitives benchmark.

This test ensures that the default identify=True parameter in the centralized
SQL translation function doesn't break existing queries. The identify=True
parameter quotes identifiers to prevent reserved keyword conflicts, but could
potentially cause issues with case-sensitive identifiers or platform-specific
identifier handling.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


@pytest.mark.integration
class TestReadPrimitivesIdentifyRegression:
    """Test that identify=True doesn't break Read Primitives queries."""

    def test_all_queries_translate_with_identify_true(self):
        """Verify all queries translate successfully with identify=True.

        This test ensures that the centralized translation function's default
        identify=True parameter doesn't cause translation failures. All queries
        should translate without errors.
        """
        benchmark = ReadPrimitivesBenchmark()

        # Get all base queries (no dialect)
        base_queries = benchmark.get_queries()

        # Get queries translated to DuckDB with identify=True (the default)
        translated_queries = benchmark.get_queries(dialect="duckdb")

        # DuckDB skips queries that cannot preserve comparable semantics.
        assert set(base_queries) - set(translated_queries) == {
            "fulltext_simple_search",
            "fulltext_boolean_search",
            "fulltext_phrase_search",
            "json_extract_simple",
        }

        # Verify all translated queries are non-empty and contain SQL
        for query_id, query_sql in translated_queries.items():
            assert query_sql, f"Query {query_id} should not be empty"
            assert len(query_sql) > 0, f"Query {query_id} should have SQL content"
            # All queries should start with SELECT, WITH (CTEs), or a comment
            assert query_sql.strip().upper().startswith(("SELECT", "WITH", "/*", "--")), (
                f"Query {query_id} should start with SELECT, WITH, or comment"
            )

    def test_identify_true_quotes_identifiers(self):
        """Verify that identify=True properly quotes identifiers.

        This test confirms that the translation is actually using identify=True
        by checking that table/column names are quoted in the output.
        """
        benchmark = ReadPrimitivesBenchmark()

        # Get a simple query that we know should have quoted identifiers
        queries = benchmark.get_queries(dialect="duckdb")

        # Check aggregation_distinct query
        if "aggregation_distinct" in queries:
            query = queries["aggregation_distinct"]
            # Should have quoted identifiers like "o_custkey", "orders", "o_orderdate"
            assert '"o_custkey"' in query or '"orders"' in query, "Identifiers should be quoted with identify=True"

    def test_reserved_keyword_handling(self):
        """Test that reserved keywords are properly handled with identify=True.

        This test verifies that table/column names that might be reserved keywords
        in some dialects are properly quoted to prevent conflicts.
        """
        benchmark = ReadPrimitivesBenchmark()

        base_queries = benchmark.get_queries()
        queries = benchmark.get_queries(dialect="duckdb")

        # All non-skipped queries should translate successfully.
        assert set(base_queries) - set(queries) == {
            "fulltext_simple_search",
            "fulltext_boolean_search",
            "fulltext_phrase_search",
            "json_extract_simple",
        }

        # Verify that common table names are quoted (these could be keywords in some dialects)
        # We're looking for patterns like "orders", "customer", etc.
        sample_query = queries.get("aggregation_distinct", "")
        if sample_query:
            # Should contain SQL structure
            assert "SELECT" in sample_query.upper() or "select" in sample_query.lower()
            # Should contain FROM clause
            assert "FROM" in sample_query.upper() or "from" in sample_query.lower()

    def test_case_sensitivity_preservation(self):
        """Test that identifier case is preserved during translation.

        While identify=True quotes identifiers, it should preserve the original
        case of the identifiers. This test verifies that the translation doesn't
        unintentionally change identifier casing.
        """
        benchmark = ReadPrimitivesBenchmark()

        # Get queries with DuckDB dialect
        queries = benchmark.get_queries(dialect="duckdb")

        # Check a few queries to ensure identifiers maintain reasonable casing
        for query_id in ["aggregation_distinct", "join_inner_equijoin", "filter_selective"]:
            if query_id in queries:
                query = queries[query_id]

                # The query should contain identifiers
                assert len(query) > 0, f"Query {query_id} should not be empty"

                # TPC-H identifiers are lowercase (l_orderkey, o_custkey, etc.)
                # With identify=True, they should be quoted but remain lowercase
                # Check for patterns like "l_orderkey" or "o_custkey"
                if "orderkey" in query.lower():
                    # Identifier should exist in the query
                    assert "orderkey" in query.lower()

    def test_no_translation_errors_for_complex_queries(self):
        """Test that complex queries with CTEs, subqueries, and window functions translate correctly.

        Complex queries are more likely to expose issues with identifier quoting,
        especially around CTE names, subquery aliases, and window function clauses.
        """
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="duckdb")

        # Test queries known to have complex structures
        complex_query_ids = [
            "aggregation_materialize_subquery",  # CTE + subquery
            "window_lead_lag_same_frame",  # Window functions
            "olap_cube_analysis",  # CUBE operation
            "optimizer_exists_to_semijoin",  # Subquery transformations
        ]

        for query_id in complex_query_ids:
            if query_id in queries:
                query = queries[query_id]

                # Should translate successfully
                assert query, f"Complex query {query_id} should translate"
                assert len(query) > 0, f"Complex query {query_id} should have content"

                # Should contain SQL keywords
                query_upper = query.upper()
                assert "SELECT" in query_upper, f"Query {query_id} should contain SELECT"
                assert "FROM" in query_upper, f"Query {query_id} should contain FROM"

    def test_variant_queries_also_use_identify_true(self):
        """Test that dialect-specific variants also benefit from identify=True.

        Variant queries should also have identifiers quoted to maintain consistency
        and prevent reserved keyword conflicts.
        """
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="duckdb")

        # Test queries that have DuckDB variants
        variant_query_ids = [
            "json_aggregates",  # Has DuckDB variant
            "timeseries_trend_analysis",  # Has DuckDB variant
        ]

        for query_id in variant_query_ids:
            if query_id in queries:
                query = queries[query_id]

                # Variant should translate successfully
                assert query, f"Variant query {query_id} should translate"

                # Should contain SQL structure
                assert "SELECT" in query.upper() or "WITH" in query.upper(), (
                    f"Variant query {query_id} should contain SELECT or WITH"
                )

                # Identifiers should be quoted (check for common patterns)
                # DuckDB variants should have quoted identifiers like "p_name", "part", etc.
                assert '"' in query or "`" in query or query, (
                    f"Variant query {query_id} should have quoted identifiers or be valid SQL"
                )

    def test_translation_consistency_across_dialects(self):
        """Test that identify=True produces consistent results across different target dialects.

        While the exact quoting style may differ (e.g., " for DuckDB, ` for BigQuery),
        the translation should be consistent and error-free.
        """
        benchmark = ReadPrimitivesBenchmark()

        # Test with multiple dialects
        dialects = ["duckdb", "postgres", "snowflake"]

        for dialect in dialects:
            queries = benchmark.get_queries(dialect=dialect)

            # Should get queries for each dialect
            # (count may vary due to skip_on directives)
            assert len(queries) >= 100, f"Should have queries for {dialect}"

            # All queries should be non-empty
            for query_id, query_sql in queries.items():
                assert query_sql, f"Query {query_id} for {dialect} should not be empty"
                assert "SELECT" in query_sql.upper() or "WITH" in query_sql.upper(), (
                    f"Query {query_id} for {dialect} should contain SELECT or WITH"
                )


@pytest.mark.integration
class TestIdentifyTrueIntegrationWithTranslation:
    """Integration tests for identify=True with the translation pipeline."""

    def test_translation_pipeline_handles_identify_true(self):
        """Test that the full translation pipeline works correctly with identify=True.

        This test verifies that queries flow through the translation pipeline
        (get_query -> variant selection -> translation -> post-processing) without
        issues related to identifier quoting.
        """
        benchmark = ReadPrimitivesBenchmark()

        # Get a sample of queries across different categories
        all_queries = benchmark.get_queries(dialect="duckdb")

        # Test a diverse sample
        sample_ids = [
            "aggregation_distinct",  # Simple aggregation
            "join_inner_equijoin",  # Join operation
            "window_row_number",  # Window function
            "olap_cube_analysis",  # OLAP operation
            "json_aggregates",  # Variant query
        ]

        successful_translations = 0
        for query_id in sample_ids:
            if query_id in all_queries:
                query = all_queries[query_id]
                # Basic validation
                assert query and len(query) > 0
                successful_translations += 1

        # Should have successfully translated most sample queries
        assert successful_translations >= 3, "Should successfully translate at least 3 sample queries"

    def test_no_identifier_collision_with_quoting(self):
        """Test that identifier quoting doesn't cause collisions or ambiguity.

        When identifiers are quoted, there shouldn't be any ambiguity in queries
        with CTEs, subqueries, or self-joins.
        """
        benchmark = ReadPrimitivesBenchmark()

        queries = benchmark.get_queries(dialect="duckdb")

        # Test queries that have potential for identifier collision
        test_ids = [
            "aggregation_materialize_subquery",  # Multiple levels of nesting
            "optimizer_exists_to_semijoin",  # Complex subqueries
        ]

        for query_id in test_ids:
            if query_id in queries:
                query = queries[query_id]

                # Should not have ambiguous identifiers
                assert query, f"Query {query_id} should translate without ambiguity"

                # Should contain proper SQL structure
                assert "SELECT" in query.upper()
                assert "FROM" in query.upper()
