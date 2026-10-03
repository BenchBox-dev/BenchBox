"""Integration tests for DataFrame maintenance operations.

Tests the end-to-end workflow of maintenance operations (INSERT, DELETE, UPDATE, MERGE)
across different DataFrame platforms (Polars, Delta Lake, Iceberg).

These tests verify:
1. Maintenance operations work correctly on each platform
2. TPC compliance metrics are captured correctly
3. Cross-platform consistency for supported operations

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


# =============================================================================
# Platform availability checks
# =============================================================================

try:
    import polars as pl
    import pyarrow as pa

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None
    pa = None

try:
    import deltalake

    DELTA_LAKE_AVAILABLE = True
except ImportError:
    DELTA_LAKE_AVAILABLE = False
    deltalake = None

try:
    import pyiceberg

    ICEBERG_AVAILABLE = True
except ImportError:
    ICEBERG_AVAILABLE = False
    pyiceberg = None


# =============================================================================
# Test fixtures
# =============================================================================


@pytest.fixture
def sample_orders_data():
    """Create sample TPC-H style orders data for testing."""
    if not POLARS_AVAILABLE:
        pytest.skip("Polars not installed")

    return pl.DataFrame(
        {
            "o_orderkey": [1, 2, 3, 4, 5],
            "o_custkey": [100, 100, 200, 200, 300],
            "o_orderstatus": ["F", "O", "F", "O", "P"],
            "o_totalprice": [1000.50, 2000.75, 1500.25, 2500.00, 3000.00],
            "o_orderdate": ["1995-01-01", "1995-02-15", "1995-03-20", "1995-04-10", "1995-05-01"],
            "o_orderpriority": ["1-URGENT", "2-HIGH", "3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"],
        }
    )


@pytest.fixture
def sample_lineitem_data():
    """Create sample TPC-H style lineitem data for testing."""
    if not POLARS_AVAILABLE:
        pytest.skip("Polars not installed")

    return pl.DataFrame(
        {
            "l_orderkey": [1, 1, 2, 3, 4, 5],
            "l_partkey": [101, 102, 103, 104, 105, 106],
            "l_suppkey": [1001, 1002, 1003, 1004, 1005, 1006],
            "l_quantity": [10.0, 20.0, 15.0, 25.0, 30.0, 5.0],
            "l_extendedprice": [1000.0, 2000.0, 1500.0, 2500.0, 3000.0, 500.0],
            "l_discount": [0.05, 0.10, 0.0, 0.05, 0.15, 0.0],
        }
    )


# =============================================================================
# Polars Maintenance Integration Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
class TestPolarsMaintenanceIntegration:
    """Integration tests for Polars maintenance operations."""

    def test_insert_and_query_workflow(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        # Insert initial data
        result = ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")
        assert result.success is True
        assert result.rows_affected == 5

        read_df = pl.read_parquet(table_path / "*.parquet")
        assert len(read_df) == 5

    def test_insert_append_preserves_existing_data(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        # Insert initial data
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        new_orders = pl.DataFrame(
            {
                "o_orderkey": [6, 7],
                "o_custkey": [400, 400],
                "o_orderstatus": ["F", "O"],
                "o_totalprice": [4000.0, 5000.0],
                "o_orderdate": ["1995-06-01", "1995-07-01"],
                "o_orderpriority": ["1-URGENT", "2-HIGH"],
            }
        )
        result = ops.insert_rows(table_path=table_path, dataframe=new_orders, mode="append")

        assert result.success is True
        assert result.rows_affected == 2

        read_df = pl.read_parquet(table_path / "*.parquet")
        assert len(read_df) == 7  # 5 original + 2 new

    def test_delete_reduces_row_count(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        # Insert initial data
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # Delete orders with totalprice > 2500 (only 3000)
        result = ops.delete_rows(table_path=table_path, condition="o_totalprice > 2500")

        assert result.success is True
        assert result.rows_affected == 1  # Only 3000.00

        # Verify remaining data
        read_df = pl.read_parquet(table_path / "*.parquet")
        assert len(read_df) == 4  # 5 - 1 = 4

    def test_tpc_h_rf1_simulation(self, tmp_path, sample_lineitem_data):
        """Simulate TPC-H RF1 (insert new lineitems)."""
        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "lineitem"

        # Initial load
        ops.insert_rows(table_path=table_path, dataframe=sample_lineitem_data, mode="append")

        # RF1: Insert new lineitems (simulating refresh function 1)
        new_lineitems = pl.DataFrame(
            {
                "l_orderkey": [6, 6, 7],
                "l_partkey": [107, 108, 109],
                "l_suppkey": [1007, 1008, 1009],
                "l_quantity": [12.0, 8.0, 15.0],
                "l_extendedprice": [1200.0, 800.0, 1500.0],
                "l_discount": [0.02, 0.08, 0.0],
            }
        )

        result = ops.insert_rows(table_path=table_path, dataframe=new_lineitems, mode="append")

        assert result.success is True
        assert result.rows_affected == 3

        # Verify timing metrics are captured
        assert result.duration >= 0
        assert result.start_time > 0
        assert result.end_time >= result.start_time

    def test_tpc_h_rf2_simulation(self, tmp_path, sample_orders_data):
        """Simulate TPC-H RF2 (delete old orders)."""
        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        # Initial load
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # RF2: Delete orders (simulating refresh function 2)
        result = ops.delete_rows(table_path=table_path, condition="o_orderkey IN (1, 2)")

        assert result.success is True
        assert result.rows_affected == 2

        # Verify remaining orders
        read_df = pl.read_parquet(table_path / "*.parquet")
        remaining_keys = read_df["o_orderkey"].to_list()
        assert 1 not in remaining_keys
        assert 2 not in remaining_keys
        assert 3 in remaining_keys

    def test_tpc_ds_dm3_simulation(self, tmp_path, sample_orders_data):
        """Simulate TPC-DS DM3 (update dimension table)."""
        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        # Initial load
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # DM3: Update order status (simulating dimension update)
        result = ops.update_rows(
            table_path=table_path,
            condition="o_orderstatus = 'P'",
            updates={"o_orderstatus": "'F'"},  # Change pending to fulfilled
        )

        assert result.success is True
        assert result.rows_affected == 1  # One pending order

        # Verify update
        read_df = pl.read_parquet(table_path / "*.parquet")
        pending_count = len(read_df.filter(pl.col("o_orderstatus") == "P"))
        assert pending_count == 0

    def test_merge_upsert_workflow(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        # Initial load
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # Merge: Update order 1, insert order 10
        source_df = pl.DataFrame(
            {
                "o_orderkey": [1, 10],
                "o_custkey": [100, 999],
                "o_orderstatus": ["X", "N"],  # Updated and new
                "o_totalprice": [9999.0, 1000.0],
                "o_orderdate": ["1995-01-01", "1996-01-01"],
                "o_orderpriority": ["1-URGENT", "5-LOW"],
            }
        )

        result = ops.merge_rows(
            table_path=table_path,
            source_dataframe=source_df,
            merge_condition="o_orderkey",
            when_matched={"o_orderstatus": "source.o_orderstatus"},
            when_not_matched={"o_orderkey": "source.o_orderkey", "o_orderstatus": "source.o_orderstatus"},
        )

        assert result.success is True
        assert result.rows_affected == 2  # 1 update + 1 insert

        # Verify results
        read_df = pl.read_parquet(table_path / "*.parquet")
        assert len(read_df) == 6  # 5 original + 1 new

        # Order 1 should have status 'X'
        order1 = read_df.filter(pl.col("o_orderkey") == 1)
        assert order1["o_orderstatus"][0] == "X"

        # Order 10 should exist
        order10 = read_df.filter(pl.col("o_orderkey") == 10)
        assert len(order10) == 1


# =============================================================================
# Delta Lake Maintenance Integration Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.skipif(not DELTA_LAKE_AVAILABLE or not POLARS_AVAILABLE, reason="Delta Lake or Polars not installed")
class TestDeltaLakeMaintenanceIntegration:
    """Integration tests for Delta Lake maintenance operations."""

    def test_insert_and_query_workflow(self, tmp_path, sample_orders_data):

        from deltalake import DeltaTable

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        table_path = tmp_path / "delta_orders"

        # Insert initial data
        result = ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")
        assert result.success is True
        assert result.rows_affected == 5

        # Read back via Delta Lake and verify
        dt = DeltaTable(str(table_path))
        read_df = dt.to_pandas()
        assert len(read_df) == 5

    def test_delete_with_acid_guarantees(self, tmp_path, sample_orders_data):

        from deltalake import DeltaTable

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        table_path = tmp_path / "delta_orders"

        # Insert initial data
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # Delete orders with custkey = 200
        result = ops.delete_rows(table_path=table_path, condition="o_custkey = 200")

        assert result.success is True
        assert result.rows_affected == 2  # Orders 3 and 4

        # Verify via Delta Lake
        dt = DeltaTable(str(table_path))
        read_df = dt.to_pandas()
        assert len(read_df) == 3
        assert 200 not in read_df["o_custkey"].values

    def test_update_rows_acid(self, tmp_path, sample_orders_data):

        from deltalake import DeltaTable

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        table_path = tmp_path / "delta_orders"

        # Insert initial data
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # Update order status for pending orders
        result = ops.update_rows(
            table_path=table_path,
            condition="o_orderstatus = 'P'",
            updates={"o_orderstatus": "'F'"},  # SQL-style string literal
        )

        assert result.success is True

        # Verify update
        dt = DeltaTable(str(table_path))
        read_df = dt.to_pandas()
        pending_count = len(read_df[read_df["o_orderstatus"] == "P"])
        assert pending_count == 0  # No more pending orders

    def test_merge_upsert_operation(self, tmp_path, sample_orders_data):

        from deltalake import DeltaTable

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        table_path = tmp_path / "delta_orders"

        # Insert initial data
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # Merge: update existing order 1, insert new order 6
        source_data = pa.table(
            {
                "o_orderkey": [1, 6],
                "o_custkey": [100, 500],
                "o_orderstatus": ["F", "O"],
                "o_totalprice": [1500.0, 6000.0],  # Updated price for order 1
                "o_orderdate": ["1995-01-01", "1995-08-01"],
                "o_orderpriority": ["1-URGENT", "1-URGENT"],
            }
        )

        result = ops.merge_rows(
            table_path=table_path,
            source_dataframe=source_data,
            merge_condition="target.o_orderkey = source.o_orderkey",
            when_matched={"o_totalprice": "source.o_totalprice"},
            when_not_matched={
                "o_orderkey": "source.o_orderkey",
                "o_custkey": "source.o_custkey",
                "o_orderstatus": "source.o_orderstatus",
                "o_totalprice": "source.o_totalprice",
                "o_orderdate": "source.o_orderdate",
                "o_orderpriority": "source.o_orderpriority",
            },
        )

        assert result.success is True

        # Verify merge results
        dt = DeltaTable(str(table_path))
        read_df = dt.to_pandas()
        assert len(read_df) == 6  # 5 original + 1 new

        # Check order 1 was updated
        order1 = read_df[read_df["o_orderkey"] == 1]
        assert order1["o_totalprice"].iloc[0] == 1500.0

        # Check order 6 was inserted
        order6 = read_df[read_df["o_orderkey"] == 6]
        assert len(order6) == 1

    def test_time_travel_capability(self, tmp_path, sample_orders_data):

        from deltalake import DeltaTable

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        table_path = tmp_path / "delta_orders"

        # Insert initial data
        ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        # Delete some rows
        ops.delete_rows(table_path=table_path, condition="o_custkey = 300")

        # Current version should have 4 rows
        dt = DeltaTable(str(table_path))
        current_count = dt.to_pyarrow_table().num_rows
        assert current_count == 4

        # Time travel to version 0 should have 5 rows
        dt_v0 = DeltaTable(str(table_path), version=0)
        v0_count = dt_v0.to_pyarrow_table().num_rows
        assert v0_count == 5


# =============================================================================
# Iceberg Maintenance Integration Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.skipif(not ICEBERG_AVAILABLE or not POLARS_AVAILABLE, reason="Iceberg or Polars not installed")
@pytest.mark.skipif(__import__("sys").platform == "win32", reason="pyiceberg does not support Windows paths")
class TestIcebergMaintenanceIntegration:
    """Integration tests for Apache Iceberg maintenance operations."""

    def test_insert_and_query_workflow(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.iceberg_maintenance import IcebergMaintenanceOperations

        ops = IcebergMaintenanceOperations(working_dir=tmp_path)

        # Insert initial data - use qualified table name
        result = ops.insert_rows(table_path="default.orders", dataframe=sample_orders_data, mode="append")
        assert result.success is True
        assert result.rows_affected == 5

        # Read back via Iceberg
        table = ops.catalog.load_table("default.orders")
        read_table = table.scan().to_arrow()
        assert read_table.num_rows == 5

    def test_insert_append_mode(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.iceberg_maintenance import IcebergMaintenanceOperations

        ops = IcebergMaintenanceOperations(working_dir=tmp_path)

        # Insert initial data
        ops.insert_rows(table_path="default.orders", dataframe=sample_orders_data, mode="append")

        new_orders = pl.DataFrame(
            {
                "o_orderkey": [6, 7],
                "o_custkey": [400, 400],
                "o_orderstatus": ["F", "O"],
                "o_totalprice": [4000.0, 5000.0],
                "o_orderdate": ["1995-06-01", "1995-07-01"],
                "o_orderpriority": ["1-URGENT", "2-HIGH"],
            }
        )
        result = ops.insert_rows(table_path="default.orders", dataframe=new_orders, mode="append")

        assert result.success is True
        assert result.rows_affected == 2

        # Verify total rows
        table = ops.catalog.load_table("default.orders")
        read_table = table.scan().to_arrow()
        assert read_table.num_rows == 7


# =============================================================================
# Cross-Platform Consistency Tests
# =============================================================================


@pytest.mark.integration
class TestMaintenanceCapabilitiesConsistency:
    """Tests that verify consistent capability reporting across platforms."""

    @pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
    def test_polars_capabilities_match_spec(self):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations()
        caps = ops.get_capabilities()

        # Polars supports all operations via read-modify-write pattern
        assert caps.supports_insert is True
        assert caps.supports_delete is True
        assert caps.supports_update is True
        assert caps.supports_merge is True
        assert caps.supports_partitioned_delete is True

        # Polars does NOT have transaction logs (no ACID guarantees)
        assert caps.supports_transactions is False
        assert caps.supports_time_travel is False

    @pytest.mark.skipif(not DELTA_LAKE_AVAILABLE, reason="Delta Lake not installed")
    def test_delta_lake_capabilities_match_spec(self):

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        caps = ops.get_capabilities()

        # Delta Lake should support full ACID
        assert caps.supports_insert is True
        assert caps.supports_delete is True
        assert caps.supports_update is True
        assert caps.supports_merge is True
        assert caps.supports_transactions is True
        assert caps.supports_time_travel is True

    @pytest.mark.skipif(not ICEBERG_AVAILABLE, reason="Iceberg not installed")
    def test_iceberg_capabilities_match_spec(self):

        from benchbox.platforms.dataframe.iceberg_maintenance import IcebergMaintenanceOperations

        ops = IcebergMaintenanceOperations()
        caps = ops.get_capabilities()

        # Iceberg should support full ACID
        assert caps.supports_insert is True
        assert caps.supports_delete is True
        assert caps.supports_update is True
        assert caps.supports_merge is True
        assert caps.supports_transactions is True
        assert caps.supports_time_travel is True


# =============================================================================
# TPC Compliance Validation Tests
# =============================================================================


@pytest.mark.integration
class TestTPCComplianceValidation:
    """Tests that verify TPC compliance requirements are met."""

    @pytest.mark.skipif(not DELTA_LAKE_AVAILABLE, reason="Delta Lake not installed")
    def test_delta_lake_tpc_h_compliance(self):

        from benchbox.platforms.dataframe.delta_lake_maintenance import DeltaLakeMaintenanceOperations

        ops = DeltaLakeMaintenanceOperations()
        caps = ops.get_capabilities()

        is_compliant, missing = caps.validate_tpc_compliance()

        assert is_compliant is True, f"Delta Lake should be TPC compliant. Missing: {missing}"
        assert len(missing) == 0

    @pytest.mark.skipif(not ICEBERG_AVAILABLE, reason="Iceberg not installed")
    def test_iceberg_tpc_h_compliance(self):

        from benchbox.platforms.dataframe.iceberg_maintenance import IcebergMaintenanceOperations

        ops = IcebergMaintenanceOperations()
        caps = ops.get_capabilities()

        is_compliant, missing = caps.validate_tpc_compliance()

        assert is_compliant is True, f"Iceberg should be TPC compliant. Missing: {missing}"
        assert len(missing) == 0

    @pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
    def test_polars_tpc_compliance(self):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations()
        caps = ops.get_capabilities()

        is_compliant, missing = caps.validate_tpc_compliance()

        # Polars should be fully TPC compliant (all operations supported)
        assert is_compliant is True, f"Polars should be TPC compliant. Missing: {missing}"
        assert len(missing) == 0


# =============================================================================
# Performance Metrics Capture Tests
# =============================================================================


@pytest.mark.integration
@pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
class TestMaintenanceMetricsCapture:
    """Tests that verify maintenance metrics are captured correctly."""

    def test_timing_metrics_captured(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        result = ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")

        assert result.start_time > 0
        assert result.end_time >= result.start_time
        assert result.duration >= 0
        assert result.duration == result.end_time - result.start_time

    def test_row_count_metrics_accurate(self, tmp_path, sample_orders_data):

        from benchbox.platforms.dataframe.polars_maintenance import PolarsMaintenanceOperations

        ops = PolarsMaintenanceOperations(working_dir=tmp_path)
        table_path = tmp_path / "orders"

        insert_result = ops.insert_rows(table_path=table_path, dataframe=sample_orders_data, mode="append")
        assert insert_result.rows_affected == 5

        # Delete
        delete_result = ops.delete_rows(table_path=table_path, condition="o_custkey = 100")
        assert delete_result.rows_affected == 2  # Two orders for customer 100
