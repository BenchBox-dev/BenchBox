from __future__ import annotations

from dataclasses import dataclass
from importlib import resources as _resources

from benchbox.core.primitives.catalog.loader import ResultContract, load_query_catalog

CATALOG_FILENAME = "queries.yaml"
resources = _resources


class PrimitivesCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class PrimitiveQuery:
    id: str
    category: str
    sql: str
    description: str | None = None
    variants: dict[str, str] | None = None
    skip_on: list[str] | None = None
    result_contract: ResultContract | None = None


@dataclass(frozen=True)
class PrimitiveCatalog:
    version: int
    queries: dict[str, PrimitiveQuery]


def load_primitives_catalog() -> PrimitiveCatalog:
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
