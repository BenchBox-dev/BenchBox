"""Official TPC-H tests for BenchBox.

This module provides comprehensive tests for the TPC-H benchmark implementation,
including query generation, parameter substitution, database integration, and
official benchmark execution with QphH@Size calculation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import patch

import pytest

# Import TPC-H components
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch.queries import TPCHQueries

# Mark all tests in this file appropriately
pytestmark = [
    pytest.mark.medium,
    pytest.mark.tpch,
]


class TestTPCHQueryGeneration:
    """Test TPC-H query generation functionality."""

    def test_initialization_requires_qgen(self):
        """Test that initialization fails fast if qgen not available."""
        with patch("benchbox.core.tpch.queries.QGenBinary") as mock_qgen:
            mock_qgen.side_effect = RuntimeError("qgen binary required but not found")

            with pytest.raises(RuntimeError) as exc_info:
                TPCHQueries()

            assert "qgen binary required but not found" in str(exc_info.value)

    def test_successful_initialization(self):
        """Test successful initialization with qgen available."""
        queries = TPCHQueries()
        assert hasattr(queries.qgen, "generate")

    def test_get_query_all_valid_ids(self):
        """Test get_query for all 22 TPC-H queries."""
        queries = TPCHQueries()

        # Test all valid query IDs
        for query_id in range(1, 23):
            sql = queries.get_query(query_id)

            assert isinstance(sql, str)
            assert len(sql) > 50  # Should be substantial SQL
            assert "select" in sql.lower() or "with" in sql.lower()  # Valid SQL
            assert ":1" not in sql  # No parameter placeholders should remain

    def test_get_query_with_seed_determinism(self):
        """Test that same seed produces same results."""
        queries = TPCHQueries()

        # Test deterministic behavior
        sql1 = queries.get_query(1, seed=12345)
        sql2 = queries.get_query(1, seed=12345)

        assert sql1 == sql2

        # Test multiple queries with same seed
        results1 = [queries.get_query(i, seed=42) for i in range(1, 6)]
        results2 = [queries.get_query(i, seed=42) for i in range(1, 6)]

        assert results1 == results2

    def test_get_query_different_seeds(self):
        """Test that different seeds produce different results."""
        queries = TPCHQueries()

        sql_seed1 = queries.get_query(1, seed=111)
        sql_seed2 = queries.get_query(1, seed=222)

        # Different seeds should produce different parameters
        assert sql_seed1 != sql_seed2

    def test_get_query_with_scale_factor(self):
        """Test scale factor parameter functionality."""
        queries = TPCHQueries()

        # Test different scale factors
        sql_sf1 = queries.get_query(1, scale_factor=1.0)
        sql_sf01 = queries.get_query(1, scale_factor=0.1)

        assert isinstance(sql_sf1, str)
        assert isinstance(sql_sf01, str)
        assert len(sql_sf1) > 0
        assert len(sql_sf01) > 0

    def test_get_query_invalid_id(self):
        """Test error handling for invalid query IDs."""
        queries = TPCHQueries()

        invalid_ids = [0, -1, 23, 100]
        for invalid_id in invalid_ids:
            with pytest.raises(ValueError) as exc_info:
                queries.get_query(invalid_id)
            assert f"Query ID must be 1-22, got {invalid_id}" in str(exc_info.value)

    def test_get_all_queries_batch(self):
        """Test batch generation of all queries."""
        queries = TPCHQueries()

        all_queries = queries.get_all_queries()

        # Should return dictionary with all 22 queries
        assert isinstance(all_queries, dict)
        assert len(all_queries) == 22

        # Check all query IDs are present
        for query_id in range(1, 23):
            assert query_id in all_queries
            assert isinstance(all_queries[query_id], str)
            assert len(all_queries[query_id]) > 50

    def test_tpchqueries_instantiation(self):
        """Test TPCHQueries can be instantiated and used directly."""
        manager = TPCHQueries()
        sql = manager.get_query(1)
        assert isinstance(sql, str)
        assert len(sql) > 50

    def test_parameter_combinations(self):
        """Test various parameter combinations."""
        queries = TPCHQueries()

        # Test all parameter combinations
        combinations = [
            {},  # No parameters
            {"seed": 123},  # Seed only
            {"scale_factor": 0.5},  # Scale factor only
            {"seed": 456, "scale_factor": 2.0},  # Both parameters
        ]

        for params in combinations:
            sql = queries.get_query(1, **params)
            assert isinstance(sql, str)
            assert len(sql) > 50

    def test_query_content_validation(self):
        """Test that generated queries contain expected content."""
        queries = TPCHQueries()

        # Test specific queries for expected content
        query1 = queries.get_query(1)
        assert "lineitem" in query1.lower()
        assert "l_shipdate" in query1.lower()

        query2 = queries.get_query(2)
        assert "part" in query2.lower()
        assert "supplier" in query2.lower()

        query3 = queries.get_query(3)
        assert "customer" in query3.lower()
        assert "orders" in query3.lower()

    def test_no_parameter_placeholders_in_output(self):
        """Test that no parameter placeholders remain in generated SQL."""
        queries = TPCHQueries()

        # Test several queries
        for query_id in [1, 5, 10, 15, 20]:
            sql = queries.get_query(query_id, seed=99)

            # Should not contain parameter placeholders
            assert ":1" not in sql
            assert ":2" not in sql
            assert ":3" not in sql
            assert ":4" not in sql
            assert ":5" not in sql

    def test_scale_factor_edge_cases(self):
        """Test scale factor edge cases."""
        queries = TPCHQueries()

        # Test very small scale factor
        sql_tiny = queries.get_query(1, scale_factor=0.01)
        assert isinstance(sql_tiny, str)
        assert len(sql_tiny) > 0

        # Test larger scale factor
        sql_large = queries.get_query(1, scale_factor=10.0)
        assert isinstance(sql_large, str)
        assert len(sql_large) > 0

    def test_seed_edge_cases(self):
        """Test seed edge cases."""
        queries = TPCHQueries()

        # Test various seed values
        seeds = [0, 1, 999999, 2147483647]  # Including max int

        for seed in seeds:
            sql = queries.get_query(1, seed=seed)
            assert isinstance(sql, str)
            assert len(sql) > 0

    def test_error_propagation_from_qgen(self):
        """Test that errors from qgen are properly propagated."""
        queries = TPCHQueries()

        # Mock qgen to raise an error
        with patch.object(queries.qgen, "generate") as mock_generate:
            mock_generate.side_effect = RuntimeError("Mock qgen error")

            with pytest.raises(RuntimeError):
                queries.get_query(1)


class TestTPCHBenchmarkCore:
    """Test TPC-H benchmark core functionality."""

    def test_benchmark_initialization(self):
        """Test TPCHBenchmark initializes correctly."""
        benchmark = TPCHBenchmark()

        assert benchmark.query_manager is not None
        assert hasattr(benchmark.query_manager, "get_query")
        assert hasattr(benchmark.query_manager, "get_all_queries")

    def test_benchmark_query_generation(self):
        """Test benchmark query generation."""
