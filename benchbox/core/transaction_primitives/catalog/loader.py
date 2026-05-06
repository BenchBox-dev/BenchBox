"""Utilities for loading the Transaction Primitives benchmark operation catalog.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from benchbox.core.primitives.catalog.loader import load_operations_catalog

CATALOG_FILENAME = "operations.yaml"


class TransactionPrimitivesCatalogError(RuntimeError):
    """Raised when the Transaction Primitives operation catalog cannot be loaded or is invalid."""


@dataclass(frozen=True)
class ValidationQuery:
    """Representation of a validation query for a write operation.

    Field-set parity with ``write_primitives.catalog.loader.ValidationQuery``
    is enforced by ``tests/unit/core/primitives/test_loader_parity.py``;
    no current transaction_primitives operation uses the tolerance bounds
    or per-platform overrides, but the dataclass accepts them so the
    shared loader's forwarding contract is uniform across consumers.
    """

    id: str
    sql: str
    expected_rows: int | None = None
    expected_rows_min: int | None = None
    expected_rows_max: int | None = None
    expected_values: dict[str, Any] | None = None
    check_expression: str | None = None
    expected_value_min: float | None = None
    expected_value_max: float | None = None
    platform_overrides: dict[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True)
class WriteOperation:
    """Representation of a single write operation entry."""

    id: str
    category: str
    description: str
    write_sql: str
    validation_queries: list[ValidationQuery] = field(default_factory=list)
    cleanup_sql: str | None = None
    expected_rows_affected: int | None = None
    file_dependencies: list[str] = field(default_factory=list)
    platform_overrides: dict[str, str] = field(default_factory=dict)
    requires_setup: bool = True  # Whether operation requires staging tables to be set up


@dataclass(frozen=True)
class TransactionOperationsCatalog:
    """Container for the write operations catalog."""

    version: int
    operations: dict[str, WriteOperation]


def load_transaction_primitives_catalog() -> TransactionOperationsCatalog:
    """Load and validate the transaction primitives operation catalog from package resources.

    Returns:
        TransactionOperationsCatalog containing all operations

    Raises:
        TransactionPrimitivesCatalogError: If catalog cannot be loaded or is invalid
    """
    return load_operations_catalog(
        package=__package__,
        catalog_filename=CATALOG_FILENAME,
        error_class=TransactionPrimitivesCatalogError,
        label="Transaction Primitives",
        build_validation_query=ValidationQuery,
        build_operation=WriteOperation,
        build_catalog=TransactionOperationsCatalog,
    )


__all__ = [
    "TransactionOperationsCatalog",
    "WriteOperation",
    "ValidationQuery",
    "TransactionPrimitivesCatalogError",
    "load_transaction_primitives_catalog",
]
