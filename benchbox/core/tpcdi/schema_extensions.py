"""TPC-DI schema extensions for publication-ready coverage."""

from pathlib import Path
from typing import Any

import yaml


def _load_extension_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_extension_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_EXTENSION_SPECS = _load_extension_specs()
_EXTENSION_TABLE_DEFS = {entry["id"]: entry for entry in _EXTENSION_SPECS["extension_tables"]}
globals().update({symbol: entry["schema"] for symbol, entry in _EXTENSION_TABLE_DEFS.items()})

EXTENSION_TABLES = {entry["key"]: globals()[symbol] for symbol, entry in _EXTENSION_TABLE_DEFS.items()}


def get_extended_table_order() -> list[str]:
    """Get the dependency order for creating extended tables."""
    return list(_EXTENSION_SPECS["table_order"])


def get_foreign_key_constraints() -> dict[str, list[dict[str, Any]]]:
    """Get foreign key constraint definitions for extended tables."""
    return dict(_EXTENSION_SPECS["foreign_key_constraints"])


def get_extended_create_table_sql(
    table_name: str,
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for extended TPC-DI tables."""
    if table_name not in EXTENSION_TABLES:
        raise ValueError(f"Unknown extended table: {table_name}. Available: {', '.join(EXTENSION_TABLES.keys())}")

    table = EXTENSION_TABLES[table_name]
    columns = []

    for col in table["columns"]:
        col_def = f"{col['name']} {col['type']}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        columns.append(col_def)

    sql = f"CREATE TABLE IF NOT EXISTS {table['name']} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)

    if "primary_key" in table and enable_primary_keys:
        sql += f",\n  PRIMARY KEY ({', '.join(table['primary_key'])})"

    sql += "\n);"
    return sql


def get_all_extended_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for all extended TPC-DI tables."""
    return "\n\n".join(
        get_extended_create_table_sql(table_name, dialect, enable_primary_keys, enable_foreign_keys)
        for table_name in get_extended_table_order()
    )
