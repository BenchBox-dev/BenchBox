"""Star Schema Benchmark (SSB) schema definitions.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.

This module defines the schema for the Star Schema Benchmark, which is a simplified
version of TPC-H designed for testing OLAP systems and data warehouses.

The SSB schema consists of:
- One fact table (LINEORDER)
- Four dimension tables (CUSTOMER, SUPPLIER, PART, DATE)

For more information, see:
- Original paper: "Star Schema Benchmark" by O'Neil et al.
- https://www.cs.umb.edu/~poneil/StarSchemaB.PDF
"""

from typing import cast

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn

# DATE dimension table
DATE = {
    "name": "date",
    "columns": [
        {"name": "d_datekey", "type": "INTEGER", "primary_key": True},
        {"name": "d_date", "type": "VARCHAR(18)"},
        {"name": "d_dayofweek", "type": "VARCHAR(9)"},
        {"name": "d_month", "type": "VARCHAR(9)"},
        {"name": "d_year", "type": "INTEGER"},
        {"name": "d_yearmonthnum", "type": "INTEGER"},
        {"name": "d_yearmonth", "type": "VARCHAR(7)"},
        {"name": "d_daynuminweek", "type": "INTEGER"},
        {"name": "d_daynuminmonth", "type": "INTEGER"},
        {"name": "d_daynuminyear", "type": "INTEGER"},
        {"name": "d_monthnuminyear", "type": "INTEGER"},
        {"name": "d_weeknuminyear", "type": "INTEGER"},
        {"name": "d_sellingseason", "type": "VARCHAR(12)"},
        {"name": "d_lastdayinweekfl", "type": "INTEGER"},
        {"name": "d_lastdayinmonthfl", "type": "INTEGER"},
        {"name": "d_holidayfl", "type": "INTEGER"},
        {"name": "d_weekdayfl", "type": "INTEGER"},
    ],
}

# CUSTOMER dimension table
CUSTOMER = {
    "name": "customer",
    "columns": [
        {"name": "c_custkey", "type": "INTEGER", "primary_key": True},
        {"name": "c_name", "type": "VARCHAR(25)"},
        {"name": "c_address", "type": "VARCHAR(25)"},
        {"name": "c_city", "type": "VARCHAR(10)"},
        {"name": "c_nation", "type": "VARCHAR(15)"},
        {"name": "c_region", "type": "VARCHAR(12)"},
        {"name": "c_phone", "type": "VARCHAR(15)"},
        {"name": "c_mktsegment", "type": "VARCHAR(10)"},
    ],
}

# SUPPLIER dimension table
SUPPLIER = {
    "name": "supplier",
    "columns": [
        {"name": "s_suppkey", "type": "INTEGER", "primary_key": True},
        {"name": "s_name", "type": "VARCHAR(25)"},
        {"name": "s_address", "type": "VARCHAR(25)"},
        {"name": "s_city", "type": "VARCHAR(10)"},
        {"name": "s_nation", "type": "VARCHAR(15)"},
        {"name": "s_region", "type": "VARCHAR(12)"},
        {"name": "s_phone", "type": "VARCHAR(15)"},
    ],
}

# PART dimension table
PART = {
    "name": "part",
    "columns": [
        {"name": "p_partkey", "type": "INTEGER", "primary_key": True},
        {"name": "p_name", "type": "VARCHAR(22)"},
        {"name": "p_mfgr", "type": "VARCHAR(6)"},
        {"name": "p_category", "type": "VARCHAR(7)"},
        {"name": "p_brand1", "type": "VARCHAR(9)"},
        {"name": "p_color", "type": "VARCHAR(11)"},
        {"name": "p_type", "type": "VARCHAR(25)"},
        {"name": "p_size", "type": "INTEGER"},
        {"name": "p_container", "type": "VARCHAR(10)"},
    ],
}

