"""Integration tests for Write Primitives benchmark execution.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox import WritePrimitives
from benchbox.core.write_primitives.benchmark import OperationResult

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


@pytest.mark.integration
@pytest.mark.write_primitives
class TestWritePrimitivesBasic:
    """Basic integration tests for Write Primitives benchmark."""

    def test_benchmark_initialization(self):
        """Test benchmark can be instantiated."""
        bench = WritePrimitives(scale_factor=0.01, quiet=True)
        assert isinstance(bench, WritePrimitives)
        assert bench.scale_factor == 0.01

    def test_get_benchmark_info(self):
        """Test getting benchmark information."""
        bench = WritePrimitives(scale_factor=0.01, quiet=True)
        info = bench.get_benchmark_info()

        assert info["name"] == "Write Primitives Benchmark"
        assert info["version"] == "1.0"
        assert (
            info["total_operations"] == 109
        )  # Total operations: INSERT (12), UPDATE (15), DELETE (14), BULK_LOAD (36), MERGE (20), DDL (12)
        assert "insert" in info["categories"]
        assert "update" in info["categories"]
        assert "delete" in info["categories"]
        assert "ddl" in info["categories"]
        # Transaction operations moved to Transaction Primitives benchmark
        assert "transaction" not in info["categories"]

    def test_get_operations(self):
        """Test retrieving operations."""
        bench = WritePrimitives(scale_factor=0.01, quiet=True)

        # Get all operations
        all_ops = bench.get_all_operations()
        assert (
            len(all_ops) == 109
        )  # Total operations: INSERT (12), UPDATE (15), DELETE (14), BULK_LOAD (36), MERGE (20), DDL (12)

        # Get by category
        insert_ops = bench.get_operations_by_category("insert")
        assert len(insert_ops) == 12  # INSERT category has 12 operations

        # Get specific operation
        op = bench.get_operation("insert_single_row")
        assert op.id == "insert_single_row"
        assert op.category == "insert"

    def test_get_schema(self):
        """Test getting schema."""
        bench = WritePrimitives(scale_factor=0.01, quiet=True)
        schema = bench.get_schema()

        assert "update_ops_orders" in schema
        assert "delete_ops_lineitem" in schema
        assert "write_ops_log" in schema

    def test_get_create_tables_sql(self):
        """Test SQL generation."""
        bench = WritePrimitives(scale_factor=0.01, quiet=True)
        sql = bench.get_create_tables_sql()

        assert "CREATE TABLE update_ops_orders" in sql
        assert "CREATE TABLE delete_ops_lineitem" in sql
        assert "CREATE TABLE write_ops_log" in sql

    def test_operation_result_structure(self):
        """Test OperationResult dataclass."""
        result = OperationResult(
            operation_id="test_op",
            success=True,
            write_duration_ms=10.5,
            rows_affected=1,
            validation_duration_ms=2.3,
            validation_passed=True,
            validation_results=[],
            cleanup_duration_ms=1.2,
            cleanup_success=True,
        )

        assert result.operation_id == "test_op"
        assert result.success is True
        assert result.write_duration_ms == 10.5
        assert result.error is None

    def test_data_source_sharing(self):
        """Test that benchmark declares TPC-H data sharing."""
        bench = WritePrimitives(scale_factor=0.01, quiet=True)
        assert bench._impl.get_data_source_benchmark() == "tpch"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
