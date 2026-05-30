"""TPC-H schema definition."""

from enum import Enum
from pathlib import Path
from typing import Any, NamedTuple, Optional

import yaml

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


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _make_column(spec: dict[str, Any]) -> Column:
    foreign_key = spec.get("foreign_key")
    return Column(
        spec["name"],
        DataType[spec["data_type"]],
        size=spec.get("size"),
        nullable=spec.get("nullable", False),
        primary_key=spec.get("primary_key", False),
        foreign_key=tuple(foreign_key) if foreign_key else None,
    )


def _make_table(spec: dict[str, Any]) -> Table:
    return Table(spec["name"], [_make_column(column) for column in spec["columns"]])


_SCHEMA_SPECS = _load_schema_specs()
_TABLE_DEFS = {entry["id"]: _make_table(entry) for entry in _SCHEMA_SPECS["tables"]}

REGION = _TABLE_DEFS["REGION"]
NATION = _TABLE_DEFS["NATION"]
SUPPLIER = _TABLE_DEFS["SUPPLIER"]
PART = _TABLE_DEFS["PART"]
PARTSUPP = _TABLE_DEFS["PARTSUPP"]
CUSTOMER = _TABLE_DEFS["CUSTOMER"]
ORDERS = _TABLE_DEFS["ORDERS"]
LINEITEM = _TABLE_DEFS["LINEITEM"]


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
