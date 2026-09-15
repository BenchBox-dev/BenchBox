"""ClickBench DataFrame queries for Expression and Pandas families.

This module provides DataFrame implementations of ClickBench analytics queries
that can run on both expression-based (Polars, PySpark, DataFusion) and
Pandas-like (Pandas and Dask) platforms.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

# Import queries module to trigger registration
from benchbox.core.clickbench.dataframe_queries import queries as _queries  # noqa: F401
from benchbox.core.clickbench.dataframe_queries.registry import (
    CLICKBENCH_DATAFRAME_QUERIES,
    get_clickbench_query,
    list_clickbench_queries,
)

__all__ = [
    "CLICKBENCH_DATAFRAME_QUERIES",
    "get_clickbench_query",
    "list_clickbench_queries",
]
