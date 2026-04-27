"""Core data models for TPC-DS schema definitions."""

from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from benchbox.core.schema_primitives import BaseSchemaTable


class DataType(Enum):
    """Enumeration of SQL data types used in TPC-DS."""

    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL(15,2)"
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"


class Column(NamedTuple):
    """Represents a column in a database table."""

    name: str
    data_type: DataType
    size: int | None = None  # For VARCHAR and CHAR types
    nullable: bool = False
    primary_key: bool = False
    foreign_key: tuple[str, str] | None = None  # (table_name, column_name)

    def get_sql_type(self) -> str:
        """Get the SQL data type string for this column."""
        if self.data_type in (DataType.VARCHAR, DataType.CHAR) and self.size is not None:
            return f"{self.data_type.value}({self.size})"
        return self.data_type.value


class Table(BaseSchemaTable):
    """Represents a TPC-DS table with its columns and constraints."""

    def __init__(self, name: str, columns: list[Column]) -> None:
        super().__init__(name, columns)


__all__ = ["DataType", "Column", "Table"]
