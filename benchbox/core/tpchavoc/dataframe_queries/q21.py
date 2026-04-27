"""TPC-Havoc DataFrame variants for Q21."""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import build_result_replay_variants

Q21_VARIANTS: list[DataFrameQuery] = build_result_replay_variants(
    21,
    result_columns=["s_name", "numwait"],
    sort_columns=["numwait", "s_name"],
    descending=[True, False],
)
