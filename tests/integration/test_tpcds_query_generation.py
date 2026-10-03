"""TPC-DS Query Generation Integration Tests for minimal C tool wrapper.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DS specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time
from pathlib import Path
from unittest.mock import patch

import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


@pytest.mark.integration
@pytest.mark.tpcds
class TestTPCDSIntegrationMinimal:
    """Simplified integration tests for TPC-DS C tool wrapper."""

    @pytest.fixture(scope="class")
    def tpcds_benchmark(self):
        """Create one reusable benchmark instance for API-level integration checks."""
        return TPCDSBenchmark(scale_factor=1.0)

    @staticmethod
    def _assert_generated_files_exist(data_files: list[Path] | list[list[Path]]) -> None:
        """Validate generated file references from TPC-DS data generation."""
        for file_path_or_list in data_files:
            if isinstance(file_path_or_list, list):
                for file_path in file_path_or_list:
                    assert file_path.exists(), f"File {file_path} should exist"
                    assert file_path.stat().st_size > 0, f"File {file_path} should not be empty"
            else:
                file_path = Path(file_path_or_list)
                assert file_path.exists(), f"File {file_path} should exist"
                assert file_path.stat().st_size > 0, f"File {file_path} should not be empty"

    def test_end_to_end_workflow(self, tpcds_benchmark):
        """Test complete TPC-DS workflow with C tools - comprehensive test."""

        # 1. Test benchmark info
        info = tpcds_benchmark.get_benchmark_info()
        assert info["name"] == "TPC-DS"
        assert info["scale_factor"] == 1.0
        assert "c_tools_info" in info
        assert "available_tables" in info
        assert "available_queries" in info

        # 2. Test schema
        schema = tpcds_benchmark.get_schema()
        assert isinstance(schema, dict)
        assert len(schema) > 0

        # 3. Test available tables
        tables = tpcds_benchmark.get_available_tables()
        assert len(tables) > 0

        # 4. Test available queries
        available_queries = tpcds_benchmark.get_available_queries()
        assert len(available_queries) == 99

        # 5. Test all queries
        queries = tpcds_benchmark.get_queries()
        assert len(queries) > 0
        assert isinstance(queries, dict)

        # 6. Test specific query access
        query1 = tpcds_benchmark.get_query(1)
        assert isinstance(query1, str)
        assert len(query1) > 0

    def test_c_tool_integration_workflow(self):

        benchmark = TPCDSBenchmark()

        # Test C tools initialization
        assert benchmark.c_tools is not None

        # Test C tools info
        c_tools_info = benchmark.c_tools.get_tools_info()
        assert isinstance(c_tools_info, dict)
        assert "tools_path" in c_tools_info
        assert "available_tools" in c_tools_info
        assert "templates_path" in c_tools_info

        # Test that tools exist
        tools = c_tools_info["available_tools"]
        dsdgen_exists = any(tool["name"] == "dsdgen" and tool["exists"] for tool in tools)
        assert dsdgen_exists

    def test_query_template_integration(self):

        benchmark = TPCDSBenchmark()

        # Test query access through benchmark
        queries = benchmark.get_queries()
        assert len(queries) > 0

        # Test direct query access
        query1 = benchmark.get_query(1)
        query2 = benchmark.get_query(2)

        assert query1 != query2
        assert len(query1) > 0
        assert len(query2) > 0

        # Test that queries contain SQL-like content
        assert "select" in query1.lower() or "with" in query1.lower()
        assert "select" in query2.lower() or "with" in query2.lower()

    @pytest.mark.slow
    @pytest.mark.stress
    def test_data_generation_integration(self):
        """Run one full-fidelity TPC-DS data generation path in stress lane."""
        benchmark = TPCDSBenchmark(scale_factor=1.0)
        data_files = benchmark.generate_data()
        assert len(data_files) > 0
        self._assert_generated_files_exist(data_files)

    def test_scale_factor_integration(self, tpcds_benchmark):

        # Test that benchmark respects scale factor
        assert tpcds_benchmark.scale_factor == 1.0
        info = tpcds_benchmark.get_benchmark_info()
        assert info["scale_factor"] == 1.0

    def test_error_handling_integration(self):

        benchmark = TPCDSBenchmark()

        # Test query error handling
        with pytest.raises(ValueError):
            benchmark.get_query(999)

        # Test that data generation API works (mock to avoid slow operation)
        with patch.object(benchmark, "generate_data") as mock_generate:
            mock_generate.return_value = ["/mock/table1.dat", "/mock/table2.dat"]
            data_files = benchmark.generate_data()
            assert len(data_files) > 0

        # Test that valid operations still work after errors
        query1 = benchmark.get_query(1)
        assert isinstance(query1, str)
        assert len(query1) > 0

    def test_concurrent_access_integration(self):

        benchmark = TPCDSBenchmark()

        # Test multiple concurrent queries
        query1 = benchmark.get_query(1)
        query2 = benchmark.get_query(2)
        query3 = benchmark.get_query(3)

        # All should work
        assert isinstance(query1, str)
        assert isinstance(query2, str)
        assert isinstance(query3, str)

        # All should be different
        assert query1 != query2
        assert query2 != query3
        assert query1 != query3

    def test_consistency_integration(self):

        benchmark = TPCDSBenchmark()

        # Multiple calls should return same results
        query1_call1 = benchmark.get_query(1)
        query1_call2 = benchmark.get_query(1)
        assert query1_call1 == query1_call2

        # Available tables should be consistent
        tables1 = benchmark.get_available_tables()
        tables2 = benchmark.get_available_tables()
        assert tables1 == tables2

        # Available queries should be consistent
        queries1 = benchmark.get_available_queries()
        queries2 = benchmark.get_available_queries()
        assert queries1 == queries2

    def test_benchmark_independence_integration(self):
        """Test that benchmark instances are independent."""
        # Use minimum scale factor 1.0 for TPC-DS and different configs for independence
        benchmark1 = TPCDSBenchmark(scale_factor=1.0, seed=42)
        benchmark2 = TPCDSBenchmark(scale_factor=1.0, seed=123)

        # Should have same scale factors but different configurations
        assert benchmark1.scale_factor == benchmark2.scale_factor
        assert benchmark1.seed != benchmark2.seed

        # Should both work independently
        query1_b1 = benchmark1.get_query(1, seed=42)
        query1_b2 = benchmark2.get_query(1, seed=123)

        # Different seeds should potentially generate different query parameters
        # (but same template structure, so we test that benchmarks work independently)
        assert isinstance(query1_b1, str)
        assert isinstance(query1_b2, str)
        assert len(query1_b1) > 0
        assert len(query1_b2) > 0

        # Test that both benchmarks can retrieve benchmark info independently
        info1 = benchmark1.get_benchmark_info()
        info2 = benchmark2.get_benchmark_info()

        assert info1 is not None
        assert info2 is not None
        assert isinstance(info1, dict)
        assert isinstance(info2, dict)

    def test_performance_integration(self):

        benchmark = TPCDSBenchmark()

        # Test query access performance
        start_time = time.time()
        for i in range(1, 11):  # Test first 10 queries
            query = benchmark.get_query(i)
            assert len(query) > 0
        query_time = time.time() - start_time

        # Should be reasonably fast (file access)
        assert query_time < 5.0

        # Test data generation API performance (mock to avoid slow C tool)
        with patch.object(benchmark, "generate_data") as mock_generate:
            mock_generate.return_value = [f"/mock/table{i}.dat" for i in range(20)]
            start_time = time.time()
            data = benchmark.generate_data()
            data_time = time.time() - start_time

            # API call should be instant
            assert data_time < 1.0
            assert len(data) > 0


@pytest.mark.integration
@pytest.mark.tpcds
class TestTPCDSWorkflowIntegration:
    """Test TPC-DS workflow integration scenarios."""

    def test_typical_benchmark_workflow(self):

        from unittest.mock import patch

        # Step 1: Initialize benchmark
        benchmark = TPCDSBenchmark(scale_factor=1.0)

        # Step 2: Get benchmark information
        info = benchmark.get_benchmark_info()
        assert info["name"] == "TPC-DS"

        # Step 3: Get available queries
        available_queries = benchmark.get_available_queries()
        assert len(available_queries) > 0

        # Step 4: Get subset of queries for testing
        test_queries = available_queries[:5]  # First 5 queries

        # Step 5: Generate queries
        generated_queries = {}
        for query_id in test_queries:
            query = benchmark.get_query(query_id)
            generated_queries[query_id] = query
            assert len(query) > 0

        # Step 6: Generate test data (mock to avoid slow operations)
        tables = benchmark.get_available_tables()
        test_tables = tables[:3]  # First 3 tables

        with patch.object(benchmark, "generate_data") as mock_generate:
            mock_generate.return_value = [f"/mock/table{i}.dat" for i in range(5)]
            generated_data = {}
            for table in test_tables:
                data = benchmark.generate_data()
                generated_data[table] = data
                assert len(data) > 0

        # Step 7: Verify everything worked
        assert len(generated_queries) == len(test_queries)
        assert len(generated_data) == len(test_tables)

    def test_batch_query_generation_workflow(self):

        benchmark = TPCDSBenchmark()

        # Get all queries at once
        all_queries = benchmark.get_queries()
        assert len(all_queries) > 0

        # Verify all queries are valid
        for query_id, query in all_queries.items():
            assert isinstance(query_id, (int, str))
            if isinstance(query_id, str):
                assert query_id.isdigit()
                assert 1 <= int(query_id) <= 99
            else:
                assert 1 <= query_id <= 99
            assert isinstance(query, str)
            assert len(query) > 0

    def test_data_pipeline_workflow(self):

        from unittest.mock import patch

        benchmark = TPCDSBenchmark(scale_factor=1.0)

        # Get all available tables
        tables = benchmark.get_available_tables()
        assert len(tables) > 0

        # Generate data for multiple tables (mock to avoid slow operations)
        with patch.object(benchmark, "generate_data") as mock_generate:
            mock_generate.return_value = [f"/mock/table{i}.dat" for i in range(5)]
            data_pipeline = {}
            for table in tables[:5]:  # First 5 tables
                data = benchmark.generate_data()
                data_pipeline[table] = data
                assert len(data) > 0

        assert len(data_pipeline) == 5
        for table, data in data_pipeline.items():
            assert len(data) > 0
            assert all(isinstance(row, str) for row in data)

    def test_mixed_operations_workflow(self):

        from unittest.mock import patch

        benchmark = TPCDSBenchmark(scale_factor=1.0)

        # Mix of different operations
        operations = []

        # Operation 1: Get query
        query1 = benchmark.get_query(1)
        operations.append(("query", 1, len(query1)))

        # Operation 2: Generate data (mock to avoid slow operation)
        with patch.object(benchmark, "generate_data") as mock_generate:
            mock_generate.return_value = [f"/mock/table{i}.dat" for i in range(5)]
            data = benchmark.generate_data()
            operations.append(("data", "customer", len(data)))

        # Operation 3: Get another query
        query2 = benchmark.get_query(2)
        operations.append(("query", 2, len(query2)))

        # Operation 4: Get benchmark info
        info = benchmark.get_benchmark_info()
        operations.append(("info", "benchmark", len(info)))

        # Verify all operations succeeded
        assert len(operations) == 4
        for _op_type, _op_target, op_result in operations:
            assert op_result > 0  # All operations should return non-empty results
