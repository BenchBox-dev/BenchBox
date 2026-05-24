"""Registry and helper utilities for the TPC-DS schema."""

from __future__ import annotations

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn

from .models import Table
from .tables import _TABLES

_TABLE_ORDER = (
    # Dimension tables with no foreign keys (must be created first)
    "DATE_DIM",
    "TIME_DIM",
    "ITEM",
    "CUSTOMER_DEMOGRAPHICS",
    "INCOME_BAND",
    "HOUSEHOLD_DEMOGRAPHICS",
    "CUSTOMER_ADDRESS",
    "STORE",
    "WAREHOUSE",
    "WEB_SITE",
    "WEB_PAGE",
    "PROMOTION",
    "REASON",
    "CALL_CENTER",
    "CATALOG_PAGE",
    "SHIP_MODE",
    # Dimension tables with foreign keys
    "CUSTOMER",
    # Fact tables (must be created after their referenced dimension tables)
    "STORE_SALES",
    "WEB_SALES",
    "CATALOG_SALES",
    "INVENTORY",
    # Return tables (must be created after their corresponding sales tables)
    "STORE_RETURNS",
    "WEB_RETURNS",
    "CATALOG_RETURNS",
    # Metadata tables (no dependencies)
    "DBGEN_VERSION",
)

TABLES = [_TABLES[name] for name in _TABLE_ORDER]

# Map of table names to Table objects
TABLES_BY_NAME = {table.name: table for table in TABLES}


def get_table(name: str) -> Table:
    """Get a table by name.

    Args:
        name: The name of the table to retrieve

    Returns:
        The requested Table object

    Raises:
        ValueError: If the table name is invalid
    """
    name_upper = name.upper()
    if name_upper not in TABLES_BY_NAME:
        raise ValueError(f"Invalid table name: {name}")
    return TABLES_BY_NAME[name_upper]


def get_create_all_tables_sql(enable_primary_keys: bool = True, enable_foreign_keys: bool = True) -> str:
    """Generate SQL to create all TPC-DS tables.

    Args:
        enable_primary_keys: Whether to include primary key constraints
        enable_foreign_keys: Whether to include foreign key constraints

    Returns:
        SQL script for creating all tables
    """
    return "\n\n".join(
        table.get_create_table_sql(
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )
        for table in TABLES
    )


