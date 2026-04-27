"""NYC Taxi OLAP benchmark schema definition.

Defines the schema for NYC TLC trip data:
- trips: Yellow Taxi (TPEP) fact table
- green_trips: Green Taxi (LPEP) fact table
- hvfhv_trips: High Volume For-Hire Vehicle (Uber/Lyft) fact table
- taxi_zones: Dimension table for location lookups

Architecture: Separate tables per taxi type (Option A).
  - Each table matches its source schema exactly (no NULLable columns)
  - Existing Yellow Taxi queries against `trips` are untouched
  - Cross-type analytics use UNION ALL on common columns

Based on NYC Taxi & Limousine Commission data dictionaries:
https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf
https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_green.pdf
https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_hvfhs.pdf

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from enum import Enum
from typing import Any

from benchbox.sql_compat.local_exemptions import compat_local


class TaxiType(Enum):
    """NYC TLC taxi/FHV data types."""

    YELLOW = "yellow"
    GREEN = "green"
    HVFHV = "hvfhv"


# Schema definition with column specifications
NYC_TAXI_SCHEMA = {
    "trips": {
        "description": "NYC taxi trip records (Yellow and Green taxi data)",
        "columns": {
            "trip_id": {"type": "BIGINT", "description": "Unique trip identifier"},
            "vendor_id": {"type": "INTEGER", "description": "TPEP/LPEP provider (1=CMT, 2=VTS)"},
            "pickup_datetime": {"type": "TIMESTAMP", "description": "Meter engaged timestamp"},
            "dropoff_datetime": {"type": "TIMESTAMP", "description": "Meter disengaged timestamp"},
            "passenger_count": {"type": "DOUBLE", "description": "Number of passengers (stored as float in TLC CSV)"},
            "trip_distance": {"type": "DOUBLE", "description": "Trip distance in miles"},
            "pickup_location_id": {"type": "INTEGER", "description": "TLC Taxi Zone for pickup"},
            "dropoff_location_id": {"type": "INTEGER", "description": "TLC Taxi Zone for dropoff"},
            "rate_code_id": {
                "type": "DOUBLE",
                "description": "Rate code (1=Standard, 2=JFK, etc.) - stored as float in TLC CSV",
            },
            "store_and_fwd_flag": {"type": "VARCHAR(1)", "description": "Store and forward flag (Y/N)"},
            "payment_type": {"type": "INTEGER", "description": "Payment type (1=Credit, 2=Cash, etc.)"},
            "fare_amount": {"type": "DOUBLE", "description": "Time-and-distance fare"},
            "extra": {"type": "DOUBLE", "description": "Extra charges (rush hour, overnight)"},
            "mta_tax": {"type": "DOUBLE", "description": "MTA tax ($0.50)"},
            "tip_amount": {"type": "DOUBLE", "description": "Tip amount (credit card only)"},
            "tolls_amount": {"type": "DOUBLE", "description": "Total tolls paid"},
            "improvement_surcharge": {"type": "DOUBLE", "description": "Improvement surcharge ($0.30)"},
            "congestion_surcharge": {"type": "DOUBLE", "description": "Congestion surcharge"},
            "airport_fee": {"type": "DOUBLE", "description": "Airport fee"},
            "total_amount": {"type": "DOUBLE", "description": "Total trip amount"},
        },
        "primary_key": ["trip_id"],
        "partition_by": "pickup_datetime",
        "order_by": ["pickup_datetime", "pickup_location_id"],
        "indexes": ["pickup_datetime", "pickup_location_id", "dropoff_location_id"],
    },
    "taxi_zones": {
        "description": "NYC TLC taxi zone lookup table",
        "columns": {
            "location_id": {"type": "INTEGER", "description": "Unique zone identifier"},
            "borough": {"type": "VARCHAR(64)", "description": "NYC borough name"},
            "zone": {"type": "VARCHAR(128)", "description": "Zone name"},
            "service_zone": {"type": "VARCHAR(64)", "description": "Service zone (Boro Zone, Yellow Zone, Airports)"},
        },
        "primary_key": ["location_id"],
    },
    "green_trips": {
        "description": "NYC Green Taxi (LPEP) trip records - outer-borough street hail",
        "columns": {
            "trip_id": {"type": "BIGINT", "description": "Unique trip identifier"},
            "vendor_id": {"type": "INTEGER", "description": "LPEP provider (1=CMT, 2=VTS)"},
            "pickup_datetime": {"type": "TIMESTAMP", "description": "Meter engaged timestamp"},
            "dropoff_datetime": {"type": "TIMESTAMP", "description": "Meter disengaged timestamp"},
            "store_and_fwd_flag": {"type": "VARCHAR(1)", "description": "Store and forward flag (Y/N)"},
            "rate_code_id": {
                "type": "DOUBLE",
                "description": "Rate code (1=Standard, 2=JFK, etc.) - stored as float in TLC CSV",
            },
            "pickup_location_id": {"type": "INTEGER", "description": "TLC Taxi Zone for pickup"},
            "dropoff_location_id": {"type": "INTEGER", "description": "TLC Taxi Zone for dropoff"},
            "passenger_count": {"type": "DOUBLE", "description": "Number of passengers (stored as float in TLC CSV)"},
            "trip_distance": {"type": "DOUBLE", "description": "Trip distance in miles"},
            "fare_amount": {"type": "DOUBLE", "description": "Time-and-distance fare"},
            "extra": {"type": "DOUBLE", "description": "Extra charges"},
            "mta_tax": {"type": "DOUBLE", "description": "MTA tax ($0.50)"},
            "tip_amount": {"type": "DOUBLE", "description": "Tip amount"},
            "tolls_amount": {"type": "DOUBLE", "description": "Total tolls paid"},
            "ehail_fee": {"type": "DOUBLE", "description": "eHail fee (Green Taxi only)"},
            "improvement_surcharge": {"type": "DOUBLE", "description": "Improvement surcharge ($0.30)"},
            "total_amount": {"type": "DOUBLE", "description": "Total trip amount"},
            "payment_type": {"type": "INTEGER", "description": "Payment type (1=Credit, 2=Cash, etc.)"},
            "trip_type": {"type": "INTEGER", "description": "Trip type (1=Street-hail, 2=Dispatch)"},
            "congestion_surcharge": {"type": "DOUBLE", "description": "Congestion surcharge"},
        },
        "primary_key": ["trip_id"],
        "partition_by": "pickup_datetime",
        "order_by": ["pickup_datetime", "pickup_location_id"],
        "indexes": ["pickup_datetime", "pickup_location_id", "dropoff_location_id"],
    },
    "hvfhv_trips": {
        "description": "NYC High Volume For-Hire Vehicle trips (Uber/Lyft) - available Feb 2019+",
        "columns": {
            "trip_id": {"type": "BIGINT", "description": "Unique trip identifier"},
            "hvfhs_license_num": {
                "type": "VARCHAR(8)",
                "description": "TLC license number (HV0002=Juno, HV0003=Uber, HV0004=Via, HV0005=Lyft)",
            },
            "dispatching_base_num": {
                "type": "VARCHAR(8)",
                "description": "TLC base license number that dispatched the trip",
            },
            "originating_base_num": {
                "type": "VARCHAR(8)",
                "description": "Base that received the original trip request",
            },
            "request_datetime": {"type": "TIMESTAMP", "description": "When trip was requested"},
            "on_scene_datetime": {"type": "TIMESTAMP", "description": "When driver arrived at pickup"},
            "pickup_datetime": {"type": "TIMESTAMP", "description": "Pickup timestamp"},
            "dropoff_datetime": {"type": "TIMESTAMP", "description": "Dropoff timestamp"},
            "pickup_location_id": {"type": "INTEGER", "description": "TLC Taxi Zone for pickup"},
            "dropoff_location_id": {"type": "INTEGER", "description": "TLC Taxi Zone for dropoff"},
            "trip_miles": {"type": "DOUBLE", "description": "Trip distance in miles"},
            "trip_time": {"type": "INTEGER", "description": "Trip duration in seconds"},
            "base_passenger_fare": {"type": "DOUBLE", "description": "Base passenger fare before tips/tolls/fees"},
            "tolls": {"type": "DOUBLE", "description": "Total tolls paid"},
            "bcf": {"type": "DOUBLE", "description": "Black Car Fund contribution"},
            "sales_tax": {"type": "DOUBLE", "description": "NYS sales tax"},
            "congestion_surcharge": {"type": "DOUBLE", "description": "Congestion surcharge"},
            "airport_fee": {"type": "DOUBLE", "description": "Airport fee"},
            "tips": {"type": "DOUBLE", "description": "Tip amount"},
            "driver_pay": {"type": "DOUBLE", "description": "Driver pay (before tips)"},
            "shared_request_flag": {"type": "VARCHAR(1)", "description": "Did passenger request shared ride? (Y/N)"},
            "shared_match_flag": {
                "type": "VARCHAR(1)",
                "description": "Was trip matched with another passenger? (Y/N)",
            },
            "access_a_ride_flag": {
                "type": "VARCHAR(1)",
                "description": "Was trip administered for MTA Access-a-Ride? (Y/N)",
            },
            "wav_request_flag": {
                "type": "VARCHAR(1)",
                "description": "Did passenger request wheelchair accessible vehicle? (Y/N)",
            },
            "wav_match_flag": {"type": "VARCHAR(1)", "description": "Was trip fulfilled with WAV? (Y/N)"},
        },
        "primary_key": ["trip_id"],
        "partition_by": "pickup_datetime",
        "order_by": ["pickup_datetime", "pickup_location_id"],
        "indexes": ["pickup_datetime", "pickup_location_id", "dropoff_location_id", "hvfhs_license_num"],
    },
}

# Table order for creation (dimension tables first)
TABLE_ORDER = ["taxi_zones", "trips", "green_trips", "hvfhv_trips"]

# Rate code descriptions
RATE_CODES = {
    1: "Standard rate",
    2: "JFK",
    3: "Newark",
    4: "Nassau or Westchester",
    5: "Negotiated fare",
    6: "Group ride",
}

# Payment type descriptions
PAYMENT_TYPES = {
    1: "Credit card",
    2: "Cash",
    3: "No charge",
    4: "Dispute",
    5: "Unknown",
    6: "Voided trip",
}


def get_create_tables_sql(
    dialect: str = "standard",
    include_constraints: bool = True,
    time_partitioning: bool = False,
    partition_interval: str = "1 month",
    taxi_types: list[TaxiType] | None = None,
) -> str:
    """Generate CREATE TABLE SQL statements for NYC Taxi schema.

    Args:
        dialect: SQL dialect (standard, duckdb, clickhouse, postgres, etc.)
        include_constraints: Whether to include PRIMARY KEY constraints
        time_partitioning: Whether to add time-based partitioning hints
        partition_interval: Partition interval for time-based partitioning
        taxi_types: Taxi types to include. None defaults to Yellow only (trips + taxi_zones).

    Returns:
        SQL script for creating all tables
    """
    # Determine which tables to create
    tables_to_create = ["taxi_zones", "trips"]  # always include Yellow + zones
    if taxi_types:
        for taxi_type in taxi_types:
            if taxi_type == TaxiType.GREEN:
                tables_to_create.append("green_trips")
            elif taxi_type == TaxiType.HVFHV:
                tables_to_create.append("hvfhv_trips")

    statements = []
    for table_name in TABLE_ORDER:
        if table_name not in tables_to_create:
            continue
        table_def = NYC_TAXI_SCHEMA[table_name]
        sql = _generate_create_table(
            table_name,
            table_def,
            dialect,
            include_constraints,
            time_partitioning,
            partition_interval,
        )
        statements.append(sql)

    return "\n\n".join(statements)


@compat_local(
    kind="storage_layout",
    platform_specific=True,
    reason=(
        "Emits engine-specific DDL extensions: ClickHouse MergeTree+ORDER BY, "
        "PostgreSQL/TimescaleDB PARTITION BY RANGE, DuckDB partition comment. "
        "Policy branches (clickhouse/postgres/timescale) are registered in "
        "sql_compat/rules/schema_emit/nyctaxi_ddl.py. "
        "The DuckDB comment-only branch is legitimate local rendering."
    ),
)
def _generate_create_table(
    table_name: str,
    table_def: dict[str, Any],
    dialect: str,
    include_constraints: bool,
    time_partitioning: bool,
    partition_interval: str,
) -> str:
    """Generate CREATE TABLE statement for a single table."""
    columns = []

    for col_name, col_spec in table_def["columns"].items():
        col_type = _map_type_to_dialect(col_spec["type"], dialect)
        columns.append(f"    {col_name} {col_type}")

    # Add primary key constraint
    if include_constraints and "primary_key" in table_def:
        pk_cols = ", ".join(table_def["primary_key"])
        columns.append(f"    PRIMARY KEY ({pk_cols})")

    columns_sql = ",\n".join(columns)

    # Base CREATE TABLE
    sql = f"CREATE TABLE {table_name} (\n{columns_sql}\n)"

    # Add dialect-specific extensions
    if dialect == "clickhouse":
        order_by = table_def.get("order_by", table_def.get("primary_key", []))
        order_sql = ", ".join(order_by)
        sql += f"\nENGINE = MergeTree()\nORDER BY ({order_sql})"
        if time_partitioning and "partition_by" in table_def:
            partition_col = table_def["partition_by"]
            sql += f"\nPARTITION BY toYYYYMM({partition_col})"

    elif dialect in ("postgres", "postgresql", "timescale") and time_partitioning and "partition_by" in table_def:
        # PostgreSQL native partitioning for any partitioned table
        partition_col = table_def["partition_by"]
        sql = sql.rstrip(")")
        sql += f"\n) PARTITION BY RANGE ({partition_col})"

    elif dialect == "duckdb" and time_partitioning:
        # DuckDB doesn't have native partitioning, but we can add comments
        sql += f";\n-- Recommended partition by: {table_def.get('partition_by', 'pickup_datetime')}"

    return sql + ";"


@compat_local(
    kind="type_mapping",
    platform_specific=True,
    reason="Maps generic SQL types to ClickHouse / DuckDB / PostgreSQL equivalents.",
)
def _map_type_to_dialect(type_name: str, dialect: str) -> str:
    """Map generic SQL types to dialect-specific types."""
    type_upper = type_name.upper()

    if dialect == "clickhouse":
        type_map = {
            "TIMESTAMP": "DateTime64(3)",
            "BIGINT": "Int64",
            "INTEGER": "Int32",
            "DOUBLE": "Float64",
            "VARCHAR(1)": "FixedString(1)",
            "VARCHAR(8)": "String",
            "VARCHAR(64)": "String",
            "VARCHAR(128)": "String",
        }
        return type_map.get(type_upper, type_name)

    elif dialect == "duckdb":
        type_map = {
            "TIMESTAMP": "TIMESTAMP",
            "BIGINT": "BIGINT",
            "INTEGER": "INTEGER",
            "DOUBLE": "DOUBLE",
            "VARCHAR(1)": "VARCHAR(1)",
            "VARCHAR(8)": "VARCHAR(8)",
            "VARCHAR(64)": "VARCHAR",
            "VARCHAR(128)": "VARCHAR",
        }
        return type_map.get(type_upper, type_name)

    elif dialect in ("postgres", "postgresql", "timescale"):
        type_map = {
            "TIMESTAMP": "TIMESTAMPTZ",
            "BIGINT": "BIGINT",
            "INTEGER": "INTEGER",
            "DOUBLE": "DOUBLE PRECISION",
            "VARCHAR(1)": "CHAR(1)",
            "VARCHAR(8)": "VARCHAR(8)",
            "VARCHAR(64)": "TEXT",
            "VARCHAR(128)": "TEXT",
        }
        return type_map.get(type_upper, type_name)

    # Standard SQL
    return type_name


def get_table_columns(table_name: str) -> list[str]:
    """Get column names for a table.

    Args:
        table_name: Name of the table

    Returns:
        List of column names
    """
    if table_name not in NYC_TAXI_SCHEMA:
        raise ValueError(f"Unknown table: {table_name}")
    return list(NYC_TAXI_SCHEMA[table_name]["columns"].keys())


def get_trips_columns() -> list[str]:
    """Get column names for the trips table (excluding auto-generated trip_id)."""
    columns = list(NYC_TAXI_SCHEMA["trips"]["columns"].keys())
    columns.remove("trip_id")
    return columns


def get_green_trips_columns() -> list[str]:
    """Get column names for the green_trips table (excluding auto-generated trip_id)."""
    columns = list(NYC_TAXI_SCHEMA["green_trips"]["columns"].keys())
    columns.remove("trip_id")
    return columns


def get_hvfhv_trips_columns() -> list[str]:
    """Get column names for the hvfhv_trips table (excluding auto-generated trip_id)."""
    columns = list(NYC_TAXI_SCHEMA["hvfhv_trips"]["columns"].keys())
    columns.remove("trip_id")
    return columns
