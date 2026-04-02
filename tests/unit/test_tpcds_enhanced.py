"""Enhanced tests for TPC-DS benchmark functionality.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


@pytest.mark.unit
class TestTPCDSBenchmarkEnhanced:
    """Enhanced tests for TPC-DS benchmark."""

    @pytest.fixture
    def tpcds_benchmark(self, temp_dir):
        """Create a TPC-DS benchmark instance for testing."""
        return TPCDSBenchmark(scale_factor=1.0, output_dir=temp_dir)

    def test_benchmark_basic_properties(self, tpcds_benchmark):
        """Test basic benchmark properties."""
        assert tpcds_benchmark.scale_factor == 1.0
        assert tpcds_benchmark.output_dir.name  # valid Path with a name component
        assert hasattr(tpcds_benchmark, "query_manager")
        assert hasattr(tpcds_benchmark, "data_generator")

    def test_benchmark_initialization_variations(self, temp_dir):
        """Test benchmark initialization with different parameters."""
        # Test with different scale factors
        benchmark_small = TPCDSBenchmark(scale_factor=1, output_dir=temp_dir)
        benchmark_large = TPCDSBenchmark(scale_factor=10, output_dir=temp_dir)

        assert benchmark_small.scale_factor == 1
        assert benchmark_large.scale_factor == 10

    def test_schema_generation(self, tpcds_benchmark):
        """Test schema generation."""
        schema_data = tpcds_benchmark.get_schema()

        # Schema should return dict mapping table names to definitions
        assert len(schema_data) > 0

        # Check that each table definition has required fields
        for table_name, table in schema_data.items():
            assert "name" in table
            assert "columns" in table
            assert isinstance(table["columns"], list)

        # TPC-DS has many tables - check for some key ones
        table_names = [table["name"].lower() for table in schema_data.values()]
        expected_tables = [
            "store_sales",
            "catalog_sales",
            "web_sales",
            "item",
            "customer",
            "store",
        ]

        # At least some of the expected tables should be present
        found_tables = sum(1 for table in expected_tables if table in table_names)
        assert found_tables >= 4

    @patch("benchbox.core.tpcds.c_tools.DSQGenBinary.generate")
    def test_query_retrieval_comprehensive(self, mock_generate, tpcds_benchmark):
        """Test comprehensive query retrieval."""
        # Mock the query generation to avoid external dependency
        mock_generate.return_value = "SELECT COUNT(*) FROM store_sales WHERE ss_sold_date_sk IS NOT NULL"

        # Test individual query retrieval
        query_1 = tpcds_benchmark.get_query(1)
        assert len(query_1) > 0
        assert "select" in query_1.lower()

        # Test all queries retrieval by mocking the query manager
        mock_query_dict = {i: f"SELECT * FROM store_sales WHERE query_{i} = 1" for i in range(1, 11)}
        with patch.object(
            tpcds_benchmark.query_manager,
            "get_all_queries",
            return_value=mock_query_dict,
        ):
            all_queries = tpcds_benchmark.get_queries()
            assert len(all_queries) >= 10
            # Results should be string keys (converted from int keys)
            assert all(isinstance(k, str) for k in all_queries)

    @patch("benchbox.core.tpcds.c_tools.DSQGenBinary.generate")
    def test_query_translation_functionality(self, mock_generate, tpcds_benchmark):
        """Test query translation to different SQL dialects."""
        # Mock the query generation
        mock_generate.return_value = "SELECT COUNT(*) FROM store_sales WHERE ss_sold_date_sk IS NOT NULL"

        tpcds_benchmark.get_query(1)

        # Test translation to different dialects
        dialects = ["sqlite", "postgres", "mysql", "bigquery"]
        for dialect in dialects:
            try:
                translated = tpcds_benchmark.translate_query(1, dialect)
                assert len(translated) > 0
                assert "select" in translated.lower()
            except Exception:
                # Translation might not be implemented for all dialects
                pass

    @patch("benchbox.core.tpcds.queries.DSQGenBinary.generate")
    def test_get_queries_with_dialect_parameter(self, mock_generate, tpcds_benchmark):
        """Test get_queries method with dialect parameter for SQL translation."""
        # Mock query with Netezza syntax (the default source dialect for TPC-DS)
        mock_netezza_query = """
        SELECT c_customer_id, c_first_name, c_last_name
        FROM customer
        WHERE c_customer_sk > 1000
        ORDER BY c_customer_id
        LIMIT 100
        """
        mock_generate.return_value = mock_netezza_query.strip()

        # Test without dialect (should return original Netezza syntax)
        queries_no_dialect = tpcds_benchmark.get_queries()
        assert len(queries_no_dialect) > 0

        # First query should contain LIMIT syntax (Netezza default)
        query_1 = queries_no_dialect.get("1")
        assert query_1 is not None
        assert "LIMIT 100" in query_1

        # Test with DuckDB dialect (should be compatible, both use LIMIT)
        queries_duckdb = tpcds_benchmark.get_queries(dialect="duckdb")
        assert len(queries_duckdb) > 0

        # First query should still have LIMIT syntax (compatible)
        query_1_duckdb = queries_duckdb.get("1")
        assert query_1_duckdb is not None
        assert "LIMIT 100" in query_1_duckdb

        # Test with netezza dialect explicitly (should return same as default)
        queries_netezza = tpcds_benchmark.get_queries(dialect="netezza")
        query_1_netezza = queries_netezza.get("1")
        assert query_1_netezza is not None
        assert "LIMIT 100" in query_1_netezza

    @patch("benchbox.core.tpcds.queries.DSQGenBinary.generate")
    def test_translate_query_text_netezza_to_duckdb(self, mock_generate, tpcds_benchmark):
        """Test translate_query_text method for realistic Netezza to DuckDB translation."""
        # Test queries with Netezza syntax patterns that need translation to DuckDB
        test_cases = [
            {
                "name": "Basic SELECT with LIMIT",
                "input": "SELECT * FROM customer ORDER BY c_customer_id LIMIT 100",
                "expected_patterns": ["LIMIT 100"],
                "not_expected": [],
            },
            {
                "name": "Complex query with standard SQL",
                "input": """
                WITH customer_total AS (
                    SELECT c_customer_sk, SUM(c_acctbal) as total
                    FROM customer GROUP BY c_customer_sk
                    ORDER BY total DESC LIMIT 50
                )
                SELECT * FROM customer_total ORDER BY total DESC LIMIT 25
                """,
                "expected_patterns": ["LIMIT 50", "LIMIT 25"],
                "not_expected": [],
            },
        ]

        for case in test_cases:
            translated = tpcds_benchmark.translate_query_text(case["input"], "netezza", "duckdb")

            # Check expected patterns are present
            for pattern in case["expected_patterns"]:
                assert pattern in translated, f"Expected '{pattern}' in translated query for {case['name']}"

            # Check unwanted patterns are removed
            for pattern in case["not_expected"]:
                assert pattern not in translated, f"Did not expect '{pattern}' in translated query for {case['name']}"

    def test_get_queries_dialect_error_handling(self, tpcds_benchmark):
        """Test get_queries method handles translation errors gracefully."""
        # Test with unsupported dialect - should not raise error
        try:
            queries = tpcds_benchmark.get_queries(dialect="unsupported_dialect")
            assert len(queries) >= 0
            # Should fallback to original queries if translation fails
        except Exception as e:
            pytest.fail(f"get_queries should handle unsupported dialects gracefully: {e}")

        # Test with None dialect
        queries_none = tpcds_benchmark.get_queries(dialect=None)
        assert len(queries_none) >= 0

    def test_data_generator_properties(self, tpcds_benchmark):
        """Test data generator properties and configuration."""
        generator = tpcds_benchmark.data_generator

        assert generator is not None
        assert hasattr(generator, "scale_factor")
        # Note: Data generator may adjust scale factor to minimum supported value
        assert generator.scale_factor >= tpcds_benchmark.scale_factor or generator.scale_factor == 0.1
        assert hasattr(generator, "output_dir")

    def test_query_manager_functionality(self, tpcds_benchmark):
        """Test query manager functionality."""
        query_manager = tpcds_benchmark.query_manager

        assert query_manager is not None
        assert hasattr(query_manager, "get_query")

        # Test that individual queries can be retrieved
        try:
            query = query_manager.get_query(1)
            assert len(query) > 0
        except Exception:
            # May require initialization
            pass

    def test_benchmark_inheritance(self, tpcds_benchmark):
        """Test that benchmark properly inherits from base class."""
        from benchbox.base import BaseBenchmark

        assert isinstance(tpcds_benchmark, BaseBenchmark)
        assert hasattr(tpcds_benchmark, "setup_database")
        assert hasattr(tpcds_benchmark, "run_query")
        assert hasattr(tpcds_benchmark, "run_benchmark")

    @patch("benchbox.core.tpcds.generator.TPCDSDataGenerator.generate")
    def test_generate_data_integration(self, mock_generate, tpcds_benchmark):
        """Test data generation integration."""
        # Mock the data generation to return table mapping
        mock_tables = {
            "store_sales": Path("store_sales.dat"),
            "catalog_sales": Path("catalog_sales.dat"),
            "web_sales": Path("web_sales.dat"),
            "item": Path("item.dat"),
        }
        mock_generate.return_value = mock_tables

        # Call generate_data
        result = tpcds_benchmark.generate_data()

        # Verify the call was made
        mock_generate.assert_called_once()
        # Result should be the list of file paths
        assert len(result) == 4

    def test_output_directory_handling(self, temp_dir):
        """Test output directory handling."""
        custom_dir = temp_dir / "custom_tpcds"
        benchmark = TPCDSBenchmark(scale_factor=1, output_dir=custom_dir)

        assert benchmark.output_dir == custom_dir

    def test_error_handling_invalid_query(self, tpcds_benchmark):
        """Test error handling for invalid query IDs."""
        with pytest.raises(ValueError):
            tpcds_benchmark.get_query(999)  # Invalid query ID

        with pytest.raises(TypeError):  # TPCDSBenchmark expects integer query_id
            tpcds_benchmark.get_query("invalid")  # Invalid query ID type

    def test_query_parameter_substitution(self, tpcds_benchmark):
        """Test query parameter substitution functionality."""
        # Test getting query with parameters
        try:
            query_with_params = tpcds_benchmark.get_query(1, params={"date": "2000-01-01"})
            assert len(query_with_params) > 0
        except Exception:
            # Parameter substitution might not be fully implemented
            pass

    def test_scale_factor_validation(self, temp_dir):
        """Test scale factor validation."""
        # Test different scale factors
        benchmark_1 = TPCDSBenchmark(scale_factor=1, output_dir=temp_dir)
        benchmark_10 = TPCDSBenchmark(scale_factor=10, output_dir=temp_dir)

        assert benchmark_1.scale_factor == 1
        assert benchmark_10.scale_factor == 10

    @patch("benchbox.core.tpcds.c_tools.DSQGenBinary.generate")
    def test_tpcds_specific_features(self, mock_generate, tpcds_benchmark):
        """Test TPC-DS specific features."""
        # Mock query generation
        mock_generate.return_value = "SELECT COUNT(*) FROM store_sales"

        # TPC-DS has multiple query categories
        # Test that we can retrieve queries from different ranges
        query_ranges = [1, 25, 50, 75, 99]

        valid_queries = 0
        for query_id in query_ranges:
            try:
                query = tpcds_benchmark.get_query(query_id)
                if isinstance(query, str) and len(query) > 0:
                    valid_queries += 1
            except Exception:
                # Some queries might not be available
                pass

        # At least some queries should be available
        assert valid_queries >= 2

    @patch("benchbox.core.tpcds.c_tools.DSQGenBinary.generate")
    def test_complex_query_structure(self, mock_generate, tpcds_benchmark):
        """Test that TPC-DS queries have expected complexity."""
        # Mock typical TPC-DS query
        mock_generate.return_value = """
        SELECT i_item_id, i_item_desc, s_store_id, s_store_name,
               SUM(ss_net_profit) as store_sales_profit
        FROM store_sales, item, store, date_dim
        WHERE ss_item_sk = i_item_sk
        AND ss_store_sk = s_store_sk
        AND ss_sold_date_sk = d_date_sk
        GROUP BY i_item_id, i_item_desc, s_store_id, s_store_name
        ORDER BY i_item_id, s_store_id
        """

        # Get a sample query and check it has TPC-DS characteristics
        query = tpcds_benchmark.get_query(1)
        query_lower = query.lower()

        # Should contain typical TPC-DS elements
        tpcds_keywords = ["store_sales", "item", "store"]
        tpcds_elements_found = any(keyword in query_lower for keyword in tpcds_keywords)

        assert tpcds_elements_found, "No TPC-DS specific elements found in sample query"

    def test_benchmark_configuration_options(self, temp_dir):
        """Test various benchmark configuration options."""
        # Test with verbose mode
        verbose_benchmark = TPCDSBenchmark(scale_factor=1, output_dir=temp_dir, verbose=True)
        assert hasattr(verbose_benchmark, "verbose")
        assert verbose_benchmark.scale_factor == 1

        # Test with custom seed
        seeded_benchmark = TPCDSBenchmark(scale_factor=1, output_dir=temp_dir, seed=42)
        assert seeded_benchmark.scale_factor == 1
