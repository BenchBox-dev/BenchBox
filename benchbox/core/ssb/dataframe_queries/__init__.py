"""SSB DataFrame queries for Expression and Pandas families.

This module provides DataFrame implementations of Star Schema Benchmark queries
that can run on both expression-based (Polars, PySpark, DataFusion) and
Pandas-like (Pandas and Dask) platforms.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

# Import queries module to trigger registration
from benchbox.core.ssb.dataframe_queries import queries as _queries  # noqa: F401
from benchbox.core.ssb.dataframe_queries.registry import (
    SSB_DATAFRAME_QUERIES,
    get_ssb_query,
    list_ssb_queries,
)

__all__ = [
    "SSB_DATAFRAME_QUERIES",
    "get_ssb_query",
    "list_ssb_queries",
]
