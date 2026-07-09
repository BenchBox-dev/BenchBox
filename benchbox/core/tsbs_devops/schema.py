"""TSBS DevOps benchmark schema definition."""

from pathlib import Path
from typing import Any

import yaml

from benchbox.sql_compat.local_exemptions import compat_local


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
TSBS_DEVOPS_SCHEMA: dict[str, dict[str, Any]] = _SCHEMA_SPECS["schema"]
TABLE_ORDER: list[str] = list(_SCHEMA_SPECS["table_order"])
_TYPE_MAPPINGS: dict[str, dict[str, str]] = _SCHEMA_SPECS["type_mappings"]


def get_create_tables_sql(
    dialect: str = "standard",
    include_constraints: bool = True,
    time_partitioning: bool = False,
    partition_interval: str = "1 day",
) -> str:
    """Generate CREATE TABLE SQL statements for TSBS DevOps schema.

    Args:
        dialect: SQL dialect (standard, duckdb, clickhouse, timescale, etc.)
        include_constraints: Whether to include PRIMARY KEY constraints
        time_partitioning: Whether to add time-based partitioning hints
        partition_interval: Partition interval for time-based partitioning

    Returns:
        SQL script for creating all tables
    """
    statements = []

    for table_name in TABLE_ORDER:
        table_def = TSBS_DEVOPS_SCHEMA[table_name]
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
        "TimescaleDB create_hypertable(), DuckDB partition comment. "
        "Policy branches (clickhouse/timescale) are registered in "
        "sql_compat/rules/schema_emit/tsbs_devops_ddl.py. "
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
            sql += f"\nPARTITION BY toYYYYMMDD({partition_col})"

    elif dialect == "timescale" and table_name != "tags":
        # TimescaleDB hypertables
        sql += ";\n"
        sql += f"SELECT create_hypertable('{table_name}', 'time'"
        sql += f", chunk_time_interval => INTERVAL '{partition_interval}'"
        sql += ", if_not_exists => TRUE)"

    elif time_partitioning and dialect == "duckdb":
        # DuckDB doesn't have native partitioning, but we can add comments
        sql += f";\n-- Recommended partition by: {table_def.get('partition_by', 'time')}"

    return sql + ";"


@compat_local(
    kind="type_mapping",
    platform_specific=True,
    reason="Maps generic SQL types to ClickHouse / DuckDB / TimescaleDB / InfluxDB equivalents.",
)
def _map_type_to_dialect(type_name: str, dialect: str) -> str:
    """Map generic SQL types to dialect-specific types."""
    type_upper = type_name.upper()

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
    if table_name not in TSBS_DEVOPS_SCHEMA:
        raise ValueError(f"Unknown table: {table_name}")
    return list(TSBS_DEVOPS_SCHEMA[table_name]["columns"].keys())


def get_metric_tables() -> list[str]:
    """Get list of metric tables (excluding tags).

    Returns:
        List of metric table names
    """
    return [t for t in TABLE_ORDER if t != "tags"]
