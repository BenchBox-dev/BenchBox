# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from collections.abc import Iterable
from typing import Callable

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

TPCDS_DATAFRAME_QUERIES = QueryRegistry("tpcds")


def configure_query_loader(loader: Callable[[], Iterable[DataFrameQuery]]) -> None:

    TPCDS_DATAFRAME_QUERIES.set_loader(loader)


def get_tpcds_query(query_id: str) -> DataFrameQuery | None:

    return TPCDS_DATAFRAME_QUERIES.get(query_id)


def list_tpcds_queries(
    family: str | None = None,
    category: QueryCategory | None = None,
) -> list[DataFrameQuery]:

    return TPCDS_DATAFRAME_QUERIES.list_queries(family=family, category=category)


def register_query(query: DataFrameQuery) -> None:

    TPCDS_DATAFRAME_QUERIES.register(query)
