"""Flight data benchmark schema definitions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
FLIGHT_SCHEMA: dict[str, dict[str, Any]] = _SCHEMA_SPECS["schema"]
_TYPE_MAPPINGS: dict[str, dict[str, str]] = _SCHEMA_SPECS["type_mappings"]
_TABLE_ORDER = list(_SCHEMA_SPECS["table_order"])


def get_create_tables_sql(
    dialect: str = "standard",
    include_constraints: bool = True,
) -> str:
    """Generate CREATE TABLE SQL statements for the flight data benchmark.

    Args:
        dialect: SQL dialect (standard, duckdb, postgres, clickhouse, snowflake)
        include_constraints: Include PRIMARY KEY constraints

    Returns:
        SQL script for creating all tables
    """
    type_map = _TYPE_MAPPINGS.get(dialect, _TYPE_MAPPINGS["standard"])
    statements = []

    for table_name in _TABLE_ORDER:
        table_def = FLIGHT_SCHEMA[table_name]
        columns = table_def["columns"]
        primary_key = table_def.get("primary_key", [])

        col_defs = []
        for col_name, col_info in columns.items():
            col_type = type_map.get(col_info["type"], col_info["type"])
            col_def = f"    {col_name} {col_type}"
            col_defs.append(col_def)

        if include_constraints and primary_key and dialect not in ("clickhouse",):
            pk_cols = ", ".join(primary_key)
            col_defs.append(f"    PRIMARY KEY ({pk_cols})")

        cols_sql = ",\n".join(col_defs)
        stmt = f"CREATE TABLE IF NOT EXISTS {table_name} (\n{cols_sql}\n)"
        statements.append(stmt)

    return ";\n\n".join(statements) + ";"
