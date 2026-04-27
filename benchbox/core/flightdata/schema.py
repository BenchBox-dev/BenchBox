"""Flight data benchmark schema definitions.

Defines the table structure for the US Bureau of Transportation Statistics
On-Time Performance dataset.

Schema source: BTS TranStats On-Time Reporting
https://www.transtats.bts.gov/Fields.asp?gnoyr_VQ=FGJ

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

# Schema definition for the flight data benchmark
FLIGHT_SCHEMA: dict[str, dict[str, Any]] = {
    "flights": {
        "description": "US domestic flight on-time performance data (BTS TranStats)",
        "columns": {
            "flight_id": {"type": "BIGINT", "description": "Synthetic unique identifier"},
            "flight_date": {"type": "DATE", "description": "Flight date"},
            "year": {"type": "INTEGER", "description": "Year of flight"},
            "month": {"type": "INTEGER", "description": "Month of flight (1-12)"},
            "day_of_month": {"type": "INTEGER", "description": "Day of month (1-31)"},
            "day_of_week": {"type": "INTEGER", "description": "Day of week (1=Monday, 7=Sunday)"},
            "reporting_airline": {"type": "VARCHAR", "description": "Carrier code (IATA)"},
            "flight_number": {"type": "INTEGER", "description": "Flight number"},
            "origin": {"type": "VARCHAR", "description": "Origin airport code (IATA)"},
            "dest": {"type": "VARCHAR", "description": "Destination airport code (IATA)"},
            "crs_dep_time": {"type": "INTEGER", "description": "Scheduled departure time (HHMM)"},
            "dep_time": {"type": "DOUBLE", "description": "Actual departure time (HHMM), NULL if cancelled"},
            "dep_delay": {"type": "DOUBLE", "description": "Departure delay in minutes (negative=early)"},
            "crs_arr_time": {"type": "INTEGER", "description": "Scheduled arrival time (HHMM)"},
            "arr_time": {"type": "DOUBLE", "description": "Actual arrival time (HHMM), NULL if cancelled"},
            "arr_delay": {"type": "DOUBLE", "description": "Arrival delay in minutes (negative=early)"},
            "cancelled": {"type": "INTEGER", "description": "Cancellation flag (0=not cancelled, 1=cancelled)"},
            "cancellation_code": {
                "type": "VARCHAR",
                "description": "Cancellation reason (A=Carrier, B=Weather, C=NAS, D=Security)",
            },
            "diverted": {"type": "INTEGER", "description": "Diversion flag (0=not diverted, 1=diverted)"},
            "crs_elapsed_time": {"type": "DOUBLE", "description": "Scheduled elapsed flight time in minutes"},
            "actual_elapsed_time": {"type": "DOUBLE", "description": "Actual elapsed flight time in minutes"},
            "air_time": {"type": "DOUBLE", "description": "Air time in minutes"},
            "distance": {"type": "DOUBLE", "description": "Distance between airports in miles"},
            "carrier_delay": {"type": "DOUBLE", "description": "Carrier-caused delay in minutes"},
            "weather_delay": {"type": "DOUBLE", "description": "Weather-caused delay in minutes"},
            "nas_delay": {"type": "DOUBLE", "description": "National Air System delay in minutes"},
            "security_delay": {"type": "DOUBLE", "description": "Security-caused delay in minutes"},
            "late_aircraft_delay": {"type": "DOUBLE", "description": "Late aircraft delay in minutes"},
        },
        "primary_key": ["flight_id"],
        "indexes": ["flight_date", "reporting_airline", "origin", "dest"],
    },
    "airlines": {
        "description": "Airline carrier reference data",
        "columns": {
            "code": {"type": "VARCHAR", "description": "IATA carrier code"},
            "name": {"type": "VARCHAR", "description": "Carrier name"},
        },
        "primary_key": ["code"],
    },
    "airports": {
        "description": "Airport reference data with geographic coordinates",
        "columns": {
            "code": {"type": "VARCHAR", "description": "IATA airport code"},
            "name": {"type": "VARCHAR", "description": "Airport name"},
            "city": {"type": "VARCHAR", "description": "City name"},
            "state": {"type": "VARCHAR", "description": "State code"},
            "latitude": {"type": "DOUBLE", "description": "Latitude coordinate"},
            "longitude": {"type": "DOUBLE", "description": "Longitude coordinate"},
        },
        "primary_key": ["code"],
    },
}

# Type mappings for different SQL dialects
_TYPE_MAPPINGS: dict[str, dict[str, str]] = {
    "standard": {
        "BIGINT": "BIGINT",
        "INTEGER": "INTEGER",
        "VARCHAR": "VARCHAR",
        "DOUBLE": "DOUBLE PRECISION",
        "DATE": "DATE",
    },
    "duckdb": {
        "BIGINT": "BIGINT",
        "INTEGER": "INTEGER",
        "VARCHAR": "VARCHAR",
        "DOUBLE": "DOUBLE",
        "DATE": "DATE",
    },
    "postgres": {
        "BIGINT": "BIGINT",
        "INTEGER": "INTEGER",
        "VARCHAR": "VARCHAR",
        "DOUBLE": "DOUBLE PRECISION",
        "DATE": "DATE",
    },
    "clickhouse": {
        "BIGINT": "Int64",
        "INTEGER": "Int32",
        "VARCHAR": "String",
        "DOUBLE": "Float64",
        "DATE": "Date",
    },
    "snowflake": {
        "BIGINT": "NUMBER(19,0)",
        "INTEGER": "NUMBER(10,0)",
        "VARCHAR": "VARCHAR",
        "DOUBLE": "FLOAT",
        "DATE": "DATE",
    },
}


def get_create_tables_sql(
    dialect: str = "standard",
    include_constraints: bool = True,
) -> str:
    """Generate CREATE TABLE SQL statements for the flight data benchmark.

    Args:
        dialect: SQL dialect (standard, duckdb, postgres, clickhouse, snowflake)
        include_constraints: Include PRIMARY KEY constraints

    Returns:
        SQL script for creating all tables
    """
    type_map = _TYPE_MAPPINGS.get(dialect, _TYPE_MAPPINGS["standard"])
    statements = []

    table_order = ["airlines", "airports", "flights"]

    for table_name in table_order:
        table_def = FLIGHT_SCHEMA[table_name]
        columns = table_def["columns"]
        primary_key = table_def.get("primary_key", [])

        col_defs = []
        for col_name, col_info in columns.items():
            col_type = type_map.get(col_info["type"], col_info["type"])
            col_def = f"    {col_name} {col_type}"
            col_defs.append(col_def)

        if include_constraints and primary_key and dialect not in ("clickhouse",):
            pk_cols = ", ".join(primary_key)
            col_defs.append(f"    PRIMARY KEY ({pk_cols})")

        cols_sql = ",\n".join(col_defs)
        stmt = f"CREATE TABLE IF NOT EXISTS {table_name} (\n{cols_sql}\n)"
        statements.append(stmt)

    return ";\n\n".join(statements) + ";"
