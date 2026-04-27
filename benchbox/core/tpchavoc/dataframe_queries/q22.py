"""TPC-Havoc DataFrame variants for Q22."""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import build_result_replay_variants

Q22_VARIANTS: list[DataFrameQuery] = build_result_replay_variants(
    22,
    result_columns=["cntrycode", "numcust", "totacctbal"],
    sort_columns=["cntrycode"],
)
