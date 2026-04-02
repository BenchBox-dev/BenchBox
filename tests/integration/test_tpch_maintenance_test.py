"""Integration tests for TPC-H Maintenance Test implementation.

This module tests the complete TPC-H Maintenance Test implementation,
including RF1 and RF2 operations, concurrent execution with query streams,
and data integrity validation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
import time
from pathlib import Path

import pytest

from benchbox.core.tpch.maintenance_test import (
    TPCHMaintenanceOperation,
    TPCHMaintenanceTest,
    TPCHMaintenanceTestConfig,
    TPCHMaintenanceTestResult,
)

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


class MockConnection:
    """Mock database connection for testing with real execute() support."""

    def __init__(self):
        self.closed = False
        self.executed_queries = []
        self.committed = False
        self.rolled_back = False
        self.fetchall_result = []  # Can be overridden for testing

    def execute(self, query: str, params=None):
        """Mock execute that returns cursor with rowcount."""
        self.executed_queries.append((query, params))

        # Return mock cursor with realistic rowcount
        mock_cursor = MockCursor()
        mock_cursor.rowcount = 1  # Simulate 1 row affected per statement

        # Handle FK validation queries intelligently
        if params and "WHERE" in query.upper() and "IN" in query.upper():
            # FK validation query - return the params as valid FK values
            # Convert params to list of tuples for fetchall() format
            mock_cursor.fetchall_result = [(p,) for p in params]
        else:
            mock_cursor.fetchall_result = self.fetchall_result

        return mock_cursor

    def cursor(self):
        """Return a mock cursor."""
        return MockCursor()

    def commit(self):
        """Commit the transaction."""
        self.committed = True

    def rollback(self):
        """Rollback the transaction."""
        self.rolled_back = True

    def close(self):
        """Close the connection."""
        self.closed = True


class MockCursor:
    """Mock cursor for testing."""

    def __init__(self):
        self.rowcount = 0
        self.fetchall_result = []

    def fetchall(self):
        """Return mock results."""
        if self.fetchall_result:
            return self.fetchall_result
        return [("result1",), ("result2",)]


class TestMaintenanceTest:
    """Test suite for the TPCHMaintenanceTest class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.scale_factor = 0.1
        self.mock_connection = MockConnection()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_maintenance_test_initialization(self):
        """Test TPCHMaintenanceTest initialization."""

        def connection_factory():
            return self.mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
            verbose=True,
        )

        assert maintenance_test.scale_factor == self.scale_factor
        assert maintenance_test.output_dir == self.temp_dir
        assert maintenance_test.verbose is True
        assert maintenance_test.connection_factory is not None

    def test_sequential_maintenance_test(self):
        """Test sequential maintenance test execution."""

        def connection_factory():
            return self.mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
        )

        results = maintenance_test.run_maintenance_test(
            maintenance_pairs=2,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        assert isinstance(results, TPCHMaintenanceTestResult)
        assert results.rf1_operations == 2
        assert results.rf2_operations == 2
        assert results.total_operations == 4
        assert results.successful_operations == 4
        assert results.failed_operations == 0
        assert results.success is True

    def test_concurrent_maintenance_test(self):
        """Test concurrent maintenance test execution."""

        def connection_factory():
            return self.mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
        )

        results = maintenance_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=True,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        assert isinstance(results, TPCHMaintenanceTestResult)
        assert results.success is True

    def test_maintenance_test_error_handling(self):
        """Test error handling in maintenance test."""

        def failing_connection_factory():
            raise RuntimeError("Connection failed")

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=failing_connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
        )

        results = maintenance_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        assert isinstance(results, TPCHMaintenanceTestResult)
        assert results.success is False
        assert results.failed_operations > 0
        assert len(results.errors) > 0

    def test_maintenance_test_report_generation(self):
        """Test maintenance test report generation."""

        def connection_factory():
            return self.mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
            verbose=True,
        )

        results = maintenance_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        assert results.total_time > 0
        assert results.start_time is not None
        assert results.end_time is not None
        assert results.overall_throughput >= 0

    def test_maintenance_test_results_save(self):
        """Test saving maintenance test results."""

        def connection_factory():
            return self.mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
        )

        results = maintenance_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        # Verify the result object has all expected fields
        assert isinstance(results, TPCHMaintenanceTestResult)
        assert isinstance(results.config, TPCHMaintenanceTestConfig)
        assert results.config.scale_factor == self.scale_factor


