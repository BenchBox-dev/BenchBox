"""Schema normalization helpers for DataFrame loading paths."""

from __future__ import annotations

from typing import Any


def iter_schema_columns(table_schema: Any) -> list[Any]:
    """Return a table schema's columns across BenchBox schema shapes."""
    if isinstance(table_schema, dict):
        columns = table_schema.get("columns", [])
        if isinstance(columns, dict):
            normalized = []
            for name, spec in columns.items():
                column = dict(spec) if isinstance(spec, dict) else {"type": spec}
                column.setdefault("name", name)
                normalized.append(column)
            return normalized
        if isinstance(columns, (list, tuple)):
            return list(columns)
        return []

    columns = getattr(table_schema, "columns", None)
    if columns is None:
        return []
    return list(columns)


def column_name(column: Any) -> str | None:
    """Return a schema column's name, if present."""
    if isinstance(column, dict):
        name = column.get("name")
    else:
        name = getattr(column, "name", None)
    return str(name) if name else None


def column_sql_type(column: Any, default: str = "VARCHAR") -> str:
    """Return a schema column's SQL type across dict and object schemas."""
    candidates: list[Any] = []
    if isinstance(column, dict):
        candidates.append(column.get("type") or column.get("data_type"))
    else:
        for attr_name in ("get_sql_type", "sql_type"):
            attr = getattr(column, attr_name, None)
            if callable(attr):
                candidates.append(attr())
            elif attr is not None:
                candidates.append(attr)
        candidates.append(getattr(column, "data_type", None))

    for value in candidates:
        enum_value = getattr(value, "value", None)
        if isinstance(enum_value, str):
            return enum_value
        if isinstance(value, str):
            return value
    return default


def extract_schema_columns(schema: Any) -> dict[str, list[dict[str, str]]]:
    """Normalize a benchmark schema to table -> column definitions."""
    if not isinstance(schema, dict):
        return {}

    result: dict[str, list[dict[str, str]]] = {}
    for table_name, table_schema in schema.items():
        columns = []
        for column in iter_schema_columns(table_schema):
            name = column_name(column)
            if name:
                columns.append({"name": name, "type": column_sql_type(column)})
        if columns:
            result[str(table_name).lower()] = columns
    return result


def get_benchmark_schema_columns(benchmark: Any) -> dict[str, list[dict[str, str]]]:
    """Extract normalized schema columns from a benchmark instance."""
    if not hasattr(benchmark, "get_schema"):
        return {}
    try:
        return extract_schema_columns(benchmark.get_schema())
    except Exception:
        return {}
