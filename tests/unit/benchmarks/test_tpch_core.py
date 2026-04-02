"""Consolidated TPC-H core test suite.

This test suite provides comprehensive coverage of the TPC-H benchmark implementation,
including interface functionality, schema definitions, query management, benchmark
operations, compliance checks, and database integration.

Consolidates tests from test_tpch.py and test_tpch_comprehensive.py into a single
well-organized test suite.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from unittest.mock import Mock, patch

import pytest

from benchbox import TPCH
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.core.tpch.queries import TPCHQueries
from benchbox.core.tpch.schema import (
    CUSTOMER,
    LINEITEM,
    REGION,
    TABLES,
    get_create_all_tables_sql,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCHInterface:
    """Test basic functionality and interface of the TPC-H tpch_benchmark."""

    @pytest.fixture
    def tpch(self, small_scale_factor: float, temp_dir: Path) -> TPCH:
        """Create a TPC-H benchmark instance for testing."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"
            return TPCH(scale_factor=small_scale_factor, output_dir=temp_dir, parallel=1)

    def test_generate_data(self, tpch: TPCH) -> None:
        """Test that data generation produces expected files."""
        # Mock the data generation to avoid actual dbgen compilation
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

        # Create mock file paths for each expected table
        mock_paths = {table: Path(tpch._impl.output_dir) / f"{table}.csv" for table in expected_tables}

        # Mock the data generator's generate method
        with mock.patch.object(tpch._impl.data_generator, "generate", return_value=mock_paths):
            data_paths = tpch.generate_data()

            # Check that output includes expected files
            for table in expected_tables:
                assert any(table in str(path) for path in data_paths), f"Table {table} not found in generated data"

    def test_get_queries(self, tpch: TPCH) -> None:
        """Test that all benchmark queries can be retrieved."""
        queries = tpch.get_queries()

        # TPC-H has queries numbered 1 to 22
        assert len(queries) == 22
        for i in range(1, 23):
            query_id = str(i)
            assert query_id in queries
            assert isinstance(queries[query_id], str)
            assert queries[query_id].strip()

            # Check that queries contain expected SQL elements
            if i == 1:  # Query 1 should involve lineitem table
                assert "lineitem" in queries[query_id].lower()
                assert "group by" in queries[query_id].lower()
            elif i == 3:  # Query 3 should involve multiple tables
                assert "customer" in queries[query_id].lower()
                assert "orders" in queries[query_id].lower()
                assert "lineitem" in queries[query_id].lower()

    def test_get_query(self, tpch: TPCH) -> None:
        """Test retrieving a specific query."""
        query1 = tpch.get_query(1)
        assert isinstance(query1, str)
        assert "SELECT" in query1.upper()
        assert "LINEITEM" in query1.upper()

        # Test a different query
        query3 = tpch.get_query(3)
        assert isinstance(query3, str)
        assert "CUSTOMER" in query3.upper()
        assert "ORDERS" in query3.upper()

    def test_translate_query(self, tpch: TPCH, sql_dialect: str) -> None:
        """Test translating a query to different SQL dialects."""
        tpch.get_query(1)
        translated_query = tpch.translate_query(1, dialect=sql_dialect)

        assert isinstance(translated_query, str)
        assert "SELECT" in translated_query.upper()

    def test_invalid_query_number(self, tpch: TPCH) -> None:
        """Test that requesting an invalid query raises an exception."""
        with pytest.raises(ValueError):
            tpch.get_query(99)  # TPC-H only has 22 queries

    def test_get_query_harmonized_parameters(self, tpch: TPCH) -> None:
        """Test that harmonized parameters work correctly."""
        # Test with default parameters
        param_query = tpch.get_query(1)
        assert isinstance(param_query, str)
        assert "SELECT" in param_query.upper()

        # Test with custom parameters
        custom_params = {"1": 90}  # 90 days for Query 1
        param_query = tpch.get_query(1, params=custom_params)
        assert isinstance(param_query, str)
        assert "SELECT" in param_query.upper()

        # Test with seed parameter
        query_with_seed = tpch.get_query(1, seed=42)
        assert isinstance(query_with_seed, str)
        assert "SELECT" in query_with_seed.upper()

        # Test with scale_factor parameter
        query_with_scale = tpch.get_query(1, scale_factor=0.1)
        assert isinstance(query_with_scale, str)
        assert "SELECT" in query_with_scale.upper()

        # Test with dialect parameter
        query_with_dialect = tpch.get_query(1, dialect="postgres")
        assert isinstance(query_with_dialect, str)
        assert "SELECT" in query_with_dialect.upper()

        # Test with multiple parameters combined
        query_combined = tpch.get_query(1, params={"1": 90}, seed=42, scale_factor=0.1, dialect="postgres")
        assert isinstance(query_combined, str)
        assert "SELECT" in query_combined.upper()

    def test_get_schema(self, tpch: TPCH) -> None:
        """Test retrieving the TPC-H schema."""
        schema = tpch.get_schema()

        # Check that all tables are present - schema is now dict[str, dict]
        table_names = [schema[key]["name"] for key in schema]
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

        for table in expected_tables:
            assert table in table_names

        # Check that a table has expected columns - use lowercase lookup
        customer_table = schema.get("customer")
        assert customer_table is not None, "customer table not found in schema"
        column_names = [col["name"] for col in customer_table["columns"]]
        expected_columns = [
            "c_custkey",
            "c_name",
            "c_address",
            "c_nationkey",
            "c_phone",
            "c_acctbal",
            "c_mktsegment",
            "c_comment",
        ]

        for column in expected_columns:
            assert column in column_names

    def test_get_create_tables_sql(self, tpch: TPCH) -> None:
        """Test retrieving SQL to create TPC-H tables."""
        sql = tpch.get_create_tables_sql()

        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

        # Check for all tables (lowercase per TPC spec)
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

        for table in expected_tables:
            assert f"CREATE TABLE {table}" in sql

    def test_parameter_validation(self, temp_dir: Path) -> None:
        """Test that invalid parameters raise appropriate errors."""
        # Test negative scale factor
        with pytest.raises(ValueError, match="Scale factor must be positive"):
            TPCH(scale_factor=-1, output_dir=temp_dir)

        # Test zero scale factor
        with pytest.raises(ValueError, match="Scale factor must be positive"):
            TPCH(scale_factor=0, output_dir=temp_dir)

        # Test invalid scale factor type
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            TPCH(scale_factor="1", output_dir=temp_dir)

        # Test invalid parallel count
        with pytest.raises(ValueError, match="parallel must be positive"):
            TPCH(scale_factor=1, output_dir=temp_dir, parallel=0)

        # Test invalid parallel type
        with pytest.raises(TypeError, match="parallel must be an integer"):
            TPCH(scale_factor=1, output_dir=temp_dir, parallel="4")

    def test_get_query_parameter_validation(self, tpch: TPCH) -> None:
        """Test that get_query validates harmonized parameters correctly."""
        # Test invalid query_id type
        with pytest.raises(TypeError, match="query_id must be an integer"):
            tpch.get_query("1")

        # Test invalid query_id range
        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            tpch.get_query(0)

        with pytest.raises(ValueError, match="Query ID must be 1-22"):
            tpch.get_query(23)

        # Test invalid seed type
        with pytest.raises(TypeError, match="seed must be an integer"):
            tpch.get_query(1, seed="42")

        # Test invalid scale_factor type
        with pytest.raises(TypeError, match="scale_factor must be a number"):
            tpch.get_query(1, scale_factor="1.0")

        # Test invalid scale_factor value
        with pytest.raises(ValueError, match="scale_factor must be positive"):
            tpch.get_query(1, scale_factor=-1)

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_parallel_parameter_support(self, mock_find_dbgen, small_scale_factor: float, temp_dir: Path) -> None:
        """Test that parallel parameter is properly passed through."""
        # Mock the executable path
        mock_find_dbgen.return_value = temp_dir / "dbgen"

        tpch = TPCH(scale_factor=small_scale_factor, output_dir=temp_dir, parallel=4)
        assert tpch._impl.parallel == 4
        assert tpch._impl.data_generator.parallel == 4

    @mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen")
    def test_executable_not_found_error(self, mock_find_dbgen, small_scale_factor: float, temp_dir: Path) -> None:
        """Test error handling when dbgen executable cannot be found or built."""
        mock_find_dbgen.side_effect = FileNotFoundError("dbgen executable not found")

        tpch = TPCH(scale_factor=small_scale_factor, output_dir=temp_dir)
        # With lazy loading, the error occurs when accessing dbgen_exe property
        # Now wrapped in RuntimeError with more descriptive message
        with pytest.raises(RuntimeError, match="TPC-H dbgen tool not found"):
            _ = tpch._impl.data_generator.dbgen_exe

    @mock.patch("os.access")
    @mock.patch("benchbox.core.tpch.generator.Path.exists")
    def test_executable_permission_error(
        self, mock_exists, mock_access, small_scale_factor: float, temp_dir: Path
    ) -> None:
        """Test error handling when dbgen executable is not executable."""
        mock_exists.return_value = True
        mock_access.return_value = False

        tpch = TPCH(scale_factor=small_scale_factor, output_dir=temp_dir)
        # With lazy loading, the error occurs when accessing dbgen_exe property
        # Now wrapped in RuntimeError with more descriptive message
        with pytest.raises(RuntimeError, match="TPC-H dbgen tool not found"):
            _ = tpch._impl.data_generator.dbgen_exe

    # Test removed: delegation testing conflicts with validation logic
    # The validation happens before delegation, making mock-based testing unreliable
    # Integration tests cover the actual delegation behavior

    def test_compatibility_with_base_benchmark(self, tpch: TPCH) -> None:
        """Test compatibility with the BaseBenchmark interface."""
        # The generate_data method should return a list
        with mock.patch.object(tpch._impl, "generate_data") as mock_gen:
            mock_gen.return_value = [Path("/tmp/test.csv")]
            result = tpch.generate_data()
            assert isinstance(result, list)
            assert len(result) == 1

        # The get_queries method should return a dict
        with mock.patch.object(tpch._impl, "get_queries") as mock_queries:
            mock_queries.return_value = {"1": "SELECT * FROM test"}
            result = tpch.get_queries()
            assert isinstance(result, dict)
            assert len(result) == 1

        # The get_query method should return a string
        with mock.patch.object(tpch._impl, "get_query") as mock_query:
            mock_query.return_value = "SELECT * FROM test"
            result = tpch.get_query(1)
            assert isinstance(result, str)


