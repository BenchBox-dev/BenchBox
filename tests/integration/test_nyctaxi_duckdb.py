"""Integration tests for NYC Taxi OLAP benchmark with DuckDB.

This module tests the NYC Taxi implementation with a real DuckDB database,
focusing on data generation (synthetic), schema creation, and query execution.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import duckdb
import pytest

from benchbox import NYCTaxi

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


@pytest.mark.duckdb
@pytest.mark.nyctaxi
class TestNYCTaxiDuckDBIntegration:
    """Integration tests for NYC Taxi OLAP benchmark with DuckDB."""

    @pytest.fixture
    def nyctaxi(self, temp_dir):
        """Create a tiny NYC Taxi instance for testing (synthetic data)."""
        # Use a very small scale factor for quick testing
        # SF=0.01 generates ~300K trips synthetic data
        return NYCTaxi(
            scale_factor=0.01,
            output_dir=temp_dir,
            year=2019,
            months=[1],  # Just January for quick testing
        )

    @pytest.fixture
    def duckdb_conn(self):
        """Create a temporary DuckDB database."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_benchmark_instantiation(self, nyctaxi):
        """Test that NYC Taxi benchmark can be instantiated."""
        assert nyctaxi.scale_factor == 0.01
        assert nyctaxi.year == 2019
        assert nyctaxi._impl is not None

    def test_benchmark_info(self, nyctaxi):
        """Test that benchmark info provides comprehensive metadata."""
        info = nyctaxi.get_benchmark_info()

        # Check required fields
        assert "name" in info
        assert "description" in info
        assert "scale_factor" in info
        assert "year" in info
        assert "num_queries" in info
        assert "query_categories" in info
        assert "tables" in info

        # Check values
        assert info["name"] == "NYC Taxi OLAP"
        assert info["scale_factor"] == 0.01
        assert info["year"] == 2019
        assert info["num_queries"] == 25
        assert "temporal" in info["query_categories"]
        assert "geographic" in info["query_categories"]

    def test_get_queries(self, nyctaxi):
        """Test that all queries can be retrieved."""
        queries = nyctaxi.get_queries()

        # Should have 25 queries
        assert len(queries) == 25

        # Each query should be a non-empty SQL string
        for query_id, query_text in queries.items():
            assert isinstance(query_text, str), f"Query {query_id} should be a string"
            assert len(query_text.strip()) > 0, f"Query {query_id} should not be empty"
            assert "SELECT" in query_text.upper(), f"Query {query_id} should be a SELECT statement"

    def test_get_query_by_id(self, nyctaxi):
        """Test retrieving individual queries."""
        # Test a known query ID
        query = nyctaxi.get_query("trips-per-hour")
        assert isinstance(query, str)
        assert "SELECT" in query.upper()
        assert "trips" in query.lower()

    def test_get_queries_by_category(self, nyctaxi):
        """Test filtering queries by category."""
        # Test temporal category
        temporal_queries = nyctaxi.get_queries_by_category("temporal")
        assert len(temporal_queries) > 0
        assert all(isinstance(q, str) for q in temporal_queries)

        # Test geographic category
        geographic_queries = nyctaxi.get_queries_by_category("geographic")
        assert len(geographic_queries) > 0

        # Test financial category
        financial_queries = nyctaxi.get_queries_by_category("financial")
        assert len(financial_queries) > 0

    def test_query_info(self, nyctaxi):
        """Test that query metadata is available."""
        info = nyctaxi.get_query_info("trips-per-hour")

        assert "name" in info
        assert "category" in info
        assert "description" in info or "query" in info

    def test_schema_creation(self, nyctaxi, duckdb_conn):
        """Test that schema can be created in DuckDB."""
        # Get schema SQL
        sql = nyctaxi.get_create_tables_sql(dialect="duckdb")

        # Execute schema creation
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

        table_names = [row[0].lower() for row in tables_result]

        # NYC Taxi should have taxi_zones and trips tables
        assert "taxi_zones" in table_names, "taxi_zones table should exist"
        assert "trips" in table_names, "trips table should exist"

    def test_schema_columns(self, nyctaxi):
        """Test that schema has correct column definitions."""
        schema = nyctaxi.get_schema()

        # Check taxi_zones table
        assert "taxi_zones" in schema
        zones_columns = schema["taxi_zones"]["columns"]
        assert "location_id" in zones_columns
        assert "borough" in zones_columns
        assert "zone" in zones_columns
        assert "service_zone" in zones_columns

        # Check trips table
        assert "trips" in schema
        trips_columns = schema["trips"]["columns"]
        assert "pickup_datetime" in trips_columns
        assert "dropoff_datetime" in trips_columns
        assert "pickup_location_id" in trips_columns
        assert "dropoff_location_id" in trips_columns
        assert "fare_amount" in trips_columns
        assert "tip_amount" in trips_columns

    def test_query_sql_syntax_validity(self, nyctaxi):
        """Test that all queries have valid SQL syntax."""
        queries = nyctaxi.get_queries()

        for query_id, query_text in queries.items():
            # Basic SQL syntax checks
            upper_sql = query_text.upper()
            assert "SELECT" in upper_sql, f"Query {query_id} should have SELECT"
            assert "FROM" in upper_sql, f"Query {query_id} should have FROM"

            # Should be well-formed (basic check)
            assert query_text.count("(") == query_text.count(")"), f"Query {query_id} should have balanced parentheses"

    def test_year_validation(self, temp_dir):
        """Test that invalid years are rejected."""
        with pytest.raises(ValueError, match="year must be in"):
            NYCTaxi(scale_factor=0.01, output_dir=temp_dir, year=2010)

        with pytest.raises(ValueError, match="year must be in"):
            NYCTaxi(scale_factor=0.01, output_dir=temp_dir, year=2030)

    def test_scale_factor_validation(self, temp_dir):
        """Test that invalid scale factors are rejected."""
        with pytest.raises(ValueError, match="Scale factor must be positive"):
            NYCTaxi(scale_factor=0, output_dir=temp_dir)

        with pytest.raises(ValueError, match="Scale factor must be positive"):
            NYCTaxi(scale_factor=-1.0, output_dir=temp_dir)

    def test_download_stats(self, nyctaxi):
        """Test that download stats are available."""
        stats = nyctaxi.get_download_stats()

        assert "scale_factor" in stats
        assert stats["scale_factor"] == 0.01


