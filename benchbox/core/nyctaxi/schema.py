"""NYC Taxi OLAP benchmark schema definition."""

from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from benchbox.sql_compat.local_exemptions import compat_local


class TaxiType(Enum):
    """NYC TLC taxi/FHV data types."""

    YELLOW = "yellow"
    GREEN = "green"
    HVFHV = "hvfhv"


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
NYC_TAXI_SCHEMA: dict[str, dict[str, Any]] = _SCHEMA_SPECS["schema"]
TABLE_ORDER: list[str] = list(_SCHEMA_SPECS["table_order"])
RATE_CODES: dict[int, str] = _SCHEMA_SPECS["rate_codes"]
PAYMENT_TYPES: dict[int, str] = _SCHEMA_SPECS["payment_types"]
_TYPE_MAPPINGS: dict[str, dict[str, str]] = _SCHEMA_SPECS["type_mappings"]


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

    if dialect in ("postgresql", "timescale"):
        dialect = "postgres"
    if dialect in _TYPE_MAPPINGS:
        return _TYPE_MAPPINGS[dialect].get(type_upper, type_name)

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
