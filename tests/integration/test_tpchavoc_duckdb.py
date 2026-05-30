"""Integration tests for TPC-Havoc with DuckDB.

This module tests the TPC-Havoc implementation with a real DuckDB database,
focusing on query variant generation, execution, and validation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest import mock

import duckdb
import pytest

from benchbox import TPCHavoc

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.tpchavoc
class TestTPCHavocDuckDBIntegration:
    """Integration tests for TPC-Havoc with DuckDB."""

    @pytest.fixture
    def tpchavoc(self, small_scale_factor, temp_dir):
        """Create a tiny TPC-Havoc instance for testing."""
        # Use a very small scale factor for quick testing
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"
            return TPCHavoc(scale_factor=small_scale_factor, output_dir=temp_dir)

    @pytest.fixture
    def duckdb_conn(self):
        """Create a temporary DuckDB database."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_variant_query_generation(self, tpchavoc):
        """Test that TPC-Havoc can generate query variants."""
        # Get implemented queries
        implemented = tpchavoc.get_implemented_queries()
        assert len(implemented) > 0, "Should have at least one implemented query"

        # Test variant generation for first implemented query
        query_id = implemented[0]

        # Get all variants
        variants = tpchavoc.get_all_variants(query_id)
        assert len(variants) == 10, f"Should have 10 variants for query {query_id}"

        # Each variant should be a non-empty SQL string
        for variant_id, query_text in variants.items():
            assert isinstance(query_text, str), f"Variant {variant_id} should be a string"
            assert len(query_text.strip()) > 0, f"Variant {variant_id} should not be empty"
            assert "SELECT" in query_text.upper(), f"Variant {variant_id} should be a SELECT statement"

    def test_variant_descriptions(self, tpchavoc):
        """Test that each variant has a meaningful description."""
        implemented = tpchavoc.get_implemented_queries()
        query_id = implemented[0]

        # Get variant info
        variants_info = tpchavoc.get_all_variants_info(query_id)
        assert len(variants_info) == 10, "Should have 10 variant descriptions"

        # Each variant should have description and variant_id
        for variant_id, info in variants_info.items():
            assert "description" in info, f"Variant {variant_id} should have description"
            assert "variant_id" in info, f"Variant {variant_id} should have variant_id"
            assert len(info["description"]) > 0, f"Variant {variant_id} description should not be empty"
            assert info["variant_id"] == variant_id, "Variant ID should match key"

    def test_get_query_supports_variant_format(self, tpchavoc):
        """Test that get_query() supports both regular and variant query IDs."""
        implemented = tpchavoc.get_implemented_queries()
        query_id = implemented[0]

        # Test regular format
        regular_query = tpchavoc.get_query(query_id)
        assert isinstance(regular_query, str)
        assert len(regular_query) > 0

        # Test variant format (e.g., "1_v1")
        variant_query = tpchavoc.get_query(f"{query_id}_v1")
        assert isinstance(variant_query, str)
        assert len(variant_query) > 0

        # Variant query should be different from base query
        # (unless it's a special case where variant matches base)
        # We can't assert they're different because some variants might
        # be semantically identical

    def test_benchmark_info(self, tpchavoc):
        """Test that benchmark info provides comprehensive metadata."""
        info = tpchavoc.get_benchmark_info()

        # Check required fields
        assert "benchmark_name" in info
        assert "base_benchmark" in info
        assert "scale_factor" in info
        assert "implemented_queries" in info
        assert "total_queries_with_variants" in info
        assert "variants_per_query" in info
        assert "total_query_variants" in info
        assert "variants_info" in info
        assert "validation_tolerance" in info
        assert "description" in info

        # Check values
        assert info["benchmark_name"] == "TPC-Havoc"
        assert info["base_benchmark"] == "TPC-H"
        assert info["variants_per_query"] == 10
        assert len(info["implemented_queries"]) > 0

        # Total variants should be implemented_queries * 10
        expected_total = len(info["implemented_queries"]) * 10
        assert info["total_query_variants"] == expected_total

    def test_export_variant_queries(self, tpchavoc, temp_dir):
        """Test exporting variant queries to files."""
        output_dir = temp_dir / "exported_queries"

        # Export all variants
        exported = tpchavoc.export_variant_queries(output_dir=output_dir, format="sql")

        # Should have exported files
        assert len(exported) > 0, "Should export at least one file"

        # Each file should exist and contain SQL
        for query_key, file_path in exported.items():
            assert file_path.exists(), f"Exported file {file_path} should exist"

            # Read and validate content
            content = file_path.read_text()
            assert len(content) > 0, f"Exported file {file_path} should not be empty"
            assert "SELECT" in content.upper(), f"Exported file {file_path} should contain SELECT"
            assert "TPC-Havoc" in content, f"Exported file {file_path} should have TPC-Havoc header"

    def test_schema_compatibility_with_tpch(self, tpchavoc, duckdb_conn):
        """Test that TPC-Havoc uses the same schema as TPC-H."""
        # Get schema
        sql = tpchavoc.get_create_tables_sql()

        # Execute schema creation
        for statement in sql.strip().split(";"):
            if statement.strip():
                duckdb_conn.execute(statement.strip())

        # Verify TPC-H tables were created
        tables_result = duckdb_conn.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
        """).fetchall()

        table_names = [row[0].lower() for row in tables_result]
        expected_tables = [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]

        # All TPC-H tables should exist
        for expected_table in expected_tables:
            assert expected_table in table_names, f"TPC-H table {expected_table} not found"

    def test_variant_sql_syntax_validity(self, tpchavoc):
        """Test that all variant queries have valid SQL syntax."""
        implemented = tpchavoc.get_implemented_queries()

        for query_id in implemented[:3]:  # Test first 3 to keep tests fast
            variants = tpchavoc.get_all_variants(query_id)

            for variant_id, query_text in variants.items():
                # Basic SQL syntax checks
                upper_sql = query_text.upper()
                assert "SELECT" in upper_sql, f"Q{query_id}.{variant_id} should have SELECT"
                assert "FROM" in upper_sql, f"Q{query_id}.{variant_id} should have FROM"

                # Should be well-formed (basic check)
                assert query_text.count("(") == query_text.count(")"), (
                    f"Q{query_id}.{variant_id} should have balanced parentheses"
                )

    def test_duckdb_regression_variants_explain(self, tpchavoc, duckdb_conn):
        """Previously failing DuckDB TPC-Havoc variants should parse and bind."""
        for statement in tpchavoc.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                duckdb_conn.execute(statement.strip())

        regression_variants = [
            "2_v5",
            "5_v9",
            "7_v9",
            "9_v9",
            "10_v8",
            "10_v9",
            "11_v9",
            "13_v9",
            "17_v2",
            "17_v4",
        ]
        for query_id in regression_variants:
            duckdb_conn.execute(f"EXPLAIN {tpchavoc.get_query(query_id)}")

    def test_q10_v8_exists_correlates_to_outer_lineitem(self, tpchavoc, duckdb_conn):
        """10_v8's EXISTS must correlate to the outer lineitem, not self-bind to l2.

        The unqualified form (`l2.l_orderkey = l_orderkey`) silently bound to the
        inner alias, turning a semi-join into an uncorrelated full scan that hung
        DuckDB at SF1. The qualified form must decorrelate into a semi-join.
        """
        for statement in tpchavoc.get_create_tables_sql(dialect="duckdb").strip().split(";"):
            if statement.strip():
                duckdb_conn.execute(statement.strip())

        sql = tpchavoc.get_query("10_v8")
        assert "l2.l_orderkey = lineitem.l_orderkey" in sql, "EXISTS must correlate to the outer lineitem"

        plan = duckdb_conn.execute(f"EXPLAIN {sql}").fetchall()[0][1]
        assert "SEMI" in plan.upper(), "EXISTS should decorrelate into a semi-join, not a self-referential scan"
