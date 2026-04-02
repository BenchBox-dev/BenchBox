"""TPC-DS DataFrame query registry.

This module provides the central registry for TPC-DS DataFrame queries,
following the same pattern as TPC-H but with TPC-DS-specific parameters.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

# TPC-DS DataFrame Query Registry
TPCDS_DATAFRAME_QUERIES = QueryRegistry("tpcds")


def get_tpcds_query(query_id: str) -> DataFrameQuery | None:
    """Get a TPC-DS DataFrame query by ID.

    Args:
        query_id: Query identifier (e.g., "Q3", "Q42")

    Returns:
        DataFrameQuery if found, None otherwise
    """
    return TPCDS_DATAFRAME_QUERIES.get(query_id)


def list_tpcds_queries(
    family: str | None = None,
    category: QueryCategory | None = None,
) -> list[DataFrameQuery]:
    """List TPC-DS DataFrame queries with optional filtering."""
    return TPCDS_DATAFRAME_QUERIES.list_queries(family=family, category=category)


def register_query(query: DataFrameQuery) -> None:
    """Register a TPC-DS DataFrame query.

    Args:
        query: DataFrameQuery to register
    """
    TPCDS_DATAFRAME_QUERIES.register(query)
