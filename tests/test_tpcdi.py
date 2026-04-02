"""Tests for TPC-DI (Data Integration) Benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import duckdb
import pytest

pytest.importorskip("pandas")

from benchbox import TPCDI
from benchbox.core.tpcdi.benchmark import TPCDIBenchmark

pytestmark = [
    pytest.mark.medium,
]


class TestTPCDI:
    """Test the TPC-DI (Data Integration) Benchmark implementation."""

    @pytest.fixture
    def tpcdi(self, small_scale_factor: float, temp_dir: Path) -> TPCDI:
        """Create a TPC-DI instance for testing."""
        return TPCDI(scale_factor=small_scale_factor, output_dir=temp_dir)

    def test_generate_data(self, tpcdi: TPCDI) -> None:
        """Test that data generation produces expected files."""
        data_paths = tpcdi.generate_data()

        # Check that output includes expected files (returns list per base class)
        # Phase 1 implementation includes 7 core tables + 9 extended tables = 16 total

        expected_total_tables = 16  # 7 core + 9 extended

        assert isinstance(data_paths, list), "generate_data should return a list per BaseBenchmark interface"
        assert len(data_paths) == expected_total_tables, (
            f"Expected {expected_total_tables} files (7 core + 9 extended), got {len(data_paths)}"
        )

        # Verify files exist
        for path in data_paths:
            assert Path(path).exists(), f"Generated file {path} does not exist"

    def test_get_queries(self, tpcdi: TPCDI) -> None:
        """Test that all TPC-DI queries can be retrieved."""
        queries = tpcdi.get_queries()

        # TPC-DI has validation and analytical queries
        assert isinstance(queries, dict), "get_queries should return a dictionary"
        assert len(queries) >= 4, "Should have multiple queries"

        # Check that queries are non-empty strings
        for query_id, query_text in queries.items():
            assert isinstance(query_id, str), "Query IDs should be strings for TPC-DI"
            assert isinstance(query_text, str), "Query text should be a string"
            assert len(query_text.strip()) > 0, "Query text should not be empty"

        # Test that we can get individual queries
        if len(queries) > 0:
            first_query_id = next(iter(queries.keys()))
            individual_query = tpcdi.get_query(first_query_id)
            assert isinstance(individual_query, str), "Individual query should be a string"
            assert len(individual_query.strip()) > 0, "Individual query should not be empty"

        for query_id, query_sql in queries.items():
            assert isinstance(query_sql, str)
            assert query_sql.strip()

            # Check that queries contain expected SQL elements
            query_upper = query_sql.upper()
            assert "SELECT" in query_upper
            assert "FROM" in query_upper

            # Validation queries should check data quality
            if query_id.startswith("V"):
                # Should contain data validation patterns
                validation_keywords = ["COUNT", "WHERE", "NULL", "DISTINCT"]
                has_validation = any(kw in query_upper for kw in validation_keywords)
                assert has_validation, f"Validation query {query_id} should contain validation patterns"

            # Analytical queries should perform business intelligence
            elif query_id.startswith("A"):
                # Should contain analytical patterns
                analytical_keywords = ["GROUP BY", "ORDER BY", "SUM", "COUNT", "AVG"]
                has_analytics = any(kw in query_upper for kw in analytical_keywords)
                assert has_analytics, f"Analytical query {query_id} should contain analytical patterns"

    def test_get_query(self, tpcdi: TPCDI) -> None:
        """Test retrieving a specific query."""
        queries = tpcdi.get_queries()
        first_query_id = list(queries.keys())[0]

        query = tpcdi.get_query(first_query_id)
        assert isinstance(query, str)
        assert "SELECT" in query.upper()
        assert "FROM" in query.upper()

        # Test a validation query if available
        validation_queries = [q for q in queries if q.startswith("V")]
        if validation_queries:
            val_query = tpcdi.get_query(validation_queries[0])
            assert isinstance(val_query, str)
            assert "SELECT" in val_query.upper()

    def test_translate_query(self, tpcdi: TPCDI, sql_dialect: str) -> None:
        """Test translating a query to different SQL dialects."""
        queries = tpcdi.get_queries()
        first_query_id = list(queries.keys())[0]

        tpcdi.get_query(first_query_id)
        translated_query = tpcdi.translate_query(first_query_id, dialect=sql_dialect)

        assert isinstance(translated_query, str)
        assert "SELECT" in translated_query.upper()

    def test_invalid_query_id(self, tpcdi: TPCDI) -> None:
        """Test that requesting an invalid query raises an exception."""
        with pytest.raises(ValueError):
            tpcdi.get_query("X999")  # Non-existent query

    def test_get_query_with_params(self, tpcdi: TPCDI) -> None:
        """Test that parameterized queries can be retrieved."""
        queries = tpcdi.get_queries()
        first_query_id = list(queries.keys())[0]

        # Test with default parameters
        param_query = tpcdi.get_query(first_query_id)
        assert isinstance(param_query, str)
        assert "SELECT" in param_query.upper()

        # Test with custom parameters for analytical queries
        analytical_queries = [q for q in queries if q.startswith("A")]
        if analytical_queries:
            custom_params = {"min_trades": 100, "start_date": "2023-01-01"}
            param_query = tpcdi.get_query(analytical_queries[0], params=custom_params)
            assert isinstance(param_query, str)
            assert "SELECT" in param_query.upper()

    def test_get_schema(self, tpcdi: TPCDI) -> None:
        """Test retrieving the TPC-DI schema."""
        schema = tpcdi.get_schema()

        # Check that schema is a dictionary and all tables are present
        assert isinstance(schema, dict), "Schema should be a dictionary"
        expected_tables = [
            "DimCustomer",
            "DimAccount",
            "DimSecurity",
            "DimCompany",
            "FactTrade",
            "DimDate",
            "DimTime",
        ]

        for table in expected_tables:
            assert table in schema, f"Table {table} not found in schema"

        # Check dimension table structure (DimCustomer)
        dimcustomer_table = schema["DimCustomer"]
        customer_columns = [col["name"] for col in dimcustomer_table["columns"]]
        expected_customer_columns = [
            "SK_CustomerID",
            "CustomerID",
            "TaxID",
            "Status",
            "LastName",
            "FirstName",
            "MiddleInitial",
            "Gender",
            "Tier",
            "DOB",
            "AddressLine1",
            "AddressLine2",
            "PostalCode",
            "City",
            "StateProv",
            "Country",
            "Phone1",
            "Phone2",
            "Phone3",
            "Email1",
            "Email2",
            "EffectiveDate",
            "EndDate",
            "IsCurrent",
        ]

        for column in expected_customer_columns:
            assert column in customer_columns

        # Check fact table structure (FactTrade)
        facttrade_table = schema["FactTrade"]
        trade_columns = [col["name"] for col in facttrade_table["columns"]]
        expected_trade_columns = [
            "TradeID",
            "SK_BrokerID",
            "SK_CreateDateID",
            "SK_CreateTimeID",
            "SK_CloseDateID",
            "SK_CloseTimeID",
            "Status",
            "Type",
            "CashFlag",
            "SK_SecurityID",
            "SK_CompanyID",
            "Quantity",
            "BidPrice",
            "SK_CustomerID",
            "SK_AccountID",
            "ExecutedBy",
            "TradePrice",
            "Fee",
            "Commission",
            "Tax",
        ]

        for column in expected_trade_columns:
            assert column in trade_columns

    def test_get_create_tables_sql(self, tpcdi: TPCDI) -> None:
        """Test retrieving SQL to create TPC-DI tables."""
        sql = tpcdi.get_create_tables_sql()

        assert isinstance(sql, str)
        assert "CREATE TABLE" in sql

        # Check for all tables (using proper case names)
        # Phase 1 includes 7 core tables + 9 extended tables = 16 total
        expected_core_tables = [
            "DimCustomer",
            "DimAccount",
            "DimSecurity",
            "DimCompany",
            "FactTrade",
            "DimDate",
            "DimTime",
        ]

        expected_extended_tables = [
            "DimBroker",
            "FactCashBalances",
            "FactHoldings",
            "FactMarketHistory",
            "FactWatches",
            "Industry",
            "StatusType",
            "TaxRate",
            "TradeType",
        ]

        all_expected_tables = expected_core_tables + expected_extended_tables

        for table in all_expected_tables:
            assert f"CREATE TABLE IF NOT EXISTS {table}" in sql

    def test_tpcdi_properties(self, tpcdi: TPCDI) -> None:
        """Test TPC-DI-specific properties."""
        # Test that TPC-DI Phase 1 has 16 tables (7 core + 9 extended)
        schema = tpcdi.get_schema()
        assert len(schema) == 16, f"Expected 16 tables (Phase 1), got {len(schema)}"

        # Test dimension vs fact table classification
        table_names = list(schema.keys())
        dimension_tables = [t for t in table_names if t.startswith("Dim")]
        fact_tables = [t for t in table_names if t.startswith("Fact")]
        reference_tables = [t for t in table_names if not (t.startswith(("Dim", "Fact")))]

        assert len(dimension_tables) == 7, f"Should have 7 dimension tables, got {len(dimension_tables)}"
        assert len(fact_tables) == 5, f"Should have 5 fact tables, got {len(fact_tables)}"
        assert len(reference_tables) == 4, f"Should have 4 reference tables, got {len(reference_tables)}"

        # Test that queries are split between validation and analytical
        queries = tpcdi.get_queries()
        validation_queries = [q for q in queries if q.startswith("V")]
        analytical_queries = [q for q in queries if q.startswith("A")]

        assert len(validation_queries) >= 1, "Should have validation queries"
        assert len(analytical_queries) >= 1, "Should have analytical queries"

    def test_data_warehouse_focus(self, tpcdi: TPCDI) -> None:
        """Test that the TPC-DI benchmark focuses on data warehousing scenarios."""
        schema = tpcdi.get_schema()

        # Should have dimensional modeling characteristics
        table_names = list(schema.keys())
        dimension_tables = [t for t in table_names if t.startswith("Dim")]
        fact_tables = [t for t in table_names if t.startswith("Fact")]

        assert len(dimension_tables) >= 4, "Should have multiple dimension tables"
        assert len(fact_tables) >= 1, "Should have fact tables"

        # Check for slowly changing dimension characteristics
        dimcustomer_table = schema["DimCustomer"]
        customer_columns = [col["name"] for col in dimcustomer_table["columns"]]

        scd_columns = ["EffectiveDate", "EndDate", "IsCurrent"]
        for col in scd_columns:
            assert col in customer_columns, f"SCD column {col} not found in DimCustomer"

    def test_financial_services_domain(self, tpcdi: TPCDI) -> None:
        """Test that the TPC-DI benchmark represents a financial services domain."""
        schema = tpcdi.get_schema()

        # Should have financial-specific tables
        table_names = list(schema.keys())
        financial_tables = ["DimAccount", "DimSecurity", "DimCompany", "FactTrade"]

        for table in financial_tables:
            assert table in table_names, f"Financial table {table} not found"

        # Check for financial-specific columns
        facttrade_table = schema["FactTrade"]
        trade_columns = [col["name"] for col in facttrade_table["columns"]]

        financial_columns = ["TradePrice", "Fee", "Commission", "Tax", "BidPrice"]
        for col in financial_columns:
            assert col in trade_columns, f"Financial column {col} not found"

    def test_etl_validation_queries(self, tpcdi: TPCDI) -> None:
        """Test that validation queries focus on ETL data quality."""
        queries = tpcdi.get_queries()
        validation_queries = {k: v for k, v in queries.items() if k.startswith("V")}

        assert len(validation_queries) >= 1, "Should have validation queries"

        for query_id, query_sql in validation_queries.items():
            query_upper = query_sql.upper()

            # Validation queries should check data quality aspects
            quality_keywords = ["COUNT", "NULL", "DISTINCT", "WHERE"]
            has_quality_check = any(kw in query_upper for kw in quality_keywords)
            assert has_quality_check, f"Validation query {query_id} should check data quality"

    def test_business_intelligence_queries(self, tpcdi: TPCDI) -> None:
        """Test that analytical queries provide business intelligence."""
        queries = tpcdi.get_queries()
        analytical_queries = {k: v for k, v in queries.items() if k.startswith("A")}

        assert len(analytical_queries) >= 1, "Should have analytical queries"

        for query_id, query_sql in analytical_queries.items():
            query_upper = query_sql.upper()

            # Analytical queries should perform business analysis
            analysis_keywords = ["GROUP BY", "SUM", "COUNT", "AVG", "ORDER BY"]
            has_analysis = any(kw in query_upper for kw in analysis_keywords)
            assert has_analysis, f"Analytical query {query_id} should perform business analysis"


class TestTPCDIBenchmarkCoverage:
    """Test TPCDIBenchmark class for better coverage of key methods."""

    @pytest.fixture
    def tpcdi_benchmark(self, small_scale_factor: float, temp_dir: Path) -> TPCDIBenchmark:
        """Create a TPCDIBenchmark instance for testing."""
        return TPCDIBenchmark(scale_factor=small_scale_factor, output_dir=temp_dir)

    def test_execute_query_coverage(self, tpcdi_benchmark: TPCDIBenchmark) -> None:
        """Test execute_query method variations with DuckDB."""
        # Create DuckDB connection with test data matching TPC-DI schema
        connection = duckdb.connect(":memory:")
        connection.execute("""
            CREATE TABLE DimCustomer (
                CustomerID INTEGER,
                EffectiveDate DATE,
                CustomerName VARCHAR(100),
                Status VARCHAR(10),
                IsCurrent INTEGER DEFAULT 1
            )
        """)
        connection.execute("""
            INSERT INTO DimCustomer VALUES
            (1, '2023-01-01', 'Customer1', 'Active', 1),
            (2, '2023-01-02', 'Customer2', 'Active', 1)
        """)

        # Test actual query execution
        result = tpcdi_benchmark.execute_query("V1", connection)

        # Result should be a list of tuples
        assert isinstance(result, list)
        assert len(result) > 0

        connection.close()

    @pytest.mark.slow
    def test_load_data_to_database_coverage(self, tpcdi_benchmark: TPCDIBenchmark) -> None:
        """Test load_data_to_database with real DuckDB data."""
        # Generate actual test data first
        tpcdi_benchmark.generate_data()

        # Create DuckDB connection
        connection = duckdb.connect(":memory:")

        try:
            # Test data loading
            tpcdi_benchmark.load_data_to_database(connection)

            # Verify tables were created and populated
            tables_result = connection.execute("""
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'main'
            """).fetchall()

            table_names = [row[0] for row in tables_result]
            assert "DimCustomer" in table_names or "dimcustomer" in table_names

            # Test that at least one table has data
            if "DimCustomer" in table_names:
                count = connection.execute("SELECT COUNT(*) FROM DimCustomer").fetchone()[0]
            else:
                count = connection.execute("SELECT COUNT(*) FROM dimcustomer").fetchone()[0]
            assert count > 0

        finally:
            connection.close()

    @pytest.mark.slow
    def test_run_benchmark_coverage(self, tpcdi_benchmark: TPCDIBenchmark) -> None:
        """Test run_benchmark with real DuckDB execution."""
        # Generate test data and set up database
        tpcdi_benchmark.generate_data()

        connection = duckdb.connect(":memory:")

        try:
            # Load data into database
            tpcdi_benchmark.load_data_to_database(connection)

            # Run benchmark with limited queries for testing
            result = tpcdi_benchmark.run_benchmark(connection, iterations=1)

            assert result["benchmark"] == "TPC-DI"
            assert "queries" in result
            assert isinstance(result["queries"], dict)

        finally:
            connection.close()

    def test_error_handling_paths(self, tpcdi_benchmark: TPCDIBenchmark) -> None:
        """Test error handling in key methods."""
        # Test load_data_to_database without data
        connection = duckdb.connect(":memory:")

        try:
            with pytest.raises(ValueError, match="No data generated"):
                tpcdi_benchmark.load_data_to_database(connection)
        finally:
            connection.close()

        # Test invalid query execution
        connection = duckdb.connect(":memory:")

        try:
            # This should fail because the table doesn't exist
            with pytest.raises(Exception):  # DuckDB will raise a catalog error
                tpcdi_benchmark.execute_query("V1", connection)
        finally:
            connection.close()
