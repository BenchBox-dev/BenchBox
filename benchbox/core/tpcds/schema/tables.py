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

STORE = _TABLES["STORE"]
DATE_DIM = _TABLES["DATE_DIM"]
TIME_DIM = _TABLES["TIME_DIM"]
ITEM = _TABLES["ITEM"]
CUSTOMER = _TABLES["CUSTOMER"]
CUSTOMER_DEMOGRAPHICS = _TABLES["CUSTOMER_DEMOGRAPHICS"]
HOUSEHOLD_DEMOGRAPHICS = _TABLES["HOUSEHOLD_DEMOGRAPHICS"]
INCOME_BAND = _TABLES["INCOME_BAND"]
PROMOTION = _TABLES["PROMOTION"]
CUSTOMER_ADDRESS = _TABLES["CUSTOMER_ADDRESS"]
WAREHOUSE = _TABLES["WAREHOUSE"]
WEB_SITE = _TABLES["WEB_SITE"]
WEB_PAGE = _TABLES["WEB_PAGE"]
REASON = _TABLES["REASON"]
CALL_CENTER = _TABLES["CALL_CENTER"]
CATALOG_PAGE = _TABLES["CATALOG_PAGE"]
SHIP_MODE = _TABLES["SHIP_MODE"]
STORE_SALES = _TABLES["STORE_SALES"]
STORE_RETURNS = _TABLES["STORE_RETURNS"]
WEB_SALES = _TABLES["WEB_SALES"]
WEB_RETURNS = _TABLES["WEB_RETURNS"]
CATALOG_SALES = _TABLES["CATALOG_SALES"]
CATALOG_RETURNS = _TABLES["CATALOG_RETURNS"]
INVENTORY = _TABLES["INVENTORY"]
DBGEN_VERSION = _TABLES["DBGEN_VERSION"]

__all__ = [
    "STORE",
    "DATE_DIM",
    "TIME_DIM",
    "ITEM",
    "CUSTOMER",
    "CUSTOMER_DEMOGRAPHICS",
    "HOUSEHOLD_DEMOGRAPHICS",
    "INCOME_BAND",
    "PROMOTION",
    "CUSTOMER_ADDRESS",
    "WAREHOUSE",
    "WEB_SITE",
    "WEB_PAGE",
    "REASON",
    "CALL_CENTER",
    "CATALOG_PAGE",
    "SHIP_MODE",
    "STORE_SALES",
    "STORE_RETURNS",
    "WEB_SALES",
    "WEB_RETURNS",
    "CATALOG_SALES",
    "CATALOG_RETURNS",
    "INVENTORY",
    "DBGEN_VERSION",
]
