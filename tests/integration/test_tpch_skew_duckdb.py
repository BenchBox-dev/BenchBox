"""Integration tests for TPC-H Skew with DuckDB.

This module tests the TPC-H Skew implementation with a real DuckDB database.
It verifies skewed data generation, schema creation, and query execution.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification with skew extensions.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest import mock

import duckdb
import pytest

from benchbox import TPCHSkew
from benchbox.core.tpch_skew.benchmark import TPCHSkewBenchmark

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


@pytest.mark.duckdb
class TestTPCHSkewDuckDBIntegration:
    """Integration tests for TPC-H Skew with DuckDB."""

    @pytest.fixture
    def tpch_skew(self, small_scale_factor, temp_dir):
        """Create a tiny TPC-H Skew instance for testing."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"
            return TPCHSkew(
                scale_factor=small_scale_factor,
                output_dir=temp_dir,
                skew_preset="moderate",
            )

    @pytest.fixture
    def tpch_skew_heavy(self, small_scale_factor, temp_dir):
        """Create a TPC-H Skew instance with heavy skew for testing."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"
            return TPCHSkew(
                scale_factor=small_scale_factor,
                output_dir=temp_dir / "heavy",
                skew_preset="heavy",
            )

    @pytest.fixture
    def duckdb_conn(self):
        """Create a temporary DuckDB database."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_create_schema(self, tpch_skew, duckdb_conn):
        """Test creating the TPC-H schema in DuckDB."""
        # Get the SQL schema
        sql = tpch_skew.get_create_tables_sql()

        # Execute the schema creation
        for statement in sql.strip().split(";"):
            if statement.strip():
                duckdb_conn.execute(statement.strip())

        # Verify tables were created
        tables_result = duckdb_conn.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            ORDER BY table_name
        """).fetchall()

        table_names = [row[0] for row in tables_result]
        expected_tables = [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]

        # Check that all expected tables exist (case-insensitive)
        table_names_lower = [t.lower() for t in table_names]
        for expected_table in expected_tables:
            assert expected_table in table_names_lower, (
                f"Table {expected_table} not found in created tables: {table_names}"
            )

    def test_skew_info_accessible(self, tpch_skew):
        """Test that skew configuration is properly accessible."""
        info = tpch_skew.get_skew_info()

        assert "preset" in info
        assert "skew_factor" in info
        assert "distribution_type" in info
        assert info["preset"] == "moderate"
        assert info["skew_factor"] == 0.5

    def test_benchmark_info_includes_skew(self, tpch_skew):
        """Test benchmark info includes skew details."""
        info = tpch_skew.get_benchmark_info()

        assert "name" in info
        assert "TPC-H Skew" in info["name"]
        assert "skew_info" in info
        assert info["skew_info"]["preset"] == "moderate"

    def test_queries_available(self, tpch_skew):
        """Test that all 22 TPC-H queries are available."""
        queries = tpch_skew.get_queries()
        assert len(queries) == 22

        # Verify each query exists and is valid SQL
        for query_id in range(1, 23):
            query = tpch_skew.get_query(query_id)
            assert isinstance(query, str)
            assert "SELECT" in query.upper()

    def test_different_presets_have_different_configs(self, small_scale_factor, temp_dir):
        """Test that different presets produce different configurations."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"

            none_benchmark = TPCHSkew(
                scale_factor=small_scale_factor,
                output_dir=temp_dir / "none",
                skew_preset="none",
            )
            heavy_benchmark = TPCHSkew(
                scale_factor=small_scale_factor,
                output_dir=temp_dir / "heavy",
                skew_preset="heavy",
            )

            # None preset should have 0 skew factor
            assert none_benchmark.skew_config.skew_factor == 0.0
            assert none_benchmark.skew_config.enable_attribute_skew is False

            # Heavy preset should have high skew factor
            assert heavy_benchmark.skew_config.skew_factor == 0.8
            assert heavy_benchmark.skew_config.enable_attribute_skew is True


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.slow
class TestTPCHSkewDataGeneration:
    """Integration tests for TPC-H Skew data generation.

    These tests generate actual skewed data and may be resource-intensive.
    They are marked as slow and may be skipped in quick test runs.
    """

    @pytest.fixture
    def tpch_skew_impl(self, small_scale_factor, temp_dir):
        """Create TPCHSkewBenchmark instance for testing data generation."""
        return TPCHSkewBenchmark(
            scale_factor=small_scale_factor,
            output_dir=temp_dir,
            skew_preset="moderate",
        )

    def test_generate_data_creates_files(self, tpch_skew_impl):
        """Test that generate_data creates the expected data files."""
        try:
            # Generate skewed data
            data_paths = tpch_skew_impl.generate_data()

            # Should create 8 table files
            assert len(data_paths) >= 8

            # Verify each file exists
            for path in data_paths:
                assert path.exists(), f"Data file {path} should exist"

        except OSError as e:
            if "No space left on device" in str(e):
                pytest.skip("Insufficient disk space for data generation")
            raise

    def test_generated_data_is_loadable(self, tpch_skew_impl):
        """Test that generated data can be loaded into DuckDB."""
        try:
            # Generate data
            tpch_skew_impl.generate_data()
        except OSError as e:
            if "No space left on device" in str(e):
                pytest.skip("Insufficient disk space for data generation")
            raise

        # Create DuckDB connection and schema
        conn = duckdb.connect(":memory:")
        try:
            sql = tpch_skew_impl.get_create_tables_sql()
            for statement in sql.strip().split(";"):
                if statement.strip():
                    conn.execute(statement.strip())

            # Try to load one of the smaller tables (region or nation)
            tables = tpch_skew_impl.tables
            if "region" in tables:
                region_path = tables["region"]
                conn.execute(f"""
                    COPY region FROM '{region_path}'
                    (DELIMITER '|', HEADER FALSE)
                """)
                count = conn.execute("SELECT COUNT(*) FROM region").fetchone()[0]
                assert count == 5, "Region table should have 5 rows"

            if "nation" in tables:
                nation_path = tables["nation"]
                conn.execute(f"""
                    COPY nation FROM '{nation_path}'
                    (DELIMITER '|', HEADER FALSE)
                """)
                count = conn.execute("SELECT COUNT(*) FROM nation").fetchone()[0]
                assert count == 25, "Nation table should have 25 rows"

        finally:
            conn.close()


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.slow
class TestTPCHSkewQueryExecution:
    """Integration tests for TPC-H Skew query execution.

    These tests actually run queries and may be slower.
    They require data generation which may need significant disk space.
    """

    @pytest.fixture
    def loaded_benchmark(self, small_scale_factor, temp_dir):
        """Create and load a TPC-H Skew benchmark with data."""
        benchmark = TPCHSkewBenchmark(
            scale_factor=small_scale_factor,
            output_dir=temp_dir,
            skew_preset="moderate",
        )

        # Generate data - may fail due to disk space
        try:
            benchmark.generate_data()
        except OSError as e:
            if "No space left on device" in str(e):
                pytest.skip("Insufficient disk space for data generation")
            raise

        # Create DuckDB with loaded data
        conn = duckdb.connect(":memory:")

        # Create schema
        sql = benchmark.get_create_tables_sql()
        for statement in sql.strip().split(";"):
            if statement.strip():
                conn.execute(statement.strip())

        # Load all tables
        for table_name, file_path in benchmark.tables.items():
            conn.execute(f"""
                COPY {table_name} FROM '{file_path}'
                (DELIMITER '|', HEADER FALSE)
            """)

        yield benchmark, conn
        conn.close()

    def test_query_execution(self, loaded_benchmark):
        """Test that TPC-H queries execute successfully on skewed data."""
        benchmark, conn = loaded_benchmark

        # Get DuckDB-compatible queries
        queries = benchmark.get_queries(dialect="duckdb")

        # Test a subset of queries (Q1 and Q6 are simple and fast)
        test_queries = ["1", "6"]

        for query_id in test_queries:
            if query_id in queries:
                query = queries[query_id]
                try:
                    result = conn.execute(query).fetchall()
                    # Query should return some results (may be empty for tiny data)
                    assert isinstance(result, list)
                except Exception as e:
                    pytest.fail(f"Query {query_id} failed: {e}")

    def test_referential_integrity(self, loaded_benchmark):
        """Test that skewed data maintains referential integrity."""
        benchmark, conn = loaded_benchmark

        # Check that all order customer keys exist in customer table
        orphan_orders = conn.execute("""
            SELECT COUNT(*)
            FROM orders o
            LEFT JOIN customer c ON o.o_custkey = c.c_custkey
            WHERE c.c_custkey IS NULL
        """).fetchone()[0]
        assert orphan_orders == 0, "All orders should reference valid customers"

        # Check that all lineitem order keys exist in orders table
        orphan_lineitems = conn.execute("""
            SELECT COUNT(*)
            FROM lineitem l
            LEFT JOIN orders o ON l.l_orderkey = o.o_orderkey
            WHERE o.o_orderkey IS NULL
        """).fetchone()[0]
        assert orphan_lineitems == 0, "All lineitems should reference valid orders"

        # Check that all partsupp part keys exist in part table
        orphan_partsupp = conn.execute("""
            SELECT COUNT(*)
            FROM partsupp ps
            LEFT JOIN part p ON ps.ps_partkey = p.p_partkey
            WHERE p.p_partkey IS NULL
        """).fetchone()[0]
        assert orphan_partsupp == 0, "All partsupp should reference valid parts"

        # Check supplier foreign keys
        orphan_supplier = conn.execute("""
            SELECT COUNT(*)
            FROM partsupp ps
            LEFT JOIN supplier s ON ps.ps_suppkey = s.s_suppkey
            WHERE s.s_suppkey IS NULL
        """).fetchone()[0]
        assert orphan_supplier == 0, "All partsupp should reference valid suppliers"
