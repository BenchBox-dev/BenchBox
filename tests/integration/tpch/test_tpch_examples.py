"""Integration tests for TPC-H example scripts with ultra-simplified implementation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


class TestTPCHExamples:
    """Test that example scripts work with ultra-simplified implementation."""

    def test_example_api_usage_patterns(self):

        from benchbox import TPCH

        # Test patterns that examples typically use
        tpch = TPCH()

        # Basic query generation (common in examples)
        sql = tpch.get_query(1)
        assert isinstance(sql, str)
        assert len(sql) > 50

        # Parameterized query with params=None (backward compatibility)
        sql_param = tpch.get_query(1, params=None, dialect="duckdb")
        assert isinstance(sql_param, str)
        assert len(sql_param) > 50

        # Batch query generation
        queries = tpch.get_queries()
        assert isinstance(queries, dict)
        assert len(queries) == 22

    def test_example_parameter_usage(self):

        from benchbox import TPCH

        tpch = TPCH()

        # Test seed usage (for reproducible examples)
        sql1 = tpch.get_query(1, seed=42)
        sql2 = tpch.get_query(1, seed=42)
        assert sql1 == sql2

        # Test scale factor usage
        sql_sf = tpch.get_query(1, scale_factor=0.1)
        assert isinstance(sql_sf, str)
        assert len(sql_sf) > 50

    def test_example_dialect_handling(self):

        from benchbox import TPCH

        tpch = TPCH()

        # Common dialects used in examples
        dialects = ["duckdb", "postgres", "sqlite", "standard"]

        for dialect in dialects:
            sql = tpch.get_query(1, dialect=dialect)
            assert isinstance(sql, str)
            assert len(sql) > 50

    def test_example_error_handling_patterns(self):
        """Test error handling patterns that examples should use."""
        from benchbox import TPCH

        tpch = TPCH()

        # Invalid query ID (examples should handle this)
        with pytest.raises(ValueError) as exc_info:
            tpch.get_query(23)
        assert "Query ID must be 1-22" in str(exc_info.value)

    def test_benchmark_example_patterns(self):

        from benchbox.core.tpch.benchmark import TPCHBenchmark

        benchmark = TPCHBenchmark()

        # Common benchmark operations in examples
        sql = benchmark.get_query(1)
        assert isinstance(sql, str)

        queries = benchmark.get_queries()
        assert len(queries) == 22

        # Parameterized query with backward compatible signature
        sql_param = benchmark.get_query(1, params=None)
        assert isinstance(sql_param, str)

    @patch("duckdb.connect")
    def test_duckdb_integration_pattern(self, mock_connect):

        # Mock DuckDB connection for testing
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_conn.execute.return_value = MagicMock()

        from benchbox import TPCH

        tpch = TPCH()

        # Simulate example pattern: generate query and execute
        sql = tpch.get_query(1, seed=42)

        # This would be the pattern in examples
        try:
            import duckdb

            # Mock execution
            mock_conn.execute(sql)
            mock_conn.execute.assert_called_once_with(sql)
        except ImportError:
            pytest.skip("DuckDB not available for integration test")

    def test_multi_scale_example_pattern(self):

        from benchbox import TPCH

        scale_factors = [0.01, 0.1, 1.0]

        for sf in scale_factors:
            tpch = TPCH(scale_factor=sf)

            # Should work for all scale factors
            sql = tpch.get_query(1)
            assert isinstance(sql, str)
            assert len(sql) > 50

            # Should be able to override scale factor
            sql_override = tpch.get_query(1, scale_factor=sf * 2)
            assert isinstance(sql_override, str)

    def test_example_query_iteration_pattern(self):

        from benchbox import TPCH

        tpch = TPCH()

        # Pattern: iterate through queries (common in examples)
        results = {}
        for query_id in range(1, 6):  # Test subset for performance
            sql = tpch.get_query(query_id, seed=123)
            results[query_id] = sql

            assert isinstance(sql, str)
            assert len(sql) > 50
            assert query_id in results

        # All queries should be different
        sqls = list(results.values())
        for i, sql1 in enumerate(sqls):
            for j, sql2 in enumerate(sqls):
                if i != j:
                    assert sql1 != sql2

    def test_example_deterministic_testing_pattern(self):

        from benchbox import TPCH

        tpch = TPCH()

        # Pattern: use fixed seed for reproducible testing
        seed = 42

        # Generate queries multiple times with same seed
        queries_run1 = [tpch.get_query(i, seed=seed) for i in range(1, 6)]
        queries_run2 = [tpch.get_query(i, seed=seed) for i in range(1, 6)]

        # Should be identical
        assert queries_run1 == queries_run2

    def test_example_performance_measurement_pattern(self):

        import time

        from benchbox import TPCH

        tpch = TPCH()

        # Pattern: measure query generation time (examples often do this)
        start_time = time.time()
        sql = tpch.get_query(1)
        generation_time = time.time() - start_time

        assert isinstance(sql, str)
        assert len(sql) > 50
        assert generation_time < 1.0  # Should be fast with qgen

    def test_example_batch_generation_pattern(self):

        from benchbox import TPCH

        tpch = TPCH()

        # Pattern: generate all queries at once (common for setup)
        start_time = time.time()
        all_queries = tpch.get_queries()
        batch_time = time.time() - start_time

        assert len(all_queries) == 22
        assert batch_time < 5.0  # Should be reasonably fast

        # All should be valid SQL
        for query_id, sql in all_queries.items():
            assert isinstance(query_id, str)
            assert isinstance(sql, str)
            assert len(sql) > 50

    def test_example_error_recovery_pattern(self):
        """Test error recovery pattern that examples should implement."""
        from benchbox import TPCH

        tpch = TPCH()

        # Pattern: graceful handling of invalid inputs
        try:
            tpch.get_query(0)  # Invalid query ID
            raise AssertionError("Should have raised ValueError")
        except ValueError as e:
            assert "Query ID must be 1-22" in str(e)

        # Should still work for valid queries after error
        sql = tpch.get_query(1)
        assert isinstance(sql, str)
        assert len(sql) > 50

    def test_example_configuration_pattern(self):

        from benchbox import TPCH
        from benchbox.core.tpch.benchmark import TPCHBenchmark

        # Pattern: configure benchmark with specific parameters
        configs = [
            {"scale_factor": 0.1},
            {"scale_factor": 1.0},
        ]

        for config in configs:
            # Top-level TPCH
            tpch = TPCH(**config)
            sql = tpch.get_query(1)
            assert isinstance(sql, str)

            # Benchmark class
            benchmark = TPCHBenchmark(**config)
            sql_benchmark = benchmark.get_query(1)
            assert isinstance(sql_benchmark, str)
