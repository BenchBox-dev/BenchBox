"""Transaction Primitives benchmark schema definitions."""

from pathlib import Path
from typing import Any, cast

import yaml

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


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
_STAGING_DEFS = {entry["id"]: entry for entry in _SCHEMA_SPECS["staging_tables"]}
globals().update({symbol: entry["schema"] for symbol, entry in _STAGING_DEFS.items()})
TXN_ORDERS = cast(dict[str, Any], globals()["TXN_ORDERS"])
TXN_LINEITEM = cast(dict[str, Any], globals()["TXN_LINEITEM"])
TXN_CUSTOMER = cast(dict[str, Any], globals()["TXN_CUSTOMER"])
_STAGING_TABLE_ORDER = list(_SCHEMA_SPECS["staging_table_order"])

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
STAGING_TABLES = {entry["key"]: globals()[symbol] for symbol, entry in _STAGING_DEFS.items()}


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
    sql_statements: list[str] = []
    for table_name in _STAGING_TABLE_ORDER:
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
