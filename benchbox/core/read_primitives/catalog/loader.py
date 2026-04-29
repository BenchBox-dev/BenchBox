"""Utilities for loading the Read Primitives benchmark query catalog."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources as _resources

from benchbox.core.primitives.catalog.loader import ResultContract, load_query_catalog

CATALOG_FILENAME = "queries.yaml"
# Backward compatibility for tests that monkeypatch loader.resources.files.
resources = _resources


class PrimitivesCatalogError(RuntimeError):
    """Raised when the Read Primitives query catalog cannot be loaded or is invalid."""


@dataclass(frozen=True)
class PrimitiveQuery:
    """Representation of a single primitive query entry."""

    id: str
    category: str
    sql: str
    description: str | None = None
    variants: dict[str, str] | None = None  # dialect -> SQL mapping
    skip_on: list[str] | None = None  # list of dialects to skip this query on
    result_contract: ResultContract | None = None


@dataclass(frozen=True)
class PrimitiveCatalog:
    """Container for the primitive query catalog."""

    version: int
    queries: dict[str, PrimitiveQuery]


def load_primitives_catalog() -> PrimitiveCatalog:
    """Load and validate the Read Primitives query catalog from package resources."""
    return load_query_catalog(
        package=__package__,
        catalog_filename=CATALOG_FILENAME,
        error_class=PrimitivesCatalogError,
        label="Read Primitives",
        build_query=PrimitiveQuery,
        build_catalog=PrimitiveCatalog,
    )


__all__ = [
    "PrimitiveCatalog",
    "PrimitiveQuery",
    "PrimitivesCatalogError",
    "ResultContract",
    "load_primitives_catalog",
    "resources",
]
