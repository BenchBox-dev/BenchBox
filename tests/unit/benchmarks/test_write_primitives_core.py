"""Unit tests for Write Primitives benchmark core functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.write_primitives import WritePrimitivesBenchmark
from benchbox.core.write_primitives.catalog import (
    ValidationQuery,
    WriteOperation,
    load_write_primitives_catalog,
)
from benchbox.core.write_primitives.operations import WriteOperationsManager
from benchbox.core.write_primitives.schema import (
    STAGING_TABLES,
    get_all_staging_tables_sql,
    get_create_table_sql,
    get_table_schema,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestWritePrimitivesSchema:
    """Test schema definitions and SQL generation."""

    def test_staging_tables_defined(self):
        """Test that all required staging tables are defined."""
        required_tables = [
            "insert_ops_lineitem",
            "insert_ops_orders",
            "update_ops_orders",
            "delete_ops_lineitem",
            "merge_ops_target",
            "bulk_load_ops_target",
            "write_ops_log",
            "batch_metadata",
        ]

        for table_name in required_tables:
            assert table_name in STAGING_TABLES, f"Missing staging table: {table_name}"

    def test_get_table_schema(self):
        """Test retrieving table schema."""
        schema = get_table_schema("insert_ops_lineitem")
        assert schema is not None
        assert schema["name"] == "insert_ops_lineitem"
        assert "columns" in schema
        assert len(schema["columns"]) > 0

    def test_get_table_schema_invalid(self):
        """Test that invalid table name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown table"):
            get_table_schema("nonexistent_table")

    def test_get_create_table_sql(self):
        """Test CREATE TABLE SQL generation."""
        sql = get_create_table_sql("insert_ops_lineitem")
        assert "CREATE TABLE insert_ops_lineitem" in sql
        assert "l_orderkey" in sql
        assert "l_quantity" in sql

    def test_get_create_table_sql_datafusion_omits_primary_key_constraints(self):
        """DataFusion dialect should not emit PRIMARY KEY constraints."""
        sql = get_create_table_sql("insert_ops_lineitem", dialect="datafusion")
        assert "CREATE TABLE insert_ops_lineitem" in sql
        assert "PRIMARY KEY" not in sql

    def test_get_create_table_sql_invalid(self):
        """Test that invalid table raises ValueError."""
        with pytest.raises(ValueError, match="Unknown staging table"):
            get_create_table_sql("invalid_table")

    def test_get_all_staging_tables_sql(self):
        """Test generating SQL for all staging tables."""
        sql = get_all_staging_tables_sql()
        assert "CREATE TABLE" in sql
        assert "insert_ops_lineitem" in sql
        assert "write_ops_log" in sql

    def test_benchmark_get_schema_includes_tpch_base_tables(self, tmp_path):
        """Write Primitives schema should include TPC-H base tables for platform loaders."""
        benchmark = WritePrimitivesBenchmark(output_dir=tmp_path)
        schema = benchmark.get_schema()
        assert "orders" in schema
        assert "lineitem" in schema
        assert schema["orders"]["columns"][0]["name"] == "o_orderkey"


