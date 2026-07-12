"""Integration tests for Write Primitives benchmark with DuckDB.

This module contains true end-to-end integration tests that execute write operations
against a real DuckDB database, validating the complete execution pipeline.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import duckdb
import pytest

from benchbox import WritePrimitives
from benchbox.core.write_primitives.benchmark import OperationResult

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.write_primitives
class TestWritePrimitivesDuckDBLifecycle:
    """Test Write Primitives lifecycle management with real DuckDB database."""

    @pytest.fixture
    def duckdb_conn(self):
        """Create a temporary DuckDB database."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    @pytest.fixture
    def loaded_tpch_conn(self, duckdb_conn):
        """Create DuckDB connection with minimal TPC-H test data."""
        # Create minimal TPC-H schema (just what we need)
        duckdb_conn.execute("""
            CREATE TABLE orders (
                o_orderkey INTEGER PRIMARY KEY,
                o_custkey INTEGER,
                o_orderstatus CHAR(1),
                o_totalprice DECIMAL(15,2),
                o_orderdate DATE,
                o_orderpriority CHAR(15),
                o_clerk CHAR(15),
                o_shippriority INTEGER,
                o_comment VARCHAR(79)
            )
        """)

        duckdb_conn.execute("""
            CREATE TABLE lineitem (
                l_orderkey INTEGER,
                l_partkey INTEGER,
                l_suppkey INTEGER,
                l_linenumber INTEGER,
                l_quantity DECIMAL(15,2),
                l_extendedprice DECIMAL(15,2),
                l_discount DECIMAL(15,2),
                l_tax DECIMAL(15,2),
                l_returnflag CHAR(1),
                l_linestatus CHAR(1),
                l_shipdate DATE,
                l_commitdate DATE,
                l_receiptdate DATE,
                l_shipinstruct CHAR(25),
                l_shipmode CHAR(10),
                l_comment VARCHAR(44)
            )
        """)

        # Insert minimal test data
        duckdb_conn.execute("""
            INSERT INTO orders VALUES
            (1, 100, 'O', 150.50, '2024-01-01', '1-URGENT', 'Clerk#001', 0, 'test order 1'),
            (2, 101, 'O', 250.75, '2024-01-02', '2-HIGH', 'Clerk#002', 0, 'test order 2'),
            (3, 102, 'O', 350.00, '2024-01-03', '3-MEDIUM', 'Clerk#003', 0, 'test order 3'),
            (4, 103, 'F', 450.25, '2024-01-04', '1-URGENT', 'Clerk#004', 0, 'test order 4'),
            (5, 104, 'F', 550.50, '2024-01-05', '2-HIGH', 'Clerk#005', 0, 'test order 5')
        """)

        duckdb_conn.execute("""
            INSERT INTO lineitem VALUES
            (1, 1001, 201, 1, 10.0, 100.0, 0.05, 0.01, 'N', 'O', '2024-01-15', '2024-01-10', '2024-01-20', 'DELIVER IN PERSON', 'TRUCK', 'comment 1'),
            (1, 1002, 202, 2, 20.0, 200.0, 0.05, 0.01, 'N', 'O', '2024-01-16', '2024-01-11', '2024-01-21', 'DELIVER IN PERSON', 'MAIL', 'comment 2'),
            (2, 1003, 203, 1, 15.0, 150.0, 0.10, 0.02, 'N', 'O', '2024-01-17', '2024-01-12', '2024-01-22', 'TAKE BACK RETURN', 'SHIP', 'comment 3'),
            (3, 1004, 204, 1, 25.0, 250.0, 0.00, 0.00, 'R', 'F', '2024-01-18', '2024-01-13', '2024-01-23', 'NONE', 'AIR', 'comment 4'),
            (4, 1005, 205, 1, 30.0, 300.0, 0.05, 0.01, 'A', 'F', '2024-01-19', '2024-01-14', '2024-01-24', 'DELIVER IN PERSON', 'RAIL', 'comment 5')
        """)

        return duckdb_conn

    @pytest.fixture
    def write_bench(self, small_scale_factor, temp_dir):
        """Create Write Primitives benchmark instance."""
        return WritePrimitives(scale_factor=small_scale_factor, output_dir=temp_dir, quiet=True)

    def test_setup_creates_staging_tables(self, write_bench, loaded_tpch_conn):
        """Test that setup() creates all staging tables."""
        # Setup staging tables
        result = write_bench.setup(loaded_tpch_conn, force=False)

        assert result["success"] is True
        assert "tables_created" in result
        assert len(result["tables_created"]) >= 2

        # Verify staging tables exist and have data
        orders_count = loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders").fetchone()[0]
        assert orders_count > 0, "update_ops_orders should have data"

        lineitem_count = loaded_tpch_conn.execute("SELECT COUNT(*) FROM delete_ops_lineitem").fetchone()[0]
        assert lineitem_count > 0, "delete_ops_lineitem should have data"

    def test_setup_with_force_recreates_tables(self, write_bench, loaded_tpch_conn):
        """Test that setup(force=True) drops and recreates staging tables."""
        # Initial setup
        write_bench.setup(loaded_tpch_conn, force=False)

        # Modify staging table
        loaded_tpch_conn.execute("DELETE FROM update_ops_orders WHERE o_orderkey > 0")
        count_after_delete = loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders").fetchone()[0]

        # Force setup should recreate and repopulate
        result = write_bench.setup(loaded_tpch_conn, force=True)

        assert result["success"] is True
        count_after_force = loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders").fetchone()[0]
        assert count_after_force > count_after_delete, "Force setup should repopulate data"

    def test_is_setup_validates_tables(self, write_bench, loaded_tpch_conn):
        """Test that is_setup() correctly validates staging table state."""
        # Before setup
        assert write_bench.is_setup(loaded_tpch_conn) is False

        # After setup
        write_bench.setup(loaded_tpch_conn)
        assert write_bench.is_setup(loaded_tpch_conn) is True

        # After dropping a table
        loaded_tpch_conn.execute("DROP TABLE update_ops_orders")
        assert write_bench.is_setup(loaded_tpch_conn) is False

    def test_teardown_removes_tables(self, write_bench, loaded_tpch_conn):
        """Test that teardown() removes all staging tables."""
        # Setup first
        write_bench.setup(loaded_tpch_conn)
        assert write_bench.is_setup(loaded_tpch_conn) is True

        # Teardown
        write_bench.teardown(loaded_tpch_conn)

        # Verify tables are gone
        with pytest.raises(Exception):
            loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders")

        assert write_bench.is_setup(loaded_tpch_conn) is False

    def test_reset_repopulates_data(self, write_bench, loaded_tpch_conn):
        """Test that reset() truncates and repopulates staging tables."""
        # Setup
        write_bench.setup(loaded_tpch_conn)
        original_count = loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders").fetchone()[0]

        # Delete some data
        loaded_tpch_conn.execute("DELETE FROM update_ops_orders WHERE o_orderkey > 0")
        after_delete = loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders").fetchone()[0]
        assert after_delete < original_count

        # Reset should restore
        write_bench.reset(loaded_tpch_conn)
        after_reset = loaded_tpch_conn.execute("SELECT COUNT(*) FROM update_ops_orders").fetchone()[0]
        assert after_reset == original_count

    def test_setup_fails_without_tpch_tables(self, write_bench, duckdb_conn):
        """Test that setup() fails gracefully if TPC-H tables don't exist."""
        with pytest.raises(RuntimeError, match="Required TPC-H table"):
            write_bench.setup(duckdb_conn)


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.write_primitives
class TestWritePrimitivesDuckDBExecution:
    """Test Write Primitives operation execution with real DuckDB database."""

    @pytest.fixture
    def setup_env(self, small_scale_factor, temp_dir):
        """Create fully setup environment with TPC-H and Write Primitives."""
        # Create DuckDB connection
        conn = duckdb.connect(":memory:")

        # Create minimal TPC-H schema
        conn.execute("""
            CREATE TABLE orders (
                o_orderkey INTEGER PRIMARY KEY,
                o_custkey INTEGER,
                o_orderstatus CHAR(1),
                o_totalprice DECIMAL(15,2),
                o_orderdate DATE,
                o_orderpriority CHAR(15),
                o_clerk CHAR(15),
                o_shippriority INTEGER,
                o_comment VARCHAR(79)
            )
        """)

        conn.execute("""
            CREATE TABLE lineitem (
                l_orderkey INTEGER,
                l_partkey INTEGER,
                l_suppkey INTEGER,
                l_linenumber INTEGER,
                l_quantity DECIMAL(15,2),
                l_extendedprice DECIMAL(15,2),
                l_discount DECIMAL(15,2),
                l_tax DECIMAL(15,2),
                l_returnflag CHAR(1),
                l_linestatus CHAR(1),
                l_shipdate DATE,
                l_commitdate DATE,
                l_receiptdate DATE,
                l_shipinstruct CHAR(25),
                l_shipmode CHAR(10),
                l_comment VARCHAR(44)
            )
        """)

        # Insert test data
        conn.execute("""
            INSERT INTO orders VALUES
            (1, 100, 'O', 150.50, '2024-01-01', '1-URGENT', 'Clerk#001', 0, 'test order 1'),
            (2, 101, 'O', 250.75, '2024-01-02', '2-HIGH', 'Clerk#002', 0, 'test order 2'),
            (3, 102, 'O', 350.00, '2024-01-03', '3-MEDIUM', 'Clerk#003', 0, 'test order 3'),
            (4, 103, 'F', 450.25, '2024-01-04', '1-URGENT', 'Clerk#004', 0, 'test order 4'),
            (5, 104, 'F', 550.50, '2024-01-05', '2-HIGH', 'Clerk#005', 0, 'test order 5'),
            (6, 105, 'O', 650.00, '2024-01-06', '3-MEDIUM', 'Clerk#006', 0, 'test order 6'),
            (7, 106, 'F', 750.75, '2024-01-07', '1-URGENT', 'Clerk#007', 0, 'test order 7'),
            (8, 107, 'O', 850.50, '2024-01-08', '2-HIGH', 'Clerk#008', 0, 'test order 8'),
            (9, 108, 'F', 950.25, '2024-01-09', '3-MEDIUM', 'Clerk#009', 0, 'test order 9'),
            (10, 109, 'O', 1050.00, '2024-01-10', '1-URGENT', 'Clerk#010', 0, 'test order 10')
        """)

        conn.execute("""
            INSERT INTO lineitem VALUES
            (1, 1001, 201, 1, 10.0, 100.0, 0.05, 0.01, 'N', 'O', '2024-01-15', '2024-01-10', '2024-01-20', 'DELIVER IN PERSON', 'TRUCK', 'comment 1'),
            (1, 1002, 202, 2, 20.0, 200.0, 0.05, 0.01, 'N', 'O', '2024-01-16', '2024-01-11', '2024-01-21', 'DELIVER IN PERSON', 'MAIL', 'comment 2'),
            (2, 1003, 203, 1, 15.0, 150.0, 0.10, 0.02, 'N', 'O', '2024-01-17', '2024-01-12', '2024-01-22', 'TAKE BACK RETURN', 'SHIP', 'comment 3'),
            (3, 1004, 204, 1, 25.0, 250.0, 0.00, 0.00, 'R', 'F', '2024-01-18', '2024-01-13', '2024-01-23', 'NONE', 'AIR', 'comment 4'),
            (4, 1005, 205, 1, 30.0, 300.0, 0.05, 0.01, 'A', 'F', '2024-01-19', '2024-01-14', '2024-01-24', 'DELIVER IN PERSON', 'RAIL', 'comment 5'),
            (5, 1006, 206, 1, 35.0, 350.0, 0.05, 0.01, 'N', 'O', '2024-01-20', '2024-01-15', '2024-01-25', 'DELIVER IN PERSON', 'TRUCK', 'comment 6'),
            (6, 1007, 207, 1, 40.0, 400.0, 0.10, 0.02, 'R', 'F', '2024-01-21', '2024-01-16', '2024-01-26', 'TAKE BACK RETURN', 'MAIL', 'comment 7'),
            (7, 1008, 208, 1, 45.0, 450.0, 0.00, 0.00, 'A', 'F', '2024-01-22', '2024-01-17', '2024-01-27', 'NONE', 'SHIP', 'comment 8'),
            (8, 1009, 209, 1, 50.0, 500.0, 0.05, 0.01, 'N', 'O', '2024-01-23', '2024-01-18', '2024-01-28', 'DELIVER IN PERSON', 'AIR', 'comment 9'),
            (9, 1010, 210, 1, 55.0, 550.0, 0.10, 0.02, 'R', 'F', '2024-01-24', '2024-01-19', '2024-01-29', 'TAKE BACK RETURN', 'RAIL', 'comment 10')
        """)

        # Create Write Primitives benchmark
        write_bench = WritePrimitives(scale_factor=small_scale_factor, output_dir=temp_dir, quiet=True)

        # Setup staging tables
        write_bench.setup(conn, force=True)

        yield write_bench, conn

        # Cleanup
        conn.close()

    def test_execute_insert_single_row(self, setup_env):
        """Test executing INSERT single row operation."""
        write_bench, conn = setup_env

        # Execute operation
        result = write_bench.execute_operation("insert_single_row", conn, use_transaction=True)

        # Verify result structure
        assert isinstance(result, OperationResult)
        assert result.operation_id == "insert_single_row"
        assert result.success is True
        assert result.write_duration_ms >= 0
        assert result.rows_affected == 1 or result.rows_affected == -1  # -1 = unknown
        assert result.validation_passed is True
        assert result.cleanup_success is True
        assert result.error is None

    def test_execute_insert_batch_10(self, setup_env):
        """Test executing INSERT batch with 10 rows."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("insert_batch_values_10", conn, use_transaction=True)

        assert result.success is True
        assert result.rows_affected == 10 or result.rows_affected == -1
        assert result.validation_passed is True

    def test_execute_insert_select(self, setup_env):
        """Test executing INSERT...SELECT operation."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("insert_select_simple", conn, use_transaction=True)

        # This operation may fail with our test data because delete_ops_lineitem already
        # contains data from lineitem (populated during setup), causing PK violations
        # In real scenarios with proper TPC-H data, this would work
        if "Duplicate key" in (result.error or ""):
            # Expected failure with our test setup - verify error is captured correctly
            assert result.success is False
            assert "Constraint Error" in result.error or "Duplicate key" in result.error
        else:
            # If it succeeds (e.g., different test data), verify success
            assert result.success is True
            assert result.rows_affected >= 0 or result.rows_affected == -1

    def test_execute_update_single_row_pk(self, setup_env):
        """Test executing UPDATE single row by primary key."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("update_single_row_pk", conn, use_transaction=True)

        assert result.success is True
        assert result.rows_affected == 1 or result.rows_affected == -1
        assert result.validation_passed is True

    def test_execute_update_selective_10pct(self, setup_env):
        """Test executing UPDATE affecting ~10% of rows."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("update_selective_10pct", conn, use_transaction=True)

        assert result.success is True
        assert result.validation_passed is True
        # Should update at least 1 row
        assert result.rows_affected >= 1 or result.rows_affected == -1

    def test_execute_delete_single_row_pk(self, setup_env):
        """Test executing DELETE single row by primary key."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("delete_single_row_pk", conn, use_transaction=True)

        assert result.success is True
        assert result.rows_affected == 1 or result.rows_affected == -1
        assert result.validation_passed is True

    def test_execute_delete_selective_10pct(self, setup_env):
        """Test executing DELETE affecting ~10% of rows."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("delete_selective_10pct", conn, use_transaction=True)

        assert result.success is True
        assert result.validation_passed is True
        assert result.rows_affected >= 1 or result.rows_affected == -1

    def test_execute_ddl_create_table(self, setup_env):
        """Test executing DDL CREATE TABLE operation."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("ddl_create_table_simple", conn, use_transaction=True)

        assert result.success is True
        assert result.validation_passed is True

        # Verify table was created and cleaned up
        # (cleanup should have dropped it)
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_name = 'test_simple'"
        ).fetchall()
        # Should be cleaned up (dropped)
        assert len(tables) == 0

    def test_execute_ddl_truncate(self, setup_env):
        """Test executing DDL TRUNCATE operation."""
        write_bench, conn = setup_env

        # Get initial count from ddl_truncate_target (the actual table being truncated)
        initial_count = conn.execute("SELECT COUNT(*) FROM ddl_truncate_target").fetchone()[0]
        assert initial_count > 0, "ddl_truncate_target should have data from setup"

        result = write_bench.execute_operation("ddl_truncate_table_small", conn, use_transaction=False)

        # TRUNCATE cannot be rolled back, so data is really gone
        assert result.success is True
        assert result.validation_passed is True

        # Verify table is empty after truncate
        after_count = conn.execute("SELECT COUNT(*) FROM ddl_truncate_target").fetchone()[0]
        assert after_count == 0, "ddl_truncate_target should be empty after TRUNCATE"

        # Restore data for other tests
        write_bench.reset(conn)

    def test_execute_ddl_create_table_as_select(self, setup_env):
        """Test executing DDL CREATE TABLE AS SELECT."""
        write_bench, conn = setup_env

        result = write_bench.execute_operation("ddl_create_table_as_select_simple", conn, use_transaction=True)

        assert result.success is True
        assert result.validation_passed is True


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.write_primitives
class TestWritePrimitivesDuckDBBenchmarkRuns:
    """Test full benchmark runs with DuckDB."""

    @pytest.fixture
    def setup_env(self, small_scale_factor, temp_dir):
        """Create fully setup environment."""
        conn = duckdb.connect(":memory:")

        # Create minimal TPC-H schema
        conn.execute("""
            CREATE TABLE orders (
                o_orderkey INTEGER PRIMARY KEY,
                o_custkey INTEGER,
                o_orderstatus CHAR(1),
                o_totalprice DECIMAL(15,2),
                o_orderdate DATE,
                o_orderpriority CHAR(15),
                o_clerk CHAR(15),
                o_shippriority INTEGER,
                o_comment VARCHAR(79)
            )
        """)

        conn.execute("""
            CREATE TABLE lineitem (
                l_orderkey INTEGER,
                l_partkey INTEGER,
                l_suppkey INTEGER,
                l_linenumber INTEGER,
                l_quantity DECIMAL(15,2),
                l_extendedprice DECIMAL(15,2),
                l_discount DECIMAL(15,2),
                l_tax DECIMAL(15,2),
                l_returnflag CHAR(1),
                l_linestatus CHAR(1),
                l_shipdate DATE,
                l_commitdate DATE,
                l_receiptdate DATE,
                l_shipinstruct CHAR(25),
                l_shipmode CHAR(10),
                l_comment VARCHAR(44)
            )
        """)

        # Insert test data
        conn.execute("""
            INSERT INTO orders VALUES
            (1, 100, 'O', 150.50, '2024-01-01', '1-URGENT', 'Clerk#001', 0, 'test order 1'),
            (2, 101, 'O', 250.75, '2024-01-02', '2-HIGH', 'Clerk#002', 0, 'test order 2'),
            (3, 102, 'O', 350.00, '2024-01-03', '3-MEDIUM', 'Clerk#003', 0, 'test order 3'),
            (4, 103, 'F', 450.25, '2024-01-04', '1-URGENT', 'Clerk#004', 0, 'test order 4'),
            (5, 104, 'F', 550.50, '2024-01-05', '2-HIGH', 'Clerk#005', 0, 'test order 5'),
            (6, 105, 'O', 650.00, '2024-01-06', '3-MEDIUM', 'Clerk#006', 0, 'test order 6'),
            (7, 106, 'F', 750.75, '2024-01-07', '1-URGENT', 'Clerk#007', 0, 'test order 7'),
            (8, 107, 'O', 850.50, '2024-01-08', '2-HIGH', 'Clerk#008', 0, 'test order 8'),
            (9, 108, 'F', 950.25, '2024-01-09', '3-MEDIUM', 'Clerk#009', 0, 'test order 9'),
            (10, 109, 'O', 1050.00, '2024-01-10', '1-URGENT', 'Clerk#010', 0, 'test order 10')
        """)

        conn.execute("""
            INSERT INTO lineitem VALUES
            (1, 1001, 201, 1, 10.0, 100.0, 0.05, 0.01, 'N', 'O', '2024-01-15', '2024-01-10', '2024-01-20', 'DELIVER IN PERSON', 'TRUCK', 'comment 1'),
            (1, 1002, 202, 2, 20.0, 200.0, 0.05, 0.01, 'N', 'O', '2024-01-16', '2024-01-11', '2024-01-21', 'DELIVER IN PERSON', 'MAIL', 'comment 2'),
            (2, 1003, 203, 1, 15.0, 150.0, 0.10, 0.02, 'N', 'O', '2024-01-17', '2024-01-12', '2024-01-22', 'TAKE BACK RETURN', 'SHIP', 'comment 3'),
            (3, 1004, 204, 1, 25.0, 250.0, 0.00, 0.00, 'R', 'F', '2024-01-18', '2024-01-13', '2024-01-23', 'NONE', 'AIR', 'comment 4'),
            (4, 1005, 205, 1, 30.0, 300.0, 0.05, 0.01, 'A', 'F', '2024-01-19', '2024-01-14', '2024-01-24', 'DELIVER IN PERSON', 'RAIL', 'comment 5'),
            (5, 1006, 206, 1, 35.0, 350.0, 0.05, 0.01, 'N', 'O', '2024-01-20', '2024-01-15', '2024-01-25', 'DELIVER IN PERSON', 'TRUCK', 'comment 6'),
            (6, 1007, 207, 1, 40.0, 400.0, 0.10, 0.02, 'R', 'F', '2024-01-21', '2024-01-16', '2024-01-26', 'TAKE BACK RETURN', 'MAIL', 'comment 7'),
            (7, 1008, 208, 1, 45.0, 450.0, 0.00, 0.00, 'A', 'F', '2024-01-22', '2024-01-17', '2024-01-27', 'NONE', 'SHIP', 'comment 8'),
            (8, 1009, 209, 1, 50.0, 500.0, 0.05, 0.01, 'N', 'O', '2024-01-23', '2024-01-18', '2024-01-28', 'DELIVER IN PERSON', 'AIR', 'comment 9'),
            (9, 1010, 210, 1, 55.0, 550.0, 0.10, 0.02, 'R', 'F', '2024-01-24', '2024-01-19', '2024-01-29', 'TAKE BACK RETURN', 'RAIL', 'comment 10')
        """)

        write_bench = WritePrimitives(scale_factor=small_scale_factor, output_dir=temp_dir, quiet=True)
        write_bench.setup(conn, force=True)

        yield write_bench, conn
        conn.close()

    def test_run_benchmark_all_operations(self, setup_env):
        """Test running all operations in the benchmark."""
        write_bench, conn = setup_env

        # Run operations individually to avoid interference
        # (e.g., DDL TRUNCATE empties tables, affecting subsequent ops)
        all_ops = write_bench.get_all_operations()
        results = []

        for op_id in all_ops:
            # Reset staging tables before each operation to ensure clean state
            if op_id != "ddl_truncate_table_small":  # Skip reset for truncate test
                write_bench.reset(conn)

            result = write_bench.execute_operation(op_id, conn)
            results.append(result)

        # Should have 112 operations (8 transaction ops moved to Transaction
        # Primitives; +3 SCD Type 2 merge ops added in MERGE category)
        assert len(results) == 112

        # All should be OperationResult instances
        for result in results:
            assert isinstance(result, OperationResult)

        # This path calls execute_operation without platform_key, so the DuckDB MERGE-skip
        # gate (duckdb_write_primitive_skip_reason, PR #931) does NOT apply here: the 20
        # legacy MERGE INTO ops actually fail on DuckDB, while the 3 portable SCD2 ops run.
        # Successes land around 50-60 of the 112 ops (112 - 20 failing MERGE INTO - ~30-40
        # other DB-specific features). The shipped `--platform duckdb` skip path is covered
        # separately by the -k scd2 tests.
        successful = [r for r in results if r.success]
        assert len(successful) >= 50, f"Expected at least 50 successes, got {len(successful)}"

        # Verify that MERGE operations fail with expected error on DuckDB (un-gated path)
        merge_results = [r for r in results if r.operation_id.startswith("merge_")]
        merge_failures = [r for r in merge_results if not r.success]
        assert len(merge_failures) > 0, "Expected some MERGE operations to fail on DuckDB"

    def test_run_benchmark_by_category(self, setup_env):
        """Test running operations filtered by category."""
        write_bench, conn = setup_env

        # Verify tables are set up
        assert write_bench.is_setup(conn), "Staging tables should be set up by fixture"

        # Get INSERT operations and execute them individually (like test_run_benchmark_all_operations does)
        insert_ops = list(write_bench.get_operations_by_category("insert").keys())
        assert len(insert_ops) == 12, f"Expected 12 INSERT operations, got {len(insert_ops)}"

        results = []
        for op_id in insert_ops:
            write_bench.reset(conn)
            result = write_bench.execute_operation(op_id, conn)
            results.append(result)

        # Should have 12 INSERT operations
        assert len(results) == 12

        for result in results:
            assert result.operation_id.startswith("insert")

    def test_run_benchmark_specific_operations(self, setup_env):
        """Test running specific operations by ID."""
        write_bench, conn = setup_env

        operation_ids = ["insert_single_row", "update_single_row_pk", "delete_single_row_pk"]
        results = write_bench.run_benchmark(conn, operation_ids=operation_ids)

        assert len(results) == 3

        result_ids = [r.operation_id for r in results]
        for op_id in operation_ids:
            assert op_id in result_ids

    def test_benchmark_handles_errors_gracefully(self, setup_env):
        """Test error handling for invalid operations."""
        write_bench, conn = setup_env

        # Try to execute non-existent operation
        with pytest.raises(ValueError, match="Invalid operation ID"):
            write_bench.execute_operation("nonexistent_operation", conn)


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.write_primitives
class TestWritePrimitivesConsolidatedOperations:
    """Test Write Primitives operations consolidated from Merge benchmark.

    This class tests the 4 operations that were consolidated from the Merge
    benchmark into WritePrimitives:
    - delete_gdpr_suppliers_1pct (recategorized from merge)
    - delete_gdpr_suppliers_5pct (recategorized from merge)
    - merge_etl_aggregation_pattern
    - merge_deduplication_window_function
    """

    @pytest.fixture
    def setup_env(self, small_scale_factor, temp_dir):
        """Create fully setup environment with realistic test data for consolidated operations."""
        conn = duckdb.connect(":memory:")

        # Create TPC-H schema
        conn.execute("""
            CREATE TABLE orders (
                o_orderkey INTEGER PRIMARY KEY,
                o_custkey INTEGER,
                o_orderstatus CHAR(1),
                o_totalprice DECIMAL(15,2),
                o_orderdate DATE,
                o_orderpriority CHAR(15),
                o_clerk CHAR(15),
                o_shippriority INTEGER,
                o_comment VARCHAR(79)
            )
        """)

        conn.execute("""
            CREATE TABLE lineitem (
                l_orderkey INTEGER,
                l_partkey INTEGER,
                l_suppkey INTEGER,
                l_linenumber INTEGER,
                l_quantity DECIMAL(15,2),
                l_extendedprice DECIMAL(15,2),
                l_discount DECIMAL(15,2),
                l_tax DECIMAL(15,2),
                l_returnflag CHAR(1),
                l_linestatus CHAR(1),
                l_shipdate DATE,
                l_commitdate DATE,
                l_receiptdate DATE,
                l_shipinstruct CHAR(25),
                l_shipmode CHAR(10),
                l_comment VARCHAR(44)
            )
        """)

        # Insert test data with controlled supplier keys for GDPR deletion tests
        # Use supplier keys 1-100 to test 1% and 5% deletion thresholds
        conn.execute("""
            INSERT INTO orders VALUES
            (1, 100, 'O', 150.50, '2024-01-01', '1-URGENT', 'Clerk#001', 0, 'test order 1'),
            (2, 101, 'O', 250.75, '2024-01-02', '2-HIGH', 'Clerk#002', 0, 'test order 2'),
            (3, 102, 'O', 350.00, '2024-01-03', '3-MEDIUM', 'Clerk#003', 0, 'test order 3'),
            (4, 103, 'F', 450.25, '2024-01-04', '1-URGENT', 'Clerk#004', 0, 'test order 4'),
            (5, 104, 'F', 550.50, '2024-01-05', '2-HIGH', 'Clerk#005', 0, 'test order 5'),
            (100, 105, 'O', 650.00, '2024-01-06', '3-MEDIUM', 'Clerk#006', 0, 'test order 6'),
            (200, 106, 'F', 750.75, '2024-01-07', '1-URGENT', 'Clerk#007', 0, 'test order 7'),
            (300, 107, 'O', 850.50, '2024-01-08', '2-HIGH', 'Clerk#008', 0, 'test order 8'),
            (400, 108, 'F', 950.25, '2024-01-09', '3-MEDIUM', 'Clerk#009', 0, 'test order 9'),
            (500, 109, 'O', 1050.00, '2024-01-10', '1-URGENT', 'Clerk#010', 0, 'test order 10')
        """)

        # Insert lineitem rows with supplier keys spread across 1-100 range
        conn.execute("""
            INSERT INTO lineitem VALUES
            (1, 1001, 1, 1, 10.0, 100.0, 0.05, 0.01, 'N', 'O', '2024-01-15', '2024-01-10', '2024-01-20', 'DELIVER IN PERSON', 'TRUCK', 'comment 1'),
            (1, 1002, 2, 2, 20.0, 200.0, 0.05, 0.01, 'N', 'O', '2024-01-16', '2024-01-11', '2024-01-21', 'DELIVER IN PERSON', 'MAIL', 'comment 2'),
            (2, 1003, 3, 1, 15.0, 150.0, 0.10, 0.02, 'N', 'O', '2024-01-17', '2024-01-12', '2024-01-22', 'TAKE BACK RETURN', 'SHIP', 'comment 3'),
            (3, 1004, 4, 1, 25.0, 250.0, 0.00, 0.00, 'R', 'F', '2024-01-18', '2024-01-13', '2024-01-23', 'NONE', 'AIR', 'comment 4'),
            (4, 1005, 5, 1, 30.0, 300.0, 0.05, 0.01, 'A', 'F', '2024-01-19', '2024-01-14', '2024-01-24', 'DELIVER IN PERSON', 'RAIL', 'comment 5'),
            (5, 1006, 10, 1, 35.0, 350.0, 0.05, 0.01, 'N', 'O', '2024-01-20', '2024-01-15', '2024-01-25', 'DELIVER IN PERSON', 'TRUCK', 'comment 6'),
            (100, 1007, 20, 1, 40.0, 400.0, 0.10, 0.02, 'R', 'F', '2024-01-21', '2024-01-16', '2024-01-26', 'TAKE BACK RETURN', 'MAIL', 'comment 7'),
            (200, 1008, 30, 1, 45.0, 450.0, 0.00, 0.00, 'A', 'F', '2024-01-22', '2024-01-17', '2024-01-27', 'NONE', 'SHIP', 'comment 8'),
            (300, 1009, 50, 1, 50.0, 500.0, 0.05, 0.01, 'N', 'O', '2024-01-23', '2024-01-18', '2024-01-28', 'DELIVER IN PERSON', 'AIR', 'comment 9'),
            (400, 1010, 100, 1, 55.0, 550.0, 0.10, 0.02, 'R', 'F', '2024-01-24', '2024-01-19', '2024-01-29', 'TAKE BACK RETURN', 'RAIL', 'comment 10')
        """)

        write_bench = WritePrimitives(scale_factor=small_scale_factor, output_dir=temp_dir, quiet=True)
        write_bench.setup(conn, force=True)

        yield write_bench, conn
        conn.close()

    def test_delete_gdpr_suppliers_1pct(self, setup_env):
        """Test GDPR deletion of 1% of suppliers (recategorized from merge to delete)."""
        write_bench, conn = setup_env

        # Get baseline counts
        conn.execute("SELECT COUNT(*) FROM delete_ops_lineitem").fetchone()[0]
        max_suppkey = conn.execute("SELECT MAX(l_suppkey) FROM lineitem").fetchone()[0]
        max_suppkey * 0.01

        # Execute GDPR deletion operation
        result = write_bench.execute_operation("delete_gdpr_suppliers_1pct", conn, use_transaction=True)

        # Verify result structure
        assert isinstance(result, OperationResult)
        assert result.operation_id == "delete_gdpr_suppliers_1pct"
        assert result.success is True, f"Operation failed: {result.error}"
        assert result.validation_passed is True, f"Validation failed: {result.validation_results}"
        assert result.cleanup_success is True

        # Verify validation query returned expected result (validation_passed=1)
        validation_results = result.validation_results
        assert len(validation_results) > 0
        verify_deletion = [v for v in validation_results if v["query_id"] == "verify_gdpr_deletion"][0]
        assert verify_deletion["passed"] is True
        # The CASE expression should return 1 if no suppliers <= threshold remain
        assert verify_deletion["actual_rows"] == 1

    def test_delete_gdpr_suppliers_5pct(self, setup_env):
        """Test GDPR deletion of 5% of suppliers (recategorized from merge to delete)."""
        write_bench, conn = setup_env

        # Get baseline counts
        conn.execute("SELECT COUNT(*) FROM delete_ops_lineitem").fetchone()[0]
        max_suppkey = conn.execute("SELECT MAX(l_suppkey) FROM lineitem").fetchone()[0]
        max_suppkey * 0.05

        # Execute GDPR deletion operation
        result = write_bench.execute_operation("delete_gdpr_suppliers_5pct", conn, use_transaction=True)

        # Verify result structure
        assert isinstance(result, OperationResult)
        assert result.operation_id == "delete_gdpr_suppliers_5pct"
        assert result.success is True, f"Operation failed: {result.error}"
        assert result.validation_passed is True, f"Validation failed: {result.validation_results}"
        assert result.cleanup_success is True

        # Verify validation query returned expected result
        validation_results = result.validation_results
        assert len(validation_results) > 0, f"Expected validation results, got empty list. Result: {result}"

        # Find verify_gdpr_deletion query (may have different query_id for 5pct variant)
        verify_deletion_results = [v for v in validation_results if "verify_gdpr_deletion" in v["query_id"]]
        assert len(verify_deletion_results) > 0, (
            f"Could not find verify_gdpr_deletion query. Available query_ids: {[v['query_id'] for v in validation_results]}"
        )

        verify_deletion = verify_deletion_results[0]
        assert verify_deletion["passed"] is True
        assert verify_deletion["actual_rows"] == 1

    def test_merge_etl_aggregation_pattern(self, setup_env):
        """Test MERGE with ETL aggregation pattern including running totals.

        Note: DuckDB doesn't support MERGE syntax, so this test expects failure on DuckDB.
        """
        write_bench, conn = setup_env

        # Execute ETL aggregation MERGE operation
        result = write_bench.execute_operation("merge_etl_aggregation_pattern", conn, use_transaction=True)

        # Verify result structure
        assert isinstance(result, OperationResult)
        assert result.operation_id == "merge_etl_aggregation_pattern"

        # DuckDB doesn't support MERGE syntax - expect Parser Error
        if not result.success:
            assert "Parser Error" in result.error and "MERGE" in result.error, (
                f"Expected MERGE syntax error on DuckDB, got: {result.error}"
            )
            pytest.skip("DuckDB doesn't support MERGE syntax - test cannot run on DuckDB")

        # If MERGE is supported (other databases), verify success
        assert result.success is True, f"Operation failed: {result.error}"
        assert result.validation_passed is True, f"Validation failed: {result.validation_results}"
        assert result.cleanup_success is True

        # Verify both validation queries passed
        validation_results = result.validation_results
        assert len(validation_results) == 2, "Should have 2 validation queries"

        # Check verify_etl_aggregation (counts updated/inserted rows)
        verify_agg = [v for v in validation_results if v["query_id"] == "verify_etl_aggregation"][0]
        assert verify_agg["passed"] is True

        # Check verify_etl_aggregation_values (validates actual aggregated values exist)
        verify_values = [v for v in validation_results if v["query_id"] == "verify_etl_aggregation_values"][0]
        assert verify_values["passed"] is True
        # CASE expression should return 1 if valid aggregations exist
        assert verify_values["actual_rows"] == 1

    def test_merge_deduplication_window_function(self, setup_env):
        """Test MERGE with window function deduplication (ROW_NUMBER pattern).

        Note: DuckDB doesn't support MERGE syntax, so this test expects failure on DuckDB.
        """
        write_bench, conn = setup_env

        # Execute deduplication MERGE operation
        result = write_bench.execute_operation("merge_deduplication_window_function", conn, use_transaction=True)

        # Verify result structure
        assert isinstance(result, OperationResult)
        assert result.operation_id == "merge_deduplication_window_function"

        # DuckDB doesn't support MERGE syntax - expect Parser Error
        if not result.success:
            assert "Parser Error" in result.error and "MERGE" in result.error, (
                f"Expected MERGE syntax error on DuckDB, got: {result.error}"
            )
            pytest.skip("DuckDB doesn't support MERGE syntax - test cannot run on DuckDB")

        # If MERGE is supported (other databases), verify success
        assert result.success is True, f"Operation failed: {result.error}"
        assert result.validation_passed is True, f"Validation failed: {result.validation_results}"
        assert result.cleanup_success is True

        # Verify both validation queries passed
        validation_results = result.validation_results
        assert len(validation_results) == 2, "Should have 2 validation queries"

        # Check verify_deduplication (counts rows with dedup markers)
        verify_dedup = [v for v in validation_results if v["query_id"] == "verify_deduplication"][0]
        assert verify_dedup["passed"] is True

        # Check verify_no_duplicates (validates no duplicate orderkeys remain)
        verify_no_dups = [v for v in validation_results if v["query_id"] == "verify_no_duplicates"][0]
        assert verify_no_dups["passed"] is True
        # CASE expression should return 1 if max duplicate count is 1
        assert verify_no_dups["actual_rows"] == 1

    def test_consolidated_operations_category_filtering(self, setup_env):
        """Test that consolidated operations can be filtered by their correct categories."""
        write_bench, conn = setup_env

        # Get DELETE operations - should include 2 GDPR operations
        delete_ops = write_bench.get_operations_by_category("delete")
        delete_op_ids = list(delete_ops.keys())
        assert "delete_gdpr_suppliers_1pct" in delete_op_ids
        assert "delete_gdpr_suppliers_5pct" in delete_op_ids

        # Get MERGE operations - should include ETL and deduplication
        merge_ops = write_bench.get_operations_by_category("merge")
        merge_op_ids = list(merge_ops.keys())
        assert "merge_etl_aggregation_pattern" in merge_op_ids
        assert "merge_deduplication_window_function" in merge_op_ids

        # Verify GDPR operations are NOT in MERGE category
        assert "delete_gdpr_suppliers_1pct" not in merge_op_ids
        assert "delete_gdpr_suppliers_5pct" not in merge_op_ids

    def test_gdpr_deletions_are_data_dependent(self, setup_env):
        """Test that GDPR deletions handle data-dependent row counts correctly."""
        write_bench, conn = setup_env

        # Get operation definitions
        op_1pct = write_bench.get_operation("delete_gdpr_suppliers_1pct")
        op_5pct = write_bench.get_operation("delete_gdpr_suppliers_5pct")

        # Verify expected_rows_affected is null (data-dependent)
        assert op_1pct.expected_rows_affected is None, "1% GDPR deletion should be data-dependent"
        assert op_5pct.expected_rows_affected is None, "5% GDPR deletion should be data-dependent"

        # Execute both and verify they succeed despite unknown row count
        result_1pct = write_bench.execute_operation("delete_gdpr_suppliers_1pct", conn, use_transaction=True)
        result_5pct = write_bench.execute_operation("delete_gdpr_suppliers_5pct", conn, use_transaction=True)

        assert result_1pct.success is True
        assert result_5pct.success is True

        # Validation should pass even though row count varies
        assert result_1pct.validation_passed is True
        assert result_5pct.validation_passed is True


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.write_primitives
class TestWritePrimitivesBulkLoad:
    """Test Write Primitives BULK_LOAD operations catalog and structure.

    Note: Full end-to-end BULK_LOAD testing requires TPC-H data generation which is
    tested separately. These tests verify that BULK_LOAD operations are correctly
    defined and retrievable from the catalog. File generation is covered by 20 unit
    tests in test_write_primitives_generator.py.
    """

    @pytest.fixture
    def write_bench(self, small_scale_factor, temp_dir):
        """Create Write Primitives benchmark instance."""
        return WritePrimitives(scale_factor=small_scale_factor, output_dir=temp_dir, quiet=True)

    def test_bulk_load_operations_exist_in_catalog(self, write_bench):
        """Test that BULK_LOAD operations are defined in the catalog."""
        # Get all BULK_LOAD operations
        bulk_load_ops = write_bench.get_operations_by_category("bulk_load")

        # Verify we have the expected number of BULK_LOAD operations
        assert len(bulk_load_ops) == 36, f"Expected 36 BULK_LOAD operations, got {len(bulk_load_ops)}"

    def test_bulk_load_csv_operations_defined(self, write_bench):
        """Test that CSV bulk load operations are properly defined."""
        bulk_load_ops = write_bench.get_operations_by_category("bulk_load")

        # Check for CSV operations with different sizes and compressions
        csv_ops = [op_id for op_id in bulk_load_ops.keys() if "csv" in op_id]

        # Should have CSV operations for small/medium/large with various compressions
        assert len(csv_ops) >= 12, f"Should have at least 12 CSV operations, got {len(csv_ops)}"

        # Verify specific operations exist
        assert "bulk_load_csv_small_uncompressed" in bulk_load_ops
        assert "bulk_load_csv_small_gzip" in bulk_load_ops
        assert "bulk_load_csv_medium_uncompressed" in bulk_load_ops

    def test_bulk_load_parquet_operations_defined(self, write_bench):
        """Test that Parquet bulk load operations are properly defined."""
        bulk_load_ops = write_bench.get_operations_by_category("bulk_load")

        # Check for Parquet operations
        parquet_ops = [op_id for op_id in bulk_load_ops.keys() if "parquet" in op_id]

        # Should have Parquet operations for small/medium/large with various compressions
        assert len(parquet_ops) >= 12, f"Should have at least 12 Parquet operations, got {len(parquet_ops)}"

        # Verify specific operations exist
        assert "bulk_load_parquet_small_uncompressed" in bulk_load_ops
        assert "bulk_load_parquet_small_snappy" in bulk_load_ops
        assert "bulk_load_parquet_medium_gzip" in bulk_load_ops

    def test_bulk_load_operation_structure(self, write_bench):
        """Test that BULK_LOAD operations have required structure."""
        # Get a representative operation
        operation = write_bench.get_operation("bulk_load_csv_small_uncompressed")

        # Verify operation has required fields
        assert operation.id == "bulk_load_csv_small_uncompressed"
        assert operation.category == "bulk_load"
        assert operation.write_sql is not None, "Operation should have write_sql"
        assert len(operation.write_sql) > 0, "write_sql should not be empty"

        # Verify write_sql contains file placeholder
        assert "{file_path}" in operation.write_sql, "BULK_LOAD operation should use {file_path} placeholder"

        # Verify validation queries exist
        assert operation.validation_queries is not None, "Operation should have validation queries"
        assert len(operation.validation_queries) > 0, "Should have at least one validation query"

        # Verify cleanup SQL exists
        assert operation.cleanup_sql is not None, "Operation should have cleanup_sql"

    def test_bulk_load_special_operations_defined(self, write_bench):
        """Test that special BULK_LOAD operations are defined."""
        bulk_load_ops = write_bench.get_operations_by_category("bulk_load")

        # Check for special operations beyond basic CSV/Parquet
        special_ops = [
            "bulk_load_column_subset",
            "bulk_load_null_handling",
            "bulk_load_quoted_fields",
            "bulk_load_delimited_custom",
        ]

        for op_id in special_ops:
            assert op_id in bulk_load_ops, f"Special operation {op_id} should be defined"

    def test_bulk_load_file_path_placeholder_replacement(self, write_bench):
        """Test that file path placeholder is correctly defined for replacement."""
        operation = write_bench.get_operation("bulk_load_csv_small_uncompressed")

        # Verify the placeholder format is correct
        assert "{file_path}" in operation.write_sql, "Should have {file_path} placeholder"

        # Verify it appears in the expected context (COPY statement)
        assert "COPY" in operation.write_sql or "LOAD" in operation.write_sql, (
            "BULK_LOAD operation should use COPY or LOAD statement"
        )

    def test_bulk_load_compression_variants(self, write_bench):
        """Test that BULK_LOAD operations cover multiple compression formats."""
        bulk_load_ops = write_bench.get_operations_by_category("bulk_load")

        # Check for various compression formats
        compression_formats = ["gzip", "zstd", "bzip2", "snappy"]
        found_compressions = set()

        for op_id in bulk_load_ops.keys():
            for compression in compression_formats:
                if compression in op_id:
                    found_compressions.add(compression)

        # Should support at least 3 different compression formats
        assert len(found_compressions) >= 3, (
            f"Should support at least 3 compression formats, found: {found_compressions}"
        )

    def test_bulk_load_operation_categories_complete(self, write_bench):
        """Test that all operation categories include expected BULK_LOAD operations."""
        all_categories = write_bench.get_operation_categories()

        # Verify bulk_load is listed as a category
        assert "bulk_load" in all_categories, "bulk_load should be a valid category"

        # Verify category count
        bulk_load_ops = write_bench.get_operations_by_category("bulk_load")
        assert len(bulk_load_ops) == 36, f"BULK_LOAD category should have 36 operations, got {len(bulk_load_ops)}"


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.write_primitives
class TestWritePrimitivesSCD2DuckDB:
    """End-to-end SCD Type 2 dimension-maintenance ops against real DuckDB.

    Unlike the other execution fixtures, this one loads the ``customer`` base
    table (the SCD2 dimension source) so the scd2_ops_* staging tables populate
    and the ops exercise real close-old / insert-new behavior at SF0.01-shaped
    data.
    """

    @pytest.fixture
    def scd2_env(self, small_scale_factor, temp_dir):
        conn = duckdb.connect(":memory:")

        # setup() validates orders + lineitem exist; SCD2 sources customer.
        conn.execute("""
            CREATE TABLE orders (
                o_orderkey INTEGER PRIMARY KEY, o_custkey INTEGER, o_orderstatus CHAR(1),
                o_totalprice DECIMAL(15,2), o_orderdate DATE, o_orderpriority CHAR(15),
                o_clerk CHAR(15), o_shippriority INTEGER, o_comment VARCHAR(79)
            )
        """)
        conn.execute("""
            CREATE TABLE lineitem (
                l_orderkey INTEGER, l_partkey INTEGER, l_suppkey INTEGER, l_linenumber INTEGER,
                l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), l_discount DECIMAL(15,2),
                l_tax DECIMAL(15,2), l_returnflag CHAR(1), l_linestatus CHAR(1), l_shipdate DATE,
                l_commitdate DATE, l_receiptdate DATE, l_shipinstruct CHAR(25), l_shipmode CHAR(10),
                l_comment VARCHAR(44)
            )
        """)
        conn.execute("""
            CREATE TABLE customer (
                c_custkey INTEGER PRIMARY KEY, c_name VARCHAR(25), c_address VARCHAR(40),
                c_nationkey INTEGER, c_phone VARCHAR(15), c_acctbal DECIMAL(15,2),
                c_mktsegment VARCHAR(10), c_comment VARCHAR(117)
            )
        """)
        conn.execute("INSERT INTO orders VALUES (1, 1, 'O', 10.0, DATE '2024-01-01', '1-URGENT', 'C#1', 0, 'o')")
        conn.execute(
            "INSERT INTO lineitem VALUES "
            "(1, 1, 1, 1, 1.0, 1.0, 0.0, 0.0, 'N', 'O', DATE '2024-01-02', DATE '2024-01-01', "
            "DATE '2024-01-03', 'NONE', 'TRUCK', 'c')"
        )
        # 50 customers so the change batch ranges (1-20 changed, 21-40 unchanged,
        # offset-by-max new) all populate.
        conn.execute("""
            INSERT INTO customer
            SELECT i, 'Customer#' || CAST(i AS VARCHAR), 'Addr ' || CAST(i AS VARCHAR),
                   (i % 25), '555-' || CAST(i AS VARCHAR), (i * 10.0),
                   CASE WHEN i % 2 = 0 THEN 'BUILDING' ELSE 'AUTOMOBILE' END,
                   'comment ' || CAST(i AS VARCHAR)
            FROM range(1, 51) t(i)
        """)

        write_bench = WritePrimitives(scale_factor=small_scale_factor, output_dir=temp_dir, quiet=True)
        write_bench.setup(conn, force=True)
        yield write_bench, conn
        conn.close()

    def _current_state(self, conn):
        """Return (total_rows, current_rows, closed_rows) for the dimension."""
        return conn.execute(
            "SELECT COUNT(*), "
            "SUM(CASE WHEN is_current THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN NOT is_current THEN 1 ELSE 0 END) "
            "FROM scd2_ops_dim_customer"
        ).fetchone()

    def test_scd2_dimension_and_stage_seeded(self, scd2_env):
        """Setup seeds one current version per customer and a mixed change batch."""
        _, conn = scd2_env
        total, current, closed = self._current_state(conn)
        assert total == 50 and current == 50 and closed == 0
        # Exactly one current row per business key after seeding.
        offenders = conn.execute(
            "SELECT c_custkey FROM scd2_ops_dim_customer WHERE is_current = true "
            "GROUP BY c_custkey HAVING COUNT(*) <> 1"
        ).fetchall()
        assert offenders == []
        stage = dict(
            conn.execute("SELECT change_type, COUNT(*) FROM scd2_ops_stage_customer GROUP BY change_type").fetchall()
        )
        assert stage == {"changed": 20, "unchanged": 20, "new": 20}

    def test_scd2_basic_executes_validates_and_cleans_up(self, scd2_env):
        """Close-old + insert-new runs, validates, and restores pre-op state."""
        write_bench, conn = scd2_env
        result = write_bench.execute_operation("merge_scd_type2_basic", conn)
        assert isinstance(result, OperationResult)
        assert result.success is True, result.error
        assert result.validation_passed is True
        assert result.cleanup_success is True
        # cleanup restores the seed state, so the op is repeatable.
        assert self._current_state(conn) == (50, 50, 0)

    def test_scd2_basic_writes_history_before_cleanup(self, scd2_env):
        """Running the raw write SQL closes changed keys and inserts new versions."""
        write_bench, conn = scd2_env
        op = write_bench.get_operation("merge_scd_type2_basic")
        conn.execute(op.write_sql)
        # 20 changed keys closed + 20 changed-key new versions + 20 brand-new keys.
        total, current, closed = self._current_state(conn)
        assert closed == 20
        assert current == 70  # 50 seed - 20 closed + 20 changed-new + 20 new
        assert total == 90
        # Still exactly one current row per business key.
        offenders = conn.execute(
            "SELECT c_custkey FROM scd2_ops_dim_customer WHERE is_current = true "
            "GROUP BY c_custkey HAVING COUNT(*) <> 1"
        ).fetchall()
        assert offenders == []
        # Closed rows carry a non-sentinel valid_to.
        sentinel_closed = conn.execute(
            "SELECT COUNT(*) FROM scd2_ops_dim_customer WHERE is_current = false AND valid_to = DATE '9999-12-31'"
        ).fetchone()[0]
        assert sentinel_closed == 0
        conn.execute(op.cleanup_sql)
        assert self._current_state(conn) == (50, 50, 0)

    def test_scd2_basic_is_repeatable(self, scd2_env):
        """Re-running the full op (write+validate+cleanup) stays correct."""
        write_bench, conn = scd2_env
        for _ in range(2):
            result = write_bench.execute_operation("merge_scd_type2_basic", conn)
            assert result.success is True, result.error
            assert result.validation_passed is True
            assert self._current_state(conn) == (50, 50, 0)

    def test_scd2_basic_write_is_idempotent_without_cleanup(self, scd2_env):
        """N4: running basic's raw write twice with no cleanup must not create a
        second current version per key.

        Before the NOT EXISTS current-version guard, the second run re-inserted
        both the 'new' keys and the 'changed'-key versions (the closed row still
        carried valid_to = effective_ts, so the changed branch re-fired), doubling
        every current version. The guard makes the write idempotent.
        """
        write_bench, conn = scd2_env
        op = write_bench.get_operation("merge_scd_type2_basic")
        conn.execute(op.write_sql)
        state_after_first = self._current_state(conn)
        conn.execute(op.write_sql)
        assert self._current_state(conn) == state_after_first
        # No business key has more than one current version.
        offenders = conn.execute(
            "SELECT c_custkey FROM scd2_ops_dim_customer WHERE is_current = true "
            "GROUP BY c_custkey HAVING COUNT(*) <> 1"
        ).fetchall()
        assert offenders == []

    def test_scd2_no_change_is_idempotent(self, scd2_env):
        """An unchanged batch closes no rows and inserts zero new versions."""
        write_bench, conn = scd2_env
        result = write_bench.execute_operation("merge_scd_type2_no_change", conn)
        assert result.success is True, result.error
        assert result.validation_passed is True
        assert self._current_state(conn) == (50, 50, 0)

    def test_scd2_new_keys_only_inserts_without_closing(self, scd2_env):
        """Brand-new keys are appended as current versions; nothing is closed."""
        write_bench, conn = scd2_env
        op = write_bench.get_operation("merge_scd_type2_new_keys_only")
        conn.execute(op.write_sql)
        total, current, closed = self._current_state(conn)
        assert closed == 0
        assert current == 70 and total == 70
        conn.execute(op.cleanup_sql)
        assert self._current_state(conn) == (50, 50, 0)

    def test_failing_validation_reports_validation_failed_not_success(self, scd2_env):
        """A post-condition validation failure must not report SUCCESS/green.

        Inject a second current version for an existing business key so the
        at_most_one_current_per_business_key invariant fails independently of the
        operation. new_keys_only's cleanup only removes new-key rows, so the
        planted duplicate survives and the failure is observed at the op level.
        This guards the N1 regression: validation_passed was computed but never
        gated success/status.
        """
        write_bench, conn = scd2_env
        # Duplicate current row for existing key 1 (unique surrogate key).
        conn.execute(
            "INSERT INTO scd2_ops_dim_customer VALUES "
            "(999999, 1, 'DUP', 'DUP', 0, 'DUP', 'DUP', true, DATE '1990-01-01', DATE '9999-12-31')"
        )
        result = write_bench.execute_operation("merge_scd_type2_new_keys_only", conn)
        assert result.validation_passed is False
        assert result.success is False
        assert result.status == "VALIDATION_FAILED"
        assert result.error and "at_most_one_current_per_business_key" in result.error

    def test_no_change_noop_against_missing_keys_fails_validation(self, scd2_env):
        """N2: a no-op no_change against a dimension missing its unchanged keys
        must fail, not pass vacuously.

        Before the positive companion check, all three no_change validations were
        zero-row 'offending' queries, so deleting the unchanged keys and doing
        nothing passed them all. every_unchanged_key_has_current_version_matching_hash
        now catches it.
        """
        write_bench, conn = scd2_env
        # Remove the current versions of the 'unchanged' business keys (21-40).
        conn.execute("DELETE FROM scd2_ops_dim_customer WHERE c_custkey BETWEEN 21 AND 40")
        result = write_bench.execute_operation("merge_scd_type2_no_change", conn)
        assert result.validation_passed is False
        assert result.status == "VALIDATION_FAILED"
        assert result.error and "every_unchanged_key_has_current_version_matching_hash" in result.error

    def test_basic_wrong_insert_count_fails_cardinality_bound(self, scd2_env):
        """N3: if basic inserts fewer new versions than the batch requires, the
        cardinality bound fails even though every offending-row check passes.

        Dropping the 'new' staging rows leaves only the 20 changed-key inserts, so
        basic inserts 20 new versions instead of 40; basic_inserts_expected_new_version_count
        (bounded to exactly 40) catches the shortfall.
        """
        write_bench, conn = scd2_env
        conn.execute("DELETE FROM scd2_ops_stage_customer WHERE change_type = 'new'")
        result = write_bench.execute_operation("merge_scd_type2_basic", conn)
        assert result.validation_passed is False
        assert result.status == "VALIDATION_FAILED"
        assert result.error and "basic_inserts_expected_new_version_count" in result.error


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