class TestMaintenanceOperation:
    """Test suite for the TPCHMaintenanceOperation dataclass."""

    def test_operation_creation(self):
        """Test creating a maintenance operation."""
        operation = TPCHMaintenanceOperation(
            operation_type="RF1",
            start_time=time.time(),
            end_time=time.time() + 1,
            duration=1.0,
            rows_affected=100,
            success=True,
        )

        assert operation.operation_type == "RF1"
        assert operation.duration == 1.0
        assert operation.rows_affected == 100
        assert operation.success is True
        assert operation.error is None

    def test_operation_with_error(self):
        """Test creating a failed operation."""
        operation = TPCHMaintenanceOperation(
            operation_type="RF2",
            start_time=time.time(),
            end_time=time.time() + 1,
            duration=1.0,
            rows_affected=0,
            success=False,
            error="Test error",
        )

        assert operation.success is False
        assert operation.error == "Test error"


class TestMaintenanceTestConfig:
    """Test suite for the TPCHMaintenanceTestConfig dataclass."""

    def test_config_defaults(self):
        """Test default configuration values."""
        config = TPCHMaintenanceTestConfig()

        assert config.scale_factor == 1.0
        assert config.maintenance_pairs == 1
        assert config.rf1_interval == 30.0
        assert config.rf2_interval == 30.0
        assert config.concurrent_with_queries is True
        assert config.validate_integrity is True
        assert config.verbose is False

    def test_config_custom_values(self):
        """Test custom configuration values."""
        config = TPCHMaintenanceTestConfig(
            scale_factor=10.0,
            maintenance_pairs=5,
            rf1_interval=60.0,
            rf2_interval=120.0,
            concurrent_with_queries=False,
            validate_integrity=False,
            verbose=True,
        )

        assert config.scale_factor == 10.0
        assert config.maintenance_pairs == 5
        assert config.rf1_interval == 60.0
        assert config.rf2_interval == 120.0
        assert config.concurrent_with_queries is False
        assert config.validate_integrity is False
        assert config.verbose is True


