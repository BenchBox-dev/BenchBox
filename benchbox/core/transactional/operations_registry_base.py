from __future__ import annotations

from typing import Generic, TypeVar

from benchbox.core.primitives_utils import get_entry_by_id

OperationT = TypeVar("OperationT")


class OperationsRegistryBase(Generic[OperationT]):
    def __init__(self, version: int, operations: dict[str, OperationT]) -> None:
        self._catalog_version = version
        self._operations = operations
        self._category_index = self._build_category_index(operations)

    @staticmethod
    def _build_category_index(operations: dict[str, OperationT]) -> dict[str, list[str]]:
        category_index: dict[str, list[str]] = {}
        for operation_id, operation in operations.items():
            category = operation.category.lower()
            category_index.setdefault(category, []).append(operation_id)
        return category_index

    @property
    def catalog_version(self) -> int:
        return self._catalog_version

    def get_operation(self, operation_id: str) -> OperationT:
        return get_entry_by_id(self._operations, operation_id, "operation")

    def get_all_operations(self) -> dict[str, OperationT]:
        return self._operations.copy()

    def get_operations_by_category(self, category: str) -> dict[str, OperationT]:
        normalized = category.lower()
        operation_ids = self._category_index.get(normalized, [])
        return {op_id: self._operations[op_id] for op_id in operation_ids}

    def get_operation_categories(self) -> list[str]:
        return sorted(self._category_index.keys())

    def get_operation_count(self) -> int:
        return len(self._operations)

    def get_category_count(self, category: str) -> int:
        normalized = category.lower()
        return len(self._category_index.get(normalized, []))
