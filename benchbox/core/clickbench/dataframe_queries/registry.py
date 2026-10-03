"""ClickBench DataFrame query registry.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

CLICKBENCH_DATAFRAME_QUERIES = QueryRegistry("clickbench")


def get_clickbench_query(query_id: str) -> DataFrameQuery | None:

    return CLICKBENCH_DATAFRAME_QUERIES.get(query_id)


def list_clickbench_queries(family: str | None = None, category: QueryCategory | None = None) -> list[DataFrameQuery]:

    return CLICKBENCH_DATAFRAME_QUERIES.list_queries(family=family, category=category)


def register_query(query: DataFrameQuery) -> None:

    CLICKBENCH_DATAFRAME_QUERIES.register(query)