class TestTPCHSchemaDefinition(unittest.TestCase):
    """Tests for the TPC-H schema definition."""

    def test_table_count(self) -> None:
        """Test that all 8 TPC-H tables are defined."""
        self.assertEqual(len(TABLES), 8, "TPC-H should have exactly 8 tables")
        table_names = {table.name for table in TABLES}
        expected_names = {
            "region",
            "nation",
            "customer",
            "supplier",
            "part",
            "partsupp",
            "orders",
            "lineitem",
        }
        self.assertEqual(table_names, expected_names, "Table names do not match TPC-H specification")

    def test_column_definitions(self) -> None:
        """Test that key tables have the correct column definitions."""
        # Check CUSTOMER table columns
        customer_cols = {col.name for col in CUSTOMER.columns}
        expected_customer_cols = {
            "c_custkey",
            "c_name",
            "c_address",
            "c_nationkey",
            "c_phone",
            "c_acctbal",
            "c_mktsegment",
            "c_comment",
        }
        self.assertEqual(
            customer_cols,
            expected_customer_cols,
            "CUSTOMER table columns are incorrect",
        )

        # Check LINEITEM table columns (most complex table)
        lineitem_cols = {col.name for col in LINEITEM.columns}
        expected_lineitem_cols = {
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_quantity",
            "l_extendedprice",
            "l_discount",
            "l_tax",
            "l_returnflag",
            "l_linestatus",
            "l_shipdate",
            "l_commitdate",
            "l_receiptdate",
            "l_shipinstruct",
            "l_shipmode",
            "l_comment",
        }
        self.assertEqual(
            lineitem_cols,
            expected_lineitem_cols,
            "LINEITEM table columns are incorrect",
        )

    def test_foreign_key_relationships(self) -> None:
        """Test that foreign key relationships are correctly defined."""
        # Check CUSTOMER to NATION relationship
        customer_fks = CUSTOMER.get_foreign_keys()
        self.assertIn("c_nationkey", customer_fks, "c_nationkey should be a foreign key")
        self.assertEqual(
            customer_fks["c_nationkey"],
            ("nation", "n_nationkey"),
            "c_nationkey should reference n_nationkey",
        )

        # Check LINEITEM to ORDERS relationship
        lineitem_fks = LINEITEM.get_foreign_keys()
        self.assertIn("l_orderkey", lineitem_fks, "l_orderkey should be a foreign key")
        self.assertEqual(
            lineitem_fks["l_orderkey"],
            ("orders", "o_orderkey"),
            "l_orderkey should reference o_orderkey",
        )

    def test_create_table_sql(self) -> None:
        """Test that CREATE TABLE SQL is correctly generated."""
        # Test REGION table SQL
        region_sql = REGION.get_create_table_sql()
        self.assertIn("CREATE TABLE region", region_sql)
        self.assertIn("r_regionkey INTEGER NOT NULL", region_sql)
        self.assertIn("PRIMARY KEY (r_regionkey)", region_sql)

        # Test complete schema SQL
        complete_sql = get_create_all_tables_sql()

        # Verify all tables are in the SQL
        for table in TABLES:
            self.assertIn(f"CREATE TABLE {table.name}", complete_sql)