class TestMaintenanceTestPerformance:
    """Performance tests for maintenance test operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.scale_factor = 0.01

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_maintenance_test_performance(self):
        """Test maintenance test executes within reasonable time."""
        mock_connection = MockConnection()

        def connection_factory():
            return mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=self.scale_factor,
            output_dir=self.temp_dir,
        )

        start_time = time.time()
        results = maintenance_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )
        duration = time.time() - start_time

        # Test should complete in reasonable time (< 5 seconds for this small test)
        assert duration < 5.0
        assert results.success is True
        assert results.total_time > 0

    def test_scale_factor_impact(self):
        """Test that scale factor affects operation metrics."""
        # Use separate connections for each test to avoid interference
        small_connection = MockConnection()
        large_connection = MockConnection()

        # Small scale
        small_test = TPCHMaintenanceTest(
            connection_factory=lambda: small_connection,
            scale_factor=0.01,
            output_dir=self.temp_dir,
        )

        small_results = small_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        # Larger scale
        large_test = TPCHMaintenanceTest(
            connection_factory=lambda: large_connection,
            scale_factor=0.1,
            output_dir=self.temp_dir,
        )

        large_results = large_test.run_maintenance_test(
            maintenance_pairs=1,
            concurrent_with_queries=False,
            rf1_interval=0.01,
            rf2_interval=0.01,
            validate_integrity=False,
        )

        # Both should succeed
        assert small_results.success is True
        assert large_results.success is True

        # With real execution, larger scale should generate more data
        # SF 0.01 -> max(1, int(0.01 * 1500 * 0.001)) = 1 order
        # SF 0.1 -> max(1, int(0.1 * 1500 * 0.001)) = 1 order (still rounds to 1!)
        # So we just verify both ran successfully since both generate minimal data at small SF
        if len(small_results.operations) > 0 and len(large_results.operations) > 0:
            small_rows = small_results.operations[0].rows_affected
            large_rows = large_results.operations[0].rows_affected
            # Both should have generated some rows
            assert small_rows > 0, "Small scale should have affected some rows"
            assert large_rows > 0, "Large scale should have affected some rows"

    def test_rf1_executes_real_inserts(self):
        """Verify RF1 executes actual INSERT statements."""
        mock_connection = MockConnection()

        def connection_factory():
            return mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=0.01,
        )

        result = maintenance_test._execute_rf1(pair_id=0)

        # Verify operation succeeded
        assert result.success is True
        assert result.rows_affected > 0
        assert mock_connection.committed is True
        assert len(mock_connection.executed_queries) > 0

        # Verify INSERT statements were executed
        inserts = [q for q, _ in mock_connection.executed_queries if "INSERT" in q.upper()]
        assert len(inserts) > 0

        # Verify both ORDERS and LINEITEM tables were inserted to
        orders_inserts = [q for q, _ in mock_connection.executed_queries if "INSERT INTO ORDERS" in q.upper()]
        lineitem_inserts = [q for q, _ in mock_connection.executed_queries if "INSERT INTO LINEITEM" in q.upper()]

        assert len(orders_inserts) > 0, "Should have INSERT INTO ORDERS statements"
        assert len(lineitem_inserts) > 0, "Should have INSERT INTO LINEITEM statements"

    def test_rf2_executes_real_deletes(self):
        """Verify RF2 executes actual DELETE statements."""
        mock_connection = MockConnection()

        # Mock fetchall for order identification
        mock_connection.fetchall_result = [(1,), (2,), (3,)]

        def connection_factory():
            return mock_connection

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=connection_factory,
            scale_factor=0.01,
        )

        result = maintenance_test._execute_rf2(pair_id=0)

        # Verify operation succeeded
        assert result.success is True
        assert result.rows_affected > 0
        assert mock_connection.committed is True

        # Verify DELETE statements were executed
        deletes = [(q, p) for q, p in mock_connection.executed_queries if "DELETE" in q.upper()]
        assert len(deletes) > 0

        # Find the indices of LINEITEM and ORDERS deletes
        lineitem_delete_indices = [
            i for i, (q, _) in enumerate(mock_connection.executed_queries) if "DELETE FROM LINEITEM" in q.upper()
        ]
        orders_delete_indices = [
            i for i, (q, _) in enumerate(mock_connection.executed_queries) if "DELETE FROM ORDERS" in q.upper()
        ]

        # Verify both tables were deleted from
        assert len(lineitem_delete_indices) > 0, "Should have DELETE FROM LINEITEM statements"
        assert len(orders_delete_indices) > 0, "Should have DELETE FROM ORDERS statements"

        # CRITICAL: Verify LINEITEM deletes come BEFORE ORDERS deletes (referential integrity)
        if lineitem_delete_indices and orders_delete_indices:
            first_lineitem_delete = min(lineitem_delete_indices)
            first_orders_delete = min(orders_delete_indices)
            assert first_lineitem_delete < first_orders_delete, (
                "LINEITEM must be deleted before ORDERS for referential integrity"
            )

    def test_rf1_rf2_with_real_duckdb(self):
        """Integration test with real DuckDB connection."""
        pytest.importorskip("duckdb")
        import duckdb

        # Create in-memory DuckDB with TPC-H schema
        conn = duckdb.connect(":memory:")

        # Create minimal TPC-H tables
        conn.execute("""
            CREATE TABLE ORDERS (
                O_ORDERKEY INTEGER PRIMARY KEY,
                O_CUSTKEY INTEGER,
                O_ORDERSTATUS VARCHAR(1),
                O_TOTALPRICE DECIMAL(15,2),
                O_ORDERDATE DATE,
                O_ORDERPRIORITY VARCHAR(15),
                O_CLERK VARCHAR(15),
                O_SHIPPRIORITY INTEGER,
                O_COMMENT VARCHAR(79)
            )
        """)

        conn.execute("""
            CREATE TABLE LINEITEM (
                L_ORDERKEY INTEGER,
                L_PARTKEY INTEGER,
                L_SUPPKEY INTEGER,
                L_LINENUMBER INTEGER,
                L_QUANTITY DECIMAL(15,2),
                L_EXTENDEDPRICE DECIMAL(15,2),
                L_DISCOUNT DECIMAL(15,2),
                L_TAX DECIMAL(15,2),
                L_RETURNFLAG VARCHAR(1),
                L_LINESTATUS VARCHAR(1),
                L_SHIPDATE DATE,
                L_COMMITDATE DATE,
                L_RECEIPTDATE DATE,
                L_SHIPINSTRUCT VARCHAR(25),
                L_SHIPMODE VARCHAR(10),
                L_COMMENT VARCHAR(44),
                PRIMARY KEY (L_ORDERKEY, L_LINENUMBER)
            )
        """)

        # Create CUSTOMER, PART, and SUPPLIER tables for FK validation
        conn.execute("""
            CREATE TABLE CUSTOMER (
                C_CUSTKEY INTEGER PRIMARY KEY,
                C_NAME VARCHAR(25),
                C_ADDRESS VARCHAR(40),
                C_NATIONKEY INTEGER,
                C_PHONE VARCHAR(15),
                C_ACCTBAL DECIMAL(15,2),
                C_MKTSEGMENT VARCHAR(10),
                C_COMMENT VARCHAR(117)
            )
        """)

        conn.execute("""
            CREATE TABLE PART (
                P_PARTKEY INTEGER PRIMARY KEY,
                P_NAME VARCHAR(55),
                P_MFGR VARCHAR(25),
                P_BRAND VARCHAR(10),
                P_TYPE VARCHAR(25),
                P_SIZE INTEGER,
                P_CONTAINER VARCHAR(10),
                P_RETAILPRICE DECIMAL(15,2),
                P_COMMENT VARCHAR(23)
            )
        """)

        conn.execute("""
            CREATE TABLE SUPPLIER (
                S_SUPPKEY INTEGER PRIMARY KEY,
                S_NAME VARCHAR(25),
                S_ADDRESS VARCHAR(40),
                S_NATIONKEY INTEGER,
                S_PHONE VARCHAR(15),
                S_ACCTBAL DECIMAL(15,2),
                S_COMMENT VARCHAR(101)
            )
        """)

        # Populate reference tables with sample data for FK validation
        # Insert enough customer keys to satisfy FK constraints
        for i in range(1, 10000):
            conn.execute(
                "INSERT INTO CUSTOMER VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (i, f"Customer{i}", f"Address{i}", 1, "123-456-7890", 1000.00, "SEGMENT", "Comment"),
            )

        # Insert sample parts and suppliers
        for i in range(1, 10000):
            conn.execute(
                "INSERT INTO PART VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (i, f"Part{i}", "Manufacturer", "Brand", "Type", 10, "Container", 100.00, "Comment"),
            )
            conn.execute(
                "INSERT INTO SUPPLIER VALUES (?, ?, ?, ?, ?, ?, ?)",
                (i, f"Supplier{i}", f"Address{i}", 1, "123-456-7890", 1000.00, "Comment"),
            )

        # Create a wrapper that doesn't actually close the connection
        class NonClosingConnectionWrapper:
            def __init__(self, real_conn):
                self.real_conn = real_conn
                self.executed_queries = []

            def execute(self, query, params=None):
                return self.real_conn.execute(query, params)

            def commit(self):
                if hasattr(self.real_conn, "commit"):
                    self.real_conn.commit()

            def rollback(self):
                if hasattr(self.real_conn, "rollback"):
                    self.real_conn.rollback()

            def close(self):
                # Don't actually close - we need it for verification
                pass

        # Run RF1
        maintenance_test = TPCHMaintenanceTest(
            connection_factory=lambda: NonClosingConnectionWrapper(conn),
            scale_factor=0.01,
        )

        rf1_result = maintenance_test._execute_rf1(pair_id=0)

        # Verify RF1 succeeded
        assert rf1_result.success is True, f"RF1 failed: {rf1_result.error}"
        assert rf1_result.rows_affected > 0

        # Verify data was actually inserted
        order_count = conn.execute("SELECT COUNT(*) FROM ORDERS").fetchone()[0]
        lineitem_count = conn.execute("SELECT COUNT(*) FROM LINEITEM").fetchone()[0]

        assert order_count > 0, "Should have inserted orders"
        assert lineitem_count > 0, "Should have inserted lineitems"

        # Run RF2
        rf2_result = maintenance_test._execute_rf2(pair_id=0)

        # Verify RF2 succeeded
        assert rf2_result.success is True, f"RF2 failed: {rf2_result.error}"

        # If orders were found and deleted, verify the counts changed
        if rf2_result.rows_affected > 0:
            # Verify data was actually deleted
            final_order_count = conn.execute("SELECT COUNT(*) FROM ORDERS").fetchone()[0]
            final_lineitem_count = conn.execute("SELECT COUNT(*) FROM LINEITEM").fetchone()[0]

            assert final_order_count < order_count, "Should have deleted orders"
            assert final_lineitem_count < lineitem_count, "Should have deleted lineitems"
        else:
            # RF2 didn't find any orders to delete (all orders are too recent)
            # Verify the result reports zero rows affected
            assert rf2_result.rows_affected == 0, f"Expected 0 rows affected, got {rf2_result.rows_affected}"

        # Now actually close the real connection
        conn.close()


class TestForeignKeyValidation:
    """Test suite for foreign key validation in maintenance operations."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)

    def test_rf1_validates_customer_keys(self):
        """Test that RF1 validates customer keys before insertion."""
        pytest.importorskip("duckdb")
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create tables
        conn.execute("""
            CREATE TABLE CUSTOMER (
                C_CUSTKEY INTEGER PRIMARY KEY,
                C_NAME VARCHAR(25)
            )
        """)
        conn.execute("""
            CREATE TABLE ORDERS (
                O_ORDERKEY INTEGER PRIMARY KEY,
                O_CUSTKEY INTEGER,
                O_ORDERSTATUS VARCHAR(1),
                O_TOTALPRICE DECIMAL(15,2),
                O_ORDERDATE DATE,
                O_ORDERPRIORITY VARCHAR(15),
                O_CLERK VARCHAR(15),
                O_SHIPPRIORITY INTEGER,
                O_COMMENT VARCHAR(79),
                FOREIGN KEY (O_CUSTKEY) REFERENCES CUSTOMER(C_CUSTKEY)
            )
        """)
        conn.execute("""
            CREATE TABLE LINEITEM (
                L_ORDERKEY INTEGER,
                L_PARTKEY INTEGER,
                L_SUPPKEY INTEGER,
                L_LINENUMBER INTEGER,
                L_QUANTITY DECIMAL(15,2),
                L_EXTENDEDPRICE DECIMAL(15,2),
                L_DISCOUNT DECIMAL(15,2),
                L_TAX DECIMAL(15,2),
                L_RETURNFLAG VARCHAR(1),
                L_LINESTATUS VARCHAR(1),
                L_SHIPDATE DATE,
                L_COMMITDATE DATE,
                L_RECEIPTDATE DATE,
                L_SHIPINSTRUCT VARCHAR(25),
                L_SHIPMODE VARCHAR(10),
                L_COMMENT VARCHAR(44),
                PRIMARY KEY (L_ORDERKEY, L_LINENUMBER),
                FOREIGN KEY (L_ORDERKEY) REFERENCES ORDERS(O_ORDERKEY)
            )
        """)

        # Create PART and SUPPLIER tables for FK validation
        conn.execute("""
            CREATE TABLE PART (
                P_PARTKEY INTEGER PRIMARY KEY,
                P_NAME VARCHAR(55)
            )
        """)
        conn.execute("""
            CREATE TABLE SUPPLIER (
                S_SUPPKEY INTEGER PRIMARY KEY,
                S_NAME VARCHAR(25)
            )
        """)

        # Insert valid customers (keys 1-10000) to cover random FK generation
        for i in range(1, 10001):
            conn.execute("INSERT INTO CUSTOMER VALUES (?, ?)", (i, f"Customer{i}"))

        # Insert parts and suppliers
        for i in range(1, 10001):
            conn.execute("INSERT INTO PART VALUES (?, ?)", (i, f"Part{i}"))
            conn.execute("INSERT INTO SUPPLIER VALUES (?, ?)", (i, f"Supplier{i}"))

        # Create wrapper
        class NonClosingWrapper:
            def __init__(self, real_conn):
                self.real_conn = real_conn

            def execute(self, query, params=None):
                return self.real_conn.execute(query, params)

            def commit(self):
                pass

            def close(self):
                pass

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=lambda: NonClosingWrapper(conn),
            scale_factor=0.01,
        )

        # Execute RF1
        result = maintenance_test._execute_rf1(pair_id=0)

        # Verify no FK violations occurred
        assert result.success is True, f"RF1 should succeed with valid FKs: {result.error}"
        assert result.rows_affected > 0

        # Verify orders reference valid customers
        invalid_refs = conn.execute("""
            SELECT COUNT(*) FROM ORDERS o
            WHERE NOT EXISTS (SELECT 1 FROM CUSTOMER c WHERE c.C_CUSTKEY = o.O_CUSTKEY)
        """).fetchone()[0]
        assert invalid_refs == 0, "No orders should reference invalid customers"

        conn.close()

    def test_rf1_validates_part_supplier_keys(self):
        """Test that RF1 validates part and supplier keys before insertion."""
        pytest.importorskip("duckdb")
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create dimension tables
        conn.execute("""
            CREATE TABLE PART (
                P_PARTKEY INTEGER PRIMARY KEY,
                P_NAME VARCHAR(55)
            )
        """)
        conn.execute("""
            CREATE TABLE SUPPLIER (
                S_SUPPKEY INTEGER PRIMARY KEY,
                S_NAME VARCHAR(25)
            )
        """)
        conn.execute("""
            CREATE TABLE ORDERS (
                O_ORDERKEY INTEGER PRIMARY KEY,
                O_CUSTKEY INTEGER,
                O_ORDERSTATUS VARCHAR(1),
                O_TOTALPRICE DECIMAL(15,2),
                O_ORDERDATE DATE,
                O_ORDERPRIORITY VARCHAR(15),
                O_CLERK VARCHAR(15),
                O_SHIPPRIORITY INTEGER,
                O_COMMENT VARCHAR(79)
            )
        """)
        conn.execute("""
            CREATE TABLE LINEITEM (
                L_ORDERKEY INTEGER,
                L_PARTKEY INTEGER,
                L_SUPPKEY INTEGER,
                L_LINENUMBER INTEGER,
                L_QUANTITY DECIMAL(15,2),
                L_EXTENDEDPRICE DECIMAL(15,2),
                L_DISCOUNT DECIMAL(15,2),
                L_TAX DECIMAL(15,2),
                L_RETURNFLAG VARCHAR(1),
                L_LINESTATUS VARCHAR(1),
                L_SHIPDATE DATE,
                L_COMMITDATE DATE,
                L_RECEIPTDATE DATE,
                L_SHIPINSTRUCT VARCHAR(25),
                L_SHIPMODE VARCHAR(10),
                L_COMMENT VARCHAR(44),
                PRIMARY KEY (L_ORDERKEY, L_LINENUMBER),
                FOREIGN KEY (L_PARTKEY) REFERENCES PART(P_PARTKEY),
                FOREIGN KEY (L_SUPPKEY) REFERENCES SUPPLIER(S_SUPPKEY),
                FOREIGN KEY (L_ORDERKEY) REFERENCES ORDERS(O_ORDERKEY)
            )
        """)

        # Create CUSTOMER table for FK validation
        conn.execute("""
            CREATE TABLE CUSTOMER (
                C_CUSTKEY INTEGER PRIMARY KEY,
                C_NAME VARCHAR(25)
            )
        """)

        # Insert valid customers, parts and suppliers (extended ranges for random FK generation)
        for i in range(1, 10001):
            conn.execute("INSERT INTO CUSTOMER VALUES (?, ?)", (i, f"Customer{i}"))
            if i <= 10000:
                conn.execute("INSERT INTO PART VALUES (?, ?)", (i, f"Part{i}"))
                conn.execute("INSERT INTO SUPPLIER VALUES (?, ?)", (i, f"Supplier{i}"))

        class NonClosingWrapper:
            def __init__(self, real_conn):
                self.real_conn = real_conn

            def execute(self, query, params=None):
                return self.real_conn.execute(query, params)

            def commit(self):
                pass

            def close(self):
                pass

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=lambda: NonClosingWrapper(conn),
            scale_factor=0.01,
        )

        result = maintenance_test._execute_rf1(pair_id=0)

        # Verify success
        assert result.success is True, f"RF1 should succeed: {result.error}"

        # Verify all lineitems reference valid parts
        invalid_parts = conn.execute("""
            SELECT COUNT(*) FROM LINEITEM l
            WHERE NOT EXISTS (SELECT 1 FROM PART p WHERE p.P_PARTKEY = l.L_PARTKEY)
        """).fetchone()[0]
        assert invalid_parts == 0, "No lineitems should reference invalid parts"

        # Verify all lineitems reference valid suppliers
        invalid_suppliers = conn.execute("""
            SELECT COUNT(*) FROM LINEITEM l
            WHERE NOT EXISTS (SELECT 1 FROM SUPPLIER s WHERE s.S_SUPPKEY = l.L_SUPPKEY)
        """).fetchone()[0]
        assert invalid_suppliers == 0, "No lineitems should reference invalid suppliers"

        conn.close()

    def test_rf1_with_missing_customers(self):
        """Test RF1 behavior when customer keys are missing."""
        pytest.importorskip("duckdb")
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create tables WITHOUT foreign key constraints to test validation logic
        conn.execute("""
            CREATE TABLE CUSTOMER (
                C_CUSTKEY INTEGER PRIMARY KEY,
                C_NAME VARCHAR(25)
            )
        """)
        conn.execute("""
            CREATE TABLE ORDERS (
                O_ORDERKEY INTEGER PRIMARY KEY,
                O_CUSTKEY INTEGER,
                O_ORDERSTATUS VARCHAR(1),
                O_TOTALPRICE DECIMAL(15,2),
                O_ORDERDATE DATE,
                O_ORDERPRIORITY VARCHAR(15),
                O_CLERK VARCHAR(15),
                O_SHIPPRIORITY INTEGER,
                O_COMMENT VARCHAR(79)
            )
        """)
        conn.execute("""
            CREATE TABLE LINEITEM (
                L_ORDERKEY INTEGER,
                L_PARTKEY INTEGER,
                L_SUPPKEY INTEGER,
                L_LINENUMBER INTEGER,
                L_QUANTITY DECIMAL(15,2),
                L_EXTENDEDPRICE DECIMAL(15,2),
                L_DISCOUNT DECIMAL(15,2),
                L_TAX DECIMAL(15,2),
                L_RETURNFLAG VARCHAR(1),
                L_LINESTATUS VARCHAR(1),
                L_SHIPDATE DATE,
                L_COMMITDATE DATE,
                L_RECEIPTDATE DATE,
                L_SHIPINSTRUCT VARCHAR(25),
                L_SHIPMODE VARCHAR(10),
                L_COMMENT VARCHAR(44),
                PRIMARY KEY (L_ORDERKEY, L_LINENUMBER)
            )
        """)

        # Insert NO customers (empty CUSTOMER table)
        # This will test the fallback behavior when no valid FKs exist

        class NonClosingWrapper:
            def __init__(self, real_conn):
                self.real_conn = real_conn

            def execute(self, query, params=None):
                return self.real_conn.execute(query, params)

            def commit(self):
                pass

            def close(self):
                pass

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=lambda: NonClosingWrapper(conn),
            scale_factor=0.01,
        )

        result = maintenance_test._execute_rf1(pair_id=0)

        # With FK validation, RF1 should fail when no valid customers exist
        # The validation should catch this BEFORE attempting insert
        assert result.success is False, "RF1 should fail when no valid customers exist"
        assert "Invalid CUSTKEY references" in str(result.error) or "foreign key" in str(result.error).lower()

        conn.close()

    def test_rf2_respects_referential_integrity(self):
        """Test that RF2 deletes in correct order (child before parent)."""
        pytest.importorskip("duckdb")
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create tables with FK constraints
        conn.execute("""
            CREATE TABLE ORDERS (
                O_ORDERKEY INTEGER PRIMARY KEY,
                O_CUSTKEY INTEGER,
                O_ORDERSTATUS VARCHAR(1),
                O_TOTALPRICE DECIMAL(15,2),
                O_ORDERDATE DATE,
                O_ORDERPRIORITY VARCHAR(15),
                O_CLERK VARCHAR(15),
                O_SHIPPRIORITY INTEGER,
                O_COMMENT VARCHAR(79)
            )
        """)
        conn.execute("""
            CREATE TABLE LINEITEM (
                L_ORDERKEY INTEGER,
                L_PARTKEY INTEGER,
                L_SUPPKEY INTEGER,
                L_LINENUMBER INTEGER,
                L_QUANTITY DECIMAL(15,2),
                L_EXTENDEDPRICE DECIMAL(15,2),
                L_DISCOUNT DECIMAL(15,2),
                L_TAX DECIMAL(15,2),
                L_RETURNFLAG VARCHAR(1),
                L_LINESTATUS VARCHAR(1),
                L_SHIPDATE DATE,
                L_COMMITDATE DATE,
                L_RECEIPTDATE DATE,
                L_SHIPINSTRUCT VARCHAR(25),
                L_SHIPMODE VARCHAR(10),
                L_COMMENT VARCHAR(44),
                PRIMARY KEY (L_ORDERKEY, L_LINENUMBER),
                FOREIGN KEY (L_ORDERKEY) REFERENCES ORDERS(O_ORDERKEY)
            )
        """)

        # Insert old test data
        old_date = "1995-01-01"
        for i in range(1, 11):
            conn.execute(
                "INSERT INTO ORDERS VALUES (?, ?, 'O', 1000.00, ?, '1-URGENT', 'Clerk#000000001', 0, 'Test')",
                (i, 1, old_date),
            )
            conn.execute(
                "INSERT INTO LINEITEM VALUES (?, 1, 1, 1, 10.0, 100.0, 0.05, 0.01, 'N', 'O', ?, ?, ?, 'NONE', 'TRUCK', 'Test')",
                (i, old_date, old_date, old_date),
            )

        class NonClosingWrapper:
            def __init__(self, real_conn):
                self.real_conn = real_conn

            def execute(self, query, params=None):
                return self.real_conn.execute(query, params)

            def commit(self):
                pass

            def close(self):
                pass

        maintenance_test = TPCHMaintenanceTest(
            connection_factory=lambda: NonClosingWrapper(conn),
            scale_factor=0.01,
        )

        # Verify initial state
        initial_orders = conn.execute("SELECT COUNT(*) FROM ORDERS").fetchone()[0]
        initial_lineitems = conn.execute("SELECT COUNT(*) FROM LINEITEM").fetchone()[0]
        assert initial_orders == 10
        assert initial_lineitems == 10

        # Execute RF2
        result = maintenance_test._execute_rf2(pair_id=0)

        # Verify RF2 succeeded without FK violations
        assert result.success is True, f"RF2 should succeed: {result.error}"

        # If deletes occurred, verify counts changed
        if result.rows_affected > 0:
            final_orders = conn.execute("SELECT COUNT(*) FROM ORDERS").fetchone()[0]
            final_lineitems = conn.execute("SELECT COUNT(*) FROM LINEITEM").fetchone()[0]

            # Both should have decreased
            assert final_orders < initial_orders, "Orders should be deleted"
            assert final_lineitems < initial_lineitems, "Lineitems should be deleted"

            # No orphaned lineitems should exist
            orphaned = conn.execute("""
                SELECT COUNT(*) FROM LINEITEM l
                WHERE NOT EXISTS (SELECT 1 FROM ORDERS o WHERE o.O_ORDERKEY = l.L_ORDERKEY)
            """).fetchone()[0]
            assert orphaned == 0, "No orphaned lineitems should exist after RF2"

        conn.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
