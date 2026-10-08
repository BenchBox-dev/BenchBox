# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.primitives.catalog.loader import load_query_catalog

CATALOG_FILENAME = "queries.yaml"


class MetadataCatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetadataQuery:
    id: str
    category: str
    sql: str
    description: str | None = None
    variants: dict[str, str] | None = None
    skip_on: list[str] | None = None


@dataclass(frozen=True)
class MetadataCatalog:
    version: int
    queries: dict[str, MetadataQuery]


def load_metadata_catalog() -> MetadataCatalog:
    return load_query_catalog(
        package=__package__,
        catalog_filename=CATALOG_FILENAME,
        error_class=MetadataCatalogError,
        label="Metadata Primitives",
        build_query=MetadataQuery,
        build_catalog=MetadataCatalog,
    )


__all__ = [
    "MetadataCatalog",
    "MetadataCatalogError",
    "MetadataQuery",
    "load_metadata_catalog",
]
