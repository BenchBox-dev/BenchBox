"""TSBS DevOps benchmark schema definition.

Defines the schema for DevOps infrastructure monitoring data:
- cpu: CPU usage metrics per host
- mem: Memory usage metrics per host
- disk: Disk I/O metrics per host and device
- net: Network metrics per host and interface
- tags: Host metadata (hostname, region, datacenter, OS, etc.)

Based on the TSBS DevOps use case:
https://github.com/timescale/tsbs/tree/master/cmd/tsbs_generate_data

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import Any

from benchbox.sql_compat.local_exemptions import compat_local

# Schema definition with column specifications
TSBS_DEVOPS_SCHEMA = {
    "tags": {
        "description": "Host metadata and tags",
        "columns": {
            "hostname": {"type": "VARCHAR(255)", "description": "Host identifier"},
            "region": {"type": "VARCHAR(64)", "description": "Cloud region"},
            "datacenter": {"type": "VARCHAR(64)", "description": "Datacenter name"},
            "rack": {"type": "VARCHAR(64)", "description": "Rack identifier"},
            "os": {"type": "VARCHAR(64)", "description": "Operating system"},
            "arch": {"type": "VARCHAR(32)", "description": "CPU architecture"},
            "team": {"type": "VARCHAR(64)", "description": "Team owner"},
            "service": {"type": "VARCHAR(64)", "description": "Service name"},
            "service_version": {"type": "VARCHAR(32)", "description": "Service version"},
            "service_environment": {"type": "VARCHAR(32)", "description": "Environment (prod, staging, dev)"},
        },
        "primary_key": ["hostname"],
        "indexes": ["region", "datacenter", "service"],
    },
    "cpu": {
        "description": "CPU metrics per host at regular intervals",
        "columns": {
            "time": {"type": "TIMESTAMP", "description": "Measurement timestamp"},
            "hostname": {"type": "VARCHAR(255)", "description": "Host identifier"},
            "usage_user": {"type": "DOUBLE", "description": "CPU % in user space"},
            "usage_system": {"type": "DOUBLE", "description": "CPU % in kernel space"},
            "usage_idle": {"type": "DOUBLE", "description": "CPU % idle"},
            "usage_nice": {"type": "DOUBLE", "description": "CPU % nice priority"},
            "usage_iowait": {"type": "DOUBLE", "description": "CPU % waiting for I/O"},
            "usage_irq": {"type": "DOUBLE", "description": "CPU % hardware interrupts"},
            "usage_softirq": {"type": "DOUBLE", "description": "CPU % software interrupts"},
            "usage_steal": {"type": "DOUBLE", "description": "CPU % stolen by hypervisor"},
            "usage_guest": {"type": "DOUBLE", "description": "CPU % running guest VMs"},
            "usage_guest_nice": {"type": "DOUBLE", "description": "CPU % guest nice priority"},
        },
        "primary_key": ["time", "hostname"],
        "partition_by": "time",
        "order_by": ["hostname", "time"],
    },
    "mem": {
        "description": "Memory metrics per host",
        "columns": {
            "time": {"type": "TIMESTAMP", "description": "Measurement timestamp"},
            "hostname": {"type": "VARCHAR(255)", "description": "Host identifier"},
            "total": {"type": "BIGINT", "description": "Total memory bytes"},
            "available": {"type": "BIGINT", "description": "Available memory bytes"},
            "used": {"type": "BIGINT", "description": "Used memory bytes"},
            "free": {"type": "BIGINT", "description": "Free memory bytes"},
            "cached": {"type": "BIGINT", "description": "Cached memory bytes"},
            "buffered": {"type": "BIGINT", "description": "Buffered memory bytes"},
            "used_percent": {"type": "DOUBLE", "description": "Memory usage percent"},
            "available_percent": {"type": "DOUBLE", "description": "Available memory percent"},
        },
        "primary_key": ["time", "hostname"],
        "partition_by": "time",
        "order_by": ["hostname", "time"],
    },
    "disk": {
        "description": "Disk I/O metrics per host and device",
        "columns": {
            "time": {"type": "TIMESTAMP", "description": "Measurement timestamp"},
            "hostname": {"type": "VARCHAR(255)", "description": "Host identifier"},
            "device": {"type": "VARCHAR(64)", "description": "Disk device name"},
            "reads_completed": {"type": "BIGINT", "description": "Total read operations"},
            "reads_merged": {"type": "BIGINT", "description": "Merged read operations"},
            "sectors_read": {"type": "BIGINT", "description": "Sectors read"},
            "read_time_ms": {"type": "BIGINT", "description": "Read time in milliseconds"},
            "writes_completed": {"type": "BIGINT", "description": "Total write operations"},
            "writes_merged": {"type": "BIGINT", "description": "Merged write operations"},
            "sectors_written": {"type": "BIGINT", "description": "Sectors written"},
            "write_time_ms": {"type": "BIGINT", "description": "Write time in milliseconds"},
            "io_in_progress": {"type": "INTEGER", "description": "Current I/O operations"},
            "io_time_ms": {"type": "BIGINT", "description": "Total I/O time"},
            "weighted_io_time_ms": {"type": "BIGINT", "description": "Weighted I/O time"},
        },
        "primary_key": ["time", "hostname", "device"],
        "partition_by": "time",
        "order_by": ["hostname", "device", "time"],
    },
    "net": {
        "description": "Network metrics per host and interface",
        "columns": {
            "time": {"type": "TIMESTAMP", "description": "Measurement timestamp"},
            "hostname": {"type": "VARCHAR(255)", "description": "Host identifier"},
            "interface": {"type": "VARCHAR(64)", "description": "Network interface name"},
            "bytes_recv": {"type": "BIGINT", "description": "Bytes received"},
            "bytes_sent": {"type": "BIGINT", "description": "Bytes sent"},
            "packets_recv": {"type": "BIGINT", "description": "Packets received"},
            "packets_sent": {"type": "BIGINT", "description": "Packets sent"},
            "err_in": {"type": "BIGINT", "description": "Receive errors"},
            "err_out": {"type": "BIGINT", "description": "Send errors"},
            "drop_in": {"type": "BIGINT", "description": "Dropped incoming packets"},
            "drop_out": {"type": "BIGINT", "description": "Dropped outgoing packets"},
        },
        "primary_key": ["time", "hostname", "interface"],
        "partition_by": "time",
        "order_by": ["hostname", "interface", "time"],
    },
}

# Table order for creation (tags first, then metrics tables)
TABLE_ORDER = ["tags", "cpu", "mem", "disk", "net"]


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

    if dialect == "clickhouse":
        type_map = {
            "TIMESTAMP": "DateTime64(3)",
            "BIGINT": "Int64",
            "INTEGER": "Int32",
            "DOUBLE": "Float64",
            "VARCHAR(255)": "String",
            "VARCHAR(64)": "String",
            "VARCHAR(32)": "String",
        }
        return type_map.get(type_upper, type_name)

    elif dialect == "duckdb":
        type_map = {
            "TIMESTAMP": "TIMESTAMP",
            "BIGINT": "BIGINT",
            "INTEGER": "INTEGER",
            "DOUBLE": "DOUBLE",
            "VARCHAR(255)": "VARCHAR",
            "VARCHAR(64)": "VARCHAR",
            "VARCHAR(32)": "VARCHAR",
        }
        return type_map.get(type_upper, type_name)

    elif dialect == "timescale":
        type_map = {
            "TIMESTAMP": "TIMESTAMPTZ",
            "BIGINT": "BIGINT",
            "INTEGER": "INTEGER",
            "DOUBLE": "DOUBLE PRECISION",
            "VARCHAR(255)": "TEXT",
            "VARCHAR(64)": "TEXT",
            "VARCHAR(32)": "TEXT",
        }
        return type_map.get(type_upper, type_name)

    elif dialect == "influxdb":
        # InfluxDB 3.x uses standard SQL types via FlightSQL
        # Time column is handled specially (nanosecond precision)
        type_map = {
            "TIMESTAMP": "TIMESTAMP",
            "BIGINT": "BIGINT",
            "INTEGER": "INTEGER",
            "DOUBLE": "DOUBLE",
            "VARCHAR(255)": "STRING",
            "VARCHAR(64)": "STRING",
            "VARCHAR(32)": "STRING",
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
    if table_name not in TSBS_DEVOPS_SCHEMA:
        raise ValueError(f"Unknown table: {table_name}")
    return list(TSBS_DEVOPS_SCHEMA[table_name]["columns"].keys())


def get_metric_tables() -> list[str]:
    """Get list of metric tables (excluding tags).

    Returns:
        List of metric table names
    """
    return [t for t in TABLE_ORDER if t != "tags"]
