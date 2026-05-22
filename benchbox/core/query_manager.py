"""Shared query manager primitives.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional


def copy_query_metadata(metadata: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return a shallow metadata copy that also copies list values."""
    return {
        query_id: {key: value.copy() if isinstance(value, list) else value for key, value in query_metadata.items()}
        for query_id, query_metadata in metadata.items()
    }


class ParameterizedQueryManager(ABC):
    """Base class for query managers with default-parameter expansion."""

    invalid_query_label = "query"

    def get_query(self, query_id: str, params: Optional[dict[str, Any]] = None) -> str:
        """Return a query by ID with merged default and override parameters."""
        if query_id not in self._queries:
            available = ", ".join(sorted(self._queries.keys()))
            raise ValueError(
                f"Invalid {self.invalid_query_label} ID: {query_id}. Available: {available}",
            )

        template = self._queries[query_id]
        merged_params = self._generate_default_params(query_id)
        if params:
            merged_params.update(params)
        return template.format(**merged_params)

    def get_all_queries(self) -> dict[str, str]:
        """Return all queries rendered with default parameters."""
        return {query_id: self.get_query(query_id) for query_id in self._queries}

    def _get_query_metadata_copy(
        self,
        metadata: dict[str, dict[str, Any]],
        query_id: str,
        query_label: str,
    ) -> dict[str, Any]:
        """Return a copy of query metadata, raising a consistent invalid-ID error."""
        if query_id not in metadata:
            available = ", ".join(sorted(metadata.keys()))
            raise ValueError(f"Invalid {query_label} ID: {query_id}. Available: {available}")
        return metadata[query_id].copy()

    def _validate_selector_value(
        self, value: str, valid_values: set[str], selector_name: str, *, plural: str | None = None
    ) -> None:
        """Validate selector values (category/severity/etc.) against allowed options."""
        if value not in valid_values:
            plural_label = plural or f"{selector_name}s"
            options = ", ".join(sorted(valid_values))
            raise ValueError(f"Invalid {selector_name}: {value}. Valid {plural_label}: {options}")

    def _query_ids_by_metadata(self, metadata: dict[str, dict[str, Any]], key: str, expected_value: Any) -> list[str]:
        """Return query IDs whose metadata key matches the expected value."""
        return [query_id for query_id, query_metadata in metadata.items() if query_metadata.get(key) == expected_value]

    def _query_ids_for_valid_metadata(
        self,
        metadata: dict[str, dict[str, Any]],
        key: str,
        value: str,
        selector_name: str,
        *,
        plural: str | None = None,
    ) -> list[str]:
        """Validate a metadata selector and return matching query IDs."""
        valid_values = {query_metadata[key] for query_metadata in metadata.values() if key in query_metadata}
        self._validate_selector_value(value, valid_values, selector_name, plural=plural)
        return self._query_ids_by_metadata(metadata, key, value)

    @abstractmethod
    def _generate_default_params(self, query_id: str) -> dict[str, Any]:
        """Return default parameters for a specific query."""
