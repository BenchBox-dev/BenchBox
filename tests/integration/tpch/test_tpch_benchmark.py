"""Integration tests for TPC-H benchmark classes with ultra-simplified implementation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox import TPCH
from benchbox.core.tpch.benchmark import TPCHBenchmark

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


class TestTPCHBenchmarkIntegration:
    """Test TPCHBenchmark integration with ultra-simplified query manager."""

    def test_benchmark_initialization(self):
        """Test TPCHBenchmark initializes correctly with new query manager."""
        benchmark = TPCHBenchmark()

        assert benchmark.query_manager is not None
        assert hasattr(benchmark.query_manager, "get_query")
        assert hasattr(benchmark.query_manager, "get_all_queries")

    def test_benchmark_query_generation(self):
        """Test query generation through TPCHBenchmark class."""
        benchmark = TPCHBenchmark()

        # Test basic query generation
        sql = benchmark.get_query(1)
        assert len(sql) > 50
        assert "select" in sql.lower() or "with" in sql.lower()

    def test_benchmark_query_generation_with_parameters(self):
        """Test query generation with seed and scale factor parameters."""
        benchmark = TPCHBenchmark()

        # Test with seed
        sql1 = benchmark.get_query(1, seed=12345)
        sql2 = benchmark.get_query(1, seed=12345)
        assert sql1 == sql2  # Same seed should produce same result

        # Test with different seed
        sql3 = benchmark.get_query(1, seed=54321)
        assert sql1 != sql3  # Different seed should produce different result

        # Test with scale factor
        sql_sf = benchmark.get_query(1, scale_factor=0.5)
        assert "select" in sql_sf.lower() or "with" in sql_sf.lower()
        assert len(sql_sf) > 50

    def test_benchmark_scale_factor_inheritance(self):
        """Test that benchmark scale factor is used when not specified."""
        # Create benchmark with specific scale factor
        benchmark = TPCHBenchmark(scale_factor=2.0)

        # Query should work with inherited scale factor
        sql = benchmark.get_query(1)
        assert "select" in sql.lower() or "with" in sql.lower()
        assert len(sql) > 50

        # Explicit scale factor should override
        sql_override = benchmark.get_query(1, scale_factor=0.1)
        assert "select" in sql_override.lower() or "with" in sql_override.lower()
        assert len(sql_override) > 50

    def test_benchmark_get_parameterized_query_compatibility(self):
        """Test get_parameterized_query method compatibility."""
        benchmark = TPCHBenchmark()

        # Test old-style call with params=None
        sql_old = benchmark.get_query(1, params=None)
        assert "select" in sql_old.lower() or "with" in sql_old.lower()
        assert len(sql_old) > 50

        # Test new-style call with seed
        sql_new = benchmark.get_query(1, seed=12345)
        assert "select" in sql_new.lower() or "with" in sql_new.lower()
        assert len(sql_new) > 50

        # Test mixed call
        sql_mixed = benchmark.get_query(1, params=None, seed=12345, dialect="duckdb")
        assert "select" in sql_mixed.lower() or "with" in sql_mixed.lower()
        assert len(sql_mixed) > 50

    def test_benchmark_get_queries_batch(self):
        """Test get_queries method returns all queries."""
        benchmark = TPCHBenchmark()

        queries = benchmark.get_queries()

        assert len(queries) == 22

        # Keys should be valid query IDs
        for key in queries:
            assert int(key) in range(1, 23)

        # Values should be SQL strings
        for sql in queries.values():
            assert "select" in sql.lower() or "with" in sql.lower()
            assert len(sql) > 50

    def test_benchmark_all_queries_generation(self):
        """Test that all 22 queries can be generated through benchmark."""
        benchmark = TPCHBenchmark()

        for query_id in range(1, 23):
            sql = benchmark.get_query(query_id)
            assert "select" in sql.lower() or "with" in sql.lower()
            assert len(sql) > 50
            assert f"Query {query_id} failed", f"Query {query_id} should generate successfully"

    def test_benchmark_error_handling(self):
        """Test error handling through benchmark interface."""
        benchmark = TPCHBenchmark()

        # Invalid query ID should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            benchmark.get_query(23)
        assert "Query ID must be 1-22" in str(exc_info.value)

        # Same for get_parameterized_query
        with pytest.raises(ValueError):
            benchmark.get_query(0)

    def test_benchmark_with_different_scale_factors(self):
        """Test benchmark behavior with different scale factors."""
        scale_factors = [0.01, 0.1, 1.0, 2.0]

        for sf in scale_factors:
            benchmark = TPCHBenchmark(scale_factor=sf)
            sql = benchmark.get_query(1)
            assert "select" in sql.lower() or "with" in sql.lower()
            assert len(sql) > 50


class TestTopLevelTPCHIntegration:
    """Test top-level TPCH class integration."""

    def test_tpch_initialization(self):
        """Test TPCH class initializes correctly."""
        tpch = TPCH()

        assert tpch._impl is not None
        assert hasattr(tpch._impl, "query_manager")

    def test_tpch_query_generation(self):
        """Test query generation through top-level TPCH class."""
        tpch = TPCH()

        # Test basic query generation
        sql = tpch.get_query(1)
        assert "select" in sql.lower() or "with" in sql.lower()
        assert len(sql) > 50

        # Test with parameters
        sql_with_seed = tpch.get_query(1, seed=12345)
        assert "select" in sql_with_seed.lower() or "with" in sql_with_seed.lower()
        assert len(sql_with_seed) > 50

    def test_tpch_parameterized_query_compatibility(self):
        """Test get_parameterized_query compatibility."""
        tpch = TPCH()

        # Test old-style call
        sql_old = tpch.get_query(1, params=None, dialect="duckdb")
        assert "select" in sql_old.lower() or "with" in sql_old.lower()
        assert len(sql_old) > 50

        # Test new-style call
        sql_new = tpch.get_query(1, seed=12345, dialect="duckdb")
        assert "select" in sql_new.lower() or "with" in sql_new.lower()
        assert len(sql_new) > 50

    def test_tpch_get_queries_batch(self):
        """Test get_queries method through top-level TPCH."""
        tpch = TPCH()

        queries = tpch.get_queries()

        assert len(queries) == 22

        for key, sql in queries.items():
            assert int(key) in range(1, 23)
            assert "select" in sql.lower() or "with" in sql.lower()
            assert len(sql) > 50

    def test_tpch_scale_factor_inheritance(self):
        """Test scale factor inheritance in top-level TPCH."""
        tpch = TPCH(scale_factor=0.5)

        # Should use inherited scale factor
        sql = tpch.get_query(1)
        assert "select" in sql.lower() or "with" in sql.lower()
        assert len(sql) > 50

        # Should allow override
        sql_override = tpch.get_query(1, scale_factor=2.0)
        assert "select" in sql_override.lower() or "with" in sql_override.lower()
        assert len(sql_override) > 50

    def test_tpch_all_queries_integration(self):
        """Test that all queries work through top-level TPCH."""
        tpch = TPCH()

        # Test subset of queries for performance
        for query_id in [1, 5, 10, 15, 20]:
            sql = tpch.get_query(query_id, seed=42)
            assert "select" in sql.lower() or "with" in sql.lower()
            assert len(sql) > 50
            assert ":1" not in sql  # No parameter placeholders

    def test_tpch_deterministic_behavior(self):
        """Test deterministic behavior through top-level TPCH."""
        tpch = TPCH()

        # Same seed should produce same results
        sql1 = tpch.get_query(1, seed=999)
        sql2 = tpch.get_query(1, seed=999)
        assert sql1 == sql2

        # Different seeds should produce different results
        sql3 = tpch.get_query(1, seed=111)
        assert sql1 != sql3

    def test_tpch_error_propagation(self):
        """Test error propagation through top-level TPCH."""
        tpch = TPCH()

        with pytest.raises(ValueError) as exc_info:
            tpch.get_query(25)
        assert "Query ID must be 1-22" in str(exc_info.value)


class TestCrossComponentIntegration:
    """Test integration across multiple components."""

    def test_query_consistency_across_interfaces(self):
        """Test that same query generates consistently across interfaces."""
        # Initialize all interfaces
        TPCH().get_queries()
        benchmark = TPCHBenchmark()
        tpch = TPCH()

        seed = 12345
        query_id = 1

        # Get query through different interfaces with same seed
        sql_benchmark = benchmark.get_query(query_id, seed=seed)
        sql_tpch = tpch.get_query(query_id, seed=seed)

        # Should be identical
        assert sql_benchmark == sql_tpch

    def test_parameter_inheritance_consistency(self):
        """Test parameter inheritance works consistently."""
        sf = 0.75
        benchmark = TPCHBenchmark(scale_factor=sf)
        tpch = TPCH(scale_factor=sf)

        # Both should work with inherited scale factor
        sql_benchmark = benchmark.get_query(1)
        sql_tpch = tpch.get_query(1)

        assert "select" in sql_benchmark.lower() or "with" in sql_benchmark.lower()
        assert "select" in sql_tpch.lower() or "with" in sql_tpch.lower()
        assert len(sql_benchmark) > 50
        assert len(sql_tpch) > 50

    def test_error_handling_consistency(self):
        """Test error handling is consistent across interfaces."""
        benchmark = TPCHBenchmark()
        tpch = TPCH()

        # Both should raise same type of error for invalid query
        with pytest.raises(ValueError):
            benchmark.get_query(0)

        with pytest.raises(ValueError):
            tpch.get_query(0)

    def test_api_signature_consistency(self):
        """Test API signatures work consistently across interfaces."""
        benchmark = TPCHBenchmark()
        tpch = TPCH()

        # Test various parameter combinations work on both
        test_params = [
            {"seed": 123},
            {"scale_factor": 0.5},
            {"seed": 456, "scale_factor": 1.5},
        ]

        for params in test_params:
            sql_benchmark = benchmark.get_query(1, **params)
            sql_tpch = tpch.get_query(1, **params)

            assert "select" in sql_benchmark.lower() or "with" in sql_benchmark.lower()
            assert "select" in sql_tpch.lower() or "with" in sql_tpch.lower()
            assert len(sql_benchmark) > 50
            assert len(sql_tpch) > 50
