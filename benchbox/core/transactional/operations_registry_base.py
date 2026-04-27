"""Shared operation-registry base for transactional benchmark families.

``OperationsRegistryBase[OperationT]`` consolidates the near-identical
``TransactionOperationsManager`` and ``WriteOperationsManager`` classes.
Each subclass loads its spec-specific catalog in its own ``__init__`` and
passes the loaded data to ``super().__init__()``.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from benchbox.core.primitives_utils import get_entry_by_id

OperationT = TypeVar("OperationT")


class OperationsRegistryBase(Generic[OperationT]):
    """Manager base class for benchmark operations backed by a YAML catalog.

    Shared by ``TransactionOperationsManager`` and ``WriteOperationsManager``.
    Subclasses load their catalog in ``__init__`` and call::

        super().__init__(catalog.version, catalog.operations)

    All lookup and introspection methods are provided here.
    """

    def __init__(self, version: int, operations: dict[str, OperationT]) -> None:
        """Initialise from pre-loaded catalog data.

        Args:
            version: Version number declared in the catalog file.
            operations: Mapping from operation ID to operation object.
        """
        self._catalog_version = version
        self._operations = operations
        self._category_index = self._build_category_index(operations)

    @staticmethod
    def _build_category_index(operations: dict[str, OperationT]) -> dict[str, list[str]]:
        """Build index mapping categories to operation IDs.

        Args:
            operations: Dictionary of operations

        Returns:
            Dictionary mapping category names to lists of operation IDs
        """
        category_index: dict[str, list[str]] = {}
        for operation_id, operation in operations.items():
            category = operation.category.lower()  # type: ignore[attr-defined]
            category_index.setdefault(category, []).append(operation_id)
        return category_index

    @property
    def catalog_version(self) -> int:
        """Return the version declared in the catalog file.

        Returns:
            Catalog version number
        """
        return self._catalog_version

    def get_operation(self, operation_id: str) -> OperationT:
        """Get a write operation by ID.

        Args:
            operation_id: Operation identifier

        Returns:
            Operation object

        Raises:
            ValueError: If operation_id is invalid
        """
        return get_entry_by_id(self._operations, operation_id, "operation")

    def get_all_operations(self) -> dict[str, OperationT]:
        """Get all operations.

        Returns:
            Dictionary mapping operation IDs to operation objects
        """
        return self._operations.copy()

    def get_operations_by_category(self, category: str) -> dict[str, OperationT]:
        """Get operations filtered by category.

        Args:
            category: Category name (e.g., 'insert', 'update', 'delete')

        Returns:
            Dictionary mapping operation IDs to operation objects for the category
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