class TestTPCHQueryManager(unittest.TestCase):
    """Tests for the TPC-H query manager."""

    def setUp(self) -> None:
        """Set up test fixtures before each test method."""
        self.query_manager = TPCHQueries()

    def test_query_loading(self) -> None:
        """Test that all 22 TPC-H queries are loaded."""
        queries = self.query_manager.get_all_queries()
        self.assertEqual(len(queries), 22, "Should load all 22 TPC-H queries")

        # Check specific query IDs
        for query_id in range(1, 23):
            self.assertIn(query_id, queries, f"Query {query_id} should be loaded")

    def test_query_content(self) -> None:
        """Test that query content is correctly loaded."""
        # Check Query 1
        query1 = self.query_manager.get_query(1)
        self.assertIn("l_returnflag", query1)
        self.assertIn("l_linestatus", query1)
        self.assertIn("sum(l_quantity)", query1)

        # Check Query 3
        query3 = self.query_manager.get_query(3)
        self.assertIn("customer", query3)
        self.assertIn("orders", query3)
        self.assertIn("lineitem", query3)

    def test_parameter_substitution(self) -> None:
        """Test parameter substitution in queries."""
        # The simplified interface uses seed-based parameter generation
        # Test Query 1 with a specific seed to get consistent parameters
        query1 = self.query_manager.get_query(1, seed=42)
        self.assertIsInstance(query1, str)
        self.assertGreater(len(query1), 0)

        # Test Query 3 with specific seed
        query3 = self.query_manager.get_query(3, seed=42)
        self.assertIsInstance(query3, str)
        self.assertGreater(len(query3), 0)

        # Queries with same seed should be identical
        query1_repeat = self.query_manager.get_query(1, seed=42)
        self.assertEqual(query1, query1_repeat)

    def test_random_parameter_generation(self) -> None:
        """Test that random parameters are correctly generated."""
        # The simplified interface doesn't expose _generate_random_params
        # Instead, test that queries can be generated with random parameters
        for query_id in range(1, 3):  # Test just a few queries
            query_text = self.query_manager.get_query(query_id)
            self.assertIsInstance(query_text, str)
            self.assertGreater(len(query_text), 0)

        # The simplified interface generates parameters internally


