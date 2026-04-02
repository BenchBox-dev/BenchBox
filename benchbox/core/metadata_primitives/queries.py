"""Metadata Primitives benchmark query management.

Provides functionality to load and manage metadata introspection queries that test
database catalog capabilities including schema discovery, column introspection,
table statistics, and query execution plans.

All queries are defined in ``benchbox/core/metadata_primitives/catalog/queries.yaml``
and loaded at runtime.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.metadata_primitives.catalog import MetadataQuery, load_metadata_catalog
from benchbox.core.primitives_utils import get_entry_by_id
from benchbox.core.query_catalog_base import BaseQueryCatalogMixin


class MetadataPrimitivesQueryManager(BaseQueryCatalogMixin):
    """Manager for Metadata Primitives benchmark queries backed by the catalog file."""

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
        """Return the version declared in the catalog file."""
        return self._catalog_version

    # get_query() is inherited from BaseQueryCatalogMixin

    def get_query_entry(self, query_id: str) -> MetadataQuery:
        """Get the full MetadataQuery entry for a query.

        Args:
            query_id: Query identifier

        Returns:
            MetadataQuery dataclass with full metadata

        Raises:
            ValueError: If query_id is invalid
        """
        return get_entry_by_id(self._entries, query_id, "query")

    def get_all_queries(self) -> dict[str, str]:
        """Get all Metadata Primitives queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        return self._queries.copy()

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get queries filtered by category.

        Args:
            category: Category name (e.g., 'schema', 'column', 'stats', 'query')

        Returns:
            Dictionary mapping query IDs to SQL text for the category
        """
        normalized = category.lower()
        query_ids = self._category_index.get(normalized, [])
        return {query_id: self._queries[query_id] for query_id in query_ids}

    def get_query_categories(self) -> list[str]:
        """Get list of available query categories.

        Returns:
            List of category names
        """
        return sorted(self._category_index.keys())

    def get_queries_for_dialect(self, dialect: str) -> dict[str, str]:
        """Get all queries applicable to a specific dialect.

        Excludes queries marked as skip_on for the dialect and returns
        dialect-specific variants where available.

        Args:
            dialect: Target dialect name (e.g., 'duckdb', 'snowflake')

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        normalized_dialect = dialect.lower().strip()
        result = {}

        for query_id, entry in self._entries.items():
            # Skip queries not supported on this dialect
            if entry.skip_on and normalized_dialect in entry.skip_on:
                continue

            # Use dialect variant if available, otherwise base query
            if entry.variants and normalized_dialect in entry.variants:
                result[query_id] = entry.variants[normalized_dialect]
            else:
                result[query_id] = entry.sql

        return result


__all__ = ["MetadataPrimitivesQueryManager"]
