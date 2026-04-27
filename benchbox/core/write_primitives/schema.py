"""Write Primitives benchmark schema definitions.

This module defines the schema for the Write Primitives benchmark, including:
- Base TPC-H tables (reused from tpch.schema)
- Staging tables for write operations
- Metadata tables for tracking operations

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import Any, cast

# Import base TPC-H tables
from benchbox.core.tpch.schema import (
    CUSTOMER,
    LINEITEM,
    NATION,
    ORDERS,
    PART,
    PARTSUPP,
    REGION,
    SUPPLIER,
)

# Category-based staging tables for Write Primitives v2
# Each category gets dedicated staging tables to avoid shared state and enable
# non-transactional cleanup through explicit SQL statements.

# INSERT operations staging table for lineitem
INSERT_OPS_LINEITEM = {
    "name": "insert_ops_lineitem",
    "columns": [
        {"name": "l_orderkey", "type": "INTEGER"},
        {"name": "l_partkey", "type": "INTEGER"},
        {"name": "l_suppkey", "type": "INTEGER"},
        {"name": "l_linenumber", "type": "INTEGER"},
        {"name": "l_quantity", "type": "DECIMAL(15,2)"},
        {"name": "l_extendedprice", "type": "DECIMAL(15,2)"},
        {"name": "l_discount", "type": "DECIMAL(15,2)"},
        {"name": "l_tax", "type": "DECIMAL(15,2)"},
        {"name": "l_returnflag", "type": "VARCHAR(1)"},
        {"name": "l_linestatus", "type": "VARCHAR(1)"},
        {"name": "l_shipdate", "type": "DATE"},
        {"name": "l_commitdate", "type": "DATE"},
        {"name": "l_receiptdate", "type": "DATE"},
        {"name": "l_shipinstruct", "type": "VARCHAR(25)"},
        {"name": "l_shipmode", "type": "VARCHAR(10)"},
        {"name": "l_comment", "type": "VARCHAR(44)"},
    ],
    "primary_key": ["l_orderkey", "l_linenumber"],
}

# INSERT operations staging table for orders
INSERT_OPS_ORDERS = {
    "name": "insert_ops_orders",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "primary_key": True},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderstatus", "type": "VARCHAR(1)"},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "o_orderpriority", "type": "VARCHAR(15)"},
        {"name": "o_clerk", "type": "VARCHAR(15)"},
        {"name": "o_shippriority", "type": "INTEGER"},
        {"name": "o_comment", "type": "VARCHAR(79)"},
    ],
}

# INSERT operations staging table for summary/aggregated data
INSERT_OPS_ORDERS_SUMMARY = {
    "name": "insert_ops_orders_summary",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "nullable": True},
        {"name": "o_custkey", "type": "INTEGER", "nullable": True},
        {"name": "o_orderdate", "type": "DATE", "nullable": True},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)", "nullable": True},
        {"name": "customer_name", "type": "VARCHAR(25)", "nullable": True},
        {"name": "order_count", "type": "INTEGER", "nullable": True},
    ],
}

# UPDATE operations staging table (populated from orders during setup)
UPDATE_OPS_ORDERS = {
    "name": "update_ops_orders",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "primary_key": True},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderstatus", "type": "VARCHAR(1)"},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "o_orderpriority", "type": "VARCHAR(15)"},
        {"name": "o_clerk", "type": "VARCHAR(15)"},
        {"name": "o_shippriority", "type": "INTEGER"},
        {"name": "o_comment", "type": "VARCHAR(79)"},
    ],
}

# DELETE operations staging table for orders (populated from orders during setup)
DELETE_OPS_ORDERS = {
    "name": "delete_ops_orders",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "primary_key": True},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderstatus", "type": "VARCHAR(1)"},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "o_orderpriority", "type": "VARCHAR(15)"},
        {"name": "o_clerk", "type": "VARCHAR(15)"},
        {"name": "o_shippriority", "type": "INTEGER"},
        {"name": "o_comment", "type": "VARCHAR(79)"},
    ],
}

# DELETE operations staging table for lineitem (populated from lineitem during setup)
DELETE_OPS_LINEITEM = {
    "name": "delete_ops_lineitem",
    "columns": [
        {"name": "l_orderkey", "type": "INTEGER"},
        {"name": "l_partkey", "type": "INTEGER"},
        {"name": "l_suppkey", "type": "INTEGER"},
        {"name": "l_linenumber", "type": "INTEGER"},
        {"name": "l_quantity", "type": "DECIMAL(15,2)"},
        {"name": "l_extendedprice", "type": "DECIMAL(15,2)"},
        {"name": "l_discount", "type": "DECIMAL(15,2)"},
        {"name": "l_tax", "type": "DECIMAL(15,2)"},
        {"name": "l_returnflag", "type": "VARCHAR(1)"},
        {"name": "l_linestatus", "type": "VARCHAR(1)"},
        {"name": "l_shipdate", "type": "DATE"},
        {"name": "l_commitdate", "type": "DATE"},
        {"name": "l_receiptdate", "type": "DATE"},
        {"name": "l_shipinstruct", "type": "VARCHAR(25)"},
        {"name": "l_shipmode", "type": "VARCHAR(10)"},
        {"name": "l_comment", "type": "VARCHAR(44)"},
    ],
    "primary_key": ["l_orderkey", "l_linenumber"],
}

# DELETE operations staging table for supplier (for GDPR operations)
DELETE_OPS_SUPPLIER = {
    "name": "delete_ops_supplier",
    "columns": [
        {"name": "s_suppkey", "type": "INTEGER", "primary_key": True},
        {"name": "s_name", "type": "VARCHAR(25)"},
        {"name": "s_address", "type": "VARCHAR(40)"},
        {"name": "s_nationkey", "type": "INTEGER"},
        {"name": "s_phone", "type": "VARCHAR(15)"},
        {"name": "s_acctbal", "type": "DECIMAL(15,2)"},
        {"name": "s_comment", "type": "VARCHAR(101)"},
    ],
}

# MERGE operations target table
MERGE_OPS_TARGET = {
    "name": "merge_ops_target",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "primary_key": True},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderstatus", "type": "VARCHAR(1)"},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "o_orderpriority", "type": "VARCHAR(15)"},
        {"name": "o_clerk", "type": "VARCHAR(15)"},
        {"name": "o_shippriority", "type": "INTEGER"},
        {"name": "o_comment", "type": "VARCHAR(79)"},
    ],
}

# MERGE operations source table
MERGE_OPS_SOURCE = {
    "name": "merge_ops_source",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "primary_key": True},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderstatus", "type": "VARCHAR(1)"},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "o_orderpriority", "type": "VARCHAR(15)"},
        {"name": "o_clerk", "type": "VARCHAR(15)"},
        {"name": "o_shippriority", "type": "INTEGER"},
        {"name": "o_comment", "type": "VARCHAR(79)"},
    ],
}

# MERGE operations target table for lineitem
MERGE_OPS_LINEITEM_TARGET = {
    "name": "merge_ops_lineitem_target",
    "columns": [
        {"name": "l_orderkey", "type": "INTEGER"},
        {"name": "l_partkey", "type": "INTEGER"},
        {"name": "l_suppkey", "type": "INTEGER"},
        {"name": "l_linenumber", "type": "INTEGER"},
        {"name": "l_quantity", "type": "DECIMAL(15,2)"},
        {"name": "l_extendedprice", "type": "DECIMAL(15,2)"},
        {"name": "l_discount", "type": "DECIMAL(15,2)"},
        {"name": "l_tax", "type": "DECIMAL(15,2)"},
        {"name": "l_returnflag", "type": "VARCHAR(1)"},
        {"name": "l_linestatus", "type": "VARCHAR(1)"},
        {"name": "l_shipdate", "type": "DATE"},
        {"name": "l_commitdate", "type": "DATE"},
        {"name": "l_receiptdate", "type": "DATE"},
        {"name": "l_shipinstruct", "type": "VARCHAR(25)"},
        {"name": "l_shipmode", "type": "VARCHAR(10)"},
        {"name": "l_comment", "type": "VARCHAR(44)"},
    ],
    "primary_key": ["l_orderkey", "l_linenumber"],
}

# MERGE operations target table for summary data
MERGE_OPS_SUMMARY_TARGET = {
    "name": "merge_ops_summary_target",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "nullable": True},
        {"name": "o_custkey", "type": "INTEGER", "nullable": True},
        {"name": "o_orderdate", "type": "DATE", "nullable": True},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)", "nullable": True},
        {"name": "customer_name", "type": "VARCHAR(25)", "nullable": True},
        {"name": "order_count", "type": "INTEGER", "nullable": True},
    ],
}

# INSERT operations enriched table for joined data
INSERT_OPS_LINEITEM_ENRICHED = {
    "name": "insert_ops_lineitem_enriched",
    "columns": [
        # Core lineitem columns
        {"name": "l_orderkey", "type": "INTEGER"},
        {"name": "l_partkey", "type": "INTEGER"},
        {"name": "l_suppkey", "type": "INTEGER"},
        {"name": "l_quantity", "type": "DECIMAL(15,2)"},
        {"name": "l_extendedprice", "type": "DECIMAL(15,2)"},
        # Enriched columns from joins
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "c_name", "type": "VARCHAR(25)"},
        {"name": "s_name", "type": "VARCHAR(25)"},
        {"name": "p_name", "type": "VARCHAR(55)"},
    ],
}

# BULK_LOAD operations target table
BULK_LOAD_OPS_TARGET = {
    "name": "bulk_load_ops_target",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER"},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderstatus", "type": "VARCHAR(1)"},
        {"name": "o_totalprice", "type": "DECIMAL(15,2)"},
        {"name": "o_orderdate", "type": "DATE"},
        {"name": "o_orderpriority", "type": "VARCHAR(15)", "nullable": True},
        {"name": "o_clerk", "type": "VARCHAR(15)", "nullable": True},
        {"name": "o_shippriority", "type": "INTEGER", "nullable": True},
        {"name": "o_comment", "type": "VARCHAR(79)", "nullable": True},
    ],
}

# DDL operations target table for TRUNCATE tests
DDL_TRUNCATE_TARGET = {
    "name": "ddl_truncate_target",
    "columns": [
        {"name": "o_orderkey", "type": "INTEGER", "primary_key": True},
        {"name": "o_custkey", "type": "INTEGER"},
        {"name": "o_orderdate", "type": "DATE"},
    ],
}

# Audit log for tracking write operations
WRITE_OPS_LOG = {
    "name": "write_ops_log",
    "columns": [
        {"name": "log_id", "type": "INTEGER", "primary_key": True},
        {"name": "operation_id", "type": "VARCHAR(100)"},
        {"name": "operation_category", "type": "VARCHAR(50)"},
        {"name": "timestamp", "type": "TIMESTAMP"},
        {"name": "rows_affected", "type": "INTEGER"},
        {"name": "duration_ms", "type": "DECIMAL(15,2)"},
        {"name": "success", "type": "BOOLEAN"},
        {"name": "error_message", "type": "VARCHAR(500)", "nullable": True},
    ],
}

# Batch metadata for bulk operations
BATCH_METADATA = {
    "name": "batch_metadata",
    "columns": [
        {"name": "batch_id", "type": "INTEGER", "primary_key": True},
        {"name": "operation_id", "type": "VARCHAR(100)"},
        {"name": "file_path", "type": "VARCHAR(500)", "nullable": True},
        {"name": "file_size_bytes", "type": "BIGINT", "nullable": True},
        {"name": "file_format", "type": "VARCHAR(50)", "nullable": True},
        {"name": "compression", "type": "VARCHAR(50)", "nullable": True},
        {"name": "row_count", "type": "INTEGER"},
        {"name": "checksum", "type": "VARCHAR(100)", "nullable": True},
        {"name": "created_at", "type": "TIMESTAMP"},
    ],
}

# All tables in write primitives schema
TABLES = {
    # Base TPC-H tables (read-only references)
    "region": REGION,
    "nation": NATION,
    "customer": CUSTOMER,
    "supplier": SUPPLIER,
    "part": PART,
    "partsupp": PARTSUPP,
    "orders": ORDERS,
    "lineitem": LINEITEM,
    # Category-based staging tables for write operations
    "insert_ops_lineitem": INSERT_OPS_LINEITEM,
    "insert_ops_orders": INSERT_OPS_ORDERS,
    "insert_ops_orders_summary": INSERT_OPS_ORDERS_SUMMARY,
    "insert_ops_lineitem_enriched": INSERT_OPS_LINEITEM_ENRICHED,
    "update_ops_orders": UPDATE_OPS_ORDERS,
    "delete_ops_orders": DELETE_OPS_ORDERS,
    "delete_ops_lineitem": DELETE_OPS_LINEITEM,
    "delete_ops_supplier": DELETE_OPS_SUPPLIER,
    "merge_ops_target": MERGE_OPS_TARGET,
    "merge_ops_source": MERGE_OPS_SOURCE,
    "merge_ops_lineitem_target": MERGE_OPS_LINEITEM_TARGET,
    "merge_ops_summary_target": MERGE_OPS_SUMMARY_TARGET,
    "bulk_load_ops_target": BULK_LOAD_OPS_TARGET,
    "ddl_truncate_target": DDL_TRUNCATE_TARGET,
    # Metadata tables
    "write_ops_log": WRITE_OPS_LOG,
    "batch_metadata": BATCH_METADATA,
}

# Tables that need to be created (excluding base TPC-H tables)
STAGING_TABLES = {
    "insert_ops_lineitem": INSERT_OPS_LINEITEM,
    "insert_ops_orders": INSERT_OPS_ORDERS,
    "insert_ops_orders_summary": INSERT_OPS_ORDERS_SUMMARY,
    "insert_ops_lineitem_enriched": INSERT_OPS_LINEITEM_ENRICHED,
    "update_ops_orders": UPDATE_OPS_ORDERS,
    "delete_ops_orders": DELETE_OPS_ORDERS,
    "delete_ops_lineitem": DELETE_OPS_LINEITEM,
    "delete_ops_supplier": DELETE_OPS_SUPPLIER,
    "merge_ops_target": MERGE_OPS_TARGET,
    "merge_ops_source": MERGE_OPS_SOURCE,
    "merge_ops_lineitem_target": MERGE_OPS_LINEITEM_TARGET,
    "merge_ops_summary_target": MERGE_OPS_SUMMARY_TARGET,
    "bulk_load_ops_target": BULK_LOAD_OPS_TARGET,
    "ddl_truncate_target": DDL_TRUNCATE_TARGET,
    "write_ops_log": WRITE_OPS_LOG,
    "batch_metadata": BATCH_METADATA,
}


def _supports_primary_keys(dialect: str) -> bool:
    """Return whether the target SQL dialect supports PRIMARY KEY in CREATE TABLE."""
    import benchbox.sql_compat.rules.schema_emit.pk_capability  # noqa: F401
    from benchbox.sql_compat.actions import CompatAction
    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform=dialect.lower(),
        platform_version=None,
        benchmark="write_primitives",
        query_id=None,
        phase=Phase.SCHEMA_EMIT,
        mode="sql",
        dialect=dialect,
    )
    registry_decision = REGISTRY.resolve(ctx)

    if registry_decision is not None:
        return registry_decision.action == CompatAction.NATIVE
    return True  # no rule: default to supported


def get_create_table_sql(table_name: str, dialect: str = "standard", if_not_exists: bool = False) -> str:
    """Generate CREATE TABLE SQL for a given table.

    Args:
        table_name: Name of the table to create
        dialect: SQL dialect to use (standard, postgres, mysql, etc.)
        if_not_exists: If True, use CREATE TABLE IF NOT EXISTS

    Returns:
        CREATE TABLE SQL statement

    Raises:
        ValueError: If table_name is not valid
    """
    if table_name not in STAGING_TABLES:
        raise ValueError(f"Unknown staging table: {table_name}. Use STAGING_TABLES only.")

    table = STAGING_TABLES[table_name]
    supports_primary_keys = _supports_primary_keys(dialect)
    columns: list[str] = []

    for col in table["columns"]:
        col_def = f"{col['name']} {col['type']}"
        if col.get("primary_key") and supports_primary_keys:
            col_def += " PRIMARY KEY"
        if not col.get("nullable", False) and not col.get("primary_key"):
            col_def += " NOT NULL"
        columns.append(col_def)

    # Handle composite primary keys
    if supports_primary_keys and "primary_key" in table and isinstance(table["primary_key"], list):
        pk_cols = ", ".join(table["primary_key"])
        columns.append(f"PRIMARY KEY ({pk_cols})")

    # Use IF NOT EXISTS if requested (supported by DuckDB, PostgreSQL, MySQL, SQLite)
    if_not_exists_clause = " IF NOT EXISTS" if if_not_exists else ""
    sql = f"CREATE TABLE{if_not_exists_clause} {table['name']} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)
    sql += "\n);"

    return sql


def get_all_staging_tables_sql(dialect: str = "standard") -> str:
    """Generate CREATE TABLE SQL for all staging tables.

    Args:
        dialect: SQL dialect to use

    Returns:
        Complete SQL schema creation script for staging tables
    """
    # Order tables by dependencies (independent tables first)
    table_order = [
        "write_ops_log",
        "batch_metadata",
        "insert_ops_lineitem",
        "insert_ops_orders",
        "insert_ops_orders_summary",
        "insert_ops_lineitem_enriched",
        "update_ops_orders",
        "delete_ops_orders",
        "delete_ops_lineitem",
        "delete_ops_supplier",
        "merge_ops_target",
        "merge_ops_source",
        "merge_ops_lineitem_target",
        "merge_ops_summary_target",
        "bulk_load_ops_target",
        "ddl_truncate_target",
    ]

    sql_statements: list[str] = []
    for table_name in table_order:
        sql_statements.append(get_create_table_sql(table_name, dialect))

    return "\n\n".join(sql_statements)


def get_table_schema(table_name: str) -> dict[str, Any]:
    """Get schema definition for a table.

    Args:
        table_name: Name of the table

    Returns:
        Table schema dictionary

    Raises:
        ValueError: If table_name is not valid
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}")
    return cast(dict[str, Any], TABLES[table_name])


__all__ = [
    "TABLES",
    "STAGING_TABLES",
    "INSERT_OPS_LINEITEM",
    "INSERT_OPS_ORDERS",
    "INSERT_OPS_ORDERS_SUMMARY",
    "INSERT_OPS_LINEITEM_ENRICHED",
    "UPDATE_OPS_ORDERS",
    "DELETE_OPS_ORDERS",
    "DELETE_OPS_LINEITEM",
    "DELETE_OPS_SUPPLIER",
    "MERGE_OPS_TARGET",
    "MERGE_OPS_SOURCE",
    "MERGE_OPS_LINEITEM_TARGET",
    "MERGE_OPS_SUMMARY_TARGET",
    "BULK_LOAD_OPS_TARGET",
    "DDL_TRUNCATE_TARGET",
    "WRITE_OPS_LOG",
    "BATCH_METADATA",
    "get_create_table_sql",
    "get_all_staging_tables_sql",
    "get_table_schema",
]
