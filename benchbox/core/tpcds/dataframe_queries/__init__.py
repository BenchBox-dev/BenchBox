"""TPC-DS DataFrame queries for Expression and Pandas families.

This module provides DataFrame implementations of TPC-DS benchmark queries
that can run on both expression-based (Polars, PySpark, DataFusion) and
Pandas-like (Pandas, Modin, Dask) platforms.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

# Import queries module to configure the lazy registry loader.
from benchbox.core.tpcds.dataframe_queries import queries as _queries  # noqa: F401
from benchbox.core.tpcds.dataframe_queries.registry import (
    TPCDS_DATAFRAME_QUERIES,
    get_tpcds_query,
    list_tpcds_queries,
)

__all__ = [
    "TPCDS_DATAFRAME_QUERIES",
    "get_tpcds_query",
    "list_tpcds_queries",
]
