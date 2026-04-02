"""NYC Taxi DataFrame query registry.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

NYCTAXI_DATAFRAME_QUERIES = QueryRegistry("nyctaxi")


def get_nyctaxi_query(query_id: str) -> DataFrameQuery | None:
    """Get a NYC Taxi DataFrame query by ID.

    Args:
        query_id: Query identifier (e.g., "Q1", "Q25")

    Returns:
        DataFrameQuery if found, None otherwise
    """
    return NYCTAXI_DATAFRAME_QUERIES.get(query_id)


def list_nyctaxi_queries(
    family: str | None = None,
    category: QueryCategory | None = None,
) -> list[DataFrameQuery]:
    """List NYC Taxi DataFrame queries with optional filtering."""
    return NYCTAXI_DATAFRAME_QUERIES.list_queries(family=family, category=category)


def register_query(query: DataFrameQuery) -> None:
    """Register a NYC Taxi DataFrame query."""
    NYCTAXI_DATAFRAME_QUERIES.register(query)
