from __future__ import annotations

from enum import Enum
from typing import NamedTuple

from benchbox.core.schema_primitives import BaseSchemaTable


class DataType(Enum):
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL(15,2)"
    VARCHAR = "VARCHAR"
    CHAR = "CHAR"
    DATE = "DATE"
    TIME = "TIME"
    TIMESTAMP = "TIMESTAMP"


class Column(NamedTuple):
    name: str
    data_type: DataType
    size: int | None = None
    nullable: bool = False
    primary_key: bool = False
    foreign_key: tuple[str, str] | None = None

    def get_sql_type(self) -> str:
        if self.data_type in (DataType.VARCHAR, DataType.CHAR) and self.size is not None:
            return f"{self.data_type.value}({self.size})"
        return self.data_type.value


class Table(BaseSchemaTable):
    def __init__(self, name: str, columns: list[Column]) -> None:
        super().__init__(name, columns)


__all__ = ["DataType", "Column", "Table"]
