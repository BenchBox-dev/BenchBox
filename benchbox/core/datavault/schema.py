"""Data Vault 2.0 schema definition based on TPC-H source data.

This module defines the Data Vault schema consisting of 21 tables:
- 7 Hub tables (business entities)
- 6 Link tables (relationships)
- 8 Satellite tables (descriptive attributes)

The schema follows Data Vault 2.0 conventions with:
- Hash keys as surrogate keys (MD5 or SHA-256; columns sized VARCHAR(64))
- LOAD_DTS (load timestamp) for auditability
- RECORD_SOURCE for data lineage
- HASHDIFF for satellite change detection

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from enum import Enum
from typing import NamedTuple, Optional

from benchbox.core.schema_primitives import BaseSchemaTable


class DataType(Enum):
    """Enumeration of SQL data types used in Data Vault schema."""

    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL(15,2)"
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    HASHKEY = "VARCHAR(64)"  # Hash key columns: 32 chars for MD5, 64 for SHA-256


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
        if self.data_type == DataType.HASHKEY:
            return "VARCHAR(64)"
        if self.data_type in (DataType.VARCHAR, DataType.CHAR) and self.size is not None:
            return f"{self.data_type.value}({self.size})"
        return self.data_type.value


class Table(BaseSchemaTable):
    """Represents a Data Vault table with its columns and constraints."""

    def __init__(
        self,
        name: str,
        columns: list[Column],
        table_type: str = "unknown",
    ) -> None:
        """Initialize a Table with a name, columns, and Data Vault type.

        Args:
            name: The name of the table
            columns: List of column definitions
            table_type: One of 'hub', 'link', 'satellite'
        """
        super().__init__(name, columns)
        self.table_type = table_type


# =============================================================================
# HUB TABLES (7 tables)
# Hubs contain business keys with hash key surrogates
# =============================================================================

HUB_REGION = Table(
    "hub_region",
    [
        Column("hk_region", DataType.HASHKEY, primary_key=True),
        Column("r_regionkey", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

HUB_NATION = Table(
    "hub_nation",
    [
        Column("hk_nation", DataType.HASHKEY, primary_key=True),
        Column("n_nationkey", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

HUB_CUSTOMER = Table(
    "hub_customer",
    [
        Column("hk_customer", DataType.HASHKEY, primary_key=True),
        Column("c_custkey", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

HUB_SUPPLIER = Table(
    "hub_supplier",
    [
        Column("hk_supplier", DataType.HASHKEY, primary_key=True),
        Column("s_suppkey", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

HUB_PART = Table(
    "hub_part",
    [
        Column("hk_part", DataType.HASHKEY, primary_key=True),
        Column("p_partkey", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

HUB_ORDER = Table(
    "hub_order",
    [
        Column("hk_order", DataType.HASHKEY, primary_key=True),
        Column("o_orderkey", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

HUB_LINEITEM = Table(
    "hub_lineitem",
    [
        Column("hk_lineitem", DataType.HASHKEY, primary_key=True),
        Column("l_orderkey", DataType.INTEGER),
        Column("l_linenumber", DataType.INTEGER),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="hub",
)

# =============================================================================
# LINK TABLES (6 tables)
# Links represent relationships between Hubs
# =============================================================================

LINK_NATION_REGION = Table(
    "link_nation_region",
    [
        Column("hk_nation_region", DataType.HASHKEY, primary_key=True),
        Column("hk_nation", DataType.HASHKEY, foreign_key=("hub_nation", "hk_nation")),
        Column("hk_region", DataType.HASHKEY, foreign_key=("hub_region", "hk_region")),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="link",
)

LINK_CUSTOMER_NATION = Table(
    "link_customer_nation",
    [
        Column("hk_customer_nation", DataType.HASHKEY, primary_key=True),
        Column("hk_customer", DataType.HASHKEY, foreign_key=("hub_customer", "hk_customer")),
        Column("hk_nation", DataType.HASHKEY, foreign_key=("hub_nation", "hk_nation")),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="link",
)

LINK_SUPPLIER_NATION = Table(
    "link_supplier_nation",
    [
        Column("hk_supplier_nation", DataType.HASHKEY, primary_key=True),
        Column("hk_supplier", DataType.HASHKEY, foreign_key=("hub_supplier", "hk_supplier")),
        Column("hk_nation", DataType.HASHKEY, foreign_key=("hub_nation", "hk_nation")),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="link",
)

LINK_PART_SUPPLIER = Table(
    "link_part_supplier",
    [
        Column("hk_part_supplier", DataType.HASHKEY, primary_key=True),
        Column("hk_part", DataType.HASHKEY, foreign_key=("hub_part", "hk_part")),
        Column("hk_supplier", DataType.HASHKEY, foreign_key=("hub_supplier", "hk_supplier")),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="link",
)

LINK_ORDER_CUSTOMER = Table(
    "link_order_customer",
    [
        Column("hk_order_customer", DataType.HASHKEY, primary_key=True),
        Column("hk_order", DataType.HASHKEY, foreign_key=("hub_order", "hk_order")),
        Column("hk_customer", DataType.HASHKEY, foreign_key=("hub_customer", "hk_customer")),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="link",
)

LINK_LINEITEM = Table(
    "link_lineitem",
    [
        Column("hk_lineitem_link", DataType.HASHKEY, primary_key=True),
        Column("hk_lineitem", DataType.HASHKEY, foreign_key=("hub_lineitem", "hk_lineitem")),
        Column("hk_order", DataType.HASHKEY, foreign_key=("hub_order", "hk_order")),
        Column("hk_part", DataType.HASHKEY, foreign_key=("hub_part", "hk_part")),
        Column("hk_supplier", DataType.HASHKEY, foreign_key=("hub_supplier", "hk_supplier")),
        Column("load_dts", DataType.TIMESTAMP),
        Column("record_source", DataType.VARCHAR, size=50),
    ],
    table_type="link",
)

# =============================================================================
# SATELLITE TABLES (8 tables)
# Satellites contain descriptive attributes with temporal tracking
# =============================================================================

SAT_REGION = Table(
    "sat_region",
    [
        Column("hk_region", DataType.HASHKEY, primary_key=True, foreign_key=("hub_region", "hk_region")),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("r_name", DataType.CHAR, size=25),
        Column("r_comment", DataType.VARCHAR, size=152, nullable=True),
    ],
    table_type="satellite",
)

SAT_NATION = Table(
    "sat_nation",
    [
        Column("hk_nation", DataType.HASHKEY, primary_key=True, foreign_key=("hub_nation", "hk_nation")),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("n_name", DataType.CHAR, size=25),
        Column("n_comment", DataType.VARCHAR, size=152, nullable=True),
    ],
    table_type="satellite",
)

SAT_CUSTOMER = Table(
    "sat_customer",
    [
        Column("hk_customer", DataType.HASHKEY, primary_key=True, foreign_key=("hub_customer", "hk_customer")),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("c_name", DataType.VARCHAR, size=25),
        Column("c_address", DataType.VARCHAR, size=40),
        Column("c_phone", DataType.CHAR, size=15),
        Column("c_acctbal", DataType.DECIMAL),
        Column("c_mktsegment", DataType.CHAR, size=10),
        Column("c_comment", DataType.VARCHAR, size=117),
    ],
    table_type="satellite",
)

SAT_SUPPLIER = Table(
    "sat_supplier",
    [
        Column("hk_supplier", DataType.HASHKEY, primary_key=True, foreign_key=("hub_supplier", "hk_supplier")),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("s_name", DataType.CHAR, size=25),
        Column("s_address", DataType.VARCHAR, size=40),
        Column("s_phone", DataType.CHAR, size=15),
        Column("s_acctbal", DataType.DECIMAL),
        Column("s_comment", DataType.VARCHAR, size=101),
    ],
    table_type="satellite",
)

SAT_PART = Table(
    "sat_part",
    [
        Column("hk_part", DataType.HASHKEY, primary_key=True, foreign_key=("hub_part", "hk_part")),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("p_name", DataType.VARCHAR, size=55),
        Column("p_mfgr", DataType.CHAR, size=25),
        Column("p_brand", DataType.CHAR, size=10),
        Column("p_type", DataType.VARCHAR, size=25),
        Column("p_size", DataType.INTEGER),
        Column("p_container", DataType.CHAR, size=10),
        Column("p_retailprice", DataType.DECIMAL),
        Column("p_comment", DataType.VARCHAR, size=23),
    ],
    table_type="satellite",
)

SAT_PARTSUPP = Table(
    "sat_partsupp",
    [
        Column(
            "hk_part_supplier",
            DataType.HASHKEY,
            primary_key=True,
            foreign_key=("link_part_supplier", "hk_part_supplier"),
        ),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("ps_availqty", DataType.INTEGER),
        Column("ps_supplycost", DataType.DECIMAL),
        Column("ps_comment", DataType.VARCHAR, size=199),
    ],
    table_type="satellite",
)

SAT_ORDER = Table(
    "sat_order",
    [
        Column("hk_order", DataType.HASHKEY, primary_key=True, foreign_key=("hub_order", "hk_order")),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
        Column("o_orderstatus", DataType.CHAR, size=1),
        Column("o_totalprice", DataType.DECIMAL),
        Column("o_orderdate", DataType.DATE),
        Column("o_orderpriority", DataType.CHAR, size=15),
        Column("o_clerk", DataType.CHAR, size=15),
        Column("o_shippriority", DataType.INTEGER),
        Column("o_comment", DataType.VARCHAR, size=79),
    ],
    table_type="satellite",
)

SAT_LINEITEM = Table(
    "sat_lineitem",
    [
        Column(
            "hk_lineitem_link", DataType.HASHKEY, primary_key=True, foreign_key=("link_lineitem", "hk_lineitem_link")
        ),
        Column("load_dts", DataType.TIMESTAMP, primary_key=True),
        Column("load_end_dts", DataType.TIMESTAMP, nullable=True),
        Column("record_source", DataType.VARCHAR, size=50),
        Column("hashdiff", DataType.HASHKEY),
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
    table_type="satellite",
)

# =============================================================================
# TABLE COLLECTIONS
# =============================================================================

HUBS = [
    HUB_REGION,
    HUB_NATION,
    HUB_CUSTOMER,
    HUB_SUPPLIER,
    HUB_PART,
    HUB_ORDER,
    HUB_LINEITEM,
]

LINKS = [
    LINK_NATION_REGION,
    LINK_CUSTOMER_NATION,
    LINK_SUPPLIER_NATION,
    LINK_PART_SUPPLIER,
    LINK_ORDER_CUSTOMER,
    LINK_LINEITEM,
]

SATELLITES = [
    SAT_REGION,
    SAT_NATION,
    SAT_CUSTOMER,
    SAT_SUPPLIER,
    SAT_PART,
    SAT_PARTSUPP,
    SAT_ORDER,
    SAT_LINEITEM,
]

# All tables in loading order (Hubs -> Links -> Satellites)
TABLES = HUBS + LINKS + SATELLITES

# Loading order respecting referential integrity
LOADING_ORDER = [
    # Tier 1: Independent Hubs (no FK dependencies)
    "hub_region",
    "hub_nation",
    "hub_customer",
    "hub_supplier",
    "hub_part",
    "hub_order",
    "hub_lineitem",
    # Tier 2: Links (depend on Hubs)
    "link_nation_region",
    "link_customer_nation",
    "link_supplier_nation",
    "link_part_supplier",
    "link_order_customer",
    "link_lineitem",
    # Tier 3: Satellites (depend on Hubs/Links)
    "sat_region",
    "sat_nation",
    "sat_customer",
    "sat_supplier",
    "sat_part",
    "sat_partsupp",
    "sat_order",
    "sat_lineitem",
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
        raise ValueError(f"Invalid table name: {name}. Valid tables: {list(TABLES_BY_NAME.keys())}")
    return TABLES_BY_NAME[name_lower]


def get_create_all_tables_sql(enable_primary_keys: bool = True, enable_foreign_keys: bool = True) -> str:
    """Generate SQL to create all Data Vault tables in loading order.

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
        f"Generating SQL for {len(TABLES)} Data Vault tables "
        f"(primary_keys={enable_primary_keys}, foreign_keys={enable_foreign_keys})"
    )

    # Generate in loading order to respect FK dependencies
    for i, table_name in enumerate(LOADING_ORDER, 1):
        table = TABLES_BY_NAME[table_name]
        try:
            logger.debug(f"  [{i}/{len(TABLES)}] Generating SQL for table: {table.name}")
            sql = table.get_create_table_sql(
                enable_primary_keys=enable_primary_keys,
                enable_foreign_keys=enable_foreign_keys,
            )
            table_sqls.append(sql)
            logger.debug(f"  [{i}/{len(TABLES)}] Generated {len(sql)} characters for {table.name}")
        except Exception as e:
            logger.error(f"  [{i}/{len(TABLES)}] Failed to generate SQL for table {table.name}: {e}")
            raise RuntimeError(f"Schema generation failed for table {table.name}: {e}") from e

    result = "\n\n".join(table_sqls)
    logger.debug(f"Schema generation complete: {len(result)} total characters, {len(table_sqls)} tables")
    return result


def get_table_loading_order() -> list[str]:
    """Get the table names in proper loading order.

    Returns:
        List of table names ordered for loading (Hubs -> Links -> Satellites)
    """
    return LOADING_ORDER.copy()
