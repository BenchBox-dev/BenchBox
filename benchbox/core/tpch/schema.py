"""TPC-H schema definition.

This module defines the schema for the TPC-H benchmark, including all tables,
their columns, data types, and relationships.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from enum import Enum
from typing import NamedTuple, Optional

from benchbox.core.schema_primitives import BaseSchemaTable
from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn


class DataType(Enum):
    """Enumeration of SQL data types used in TPC-H."""

    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL(15,2)"
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    DATE = "DATE"


class Column(NamedTuple):
    """Represents a column in a database table."""

    name: str
    data_type: DataType
    size: Optional[int] = None  # For VARCHAR and CHAR types
    nullable: bool = False
    primary_key: bool = False
    foreign_key: Optional[tuple[str, str]] = None  # (table_name, column_name)

    def get_sql_type(self) -> str:
        """Get the SQL data type string for this column."""
        if self.data_type in (DataType.VARCHAR, DataType.CHAR) and self.size is not None:
            return f"{self.data_type.value}({self.size})"
        return self.data_type.value


class Table(BaseSchemaTable):
    """Represents a TPC-H table with its columns and constraints."""

    def __init__(self, name: str, columns: list[Column]) -> None:
        super().__init__(name, columns)


# TPC-H Schema Definition
# Based on the TPC-H spec version 3.0.0

# Region Table
REGION = Table(
    "region",
    [
        Column("r_regionkey", DataType.INTEGER, primary_key=True),
        Column("r_name", DataType.CHAR, size=25),
        Column("r_comment", DataType.VARCHAR, size=152, nullable=True),
    ],
)

# Nation Table
NATION = Table(
    "nation",
    [
        Column("n_nationkey", DataType.INTEGER, primary_key=True),
        Column("n_name", DataType.CHAR, size=25),
        Column("n_regionkey", DataType.INTEGER, foreign_key=("region", "r_regionkey")),
        Column("n_comment", DataType.VARCHAR, size=152, nullable=True),
    ],
)

# Supplier Table
SUPPLIER = Table(
    "supplier",
    [
        Column("s_suppkey", DataType.INTEGER, primary_key=True),
        Column("s_name", DataType.CHAR, size=25),
        Column("s_address", DataType.VARCHAR, size=40),
        Column("s_nationkey", DataType.INTEGER, foreign_key=("nation", "n_nationkey")),
        Column("s_phone", DataType.CHAR, size=15),
        Column("s_acctbal", DataType.DECIMAL),
        Column("s_comment", DataType.VARCHAR, size=101),
    ],
)

# Part Table
PART = Table(
    "part",
    [
        Column("p_partkey", DataType.INTEGER, primary_key=True),
        Column("p_name", DataType.VARCHAR, size=55),
        Column("p_mfgr", DataType.CHAR, size=25),
        Column("p_brand", DataType.CHAR, size=10),
        Column("p_type", DataType.VARCHAR, size=25),
        Column("p_size", DataType.INTEGER),
        Column("p_container", DataType.CHAR, size=10),
        Column("p_retailprice", DataType.DECIMAL),
        Column("p_comment", DataType.VARCHAR, size=23),
    ],
)

# PartSupp Table (Part/Supplier relationship)
PARTSUPP = Table(
    "partsupp",
    [
        Column(
            "ps_partkey",
            DataType.INTEGER,
            foreign_key=("part", "p_partkey"),
            primary_key=True,
        ),
        Column(
            "ps_suppkey",
            DataType.INTEGER,
            foreign_key=("supplier", "s_suppkey"),
            primary_key=True,
        ),
        Column("ps_availqty", DataType.INTEGER),
        Column("ps_supplycost", DataType.DECIMAL),
        Column("ps_comment", DataType.VARCHAR, size=199),
    ],
)

# Customer Table
CUSTOMER = Table(
    "customer",
    [
        Column("c_custkey", DataType.INTEGER, primary_key=True),
        Column("c_name", DataType.VARCHAR, size=25),
        Column("c_address", DataType.VARCHAR, size=40),
        Column("c_nationkey", DataType.INTEGER, foreign_key=("nation", "n_nationkey")),
        Column("c_phone", DataType.CHAR, size=15),
        Column("c_acctbal", DataType.DECIMAL),
        Column("c_mktsegment", DataType.CHAR, size=10),
        Column("c_comment", DataType.VARCHAR, size=117),
    ],
)

# Orders Table
ORDERS = Table(
    "orders",
    [
        Column("o_orderkey", DataType.INTEGER, primary_key=True),
        Column("o_custkey", DataType.INTEGER, foreign_key=("customer", "c_custkey")),
        Column("o_orderstatus", DataType.CHAR, size=1),
        Column("o_totalprice", DataType.DECIMAL),
        Column("o_orderdate", DataType.DATE),
        Column("o_orderpriority", DataType.CHAR, size=15),
        Column("o_clerk", DataType.CHAR, size=15),
        Column("o_shippriority", DataType.INTEGER),
        Column("o_comment", DataType.VARCHAR, size=79),
    ],
)

# LineItem Table
LINEITEM = Table(
    "lineitem",
    [
        Column(
            "l_orderkey",
            DataType.INTEGER,
            foreign_key=("orders", "o_orderkey"),
            primary_key=True,
        ),
        Column("l_partkey", DataType.INTEGER, foreign_key=("part", "p_partkey")),
        Column("l_suppkey", DataType.INTEGER, foreign_key=("supplier", "s_suppkey")),
        Column("l_linenumber", DataType.INTEGER, primary_key=True),
        Column("l_quantity", DataType.DECIMAL),
        Column("l_extendedprice", DataType.DECIMAL),
        Column("l_discount", DataType.DECIMAL),
        Column("l_tax", DataType.DECIMAL),
        Column("l_returnflag", DataType.CHAR, size=1),
        Column("l_linestatus", DataType.CHAR, size=1),
        Column("l_shipdate", DataType.DATE),
        Column("l_commitdate", DataType.DATE),
        Column("l_receiptdate", DataType.DATE),
        Column("l_shipinstruct", DataType.CHAR, size=25),
        Column("l_shipmode", DataType.CHAR, size=10),
        Column("l_comment", DataType.VARCHAR, size=44),
    ],
)

# Collection of all tables in the TPC-H schema
TABLES = [
    REGION,
    NATION,
    SUPPLIER,
    PART,
    PARTSUPP,
    CUSTOMER,
    ORDERS,
    LINEITEM,
]

# Map of table names to Table objects
TABLES_BY_NAME = {table.name: table for table in TABLES}


def get_table(name: str) -> Table:
    """Get a table by name (case-insensitive lookup).

    Args:
        name: The name of the table to retrieve

    Returns:
        The requested Table object

    Raises:
        ValueError: If the table name is invalid
    """
    name_lower = name.lower()
    if name_lower not in TABLES_BY_NAME:
        raise ValueError(f"Invalid table name: {name}")
    return TABLES_BY_NAME[name_lower]


def get_create_all_tables_sql(enable_primary_keys: bool = True, enable_foreign_keys: bool = True) -> str:
    """Generate SQL to create all TPC-H tables.

    Args:
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        SQL script for creating all tables
    """
    import logging

    logger = logging.getLogger(__name__)

    table_sqls = []
    logger.debug(
        f"Generating SQL for {len(TABLES)} TPC-H tables "
        f"(primary_keys={enable_primary_keys}, foreign_keys={enable_foreign_keys})"
    )

    for i, table in enumerate(TABLES, 1):
        try:
            logger.debug(f"  [{i}/{len(TABLES)}] Generating SQL for table: {table.name}")
            sql = table.get_create_table_sql(
                enable_primary_keys=enable_primary_keys,
                enable_foreign_keys=enable_foreign_keys,
            )
            table_sqls.append(sql)
            logger.debug(f"  [{i}/{len(TABLES)}] ✓ Generated {len(sql)} characters for {table.name}")
        except Exception as e:
            logger.error(f"  [{i}/{len(TABLES)}] ✗ Failed to generate SQL for table {table.name}: {e}")
            raise RuntimeError(f"Schema generation failed for table {table.name}: {e}") from e

    result = "\n\n".join(table_sqls)
    logger.debug(f"Schema generation complete: {len(result)} total characters, {len(table_sqls)} tables")
    return result


def get_tunings() -> BenchmarkTunings:
    """Get the default tuning configurations for TPC-H tables.

    These tunings are based on TPC-H query patterns and provide optimal
    performance for analytical workloads across different platforms.

    Returns:
        BenchmarkTunings containing tuning configurations for all TPC-H tables
    """
    tunings = BenchmarkTunings("tpch")

    # LineItem table - largest fact table, partitioned by ship date, clustered by order key
    lineitem_tuning = TableTuning(
        table_name="lineitem",
        partitioning=[TuningColumn("l_shipdate", "DATE", 1)],
        clustering=[TuningColumn("l_orderkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("l_linenumber", "INTEGER", 1),
            TuningColumn("l_partkey", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(lineitem_tuning)

    # Orders table - partitioned by order date, clustered by customer key
    orders_tuning = TableTuning(
        table_name="orders",
        partitioning=[TuningColumn("o_orderdate", "DATE", 1)],
        clustering=[TuningColumn("o_custkey", "INTEGER", 1)],
        sorting=[TuningColumn("o_totalprice", "DECIMAL", 1)],
    )
    tunings.add_table_tuning(orders_tuning)

    # PartSupp table - distribute by part key, sort by supplier key and availability
    partsupp_tuning = TableTuning(
        table_name="partsupp",
        distribution=[TuningColumn("ps_partkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("ps_suppkey", "INTEGER", 1),
            TuningColumn("ps_availqty", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(partsupp_tuning)

    # Customer table - distribute by customer key, sort by market segment
    customer_tuning = TableTuning(
        table_name="customer",
        distribution=[TuningColumn("c_custkey", "INTEGER", 1)],
        sorting=[TuningColumn("c_mktsegment", "CHAR", 1)],
    )
    tunings.add_table_tuning(customer_tuning)

    # Supplier table - distribute by supplier key, sort by nation
    supplier_tuning = TableTuning(
        table_name="supplier",
        distribution=[TuningColumn("s_suppkey", "INTEGER", 1)],
        sorting=[TuningColumn("s_nationkey", "INTEGER", 1)],
    )
    tunings.add_table_tuning(supplier_tuning)

    # Part table - distribute by part key, sort by type and size
    part_tuning = TableTuning(
        table_name="part",
        distribution=[TuningColumn("p_partkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("p_type", "VARCHAR", 1),
            TuningColumn("p_size", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(part_tuning)

    # Nation table - sort by nation key (small dimension table)
    nation_tuning = TableTuning(table_name="nation", sorting=[TuningColumn("n_nationkey", "INTEGER", 1)])
    tunings.add_table_tuning(nation_tuning)

    # Region table - sort by region key (small dimension table)
    region_tuning = TableTuning(table_name="region", sorting=[TuningColumn("r_regionkey", "INTEGER", 1)])
    tunings.add_table_tuning(region_tuning)

    return tunings