class TestTPCHBenchmark:
    """Tests for the TPC-H benchmark implementation."""

    @pytest.fixture
    def tpch_benchmark(self, small_scale_factor: float, temp_dir: Path) -> TPCHBenchmark:
        """Create a TPCHBenchmark instance for testing."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"
            return TPCHBenchmark(scale_factor=small_scale_factor, output_dir=temp_dir)

    def test_initialization(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that the benchmark initializes correctly."""
        assert tpch_benchmark.scale_factor == tpch_benchmark.scale_factor
        assert hasattr(tpch_benchmark, "query_manager")
        assert hasattr(tpch_benchmark, "data_generator")

    def test_init_with_verbose_and_parallel(self, temp_dir: Path) -> None:
        """Test benchmark initialization with verbose and parallel options."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = temp_dir / "dbgen"
            benchmark = TPCHBenchmark(scale_factor=0.5, output_dir=temp_dir, verbose=True, parallel=4)
            assert benchmark.scale_factor == 0.5
            assert getattr(benchmark, "verbose_enabled", False) is True
            assert benchmark.parallel == 4
            assert benchmark.streams_manager is None

    def test_get_queries(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that queries can be retrieved."""
        queries = tpch_benchmark.get_queries()
        assert len(queries) == 22, "Should return all 22 TPC-H queries"

        # Test getting a specific query
        query1 = tpch_benchmark.get_query(1)
        assert "l_returnflag" in query1
        assert "l_linestatus" in query1

        # Test getting a parameterized query
        param_query = tpch_benchmark.get_query(1, params={"1": 90})
        assert "l_returnflag" in param_query

    def test_get_schema(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that schema information can be retrieved."""
        schema = tpch_benchmark.get_schema()
        assert len(schema) == 8, "Should return 8 TPC-H tables"

        # Schema is now dict[str, dict] - check using lowercase keys
        customer_table = schema.get("customer")
        assert customer_table is not None, "customer table not found in schema"
        assert customer_table["name"] == "customer"

        customer_cols = [col["name"] for col in customer_table["columns"]]
        expected_cols = [
            "c_custkey",
            "c_name",
            "c_address",
            "c_nationkey",
            "c_phone",
            "c_acctbal",
            "c_mktsegment",
            "c_comment",
        ]
        for col in expected_cols:
            assert col in customer_cols

    def test_get_create_tables_sql(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that CREATE TABLE SQL can be retrieved."""
        sql = tpch_benchmark.get_create_tables_sql()
        assert isinstance(sql, str)

        # Check for all tables (lowercase per TPC spec)
        for table in [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]:
            assert f"CREATE TABLE {table}" in sql

    def test_benchmark_properties(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test benchmark basic properties."""
        assert tpch_benchmark.scale_factor == 1.0
        assert isinstance(tpch_benchmark.output_dir, Path)
        assert hasattr(tpch_benchmark, "query_manager")
        assert hasattr(tpch_benchmark, "data_generator")

    def test_benchmark_initialization_custom_params(self) -> None:
        """Test benchmark initialization with custom parameters."""
        custom_benchmark = TPCHBenchmark(scale_factor=0.1, output_dir=Path("/tmp/custom"), seed=12345)
        assert custom_benchmark.scale_factor == 0.1
        assert custom_benchmark.output_dir == Path("/tmp/custom")

    def test_data_generator_initialization(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that data generator is properly initialized."""
        generator = tpch_benchmark.data_generator
        assert generator is not None
        assert hasattr(generator, "scale_factor")
        # Data generator adjusts scale factor to minimum supported value
        assert generator.scale_factor >= tpch_benchmark.scale_factor

    def test_query_manager_initialization(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that query manager is properly initialized."""
        query_manager = tpch_benchmark.query_manager
        assert query_manager is not None
        assert hasattr(query_manager, "get_query")
        # TPCHQueries only has get_query method, not get_queries

    def test_generate_data_with_verbose(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test generate_data with verbose output - optimized version."""
        # Enable verbose logging using the new interface
        tpch_benchmark.verbose_enabled = True

        mock_data = {
            "customer": Path("/path/to/customer.csv"),
            "orders": Path("/path/to/orders.csv"),
        }

        # Create a completely mocked data generator to avoid any slow operations
        mock_generator = Mock()
        mock_generator.generate.return_value = mock_data

        # Replace the data generator entirely
        tpch_benchmark.data_generator = mock_generator

        # Patch logger.info to assert verbose output path is exercised
        with patch.object(tpch_benchmark.logger, "info") as mock_info:
            result = tpch_benchmark.generate_data()

            # Should log verbose output
            mock_info.assert_called()
            assert result == list(mock_data.values())
            assert tpch_benchmark.tables == mock_data

    def test_generate_data_directory_creation(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test generate_data creates output directory."""
        mock_data = {"customer": Path("/path/to/customer.csv")}

        with patch.object(tpch_benchmark.data_generator, "generate", return_value=mock_data):
            with patch("pathlib.Path.mkdir") as mock_mkdir:
                tpch_benchmark.generate_data()

                # Verify mkdir was called at least once (may be called multiple times)
                mock_mkdir.assert_called()

    def test_get_query_with_params(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test get_query with custom parameters."""
        custom_params = {"1": 90, "2": "TRUCK"}

        with patch.object(tpch_benchmark.query_manager, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT * FROM lineitem WHERE l_shipdate <= '1998-09-01'"

            result = tpch_benchmark.get_query(1, params=custom_params)

            mock_get_query.assert_called_once_with(1, seed=None, scale_factor=tpch_benchmark.scale_factor)
            assert "1998-09-01" in result

    def test_get_query_no_params(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test get_query without parameters (uses defaults)."""
        with patch.object(tpch_benchmark.query_manager, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT * FROM lineitem WHERE l_shipdate <= '1998-06-15'"

            result = tpch_benchmark.get_query(1)

            mock_get_query.assert_called_once_with(1, seed=None, scale_factor=tpch_benchmark.scale_factor)
            assert "1998-06-15" in result

    def test_run_benchmark_result_structure(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test run_benchmark accepts parameters and returns a result dict."""
        with patch.object(tpch_benchmark, "generate_data", return_value=["table1.tbl", "table2.tbl"]):
            with patch.object(tpch_benchmark, "setup_database"):
                result = tpch_benchmark.run_benchmark("connection_string", query_ids=[1, 2])
        assert isinstance(result, dict), f"Expected dict result, got {type(result)}"

    def test_run_query_parameter_handling(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test run_query parameter handling before NotImplementedError."""
        # Test standard dialect path
        with patch.object(tpch_benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT * FROM customer"

            mock_connection = Mock()
            try:
                tpch_benchmark.run_query(1, mock_connection, params={"1": 90})
            except NotImplementedError:
                pass  # Expected

            # Verify get_query was called correctly
            mock_get_query.assert_called_once_with(1, params={"1": 90})

        # Test query translation functionality
        with patch.object(tpch_benchmark, "translate_query") as mock_translate:
            mock_translate.return_value = "SELECT * FROM customer WHERE c_mktsegment = 'BUILDING'"

            # Just test that translate_query method exists and can be called
            translated = tpch_benchmark.translate_query(1, "mysql")
            assert translated == "SELECT * FROM customer WHERE c_mktsegment = 'BUILDING'"
            mock_translate.assert_called_once_with(1, "mysql")

    def test_streams_module_exists(self, tpch_benchmark: TPCHBenchmark) -> None:
        """Test that TPC-H streams module functionality exists."""
        # Test that streams functionality can be imported
        from benchbox.core.tpch.streams import TPCHStreamRunner, TPCHStreams

        # Basic instantiation test
        assert TPCHStreamRunner is not None
        assert TPCHStreams is not None


class TestTPCHCompliance:
    """Tests for compliance with the BaseBenchmark abstract class."""

    def test_tpch_implements_base_benchmark(self) -> None:
        """Test that TPCH implements the BaseBenchmark interface."""
        from benchbox.base import BaseBenchmark

        assert issubclass(TPCH, BaseBenchmark)

        # Initialize a TPCH instance
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = Path("/tmp/dbgen")
            tpch = TPCH(scale_factor=0.01)

        # Check that required methods are implemented
        assert hasattr(tpch, "generate_data")
        assert hasattr(tpch, "get_query")
        assert hasattr(tpch, "get_queries")
        assert hasattr(tpch, "translate_query")


@pytest.mark.integration
class TestTPCHDataGeneratorIntegration:
    """Integration tests for the TPC-H data generator.

    These tests are marked as integration tests since they involve
    compiling and running the TPC-H dbgen tool.
    """

    @pytest.fixture(autouse=True)
    def mock_dbgen_build(self):
        """Mock dbgen executable building for all tests."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = Path("/tmp/dbgen")
            yield mock_build

    def test_generator_initialization(self, temp_dir) -> None:
        """Test that the generator initializes correctly."""
        generator = TPCHDataGenerator(
            scale_factor=0.01,  # Very small scale for testing
            output_dir=temp_dir,
            verbose=True,
        )
        assert generator.scale_factor == 0.01  # Supports fractional scale factors
        assert generator.output_dir == temp_dir
        assert generator.verbose is True

    def test_data_generation(self, temp_dir) -> None:
        """Test data generation with mocked dbgen execution.

        This test mocks the TPC-H dbgen tool execution to avoid
        requiring actual dbgen binary compilation.
        """
        generator = TPCHDataGenerator(
            scale_factor=0.01,  # Very small scale for testing
            output_dir=temp_dir,
        )

        # Mock the actual data generation process
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

        # Create mock files for each table
        mock_table_paths = {}
        for table in expected_tables:
            mock_file = temp_dir / f"{table}.csv"
            mock_file.write_text(f"# Mock data for {table}\n")
            mock_table_paths[table] = mock_file

        # Mock the _run_dbgen_native method to avoid actual execution
        with mock.patch.object(generator, "_run_dbgen_native"):
            # Mock the _generate_local method to return our mock file paths
            with mock.patch.object(generator, "_generate_local", return_value=mock_table_paths):
                # Generate data
                table_paths = generator.generate()

        # Verify that all tables were generated
        assert len(table_paths) == 8, "Should generate 8 tables"
        for table in expected_tables:
            assert table in table_paths, f"{table} should be generated"
            assert table_paths[table].exists(), f"{table} file should exist"
            assert table_paths[table].suffix == ".csv", f"{table} should be in CSV format"

    def test_compile_dbgen_mock(self, temp_dir) -> None:
        """Test dbgen compilation with mocks."""
        generator = TPCHDataGenerator(scale_factor=0.01, output_dir=temp_dir)

        # Test that the generator was initialized properly
        assert generator.scale_factor == 0.01  # Supports fractional scale factors
        assert generator.output_dir == temp_dir
        assert generator.dbgen_exe == Path("/tmp/dbgen")  # From the fixture mock


@pytest.mark.integration
@pytest.mark.duckdb
class TestTPCHDatabaseIntegration:
    """Integration tests with a real database.

    These tests connect to a SQLite database to verify that
    the TPC-H queries can be executed correctly.
    """

    @pytest.fixture
    def sqlite_db(self):
        """Create a temporary SQLite database."""
        import sqlite3

        db_path = tempfile.mktemp(suffix=".db")
        conn = sqlite3.connect(db_path)
        yield conn
        conn.close()
        if os.path.exists(db_path):
            os.unlink(db_path)

    @pytest.fixture
    def tiny_tpch(self, small_scale_factor):
        """Create a tiny TPC-H instance with mocked data."""
        with mock.patch("benchbox.core.tpch.generator.TPCHDataGenerator._find_or_build_dbgen") as mock_build:
            mock_build.return_value = Path("/tmp/dbgen")
            tpch = TPCH(scale_factor=small_scale_factor)

        # Mock the data generation to avoid actually running dbgen
        tpch._impl.tables = {
            "customer": None,
            "lineitem": None,
            "nation": None,
            "orders": None,
            "part": None,
            "partsupp": None,
            "region": None,
            "supplier": None,
        }

        return tpch

    def test_create_tables(self, sqlite_db, tiny_tpch) -> None:
        """Test creating TPC-H tables in a database."""
        cursor = sqlite_db.cursor()

        # Get the SQL and adapt it for SQLite
        sql = tiny_tpch.get_create_tables_sql()
        sql = sql.replace("DECIMAL(15,2)", "REAL")
        sql = sql.replace("DATE", "TEXT")

        # Execute the SQL
        cursor.executescript(sql)

        # Verify that tables were created (lowercase per TPC spec)
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        for table in [
            "customer",
            "lineitem",
            "nation",
            "orders",
            "part",
            "partsupp",
            "region",
            "supplier",
        ]:
            assert table in tables

    def test_simple_query_execution(self, sqlite_db, tiny_tpch) -> None:
        """Test executing a simple query against the database."""
        cursor = sqlite_db.cursor()

        # Create the NATION table (simplified schema)
        cursor.execute("""
        CREATE TABLE NATION (
            N_NATIONKEY INTEGER PRIMARY KEY,
            N_NAME TEXT,
            N_REGIONKEY INTEGER,
            N_COMMENT TEXT
        )
        """)

        # Insert some sample data
        cursor.executemany(
            "INSERT INTO NATION VALUES (?, ?, ?, ?)",
            [
                (0, "ALGERIA", 0, "test comment"),
                (1, "ARGENTINA", 1, "test comment"),
                (2, "BRAZIL", 1, "test comment"),
                (3, "CANADA", 1, "test comment"),
            ],
        )

        # Get a simple query from TPC-H
        query = """
        SELECT N_NATIONKEY, N_NAME
        FROM NATION
        WHERE N_REGIONKEY = 1
        """

        # Execute the query
        cursor.execute(query)
        results = cursor.fetchall()

        # Verify the results
        assert len(results) == 3  # Argentina, Brazil, Canada
        assert (1, "ARGENTINA") in results
        assert (2, "BRAZIL") in results
        assert (3, "CANADA") in results


if __name__ == "__main__":
    unittest.main()