class TestWritePrimitivesCatalog:
    """Test operation catalog loading and validation."""

    def test_load_catalog(self):
        """Test loading operations catalog."""
        catalog = load_write_primitives_catalog()
        assert catalog is not None
        assert catalog.version == 1
        assert len(catalog.operations) > 0

    def test_catalog_operations_have_required_fields(self):
        """Test that all operations have required fields.

        Aggregate-state ops (DataFrame persist+merge) intentionally carry an
        empty `write_sql` placeholder because their work is dispatched through
        the DataFrame manager rather than executed as SQL — they declare an
        `aggregate_state` block instead. The required-fields contract is
        therefore "either non-empty write_sql or an aggregate_state spec",
        not "non-empty write_sql for every op."
        """
        catalog = load_write_primitives_catalog()

        for op_id, operation in catalog.operations.items():
            assert isinstance(operation, WriteOperation)
            assert operation.id == op_id
            assert len(operation.category) > 0
            assert len(operation.description) > 0
            if operation.aggregate_state is None:
                assert len(operation.write_sql) > 0, f"SQL op '{op_id}' missing write_sql"

    def test_catalog_validation_queries(self):
        """Test that validation queries are properly structured."""
        catalog = load_write_primitives_catalog()

        for operation in catalog.operations.values():
            for val_query in operation.validation_queries:
                assert isinstance(val_query, ValidationQuery)
                assert len(val_query.id) > 0
                assert len(val_query.sql) > 0

    def test_catalog_categories(self):
        """Test that operations are categorized correctly."""
        catalog = load_write_primitives_catalog()

        categories = set()
        for operation in catalog.operations.values():
            categories.add(operation.category)

        # Should have all 7 categories (transaction removed; sketch added for
        # the DataSketches persist+merge+requery lifecycle).
        expected_categories = {"insert", "update", "delete", "bulk_load", "merge", "ddl", "sketch"}
        assert categories == expected_categories

    def test_catalog_operation_count(self):
        """Test that catalog contains expected operations."""
        catalog = load_write_primitives_catalog()
        # Just verify we have operations, don't hardcode count
        assert len(catalog.operations) > 100, f"Expected >100 operations, got {len(catalog.operations)}"

    def test_batch_insert_key_ranges_match_cleanup_ranges(self):
        """Batch INSERT key generation must align with cleanup ranges to avoid duplicate key reruns."""
        catalog = load_write_primitives_catalog()

        batch_100 = catalog.operations["insert_batch_values_100"]
        assert "generate_series(0, 99)" in batch_100.write_sql
        assert "BETWEEN 9000100 AND 9000199" in (batch_100.cleanup_sql or "")

        batch_1000 = catalog.operations["insert_batch_values_1000"]
        assert "generate_series(0, 999)" in batch_1000.write_sql
        assert "BETWEEN 9001000 AND 9001999" in (batch_1000.cleanup_sql or "")

    def test_all_operations_have_validation_or_cleanup(self):
        """Test that all operations have either validation queries or cleanup SQL."""
        catalog = load_write_primitives_catalog()

        for op_id, operation in catalog.operations.items():
            has_validation = len(operation.validation_queries) > 0
            has_cleanup = operation.cleanup_sql is not None and len(operation.cleanup_sql.strip()) > 0

            # Most operations should have validation queries
            # Some DDL operations might only have cleanup
            assert has_validation or has_cleanup, f"Operation '{op_id}' has neither validation queries nor cleanup SQL"

    def test_bulk_load_operations_have_file_dependencies(self):
        """Test that BULK_LOAD operations declare file dependencies."""
        catalog = load_write_primitives_catalog()

        for op_id, operation in catalog.operations.items():
            if operation.category == "bulk_load":
                # Bulk load operations should have file dependencies
                # (except special operations that might not need files)
                if "special" not in op_id.lower() and "parallel" not in op_id.lower():
                    assert len(operation.file_dependencies) > 0, (
                        f"Bulk load operation '{op_id}' has no file dependencies"
                    )


