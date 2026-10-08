from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class VariantGenerator(ABC):
    def __init__(self, variant_id: int, description: str) -> None:
        self.variant_id = variant_id
        self.description = description

    @abstractmethod
    def generate(self, base_query: str, params: dict[str, Any] | None = None) -> str:
        pass

    def get_description(self) -> str:
        return self.description


class StaticSQLVariant(VariantGenerator):
    def __init__(self, variant_id: int, description: str, sql: str) -> None:
        super().__init__(variant_id, description)
        self._sql = sql

    def generate(self, base_query: str, params: dict[str, Any] | None = None) -> str:
        sql = self._sql
        for key, value in (params or {}).items():
            sql = sql.replace("{" + key + "}", str(value))
        return sql


__all__ = ["VariantGenerator", "StaticSQLVariant"]
