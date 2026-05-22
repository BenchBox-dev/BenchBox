"""Schema definition for the TPC-DS One Big Table benchmark.

This module builds a single wide table (`tpcds_sales_returns_obt`) that merges
all TPC-DS sales facts, returns facts, and relevant dimension attributes into
one relation. Column definitions carry lineage metadata so the ETL step can
project channel-specific columns into a canonical layout while keeping a single
table as the only benchmark artifact.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from benchbox.core.tpcds.schema.models import DataType, Table
from benchbox.core.tpcds.schema.tables import (
    CALL_CENTER,
    CATALOG_PAGE,
    CUSTOMER,
    CUSTOMER_ADDRESS,
    CUSTOMER_DEMOGRAPHICS,
    DATE_DIM,
    HOUSEHOLD_DEMOGRAPHICS,
    ITEM,
    PROMOTION,
    REASON,
    SHIP_MODE,
    STORE,
    TIME_DIM,
    WAREHOUSE,
    WEB_PAGE,
    WEB_SITE,
)

OBT_TABLE_NAME = "tpcds_sales_returns_obt"
DEFAULT_MODE = "full"
ALLOWED_MODES = {DEFAULT_MODE, "minimal"}


@dataclass(frozen=True)
class OBTColumn:
    """Column definition with lineage metadata for the OBT table."""

    name: str
    data_type: DataType
    size: int | None = None
    nullable: bool = True
    primary_key: bool = False
    source_table: str | None = None
    source_column: str | None = None
    role: str | None = None
    description: str | None = None

    def sql_type(self) -> str:
        """Return the SQL type string for this column."""
        if self.data_type in (DataType.VARCHAR, DataType.CHAR) and self.size is not None:
            return f"{self.data_type.value}({self.size})"
        return self.data_type.value


@dataclass(frozen=True)
class DimensionRole:
    """Represents a dimension role to inline into the OBT."""

    name: str
    table: Table
    prefix: str
    description: str | None = None


@dataclass(frozen=True)
class OBTTable:
    """Represents the single OBT table and generates DDL."""

    name: str
    columns: tuple[OBTColumn, ...]

    def get_primary_key(self) -> list[str]:
        """Return primary key column names if defined."""
        return [col.name for col in self.columns if col.primary_key]

    def get_create_table_sql(self) -> str:
        """Generate CREATE TABLE DDL for the OBT."""
        column_defs: list[str] = []
        pk_columns = self.get_primary_key()

        for col in self.columns:
            col_def = f"{col.name} {col.sql_type()}"
            if not col.nullable:
                col_def += " NOT NULL"
            column_defs.append(col_def)

        if pk_columns:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        sql = f"CREATE TABLE {self.name} (\n    "
        sql += ",\n    ".join(column_defs)
        sql += "\n);"
        return sql


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_DIMENSION_TABLES_BY_NAME = {
    table.name: table
    for table in (
        CALL_CENTER,
        CATALOG_PAGE,
        CUSTOMER,
        CUSTOMER_ADDRESS,
        CUSTOMER_DEMOGRAPHICS,
        DATE_DIM,
        HOUSEHOLD_DEMOGRAPHICS,
        ITEM,
        PROMOTION,
        REASON,
        SHIP_MODE,
        STORE,
        TIME_DIM,
        WAREHOUSE,
        WEB_PAGE,
        WEB_SITE,
    )
}


def _column_from_spec(spec: dict[str, Any]) -> OBTColumn:
    return OBTColumn(
        name=spec["name"],
        data_type=DataType[spec["data_type"]],
        size=spec.get("size"),
        nullable=spec.get("nullable", True),
        primary_key=spec.get("primary_key", False),
        source_table=spec.get("source_table"),
        source_column=spec.get("source_column"),
        role=spec.get("role"),
        description=spec.get("description"),
    )


def _dimension_role_from_spec(spec: dict[str, Any]) -> DimensionRole:
    return DimensionRole(
        name=spec["name"],
        table=_DIMENSION_TABLES_BY_NAME[spec["table"]],
        prefix=spec["prefix"],
        description=spec.get("description"),
    )


_SCHEMA_SPECS = _load_schema_specs()
CORE_FACT_COLUMNS: tuple[OBTColumn, ...] = tuple(_column_from_spec(spec) for spec in _SCHEMA_SPECS["core_fact_columns"])
DIMENSION_ROLES_FULL: tuple[DimensionRole, ...] = tuple(
    _dimension_role_from_spec(spec) for spec in _SCHEMA_SPECS["dimension_roles_full"]
)
MINIMAL_DIMENSION_ROLE_NAMES = set(_SCHEMA_SPECS["minimal_dimension_role_names"])
INCOME_BAND_COLUMNS: tuple[OBTColumn, ...] = tuple(
    _column_from_spec(spec) for spec in _SCHEMA_SPECS["income_band_columns"]
)
MINIMAL_INCOME_BAND_ROLES = set(_SCHEMA_SPECS["minimal_income_band_roles"])


def _prefixed_columns(role: DimensionRole) -> list[OBTColumn]:
    """Clone dimension columns with the provided prefix and role metadata."""
    prefixed: list[OBTColumn] = []
    for column in role.table.columns:
        prefixed.append(
            OBTColumn(
                name=f"{role.prefix}{column.name.lower()}",
                data_type=column.data_type,
                size=column.size,
                nullable=True,
                source_table=role.table.name,
                source_column=column.name,
                role=role.name,
                description=role.description,
            )
        )
    return prefixed


def _build_dimension_columns(role_filter: Iterable[DimensionRole]) -> list[OBTColumn]:
    """Materialize prefixed columns for the provided roles."""
    columns: list[OBTColumn] = []
    for role in role_filter:
        columns.extend(_prefixed_columns(role))
    return columns


@cache
def get_obt_columns(mode: str = DEFAULT_MODE) -> tuple[OBTColumn, ...]:
    """Return OBT columns for the requested mode."""
    mode_lower = mode.lower()
    if mode_lower not in ALLOWED_MODES:
        raise ValueError(f"Unsupported mode '{mode}'. Allowed modes: {sorted(ALLOWED_MODES)}")

    if mode_lower == "minimal":
        roles = [r for r in DIMENSION_ROLES_FULL if r.name in MINIMAL_DIMENSION_ROLE_NAMES]
        income_band_cols = [c for c in INCOME_BAND_COLUMNS if c.role in MINIMAL_INCOME_BAND_ROLES]
    else:
        roles = list(DIMENSION_ROLES_FULL)
        income_band_cols = list(INCOME_BAND_COLUMNS)

    columns: list[OBTColumn] = list(CORE_FACT_COLUMNS) + _build_dimension_columns(roles) + income_band_cols

    # Ensure unique column names to avoid ambiguous projections
    names = [col.name for col in columns]
    name_counts = Counter(names)
    duplicates = sorted(name for name, count in name_counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate column names detected in OBT schema: {duplicates}")

    return tuple(columns)


@cache
def get_obt_table(mode: str = DEFAULT_MODE) -> OBTTable:
    """Return the OBT table definition for the requested mode."""
    return OBTTable(name=OBT_TABLE_NAME, columns=get_obt_columns(mode))


def get_column_lineage(mode: str = DEFAULT_MODE) -> dict[str, dict[str, str | None]]:
    """Expose a mapping of OBT column name to source metadata."""
    lineage: dict[str, dict[str, str | None]] = {}
    for col in get_obt_columns(mode):
        lineage[col.name] = {
            "source_table": col.source_table,
            "source_column": col.source_column,
            "role": col.role,
            "description": col.description,
        }
    return lineage


# Default table definition using the full column set
TPCDS_OBT_TABLE = get_obt_table()

__all__ = [
    "ALLOWED_MODES",
    "DEFAULT_MODE",
    "OBTColumn",
    "OBT_TABLE_NAME",
    "TPCDS_OBT_TABLE",
    "get_column_lineage",
    "get_obt_columns",
    "get_obt_table",
]
