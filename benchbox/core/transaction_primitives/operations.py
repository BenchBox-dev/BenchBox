"""Transaction Primitives benchmark operation management.

Provides functionality to load and manage write operation definitions
from the YAML catalog.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.transaction_primitives.catalog import (
    WriteOperation,
    load_transaction_primitives_catalog,
)
from benchbox.core.transactional.operations_registry_base import OperationsRegistryBase


class TransactionOperationsManager(OperationsRegistryBase[WriteOperation]):
    """Manager for Transaction Primitives benchmark operations backed by the catalog file."""

    def __init__(self) -> None:
        """Initialize the operations manager by loading the catalog."""
        catalog = load_transaction_primitives_catalog()
        super().__init__(catalog.version, catalog.operations)


__all__ = ["TransactionOperationsManager"]
