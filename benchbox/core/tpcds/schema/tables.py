"""Declarative table definitions for the TPC-DS schema."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import Column, DataType, Table


def _column(spec: list[Any]) -> Column:
    name, data_type, size, nullable, primary_key, foreign_key = spec
    return Column(
        name,
        DataType[data_type],
        size=size,
        nullable=nullable,
        primary_key=primary_key,
        foreign_key=tuple(foreign_key) if foreign_key is not None else None,
    )


def _table(name: str, columns: list[list[Any]]) -> Table:
    return Table(name, [_column(column) for column in columns])


def _load_table_specs() -> dict[str, Table]:
    with (Path(__file__).with_name("table_specs.yaml")).open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return {entry["id"]: _table(entry["name"], entry["columns"]) for entry in raw["tables"]}


_TABLES = _load_table_specs()
globals().update(_TABLES)

__all__ = list(_TABLES)
