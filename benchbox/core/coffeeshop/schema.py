"""Canonical CoffeeShop benchmark schema aligned with the reference generator."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
_TABLE_DEFS = {entry["id"]: entry for entry in _SCHEMA_SPECS["tables"]}
globals().update({symbol: entry["schema"] for symbol, entry in _TABLE_DEFS.items()})

TABLES: dict[str, dict] = {entry["key"]: globals()[symbol] for symbol, entry in _TABLE_DEFS.items()}
_TABLE_ORDER = list(_SCHEMA_SPECS["table_order"])

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
    return "\n\n".join(
        get_create_table_sql(
            table_name,
            dialect=dialect,
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )
        for table_name in _TABLE_ORDER
    )


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
    *_TABLE_DEFS,
    "TABLES",
    "get_create_table_sql",
    "get_all_create_table_sql",
    "get_tunings",
]