def get_tunings() -> BenchmarkTunings:
    """Get the default tuning configurations for TPC-DS tables.

    These tunings focus on the major fact tables and key dimension tables,
    optimized for the complex analytical queries in TPC-DS.

    Returns:
        BenchmarkTunings containing tuning configurations for TPC-DS tables
    """
    tunings = BenchmarkTunings("tpcds")

    # Store Sales - largest fact table, partition by date, cluster by store and item
    store_sales_tuning = TableTuning(
        table_name="STORE_SALES",
        partitioning=[TuningColumn("SS_SOLD_DATE_SK", "INTEGER", 1)],
        clustering=[
            TuningColumn("SS_STORE_SK", "INTEGER", 1),
            TuningColumn("SS_ITEM_SK", "INTEGER", 2),
        ],
        sorting=[
            TuningColumn("SS_TICKET_NUMBER", "INTEGER", 1),
            TuningColumn("SS_QUANTITY", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(store_sales_tuning)

    # Catalog Sales - partition by date, cluster by item and customer
    catalog_sales_tuning = TableTuning(
        table_name="CATALOG_SALES",
        partitioning=[TuningColumn("CS_SOLD_DATE_SK", "INTEGER", 1)],
        clustering=[
            TuningColumn("CS_ITEM_SK", "INTEGER", 1),
            TuningColumn("CS_BILL_CUSTOMER_SK", "INTEGER", 2),
        ],
        sorting=[
            TuningColumn("CS_ORDER_NUMBER", "INTEGER", 1),
            TuningColumn("CS_QUANTITY", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(catalog_sales_tuning)

    # Web Sales - partition by date, cluster by item and customer
    web_sales_tuning = TableTuning(
        table_name="WEB_SALES",
        partitioning=[TuningColumn("WS_SOLD_DATE_SK", "INTEGER", 1)],
        clustering=[
            TuningColumn("WS_ITEM_SK", "INTEGER", 1),
            TuningColumn("WS_BILL_CUSTOMER_SK", "INTEGER", 2),
        ],
        sorting=[
            TuningColumn("WS_ORDER_NUMBER", "INTEGER", 1),
            TuningColumn("WS_QUANTITY", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(web_sales_tuning)

    # Store Returns - partition by return date, cluster by store and item
    store_returns_tuning = TableTuning(
        table_name="STORE_RETURNS",
        partitioning=[TuningColumn("SR_RETURNED_DATE_SK", "INTEGER", 1)],
        clustering=[
            TuningColumn("SR_STORE_SK", "INTEGER", 1),
            TuningColumn("SR_ITEM_SK", "INTEGER", 2),
        ],
        sorting=[TuningColumn("SR_TICKET_NUMBER", "INTEGER", 1)],
    )
    tunings.add_table_tuning(store_returns_tuning)

    # Web Returns - partition by return date, cluster by item
    web_returns_tuning = TableTuning(
        table_name="WEB_RETURNS",
        partitioning=[TuningColumn("WR_RETURNED_DATE_SK", "INTEGER", 1)],
        clustering=[TuningColumn("WR_ITEM_SK", "INTEGER", 1)],
        sorting=[TuningColumn("WR_ORDER_NUMBER", "INTEGER", 1)],
    )
    tunings.add_table_tuning(web_returns_tuning)

    # Catalog Returns - partition by return date, cluster by item
    catalog_returns_tuning = TableTuning(
        table_name="CATALOG_RETURNS",
        partitioning=[TuningColumn("CR_RETURNED_DATE_SK", "INTEGER", 1)],
        clustering=[TuningColumn("CR_ITEM_SK", "INTEGER", 1)],
        sorting=[TuningColumn("CR_ORDER_NUMBER", "INTEGER", 1)],
    )
    tunings.add_table_tuning(catalog_returns_tuning)

    # Inventory - partition by date, cluster by item and warehouse
    inventory_tuning = TableTuning(
        table_name="INVENTORY",
        partitioning=[TuningColumn("INV_DATE_SK", "INTEGER", 1)],
        clustering=[
            TuningColumn("INV_ITEM_SK", "INTEGER", 1),
            TuningColumn("INV_WAREHOUSE_SK", "INTEGER", 2),
        ],
        sorting=[TuningColumn("INV_QUANTITY_ON_HAND", "INTEGER", 1)],
    )
    tunings.add_table_tuning(inventory_tuning)

    # Key dimension tables

    # Date Dimension - sort by date key (most frequently joined)
    date_dim_tuning = TableTuning(table_name="DATE_DIM", sorting=[TuningColumn("D_DATE_SK", "INTEGER", 1)])
    tunings.add_table_tuning(date_dim_tuning)

    # Item Dimension - distribute by item key, sort by item key
    item_tuning = TableTuning(
        table_name="ITEM",
        distribution=[TuningColumn("I_ITEM_SK", "INTEGER", 1)],
        sorting=[TuningColumn("I_ITEM_ID", "CHAR", 1)],
    )
    tunings.add_table_tuning(item_tuning)

    # Customer Dimension - distribute by customer key
    customer_tuning = TableTuning(
        table_name="CUSTOMER",
        distribution=[TuningColumn("C_CUSTOMER_SK", "INTEGER", 1)],
        sorting=[TuningColumn("C_CUSTOMER_ID", "CHAR", 1)],
    )
    tunings.add_table_tuning(customer_tuning)

    # Store Dimension - sort by store key
    store_tuning = TableTuning(table_name="STORE", sorting=[TuningColumn("S_STORE_SK", "INTEGER", 1)])
    tunings.add_table_tuning(store_tuning)

    return tunings


__all__ = [
    "TABLES",
    "TABLES_BY_NAME",
    "get_table",
    "get_create_all_tables_sql",
    "get_tunings",
]
