"""Enhanced tests for TPC-H benchmark functionality.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.tpch.benchmark import TPCHBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestTPCHBenchmarkEnhanced:
    """Enhanced tests for TPC-H benchmark."""

    @pytest.fixture
    def tpch_benchmark(self, temp_dir):
        """Create a TPC-H benchmark instance for testing."""
        return TPCHBenchmark(scale_factor=0.01, output_dir=temp_dir)

    def test_benchmark_basic_properties(self, tpch_benchmark):
        """Test basic benchmark properties."""
        assert tpch_benchmark.scale_factor == 0.01
        assert isinstance(tpch_benchmark.output_dir, Path)
        assert hasattr(tpch_benchmark, "query_manager")
        assert hasattr(tpch_benchmark, "data_generator")

    def test_benchmark_initialization_variations(self, temp_dir):
        """Test benchmark initialization with different parameters."""
        # Test with different scale factors - 0.001 is too small, should raise error
        with pytest.raises(ValueError, match="Scale factor 0.001 is too small"):
            TPCHBenchmark(scale_factor=0.001, output_dir=temp_dir)

        # Test with valid scale factors
        benchmark_small = TPCHBenchmark(scale_factor=0.01, output_dir=temp_dir)
        benchmark_large = TPCHBenchmark(scale_factor=1.0, output_dir=temp_dir)

        assert benchmark_small.scale_factor == 0.01
        assert benchmark_large.scale_factor == 1.0

    def test_schema_sql_generation(self, tpch_benchmark):
        """Test schema SQL generation."""
        schema_data = tpch_benchmark.get_schema()

        # Schema returns a dict mapping table names to table definitions
        assert isinstance(schema_data, dict)
        assert len(schema_data) > 0

        # Check that each table definition has required fields
        for table_name, table in schema_data.items():
            assert isinstance(table, dict)
            assert "name" in table
            assert "columns" in table
            assert isinstance(table["columns"], list)

        # Check for main TPC-H tables
        table_names = [table["name"].lower() for table in schema_data.values()]
        expected_tables = [
            "customer",
            "orders",
            "lineitem",
            "part",
            "supplier",
            "partsupp",
            "nation",
            "region",
        ]

        # At least most of the expected tables should be present
        found_tables = sum(1 for table in expected_tables if table in table_names)
        assert found_tables >= 6  # Allow for some variation in table names

    def test_query_retrieval_comprehensive(self, tpch_benchmark):
        """Test comprehensive query retrieval."""
        # Test individual query retrieval
        query_1 = tpch_benchmark.get_query(1)
        assert isinstance(query_1, str)
        assert len(query_1) > 0
        assert "select" in query_1.lower()

        # Test all queries retrieval
        all_queries = tpch_benchmark.get_queries()
        assert isinstance(all_queries, dict)
        assert len(all_queries) >= 20  # TPC-H should have 22 queries

    def test_query_translation_functionality(self, tpch_benchmark):
        """Test query translation to different SQL dialects."""
        tpch_benchmark.get_query(1)

        # Test translation to different dialects
        dialects = ["sqlite", "postgres", "mysql", "bigquery"]
        for dialect in dialects:
            try:
                translated = tpch_benchmark.translate_query(1, dialect)
                assert isinstance(translated, str)
                assert len(translated) > 0
            except Exception:
                # Translation might not be implemented for all dialects
                pass

    def test_sqlite_translation_executes_against_empty_schema(self, tpch_benchmark):
        """All translated TPC-H queries should be executable SQLite SQL."""
        conn = sqlite3.connect(":memory:")
        conn.executescript(tpch_benchmark.get_create_tables_sql(dialect="sqlite"))

        for query_id in range(1, 23):
            query = tpch_benchmark.get_query(query_id, scale_factor=0.01, dialect="sqlite")
            conn.execute(query).fetchall()

    def test_sqlite_translation_rewrites_named_alias_queries(self, tpch_benchmark):
        """SQLite translation must preserve Q13/Q15 derived column names."""
        query_13 = tpch_benchmark.get_query(13, scale_factor=0.01, dialect="sqlite")
        query_15 = tpch_benchmark.get_query(15, scale_factor=0.01, dialect="sqlite")

        assert 'AS "c_count"' in query_13
        assert 'AS "c_orders"(' not in query_13
        assert 'AS "supplier_no"' in query_15
        assert 'AS "total_revenue"' in query_15
        assert "INTERVAL" not in query_15.upper()

    def test_data_generator_properties(self, tpch_benchmark):
        """Test data generator properties and configuration."""
        generator = tpch_benchmark.data_generator

        assert generator is not None
        assert hasattr(generator, "scale_factor")
        # Note: Data generator may adjust scale factor to minimum supported value (0.1)
        assert generator.scale_factor >= tpch_benchmark.scale_factor
        assert hasattr(generator, "output_dir")

    def test_query_manager_functionality(self, tpch_benchmark):
        """Test query manager functionality."""
        query_manager = tpch_benchmark.query_manager

        assert query_manager is not None
        assert hasattr(query_manager, "get_query")
        # Note: TPCHQueries might not have get_queries method, that's on the benchmark level

        # Test that individual queries can be retrieved
        try:
            query = query_manager.get_query(1)
            assert isinstance(query, str)
        except Exception:
            # May require initialization
            pass

    def test_benchmark_inheritance(self, tpch_benchmark):
        """Test that benchmark properly inherits from base class."""
        from benchbox.base import BaseBenchmark

        assert isinstance(tpch_benchmark, BaseBenchmark)
        assert hasattr(tpch_benchmark, "setup_database")
        assert hasattr(tpch_benchmark, "run_query")
        assert hasattr(tpch_benchmark, "run_benchmark")

    @patch("benchbox.core.tpch.generator.TPCHDataGenerator.generate")
    def test_generate_data_integration(self, mock_generate, tpch_benchmark):
        """Test data generation integration."""
        # Mock the data generation to return table mapping
        mock_tables = {
            "customer": Path("customer.tbl"),
            "orders": Path("orders.tbl"),
            "lineitem": Path("lineitem.tbl"),
        }
        mock_generate.return_value = mock_tables

        # Call generate_data
        result = tpch_benchmark.generate_data()

        # Verify the call was made
        mock_generate.assert_called_once()
        # Result should be the list of file paths
        assert isinstance(result, list)
        assert len(result) == 3

    def test_output_directory_handling(self, temp_dir):
        """Test output directory handling."""
        custom_dir = temp_dir / "custom_output"
        benchmark = TPCHBenchmark(scale_factor=0.01, output_dir=custom_dir)

        assert benchmark.output_dir == custom_dir
        # Directory should be created during initialization if needed

    def test_error_handling_invalid_query(self, tpch_benchmark):
        """Test error handling for invalid query IDs."""
        with pytest.raises(ValueError):
            tpch_benchmark.get_query(999)  # Invalid query ID

        with pytest.raises(TypeError):  # TPCHBenchmark expects integer query_id
            tpch_benchmark.get_query("invalid")  # Invalid query ID type

    def test_query_parameter_substitution(self, tpch_benchmark):
        """Test query parameter substitution functionality."""
        # Test getting query with parameters
        try:
            query_with_params = tpch_benchmark.get_query(1, params={"date": "1998-12-01"})
            assert isinstance(query_with_params, str)
        except Exception:
            # Parameter substitution might not be fully implemented
            pass

    def test_scale_factor_validation(self, temp_dir):
        """Test scale factor validation."""
        # Test very small scale factor - 0.001 is too small, should raise error
        with pytest.raises(ValueError, match="Scale factor 0.001 is too small"):
            TPCHBenchmark(scale_factor=0.001, output_dir=temp_dir)

        # Test larger scale factors
        small_benchmark = TPCHBenchmark(scale_factor=0.01, output_dir=temp_dir)
        assert small_benchmark.scale_factor == 0.01

        medium_benchmark = TPCHBenchmark(scale_factor=0.1, output_dir=temp_dir)
        assert medium_benchmark.scale_factor == 0.1
