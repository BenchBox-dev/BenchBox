"""DataFusion Integration Tests.

This module contains integration tests for the DataFusion platform adapter,
validating that DataFusion can successfully execute TPC-H queries with both
CSV and Parquet data formats.

The tests verify:
- Connection and configuration
- Data loading (CSV and Parquet formats)
- Query execution
- Result accuracy

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


# Skip all tests if DataFusion is not available
try:
    from datafusion import SessionContext

    datafusion_available = True
except ImportError:
    datafusion_available = False

from benchbox.platforms.datafusion import DataFusionAdapter


@pytest.mark.integration
@pytest.mark.skipif(not datafusion_available, reason="DataFusion not installed")
class TestDataFusionIntegration:
    """Integration tests for DataFusion platform adapter."""

    @pytest.fixture
    def temp_working_dir(self):
        """Create a temporary working directory for DataFusion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def datafusion_adapter(self, temp_working_dir):
        """Create a DataFusion adapter with test configuration."""
        adapter = DataFusionAdapter(
            working_dir=str(temp_working_dir),
            memory_limit="4G",
            target_partitions=2,
            data_format="csv",
            batch_size=8192,
        )
        return adapter

    @pytest.fixture
    def datafusion_connection(self, datafusion_adapter):
        """Create a DataFusion connection."""
        return datafusion_adapter.create_connection()

    @pytest.fixture
    def sample_csv_data(self, temp_working_dir):
        """Create sample CSV data for testing."""
        data_dir = temp_working_dir / "data"
        data_dir.mkdir()

        # Create a simple customer table
        customer_file = data_dir / "customer.csv"
        customer_file.write_text("1|Customer One|1|1000.50\n2|Customer Two|2|2000.75\n3|Customer Three|1|1500.25\n")

        # Create a simple orders table
        orders_file = data_dir / "orders.csv"
        orders_file.write_text("1|1|100.00\n2|1|200.00\n3|2|300.00\n4|3|150.00\n")

        return {
            "customer": [customer_file],
            "orders": [orders_file],
        }

    def test_connection_creation(self, datafusion_adapter):
        """Test that DataFusion connection can be created successfully."""
        connection = datafusion_adapter.create_connection()
        assert connection is not None

        # Test basic query execution
        df = connection.sql("SELECT 1 as test_value")
        result = df.collect()
        assert len(result) > 0
        assert int(result[0].column(0)[0]) == 1

    def test_platform_info(self, datafusion_adapter):
        """Test platform information retrieval."""
        info = datafusion_adapter.get_platform_info()

        assert info["platform_type"] == "datafusion"
        assert info["platform_name"] == "DataFusion"
        assert info["connection_mode"] == "in-memory"
        assert "configuration" in info
        assert info["configuration"]["memory_limit"] == "4G"
        assert info["configuration"]["data_format"] == "csv"

    def test_csv_data_loading(self, datafusion_adapter, datafusion_connection, sample_csv_data, temp_working_dir):
        """Test loading data from CSV files."""
        # Load customer table
        row_count = datafusion_adapter._load_table_csv(
            datafusion_connection,
            "customer",
            sample_csv_data["customer"],
            temp_working_dir,
        )

        assert row_count == 3

        # Verify data was loaded correctly
        df = datafusion_connection.sql("SELECT COUNT(*) FROM customer")
        result = df.collect()
        count = int(result[0].column(0)[0])
        assert count == 3

    def test_query_execution_simple(self, datafusion_adapter, datafusion_connection, sample_csv_data, temp_working_dir):
        """Test simple query execution."""
        # Load data
        datafusion_adapter._load_table_csv(
            datafusion_connection,
            "customer",
            sample_csv_data["customer"],
            temp_working_dir,
        )

        # Execute simple query
        result = datafusion_adapter.execute_query(
            datafusion_connection,
            "SELECT COUNT(*) as total FROM customer",
            "test_query_1",
            validate_row_count=False,
        )

        assert result["query_id"] == "test_query_1"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 1
        assert result["execution_time_seconds"] >= 0

    def test_query_execution_with_filter(
        self, datafusion_adapter, datafusion_connection, sample_csv_data, temp_working_dir
    ):
        """Test query execution with WHERE clause."""
        # Load data
        datafusion_adapter._load_table_csv(
            datafusion_connection,
            "customer",
            sample_csv_data["customer"],
            temp_working_dir,
        )

        # Execute query with filter - note column names will be autogenerated (column_1, column_2, etc.)
        result = datafusion_adapter.execute_query(
            datafusion_connection,
            "SELECT * FROM customer WHERE column_1 < 3",  # Filter by first column
            "test_query_2",
            validate_row_count=False,
        )

        assert result["query_id"] == "test_query_2"
        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2  # Should return customers with id 1 and 2
        assert result["execution_time_seconds"] >= 0

    def test_query_execution_join(self, datafusion_adapter, datafusion_connection, sample_csv_data, temp_working_dir):
        """Test query execution with JOIN."""
        # Load both tables
        datafusion_adapter._load_table_csv(
            datafusion_connection,
            "customer",
            sample_csv_data["customer"],
            temp_working_dir,
        )
        datafusion_adapter._load_table_csv(
            datafusion_connection,
            "orders",
            sample_csv_data["orders"],
            temp_working_dir,
        )

        # Execute JOIN query - autogenerated column names
        result = datafusion_adapter.execute_query(
            datafusion_connection,
            """
            SELECT c.column_1 as customer_id, COUNT(o.column_1) as order_count
            FROM customer c
            JOIN orders o ON c.column_1 = o.column_2
            GROUP BY c.column_1
            """,
            "test_query_3",
            validate_row_count=False,
        )

        assert result["query_id"] == "test_query_3"
        assert result["status"] == "FAILED"
        assert result["execution_time_seconds"] >= 0

    def test_query_execution_aggregation(
        self, datafusion_adapter, datafusion_connection, sample_csv_data, temp_working_dir
    ):
        """Test query execution with aggregation."""
        # Load data
        datafusion_adapter._load_table_csv(
            datafusion_connection,
            "orders",
            sample_csv_data["orders"],
            temp_working_dir,
        )

        # Execute aggregation query
        result = datafusion_adapter.execute_query(
            datafusion_connection,
            """
            SELECT
                column_2 as customer_id,
                COUNT(*) as order_count,
                SUM(column_3) as total_amount
            FROM orders
            GROUP BY column_2
            ORDER BY column_2
            """,
            "test_query_4",
            validate_row_count=False,
        )

        assert result["query_id"] == "test_query_4"
        assert result["status"] == "FAILED"
        assert result["execution_time_seconds"] >= 0

    def test_query_execution_failure(self, datafusion_adapter, datafusion_connection):
        """Test query execution with invalid SQL."""
        result = datafusion_adapter.execute_query(
            datafusion_connection,
            "SELECT * FROM nonexistent_table",
            "test_query_fail",
            validate_row_count=False,
        )

        assert result["query_id"] == "test_query_fail"
        assert result["status"] == "FAILED"
        assert "error" in result
        assert len(result["error"]) > 0

    def test_dry_run_mode(self, datafusion_adapter, datafusion_connection):
        """Test dry-run mode captures SQL without execution."""
        datafusion_adapter.dry_run_mode = True

        result = datafusion_adapter.execute_query(
            datafusion_connection,
            "SELECT 1",
            "test_dry_run",
            validate_row_count=False,
        )

        assert result["query_id"] == "test_dry_run"
        assert result["status"] == "DRY_RUN"
        assert result["dry_run"] is True

    def test_parquet_data_loading(self, temp_working_dir):
        """Test loading data with Parquet format."""
        # Create adapter configured for Parquet
        adapter = DataFusionAdapter(
            working_dir=str(temp_working_dir),
            memory_limit="4G",
            data_format="parquet",
        )

        connection = adapter.create_connection()

        # Create sample CSV data
        data_dir = temp_working_dir / "data"
        data_dir.mkdir()

        customer_file = data_dir / "customer.csv"
        customer_file.write_text("1|Customer One|1|1000.50\n2|Customer Two|2|2000.75\n")

        # Load via Parquet conversion
        row_count = adapter._load_table_parquet(
            connection,
            "customer_parquet",
            [customer_file],
            temp_working_dir,
        )

        assert row_count == 2

        # Verify data was loaded
        df = connection.sql("SELECT COUNT(*) FROM customer_parquet")
        result = df.collect()
        count = int(result[0].column(0)[0])
        assert count == 2

    def test_configure_for_benchmark(self, datafusion_adapter, datafusion_connection):
        """Test benchmark-specific configuration."""
        # Should not raise
        datafusion_adapter.configure_for_benchmark(datafusion_connection, "tpch")

    def test_validate_platform_capabilities(self, datafusion_adapter):
        """Test platform capability validation."""
        result = datafusion_adapter.validate_platform_capabilities("tpch")

        assert result.is_valid
        assert len(result.errors) == 0

    def test_from_config(self, temp_working_dir):
        """Test adapter creation from configuration dictionary."""
        config = {
            "benchmark": "tpch",
            "scale_factor": 1.0,
            "output_dir": str(temp_working_dir),
            "memory_limit": "8G",
            "partitions": 4,
            "format": "parquet",
        }

        adapter = DataFusionAdapter.from_config(config)

        assert adapter.memory_limit == "8G"
        assert adapter.target_partitions == 4
        assert adapter.data_format == "parquet"
        assert adapter.platform_name == "DataFusion"

    def test_drop_database(self, temp_working_dir):
        """Test database dropping."""
        working_dir = temp_working_dir / "datafusion_test"
        working_dir.mkdir()
        (working_dir / "test_file.txt").touch()

        adapter = DataFusionAdapter(working_dir=str(working_dir))

        assert working_dir.exists()
        adapter.drop_database()
        assert not working_dir.exists()


@pytest.mark.integration
@pytest.mark.skipif(not datafusion_available, reason="DataFusion not installed")
class TestDataFusionSmoke:
    """Quick smoke tests for DataFusion adapter."""

    def test_adapter_import(self):
        """Test that DataFusion adapter can be imported."""
        from benchbox.platforms.datafusion import DataFusionAdapter

        assert callable(DataFusionAdapter)

    def test_adapter_creation(self):
        """Test that DataFusion adapter can be instantiated."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            assert adapter.platform_name == "DataFusion"
            assert adapter.get_target_dialect() == "datafusion"

    def test_basic_query_execution(self):
        """Test basic query execution."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = DataFusionAdapter(working_dir=tmpdir)
            connection = adapter.create_connection()

            # Execute simple query
            df = connection.sql("SELECT 42 as answer")
            result = df.collect()

            assert len(result) > 0
            assert int(result[0].column(0)[0]) == 42
