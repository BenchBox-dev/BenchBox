"""Primitives benchmark schema definitions.

This module defines the TPC-H schema for the primitives benchmark, which tests
fundamental database operations on standard TPC-H tables.

Table definitions are derived from the canonical TPC-H schema in
``benchbox.core.tpch.schema`` and converted to the dict format used by
the Read Primitives benchmark and its standalone loading helpers.

The TPC-H schema consists of:
- 8 base tables (CUSTOMER, LINEITEM, NATION, ORDERS, PART, PARTSUPP, REGION, SUPPLIER)

For more information, see:
- TPC-H Specification: https://www.tpc.org/tpch/

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import Any, cast

from benchbox.core.tpch.schema import TABLES as _TPCH_TABLES, Table


def _table_to_dict(table: Table) -> dict[str, Any]:
    """Convert a canonical TPC-H ``Table`` object to a plain dict.

    The dict format is used throughout Read Primitives for schema introspection
    and standalone data loading (``load_data_to_database``, ``_load_data``).
    """
    columns: list[dict[str, Any]] = []
    pk_columns: list[str] = []

    for col in table.columns:
        col_dict: dict[str, Any] = {"name": col.name, "type": col.get_sql_type()}
        if col.primary_key:
            pk_columns.append(col.name)
        if col.foreign_key:
            ref_table, ref_col = col.foreign_key
            col_dict["foreign_key"] = f"{ref_table}.{ref_col}"
        columns.append(col_dict)

    # Single-column PK: inline on the column; composite PK: table-level list
    if len(pk_columns) == 1:
        for col_dict in columns:
            if col_dict["name"] == pk_columns[0]:
                col_dict["primary_key"] = True
    elif len(pk_columns) > 1:
        result: dict[str, Any] = {"name": table.name, "columns": columns, "primary_key": pk_columns}
        return result

    return {"name": table.name, "columns": columns}


# Build TABLES dict from canonical TPC-H schema
TABLES: dict[str, dict[str, Any]] = {table.name: _table_to_dict(table) for table in _TPCH_TABLES}


def get_create_table_sql(
    table_name: str,
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for a given table.

    Args:
        table_name: Name of the table to create
        dialect: SQL dialect to use (currently unused, reserved for future dialect-specific DDL)
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        CREATE TABLE SQL statement

    Raises:
        ValueError: If table_name is not valid
    """
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}")

    table = TABLES[table_name]
    columns = []
    fk_defs: list[str] = []

    for col in cast(list, table["columns"]):
        col_def = f"{cast(str, col['name'])} {cast(str, col['type'])}"
        # Only add PRIMARY KEY constraint if enabled
        if enable_primary_keys and col.get("primary_key"):
            col_def += " PRIMARY KEY"
        columns.append(col_def)

        # Collect foreign key constraints from per-column "foreign_key" field
        if enable_foreign_keys and col.get("foreign_key"):
            fk_ref = cast(str, col["foreign_key"])  # e.g. "region.r_regionkey"
            ref_table, ref_column = fk_ref.split(".", 1)
            fk_defs.append(f"FOREIGN KEY ({col['name']}) REFERENCES {ref_table}({ref_column})")

    # Handle composite primary keys (only if enabled)
    if enable_primary_keys and "primary_key" in table and isinstance(table["primary_key"], list):
        pk_cols = ", ".join(cast(list[str], table["primary_key"]))
        columns.append(f"PRIMARY KEY ({pk_cols})")

    # Append foreign key constraints
    columns.extend(fk_defs)

    sql = f"CREATE TABLE {table['name']} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)
    sql += "\n);"

    return sql


def get_all_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for all TPC-H tables.

    Args:
        dialect: SQL dialect to use
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        Complete SQL schema creation script
    """
    from benchbox.core.schema_utils import collect_create_table_sql

    return collect_create_table_sql(
        ["region", "nation", "customer", "supplier", "part", "partsupp", "orders", "lineitem"],
        get_create_table_sql,
        dialect,
        enable_primary_keys=enable_primary_keys,
        enable_foreign_keys=enable_foreign_keys,
    )
