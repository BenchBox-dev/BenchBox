# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from benchbox.core.metadata_primitives.catalog import MetadataQuery, load_metadata_catalog
from benchbox.core.primitives_utils import get_entry_by_id
from benchbox.core.query_catalog_base import BaseQueryCatalogMixin


class MetadataPrimitivesQueryManager(BaseQueryCatalogMixin):
    def __init__(self) -> None:
        catalog = load_metadata_catalog()
        self._catalog_version = catalog.version
        self._entries = catalog.queries
        self._queries: dict[str, str] = {query_id: entry.sql for query_id, entry in catalog.queries.items()}
        self._category_index = self._build_category_index(catalog.queries)

    @staticmethod
    def _build_category_index(queries: dict[str, MetadataQuery]) -> dict[str, list[str]]:
        category_index: dict[str, list[str]] = {}
        for query_id, entry in queries.items():
            category = entry.category.lower()
            category_index.setdefault(category, []).append(query_id)
        return category_index

    @property
    def catalog_version(self) -> int:
        return self._catalog_version

    def get_query_entry(self, query_id: str) -> MetadataQuery:
        return get_entry_by_id(self._entries, query_id, "query")

    def get_all_queries(self) -> dict[str, str]:
        return self._queries.copy()

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        normalized = category.lower()
        query_ids = self._category_index.get(normalized, [])
        return {query_id: self._queries[query_id] for query_id in query_ids}

    def get_query_categories(self) -> list[str]:
        return sorted(self._category_index.keys())

    def get_queries_for_dialect(self, dialect: str) -> dict[str, str]:
        normalized_dialect = dialect.lower().strip()
        result = {}

        for query_id, entry in self._entries.items():
            if entry.skip_on and normalized_dialect in entry.skip_on:
                continue

            if entry.variants and normalized_dialect in entry.variants:
                result[query_id] = entry.variants[normalized_dialect]
            else:
                result[query_id] = entry.sql

        return result


__all__ = ["MetadataPrimitivesQueryManager"]
