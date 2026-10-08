# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import replace

from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
from benchbox.core.tpch_skew.dataframe_queries.registry import register_query


def _register_all_queries() -> None:
    for tpch_query in TPCH_DATAFRAME_QUERIES.get_all_queries():
        skew_query: DataFrameQuery = replace(tpch_query)
        register_query(skew_query)


_register_all_queries()
