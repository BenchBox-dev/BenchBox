"""Utilities for loading the AI Primitives benchmark query catalog.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

import yaml

CATALOG_FILENAME = "queries.yaml"


class AICatalogError(RuntimeError):
    """Raised when the AI Primitives query catalog cannot be loaded or is invalid."""


@dataclass(frozen=True)
class AIQuery:
    """Representation of a single AI query entry.

    Attributes:
        id: Unique query identifier
        category: Query category (generative, nlp, transform, embedding)
        sql: Base SQL query text
        description: Human-readable description
        variants: Platform-specific SQL variants {dialect: sql}
        skip_on: List of platforms where query is not supported
        model: Default model to use (can be overridden at runtime)
        estimated_tokens: Estimated input tokens per row
        batch_size: Recommended batch size for execution
        cost_per_1k_tokens: Estimated cost per 1000 tokens (USD)
    """

    id: str
    category: str
    sql: str
    description: str | None = None
    variants: dict[str, str] | None = None
    skip_on: list[str] | None = None
    model: str | None = None
    estimated_tokens: int = 100
    batch_size: int = 10
    cost_per_1k_tokens: float = 0.001


@dataclass(frozen=True)
class AICatalog:
    """Container for the AI query catalog."""

    version: int
    queries: dict[str, AIQuery]


def _load_catalog_payload() -> dict:
    try:
        catalog_file = resources.files(__package__).joinpath(CATALOG_FILENAME)
    except (AttributeError, FileNotFoundError) as exc:
        raise AICatalogError("AI Primitives query catalog resource not found") from exc

    try:
        with catalog_file.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
    except OSError as exc:
        raise AICatalogError("Unable to read AI Primitives query catalog") from exc
    except yaml.YAMLError as exc:
        raise AICatalogError("Invalid YAML in AI Primitives query catalog") from exc

    if not isinstance(payload, dict):
        raise AICatalogError("AI Primitives query catalog must be a mapping")
    return payload


def _parse_variants(query_id: str, raw_variants: object) -> dict[str, str] | None:
    if raw_variants is None:
        return None
    if not isinstance(raw_variants, dict):
        raise AICatalogError(f"Catalog entry '{query_id}' has invalid 'variants'; expected mapping of dialect -> SQL")
    variants: dict[str, str] = {}
    for dialect, variant_sql in raw_variants.items():
        if not isinstance(dialect, str) or not dialect.strip():
            raise AICatalogError(f"Catalog entry '{query_id}' variant dialect must be a non-empty string")
        if not isinstance(variant_sql, str) or not variant_sql.strip():
            raise AICatalogError(f"Catalog entry '{query_id}' variant SQL for dialect '{dialect}' must be non-empty")
        variants[dialect.lower().strip()] = variant_sql
    return variants


def _parse_skip_on(query_id: str, raw_skip_on: object) -> list[str] | None:
    if raw_skip_on is None:
        return None
    if not isinstance(raw_skip_on, list):
        raise AICatalogError(f"Catalog entry '{query_id}' has invalid 'skip_on'; expected list of dialects")
    skip_on: list[str] = []
    for dialect in raw_skip_on:
        if not isinstance(dialect, str) or not dialect.strip():
            raise AICatalogError(f"Catalog entry '{query_id}' skip_on dialect must be a non-empty string")
        skip_on.append(dialect.lower().strip())
    return skip_on


def _parse_ai_numeric_fields(query_id: str, entry: dict) -> tuple[int, int, float]:
    estimated_tokens = entry.get("estimated_tokens", 100)
    if not isinstance(estimated_tokens, (int, float)) or estimated_tokens <= 0:
        raise AICatalogError(f"Catalog entry '{query_id}' has invalid 'estimated_tokens'; expected positive number")

    batch_size = entry.get("batch_size", 10)
    if not isinstance(batch_size, int) or batch_size <= 0:
        raise AICatalogError(f"Catalog entry '{query_id}' has invalid 'batch_size'; expected positive integer")

    cost_per_1k_tokens = entry.get("cost_per_1k_tokens", 0.001)
    if not isinstance(cost_per_1k_tokens, (int, float)) or cost_per_1k_tokens < 0:
        raise AICatalogError(
            f"Catalog entry '{query_id}' has invalid 'cost_per_1k_tokens'; expected non-negative number"
        )

    return int(estimated_tokens), batch_size, float(cost_per_1k_tokens)


def _parse_catalog_entry(index: int, entry: object, existing_ids: set[str]) -> AIQuery:
    if not isinstance(entry, dict):
        raise AICatalogError(f"Catalog entry at index {index} must be a mapping")

    query_id = entry.get("id")
    if not isinstance(query_id, str) or not query_id.strip():
        raise AICatalogError(f"Catalog entry at index {index} is missing a valid 'id'")
    query_id = query_id.strip()

    if query_id in existing_ids:
        raise AICatalogError(f"Duplicate query id detected in catalog: {query_id}")

    raw_sql = entry.get("sql")
    if not isinstance(raw_sql, str) or not raw_sql.strip():
        raise AICatalogError(f"Catalog entry '{query_id}' must include non-empty SQL text")

    category = entry.get("category")
    if category is None:
        category = query_id.split("_", 1)[0]
    if not isinstance(category, str) or not category.strip():
        raise AICatalogError(f"Catalog entry '{query_id}' must define a non-empty category")
    category = category.strip().lower()

    description = entry.get("description")
    if description is not None:
        if not isinstance(description, str) or not description.strip():
            raise AICatalogError(
                f"Catalog entry '{query_id}' has invalid 'description'; expected non-empty string",
            )
        description = description.strip()

    model = entry.get("model")
    if model is not None and (not isinstance(model, str) or not model.strip()):
        raise AICatalogError(f"Catalog entry '{query_id}' has invalid 'model'; expected non-empty string")

    estimated_tokens, batch_size, cost_per_1k_tokens = _parse_ai_numeric_fields(query_id, entry)

    return AIQuery(
        id=query_id,
        category=category,
        sql=raw_sql,
        description=description,
        variants=_parse_variants(query_id, entry.get("variants")),
        skip_on=_parse_skip_on(query_id, entry.get("skip_on")),
        model=model,
        estimated_tokens=estimated_tokens,
        batch_size=batch_size,
        cost_per_1k_tokens=cost_per_1k_tokens,
    )


def load_ai_catalog() -> AICatalog:
    """Load and validate the AI Primitives query catalog from package resources.

    Returns:
        AICatalog containing all validated queries

    Raises:
        AICatalogError: If catalog cannot be loaded or is invalid
    """
    payload = _load_catalog_payload()

    raw_version = payload.get("version", 1)
    try:
        version = int(raw_version)
    except (TypeError, ValueError) as exc:
        raise AICatalogError("AI Primitives query catalog version must be an integer") from exc

    raw_entries = payload.get("queries")
    if not isinstance(raw_entries, list):
        raise AICatalogError("AI Primitives query catalog must define a 'queries' list")

    queries: dict[str, AIQuery] = {}
    for index, entry in enumerate(raw_entries):
        query = _parse_catalog_entry(index, entry, set(queries.keys()))
        queries[query.id] = query

    return AICatalog(version=version, queries=queries)


__all__ = [
    "AICatalog",
    "AICatalogError",
    "AIQuery",
    "load_ai_catalog",
]
