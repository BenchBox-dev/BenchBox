# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

TPCH_SKEW_DATAFRAME_QUERIES = QueryRegistry("tpch_skew")


def get_tpch_skew_query(query_id: str) -> DataFrameQuery | None:

    return TPCH_SKEW_DATAFRAME_QUERIES.get(query_id)


def list_tpch_skew_queries(
    family: str | None = None,
    category: QueryCategory | None = None,
) -> list[DataFrameQuery]:

    return TPCH_SKEW_DATAFRAME_QUERIES.list_queries(family=family, category=category)


def register_query(query: DataFrameQuery) -> None:

    TPCH_SKEW_DATAFRAME_QUERIES.register(query)