@pytest.mark.integration
@pytest.mark.duckdb
@pytest.mark.nyctaxi
@pytest.mark.slow
class TestNYCTaxiDataGeneration:
    """Integration tests for NYC Taxi data generation (slower tests)."""

    @pytest.fixture
    def nyctaxi_with_data(self, temp_dir):
        """Create NYC Taxi instance and generate synthetic data."""
        benchmark = NYCTaxi(
            scale_factor=0.01,
            output_dir=temp_dir,
            year=2019,
            months=[1],
        )
        # Generate synthetic data (will use fallback since no network)
        benchmark.generate_data()
        return benchmark

    def test_data_generation_creates_files(self, nyctaxi_with_data):
        """Test that data generation creates expected files."""
        tables = nyctaxi_with_data.tables

        assert "taxi_zones" in tables
        assert "trips" in tables

        # Files should exist
        for table_name, file_path in tables.items():
            assert file_path.exists(), f"{table_name} data file should exist"
            assert file_path.stat().st_size > 0, f"{table_name} data file should not be empty"

    def test_taxi_zones_data_complete(self, nyctaxi_with_data):
        """Test that taxi zones data contains all 265 zones."""
        import csv

        zones_file = nyctaxi_with_data.tables["taxi_zones"]

        with open(zones_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            rows = list(reader)

        # NYC TLC has 265 taxi zones
        assert len(rows) == 265, f"Should have 265 taxi zones, got {len(rows)}"

        # Check some known zones exist
        zone_ids = {int(row[0]) for row in rows}
        assert 1 in zone_ids  # EWR
        assert 138 in zone_ids  # Lenox Hill East
        assert 265 in zone_ids  # Unknown

    def test_trips_data_structure(self, nyctaxi_with_data):
        """Test that trips data has correct structure."""
        import csv

        trips_file = nyctaxi_with_data.tables["trips"]

        with open(trips_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)

            # Should have expected columns
            expected_columns = [
                "pickup_datetime",
                "dropoff_datetime",
                "pickup_location_id",
                "dropoff_location_id",
                "trip_distance",
                "passenger_count",
                "fare_amount",
                "tip_amount",
                "total_amount",
            ]

            for col in expected_columns:
                assert col in header, f"Column {col} should be in trips header"

            # Sample a few rows to verify data types
            for i, row in enumerate(reader):
                if i >= 10:
                    break

                # Location IDs should be integers
                pickup_id = int(row[header.index("pickup_location_id")])
                dropoff_id = int(row[header.index("dropoff_location_id")])
                assert 0 < pickup_id <= 265
                assert 0 < dropoff_id <= 265

                # Amounts should be numeric. Real NYC TLC trip data
                # includes negative fare_amount values (refunds and
                # adjustments), so assert numeric-ness only.
                float(row[header.index("fare_amount")])
