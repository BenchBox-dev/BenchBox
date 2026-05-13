"""Canonical CoffeeShop benchmark schema aligned with the reference generator.

The CoffeeShop benchmark now models the three-table star schema provided by the
reference generator (https://github.com/JosueBogran/coffeeshopdatageneratorv2).
The schema includes two dimensions-``dim_locations`` and ``dim_products``-and a
single ``order_lines`` fact table that applies the required order-line
explosion. All previous dimension tables (customers, stores, staff, time_dim)
and the legacy ``transactions`` fact table have been removed.

The module exposes helper functions for rendering CREATE TABLE statements and
for producing default tuning recommendations used by the BenchBox planners.
"""

from __future__ import annotations

from typing import Any, cast

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn

DIM_LOCATIONS = {
    "name": "dim_locations",
    "description": "Canonical list of reference store locations and regions.",
    "row_count_formula": "len(vendored dim_locations seed file)",
    "columns": [
        {"name": "record_id", "type": "INTEGER", "primary_key": True},
        {"name": "location_id", "type": "VARCHAR(16)"},
        {"name": "city", "type": "VARCHAR(50)"},
        {"name": "state", "type": "VARCHAR(10)"},
        {"name": "country", "type": "VARCHAR(50)"},
        {"name": "region", "type": "VARCHAR(20)"},
    ],
}

DIM_PRODUCTS = {
    "name": "dim_products",
    "description": "Reference product catalog with seasonal availability windows.",
    "row_count_formula": "len(vendored dim_products seed file)",
    "columns": [
        {"name": "record_id", "type": "INTEGER", "primary_key": True},
        {"name": "product_id", "type": "INTEGER"},
        {"name": "name", "type": "VARCHAR(120)"},
        {"name": "category", "type": "VARCHAR(30)"},
        {"name": "subcategory", "type": "VARCHAR(30)"},
        {"name": "standard_cost", "type": "DECIMAL(8,2)"},
        {"name": "standard_price", "type": "DECIMAL(8,2)"},
        {"name": "from_date", "type": "DATE"},
        {"name": "to_date", "type": "DATE"},
    ],
}

ORDER_LINES = {
    "name": "order_lines",
    "description": "Exploded order lines fact table with 1-5 lines per order.",
    "row_count_formula": "50_000_000 * scale_factor * 1.5 (average lines per order)",
    "columns": [
        {"name": "order_id", "type": "BIGINT"},
        {"name": "line_number", "type": "INTEGER"},
        {"name": "location_record_id", "type": "INTEGER", "foreign_key": "dim_locations.record_id"},
        {"name": "location_id", "type": "VARCHAR(16)"},
        {"name": "product_record_id", "type": "INTEGER", "foreign_key": "dim_products.record_id"},
        {"name": "product_id", "type": "INTEGER"},
        {"name": "order_date", "type": "DATE"},
        {"name": "order_time", "type": "TIME"},
        {"name": "quantity", "type": "INTEGER"},
        {"name": "unit_price", "type": "DECIMAL(8,2)"},
        {"name": "total_price", "type": "DECIMAL(10,2)"},
        {"name": "region", "type": "VARCHAR(20)"},
    ],
}

TABLES: dict[str, dict] = {
    "dim_locations": DIM_LOCATIONS,
    "dim_products": DIM_PRODUCTS,
    "order_lines": ORDER_LINES,
}

_SPARK_FAMILY_DIALECTS = {"spark", "lakesail", "pyspark", "velox", "databricks"}


def _column_type_for_dialect(column: dict[str, Any], dialect: str) -> str:
    column_type = cast(str, column["type"])
    if column["name"] == "order_time" and dialect.lower() in _SPARK_FAMILY_DIALECTS:
        return "STRING"
    return column_type


def get_create_table_sql(
    table_name: str,
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate a CREATE TABLE statement for the requested CoffeeShop table."""
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}")

    table = TABLES[table_name]
    columns: list[str] = []

    for column in cast(list[dict[str, Any]], table["columns"]):
        column_sql = f"{column['name']} {_column_type_for_dialect(column, dialect)}"
        if column.get("primary_key") and enable_primary_keys:
            column_sql += " PRIMARY KEY"
        columns.append(column_sql)

    if enable_foreign_keys:
        for column in cast(list[dict[str, Any]], table["columns"]):
            foreign_key = column.get("foreign_key")
            if foreign_key:
                ref_table, ref_column = cast(str, foreign_key).split(".")
                columns.append(f"FOREIGN KEY ({column['name']}) REFERENCES {ref_table}({ref_column})")

    statement = f"CREATE TABLE {table['name']} (\n"
    statement += ",\n".join(f"  {col}" for col in columns)
    statement += "\n);"
    return statement


def get_all_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Render CREATE TABLE statements for all CoffeeShop tables in dependency order."""
    table_order = ["dim_locations", "dim_products", "order_lines"]
    statements = []
    for table_name in table_order:
        statements.append(
            get_create_table_sql(
                table_name,
                dialect=dialect,
                enable_primary_keys=enable_primary_keys,
                enable_foreign_keys=enable_foreign_keys,
            )
        )
    return "\n\n".join(statements)


def get_tunings() -> BenchmarkTunings:
    """Return default tuning recommendations for the CoffeeShop schema."""
    tunings = BenchmarkTunings("coffeeshop")

    tunings.add_table_tuning(
        TableTuning(
            table_name="order_lines",
            partitioning=[TuningColumn("order_date", "DATE", 1)],
            clustering=[TuningColumn("region", "VARCHAR(20)", 1), TuningColumn("location_id", "VARCHAR(16)", 2)],
            sorting=[TuningColumn("order_id", "BIGINT", 1), TuningColumn("line_number", "INTEGER", 2)],
        )
    )

    tunings.add_table_tuning(
        TableTuning(
            table_name="dim_locations",
            distribution=[TuningColumn("region", "VARCHAR(20)", 1)],
            sorting=[TuningColumn("location_id", "VARCHAR(16)", 1)],
        )
    )

    tunings.add_table_tuning(
        TableTuning(
            table_name="dim_products",
            distribution=[TuningColumn("subcategory", "VARCHAR(30)", 1)],
            sorting=[TuningColumn("product_id", "INTEGER", 1)],
        )
    )

    return tunings


__all__ = [
    "DIM_LOCATIONS",
    "DIM_PRODUCTS",
    "ORDER_LINES",
    "TABLES",
    "get_create_table_sql",
    "get_all_create_table_sql",
    "get_tunings",
]