# LINEORDER fact table
LINEORDER = {
    "name": "lineorder",
    "columns": [
        {"name": "lo_orderkey", "type": "INTEGER"},
        {"name": "lo_linenumber", "type": "INTEGER"},
        {"name": "lo_custkey", "type": "INTEGER", "foreign_key": "customer.c_custkey"},
        {"name": "lo_partkey", "type": "INTEGER", "foreign_key": "part.p_partkey"},
        {"name": "lo_suppkey", "type": "INTEGER", "foreign_key": "supplier.s_suppkey"},
        {"name": "lo_orderdate", "type": "INTEGER", "foreign_key": "date.d_datekey"},
        {"name": "lo_orderpriority", "type": "VARCHAR(15)"},
        {"name": "lo_shippriority", "type": "INTEGER"},
        {"name": "lo_quantity", "type": "INTEGER"},
        {"name": "lo_extendedprice", "type": "INTEGER"},
        {"name": "lo_ordtotalprice", "type": "INTEGER"},
        {"name": "lo_discount", "type": "INTEGER"},
        {"name": "lo_revenue", "type": "INTEGER"},
        {"name": "lo_supplycost", "type": "INTEGER"},
        {"name": "lo_tax", "type": "INTEGER"},
        {"name": "lo_commitdate", "type": "INTEGER"},
        {"name": "lo_shipmode", "type": "VARCHAR(10)"},
    ],
    "primary_key": ["lo_orderkey", "lo_linenumber"],
}

# All tables in the SSB schema
TABLES = {
    "date": DATE,
    "customer": CUSTOMER,
    "supplier": SUPPLIER,
    "part": PART,
    "lineorder": LINEORDER,
}


def get_create_table_sql(
    table_name: str,
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for a given table.

    Args:
        table_name: Name of the table to create
        dialect: SQL dialect to use (standard, postgres, mysql, etc.)
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

    for col in cast(list, table["columns"]):
        col_def = f"{cast(str, col['name'])} {cast(str, col['type'])}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        columns.append(col_def)

    # Handle composite primary keys
    if "primary_key" in table and isinstance(table["primary_key"], list) and enable_primary_keys:
        pk_cols = ", ".join(cast(list[str], table["primary_key"]))
        columns.append(f"PRIMARY KEY ({pk_cols})")

    # Use lowercase table name for TPC compliance
    table_name_lower = cast(str, table["name"]).lower()
    sql = f"CREATE TABLE {table_name_lower} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)
    sql += "\n);"

    return sql


def get_all_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for all SSB tables.

    Args:
        dialect: SQL dialect to use
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        Complete SQL schema creation script
    """
    from benchbox.core.schema_utils import collect_create_table_sql

    return collect_create_table_sql(
        ["date", "customer", "supplier", "part", "lineorder"],
        get_create_table_sql,
        dialect,
        enable_primary_keys=enable_primary_keys,
        enable_foreign_keys=enable_foreign_keys,
    )


def get_tunings() -> BenchmarkTunings:
    """Get the default tuning configurations for SSB tables.

    These tunings are optimized for the star schema pattern with focus on
    the fact table lineorder and key dimension tables.

    Returns:
        BenchmarkTunings containing tuning configurations for SSB tables
    """
    tunings = BenchmarkTunings("ssb")

    # LineOrder fact table - partition by order date, cluster by customer and supplier
    lineorder_tuning = TableTuning(
        table_name="lineorder",
        partitioning=[TuningColumn("lo_orderdate", "INTEGER", 1)],
        clustering=[
            TuningColumn("lo_custkey", "INTEGER", 1),
            TuningColumn("lo_suppkey", "INTEGER", 2),
        ],
        sorting=[
            TuningColumn("lo_orderkey", "INTEGER", 1),
            TuningColumn("lo_linenumber", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(lineorder_tuning)

    # Date dimension - sort by date key (most frequently joined)
    date_tuning = TableTuning(table_name="date", sorting=[TuningColumn("d_datekey", "INTEGER", 1)])
    tunings.add_table_tuning(date_tuning)

    # Customer dimension - distribute by customer key, sort by region for analytics
    customer_tuning = TableTuning(
        table_name="customer",
        distribution=[TuningColumn("c_custkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("c_region", "VARCHAR(12)", 1),
            TuningColumn("c_nation", "VARCHAR(15)", 2),
        ],
    )
    tunings.add_table_tuning(customer_tuning)

    # Supplier dimension - distribute by supplier key, sort by region
    supplier_tuning = TableTuning(
        table_name="supplier",
        distribution=[TuningColumn("s_suppkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("s_region", "VARCHAR(12)", 1),
            TuningColumn("s_nation", "VARCHAR(15)", 2),
        ],
    )
    tunings.add_table_tuning(supplier_tuning)

    # Part dimension - distribute by part key, sort by category for analytics
    part_tuning = TableTuning(
        table_name="part",
        distribution=[TuningColumn("p_partkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("p_category", "VARCHAR(7)", 1),
            TuningColumn("p_brand1", "VARCHAR(9)", 2),
        ],
    )
    tunings.add_table_tuning(part_tuning)

    return tunings
