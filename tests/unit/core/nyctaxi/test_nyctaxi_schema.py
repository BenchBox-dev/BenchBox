"""Tests for NYC Taxi schema module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.nyctaxi.schema import (
    NYC_TAXI_SCHEMA,
    TABLE_ORDER,
    get_create_tables_sql,
    get_table_columns,
    get_trips_columns,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSchemaDefinition:
    """Tests for NYC Taxi schema definition."""

    def test_schema_has_required_tables(self):
        """Schema should define trips and taxi_zones tables (plus multi-type tables)."""
        required_tables = {"trips", "taxi_zones", "green_trips", "hvfhv_trips"}
        assert required_tables.issubset(set(NYC_TAXI_SCHEMA.keys()))

    def test_table_order_matches_schema(self):
        """TABLE_ORDER should contain all schema tables."""
        assert set(TABLE_ORDER) == set(NYC_TAXI_SCHEMA.keys())

    def test_table_order_has_zones_first(self):
        """Taxi zones should be first (dimension table)."""
        assert TABLE_ORDER[0] == "taxi_zones"

    def test_trips_table_schema(self):
        """Trips table should have all required columns."""
        columns = NYC_TAXI_SCHEMA["trips"]["columns"]
        required_columns = {
            "trip_id",
            "vendor_id",
            "pickup_datetime",
            "dropoff_datetime",
            "passenger_count",
            "trip_distance",
            "pickup_location_id",
            "dropoff_location_id",
            "fare_amount",
            "tip_amount",
            "total_amount",
        }
        assert required_columns.issubset(set(columns.keys()))

    def test_taxi_zones_table_schema(self):
        """Taxi zones table should have zone metadata columns."""
        columns = NYC_TAXI_SCHEMA["taxi_zones"]["columns"]
        expected_columns = {"location_id", "borough", "zone", "service_zone"}
        assert set(columns.keys()) == expected_columns

    def test_trips_table_has_primary_key(self):
        """Trips table should have primary key defined."""
        assert "primary_key" in NYC_TAXI_SCHEMA["trips"]
        assert NYC_TAXI_SCHEMA["trips"]["primary_key"] == ["trip_id"]

    def test_taxi_zones_has_primary_key(self):
        """Taxi zones should have primary key on location_id."""
        assert "primary_key" in NYC_TAXI_SCHEMA["taxi_zones"]
        assert NYC_TAXI_SCHEMA["taxi_zones"]["primary_key"] == ["location_id"]


class TestGetTableColumns:
    """Tests for get_table_columns function."""

    def test_returns_column_names(self):
        """Should return list of column names for a table."""
        columns = get_table_columns("trips")
        assert "trip_id" in columns
        assert "pickup_datetime" in columns
        assert "total_amount" in columns

    def test_raises_for_unknown_table(self):
        """Should raise ValueError for unknown table."""
        with pytest.raises(ValueError, match="Unknown table"):
            get_table_columns("unknown_table")

    def test_all_tables_have_columns(self):
        """All tables should have at least one column."""
        for table_name in TABLE_ORDER:
            columns = get_table_columns(table_name)
            assert len(columns) > 0


class TestGetTripsColumns:
    """Tests for get_trips_columns function."""

    def test_excludes_trip_id(self):
        """Should exclude trip_id (auto-generated)."""
        columns = get_trips_columns()
        assert "trip_id" not in columns

    def test_includes_data_columns(self):
        """Should include data columns."""
        columns = get_trips_columns()
        assert "vendor_id" in columns
        assert "pickup_datetime" in columns
        assert "total_amount" in columns


class TestGetCreateTablesSql:
    """Tests for get_create_tables_sql function."""

    def test_generates_standard_sql(self):
        """Should generate valid SQL for Yellow+zones tables (default, no taxi_types)."""
        sql = get_create_tables_sql(dialect="standard")
        assert isinstance(sql, str)
        assert len(sql) > 0
        # Default creates taxi_zones + trips (Yellow only)
        assert "CREATE TABLE taxi_zones" in sql
        assert "CREATE TABLE trips" in sql

    def test_includes_primary_key_constraints(self):
        """Should include PRIMARY KEY constraints by default."""
        sql = get_create_tables_sql(dialect="standard", include_constraints=True)
        assert "PRIMARY KEY" in sql

    def test_excludes_constraints_when_disabled(self):
        """Should not include PRIMARY KEY when disabled."""
        sql = get_create_tables_sql(dialect="standard", include_constraints=False)
        assert "PRIMARY KEY" not in sql

    def test_generates_duckdb_sql(self):
        """Should generate DuckDB-compatible SQL."""
        sql = get_create_tables_sql(dialect="duckdb")
        assert "CREATE TABLE" in sql

    def test_generates_clickhouse_sql(self):
        """Should generate ClickHouse-compatible SQL."""
        sql = get_create_tables_sql(dialect="clickhouse")
        assert "ENGINE = MergeTree()" in sql
        assert "ORDER BY" in sql

    def test_generates_postgres_sql(self):
        """Should generate PostgreSQL-compatible SQL."""
        sql = get_create_tables_sql(dialect="postgres")
        assert "CREATE TABLE" in sql
        assert "TIMESTAMPTZ" in sql

    def test_clickhouse_with_partitioning(self):
        """Should add partitioning for ClickHouse."""
        sql = get_create_tables_sql(dialect="clickhouse", time_partitioning=True)
        assert "PARTITION BY" in sql

    def test_sql_order_is_correct(self):
        """Tables should be created in correct order (zones first)."""
        sql = get_create_tables_sql(dialect="standard")
        zones_pos = sql.find("CREATE TABLE taxi_zones")
        trips_pos = sql.find("CREATE TABLE trips")
        assert zones_pos < trips_pos


class TestTypeMapping:
    """Tests for dialect-specific type mapping."""

    def test_clickhouse_type_mapping(self):
        """ClickHouse should use specific types."""
        sql = get_create_tables_sql(dialect="clickhouse")
        assert "DateTime64(3)" in sql
        assert "Int64" in sql or "Int32" in sql
        assert "Float64" in sql

    def test_duckdb_type_mapping(self):
        """DuckDB should use standard types."""
        sql = get_create_tables_sql(dialect="duckdb")
        assert "TIMESTAMP" in sql
        assert "BIGINT" in sql
        assert "DOUBLE" in sql

    def test_postgres_type_mapping(self):
        """PostgreSQL should use PostgreSQL types."""
        sql = get_create_tables_sql(dialect="postgres")
        assert "TIMESTAMPTZ" in sql
        assert "DOUBLE PRECISION" in sql
