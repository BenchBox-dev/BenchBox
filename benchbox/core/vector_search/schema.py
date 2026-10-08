from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
_TABLE_DEFS = {entry["id"]: entry for entry in _SCHEMA_SPECS["tables"]}
globals().update({symbol: entry["schema"] for symbol, entry in _TABLE_DEFS.items()})

TABLES: dict[str, dict] = {entry["key"]: globals()[symbol] for symbol, entry in _TABLE_DEFS.items()}
_TABLE_ORDER = list(_SCHEMA_SPECS["table_order"])
_EMBEDDING_TYPE_MAP = dict(_SCHEMA_SPECS["embedding_type_map"])


def get_embedding_type(dialect: str = "duckdb", dimensions: int = 128) -> str:
    template = _EMBEDDING_TYPE_MAP.get(dialect.lower(), _EMBEDDING_TYPE_MAP["default"])
    return template.format(dim=dimensions)


def get_create_table_sql(
    table_name: str,
    dialect: str = "duckdb",
    dimensions: int = 128,
    enable_primary_keys: bool = True,
) -> str:
    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name!r}. Available: {list(TABLES)}")

    table = TABLES[table_name]
    embedding_type = get_embedding_type(dialect, dimensions)

    column_defs: list[str] = []
    for col in table["columns"]:
        col_type = embedding_type if col["type"] == "FLOAT_ARRAY" else col["type"]
        col_def = f"{col['name']} {col_type}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        column_defs.append(col_def)

    return f"CREATE TABLE {table['name']} (\n" + ",\n".join(f"  {c}" for c in column_defs) + "\n);"


def get_all_create_table_sql(
    dialect: str = "duckdb",
    dimensions: int = 128,
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    return "\n\n".join(get_create_table_sql(t, dialect, dimensions, enable_primary_keys) for t in _TABLE_ORDER)
