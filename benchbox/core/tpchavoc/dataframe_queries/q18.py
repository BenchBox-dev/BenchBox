"""TPC-Havoc DataFrame variants for Q18."""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import build_result_replay_variants

Q18_VARIANTS: list[DataFrameQuery] = build_result_replay_variants(
    18,
    result_columns=["c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice", "sum_qty"],
    sort_columns=["o_totalprice", "o_orderdate"],
    descending=[True, False],
)
