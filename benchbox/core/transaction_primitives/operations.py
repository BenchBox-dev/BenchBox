"""Transaction Primitives benchmark operation management.

Provides functionality to load and manage write operation definitions
from the YAML catalog.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.primitives_utils import get_entry_by_id
from benchbox.core.transaction_primitives.catalog import (
    WriteOperation,
    load_transaction_primitives_catalog,
)


class TransactionOperationsManager:
    """Manager for Transaction Primitives benchmark operations backed by the catalog file."""

    def __init__(self) -> None:
        """Initialize the operations manager by loading the catalog."""
        catalog = load_transaction_primitives_catalog()
        self._catalog_version = catalog.version
        self._operations = catalog.operations
        self._category_index = self._build_category_index(catalog.operations)

    @staticmethod
    def _build_category_index(operations: dict[str, WriteOperation]) -> dict[str, list[str]]:
        """Build index mapping categories to operation IDs.

        Args:
            operations: Dictionary of operations

        Returns:
            Dictionary mapping category names to lists of operation IDs
        """
        category_index: dict[str, list[str]] = {}
        for operation_id, operation in operations.items():
            category = operation.category.lower()
            category_index.setdefault(category, []).append(operation_id)
        return category_index

    @property
    def catalog_version(self) -> int:
        """Return the version declared in the catalog file.

        Returns:
            Catalog version number
        """
        return self._catalog_version

    def get_operation(self, operation_id: str) -> WriteOperation:
        """Get a write operation by ID.

        Args:
            operation_id: Operation identifier

        Returns:
            WriteOperation object

        Raises:
            ValueError: If operation_id is invalid
        """
        return get_entry_by_id(self._operations, operation_id, "operation")

    def get_all_operations(self) -> dict[str, WriteOperation]:
        """Get all write operations.

        Returns:
            Dictionary mapping operation IDs to WriteOperation objects
        """
        return self._operations.copy()

    def get_operations_by_category(self, category: str) -> dict[str, WriteOperation]:
        """Get operations filtered by category.

        Args:
            category: Category name (e.g., 'insert', 'update', 'delete')

        Returns:
            Dictionary mapping operation IDs to WriteOperation objects for the category
        """
        normalized = category.lower()
        operation_ids = self._category_index.get(normalized, [])
        return {op_id: self._operations[op_id] for op_id in operation_ids}

    def get_operation_categories(self) -> list[str]:
        """Get list of available operation categories.

        Returns:
            List of category names
        """
        return sorted(self._category_index.keys())

    def get_operation_count(self) -> int:
        """Get total number of operations.

        Returns:
            Number of operations in catalog
        """
        return len(self._operations)

    def get_category_count(self, category: str) -> int:
        """Get number of operations in a category.

        Args:
            category: Category name

        Returns:
            Number of operations in the category
        """
        normalized = category.lower()
        return len(self._category_index.get(normalized, []))


__all__ = ["TransactionOperationsManager"]
