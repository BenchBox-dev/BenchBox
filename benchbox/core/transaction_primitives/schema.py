"""Transaction Primitives benchmark schema definitions.

This module defines the schema for the Transaction Primitives benchmark, including:
- Base TPC-H tables (reused from tpch.schema)
- Staging tables for transaction operations

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

# Staging table for transaction operations on ORDERS
TXN_ORDERS = {
    "name": "txn_orders",
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

# Staging table for transaction operations on LINEITEM
TXN_LINEITEM = {
    "name": "txn_lineitem",
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

# Staging table for CUSTOMER transaction operations
TXN_CUSTOMER = {
    "name": "txn_customer",
    "columns": [
        {"name": "c_custkey", "type": "INTEGER", "primary_key": True},
        {"name": "c_name", "type": "VARCHAR(25)"},
        {"name": "c_address", "type": "VARCHAR(40)"},
        {"name": "c_nationkey", "type": "INTEGER"},
        {"name": "c_phone", "type": "VARCHAR(15)"},
        {"name": "c_acctbal", "type": "DECIMAL(15,2)"},
        {"name": "c_mktsegment", "type": "VARCHAR(10)"},
        {"name": "c_comment", "type": "VARCHAR(117)"},
    ],
}

# All tables in transaction primitives schema
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
    # Staging tables for transaction operations
    "txn_orders": TXN_ORDERS,
    "txn_lineitem": TXN_LINEITEM,
    "txn_customer": TXN_CUSTOMER,
}

# Tables that need to be created (excluding base TPC-H tables)
STAGING_TABLES = {
    "txn_orders": TXN_ORDERS,
    "txn_lineitem": TXN_LINEITEM,
    "txn_customer": TXN_CUSTOMER,
}


def _supports_primary_keys(dialect: str) -> bool:
    """Return whether the target SQL dialect supports PRIMARY KEY in CREATE TABLE."""
    import benchbox.sql_compat.rules.schema_emit.pk_capability_txn  # noqa: F401
    from benchbox.sql_compat.actions import CompatAction
    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform=dialect.lower(),
        platform_version=None,
        benchmark="transaction_primitives",
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

    supports_pk = _supports_primary_keys(dialect)
    table = STAGING_TABLES[table_name]
    columns: list[str] = []

    for col in table["columns"]:
        col_def = f"{col['name']} {col['type']}"
        if supports_pk and col.get("primary_key"):
            col_def += " PRIMARY KEY"
        if not col.get("nullable", False) and not col.get("primary_key"):
            col_def += " NOT NULL"
        columns.append(col_def)

    # Handle composite primary keys
    if supports_pk and "primary_key" in table and isinstance(table["primary_key"], list):
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
        "txn_orders",
        "txn_lineitem",
        "txn_customer",
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
    "TXN_ORDERS",
    "TXN_LINEITEM",
    "TXN_CUSTOMER",
    "get_create_table_sql",
    "get_all_staging_tables_sql",
    "get_table_schema",
]