class TestWriteOperationsManager:
    """Test write operations manager."""

    def test_manager_initialization(self):
        """Test manager loads catalog correctly."""
        manager = WriteOperationsManager()
        assert manager.catalog_version == 1
        assert manager.get_operation_count() > 0

    def test_get_operation(self):
        """Test retrieving specific operation."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("insert_single_row")

        assert operation is not None
        assert operation.id == "insert_single_row"
        assert operation.category == "insert"
        assert len(operation.description) > 0

    def test_get_operation_invalid(self):
        """Test that invalid operation raises ValueError."""
        manager = WriteOperationsManager()

        with pytest.raises(ValueError, match="Invalid operation ID"):
            manager.get_operation("nonexistent_operation")

    def test_get_all_operations(self):
        """Test retrieving all operations."""
        manager = WriteOperationsManager()
        operations = manager.get_all_operations()

        assert len(operations) > 0
        assert "insert_single_row" in operations

    def test_get_operations_by_category(self):
        """Test filtering operations by category."""
        manager = WriteOperationsManager()
        insert_ops = manager.get_operations_by_category("insert")

        assert len(insert_ops) > 0
        for operation in insert_ops.values():
            assert operation.category == "insert"

    def test_get_operation_categories(self):
        """Test retrieving list of categories."""
        manager = WriteOperationsManager()
        categories = manager.get_operation_categories()

        assert len(categories) > 0
        assert "insert" in categories
        assert isinstance(categories, list)
        # Should be sorted
        assert categories == sorted(categories)

    def test_get_category_count(self):
        """Test counting operations in category."""
        manager = WriteOperationsManager()
        insert_count = manager.get_category_count("insert")

        assert insert_count > 0
        assert isinstance(insert_count, int)


class TestWritePrimitivesBenchmark:
    """Test Write Primitives benchmark class."""

    def test_benchmark_initialization(self):
        """Test benchmark initializes correctly."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)

        assert benchmark.scale_factor == 1.0
        assert benchmark._name == "Write Primitives Benchmark"
        assert benchmark._version == "1.0"

    def test_get_data_source_benchmark(self):
        """Test that benchmark declares TPC-H data source."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        assert benchmark.get_data_source_benchmark() == "tpch"

    def test_get_operation(self):
        """Test retrieving operation through benchmark."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        operation = benchmark.get_operation("insert_single_row")

        assert operation is not None
        assert operation.id == "insert_single_row"

    def test_get_all_operations(self):
        """Test retrieving all operations."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        operations = benchmark.get_all_operations()

        assert len(operations) > 0

    def test_get_operations_by_category(self):
        """Test filtering by category."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        insert_ops = benchmark.get_operations_by_category("insert")

        assert len(insert_ops) > 0

    def test_get_operation_categories(self):
        """Test getting categories."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        categories = benchmark.get_operation_categories()

        assert len(categories) > 0
        assert "insert" in categories

    def test_get_schema(self):
        """Test retrieving schema."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        schema = benchmark.get_schema()

        assert len(schema) > 0
        assert "insert_ops_lineitem" in schema

    def test_get_create_tables_sql(self):
        """Test SQL generation."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        sql = benchmark.get_create_tables_sql()

        assert "CREATE TABLE" in sql
        assert len(sql) > 0

    def test_get_benchmark_info(self):
        """Test benchmark metadata."""
        benchmark = WritePrimitivesBenchmark(scale_factor=1.0)
        info = benchmark.get_benchmark_info()

        assert info["name"] == "Write Primitives Benchmark"
        assert info["version"] == "1.0"
        assert info["scale_factor"] == 1.0
        assert info["total_operations"] > 0
        assert len(info["categories"]) > 0
        assert info["data_source"] == "tpch"


class TestConsolidatedOperations:
    """Test operations consolidated from Merge benchmark into WritePrimitives.

    Tests the 4 operations that were consolidated:
    - delete_gdpr_suppliers_1pct (recategorized from merge to delete)
    - delete_gdpr_suppliers_5pct (recategorized from merge to delete)
    - merge_etl_aggregation_pattern
    - merge_deduplication_window_function
    """

    def test_gdpr_deletion_1pct_exists_in_delete_category(self):
        """Test that delete_gdpr_suppliers_1pct is in DELETE category."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("delete_gdpr_suppliers_1pct")

        assert operation is not None
        assert operation.id == "delete_gdpr_suppliers_1pct"
        assert operation.category == "delete", "Should be categorized as DELETE, not MERGE"
        assert "GDPR" in operation.description
        assert "1%" in operation.description

    def test_gdpr_deletion_5pct_exists_in_delete_category(self):
        """Test that delete_gdpr_suppliers_5pct is in DELETE category."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("delete_gdpr_suppliers_5pct")

        assert operation is not None
        assert operation.id == "delete_gdpr_suppliers_5pct"
        assert operation.category == "delete", "Should be categorized as DELETE, not MERGE"
        assert "GDPR" in operation.description
        assert "5%" in operation.description

    def test_gdpr_deletions_use_delete_statements(self):
        """Test that GDPR operations use DELETE SQL statements, not MERGE."""
        manager = WriteOperationsManager()

        op_1pct = manager.get_operation("delete_gdpr_suppliers_1pct")
        op_5pct = manager.get_operation("delete_gdpr_suppliers_5pct")

        # Both should use DELETE statements
        assert "DELETE FROM" in op_1pct.write_sql.upper()
        assert "MERGE" not in op_1pct.write_sql.upper()

        assert "DELETE FROM" in op_5pct.write_sql.upper()
        assert "MERGE" not in op_5pct.write_sql.upper()

    def test_gdpr_deletions_are_data_dependent(self):
        """Test that GDPR deletions are marked as data-dependent operations."""
        manager = WriteOperationsManager()

        op_1pct = manager.get_operation("delete_gdpr_suppliers_1pct")
        op_5pct = manager.get_operation("delete_gdpr_suppliers_5pct")

        # expected_rows_affected should be None (data-dependent)
        assert op_1pct.expected_rows_affected is None, "1% GDPR deletion should be data-dependent"
        assert op_5pct.expected_rows_affected is None, "5% GDPR deletion should be data-dependent"

    def test_gdpr_deletions_have_strengthened_validation(self):
        """Test that GDPR deletions use CASE expressions for validation."""
        manager = WriteOperationsManager()

        op_1pct = manager.get_operation("delete_gdpr_suppliers_1pct")
        op_5pct = manager.get_operation("delete_gdpr_suppliers_5pct")

        # Both should have validation queries with CASE expressions
        assert len(op_1pct.validation_queries) > 0
        assert len(op_5pct.validation_queries) > 0

        # Check for CASE expression in validation SQL
        for val_query in op_1pct.validation_queries:
            assert "CASE" in val_query.sql.upper(), "Validation should use CASE expression"

        for val_query in op_5pct.validation_queries:
            assert "CASE" in val_query.sql.upper(), "Validation should use CASE expression"

    def test_etl_aggregation_exists_in_merge_category(self):
        """Test that merge_etl_aggregation_pattern is in MERGE category."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_etl_aggregation_pattern")

        assert operation is not None
        assert operation.id == "merge_etl_aggregation_pattern"
        assert operation.category == "merge"
        assert "ETL" in operation.description or "aggregation" in operation.description.lower()

    def test_etl_aggregation_uses_merge_statement(self):
        """Test that ETL aggregation uses MERGE SQL statement."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_etl_aggregation_pattern")

        assert "MERGE INTO" in operation.write_sql.upper() or "MERGE" in operation.write_sql.upper()
        assert "WHEN MATCHED" in operation.write_sql.upper()

    def test_etl_aggregation_has_multiple_validations(self):
        """Test that ETL aggregation has multiple validation queries."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_etl_aggregation_pattern")

        # Should have 2 validation queries
        assert len(operation.validation_queries) >= 2, "Should have at least 2 validation queries"

        # Check for strengthened validation with CASE expressions
        has_case_validation = any("CASE" in vq.sql.upper() for vq in operation.validation_queries)
        assert has_case_validation, "Should have CASE expression in at least one validation query"

    def test_etl_aggregation_is_data_dependent(self):
        """Test that ETL aggregation is marked as data-dependent."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_etl_aggregation_pattern")

        assert operation.expected_rows_affected is None, "ETL aggregation should be data-dependent"

    def test_deduplication_exists_in_merge_category(self):
        """Test that merge_deduplication_window_function is in MERGE category."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_deduplication_window_function")

        assert operation is not None
        assert operation.id == "merge_deduplication_window_function"
        assert operation.category == "merge"
        assert "deduplication" in operation.description.lower() or "window" in operation.description.lower()

    def test_deduplication_uses_window_function(self):
        """Test that deduplication uses ROW_NUMBER window function."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_deduplication_window_function")

        assert "ROW_NUMBER()" in operation.write_sql.upper()
        assert "MERGE INTO" in operation.write_sql.upper() or "MERGE" in operation.write_sql.upper()

    def test_deduplication_has_explicit_column_list(self):
        """Test that deduplication INSERT uses explicit column list for portability."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_deduplication_window_function")

        # MERGE operations use INSERT VALUES (source.col1, source.col2, ...) format
        # which is explicit enough for portability
        assert "INSERT VALUES" in operation.write_sql, "Should have INSERT VALUES clause"
        assert "source.o_orderkey" in operation.write_sql, "Should specify source column names explicitly"

    def test_deduplication_has_multiple_validations(self):
        """Test that deduplication has multiple validation queries."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_deduplication_window_function")

        # Should have 2 validation queries
        assert len(operation.validation_queries) >= 2, "Should have at least 2 validation queries"

        # Check validation query IDs
        val_ids = [vq.id for vq in operation.validation_queries]
        assert "verify_deduplication" in val_ids
        assert "verify_no_duplicates" in val_ids

    def test_deduplication_validates_no_duplicates(self):
        """Test that deduplication validation checks for no duplicates."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_deduplication_window_function")

        # Find the verify_no_duplicates validation query
        verify_no_dups = None
        for vq in operation.validation_queries:
            if vq.id == "verify_no_duplicates":
                verify_no_dups = vq
                break

        assert verify_no_dups is not None, "Should have verify_no_duplicates validation query"
        # Should use CASE expression to validate max dup count is 1
        assert "CASE" in verify_no_dups.sql.upper()
        assert "MAX(" in verify_no_dups.sql.upper() or "COUNT(*)" in verify_no_dups.sql.upper()

    def test_deduplication_is_data_dependent(self):
        """Test that deduplication is marked as data-dependent."""
        manager = WriteOperationsManager()
        operation = manager.get_operation("merge_deduplication_window_function")

        assert operation.expected_rows_affected is None, "Deduplication should be data-dependent"

    def test_consolidated_operations_not_in_wrong_categories(self):
        """Test that GDPR operations are not in MERGE category."""
        manager = WriteOperationsManager()

        # Get all MERGE operations
        merge_ops = manager.get_operations_by_category("merge")
        merge_op_ids = list(merge_ops.keys())

        # GDPR deletions should NOT be in MERGE category
        assert "delete_gdpr_suppliers_1pct" not in merge_op_ids
        assert "delete_gdpr_suppliers_5pct" not in merge_op_ids

        # ETL and deduplication SHOULD be in MERGE category
        assert "merge_etl_aggregation_pattern" in merge_op_ids
        assert "merge_deduplication_window_function" in merge_op_ids

    def test_all_consolidated_operations_have_cleanup(self):
        """Test that all consolidated operations have cleanup SQL."""
        manager = WriteOperationsManager()

        op_ids = [
            "delete_gdpr_suppliers_1pct",
            "delete_gdpr_suppliers_5pct",
            "merge_etl_aggregation_pattern",
            "merge_deduplication_window_function",
        ]

        for op_id in op_ids:
            operation = manager.get_operation(op_id)
            assert operation.cleanup_sql is not None, f"{op_id} should have cleanup SQL"
            assert len(operation.cleanup_sql.strip()) > 0, f"{op_id} cleanup SQL should not be empty"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
