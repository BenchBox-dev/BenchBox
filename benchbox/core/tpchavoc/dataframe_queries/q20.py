"""TPC-Havoc DataFrame variants for Q20."""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import build_result_replay_variants

Q20_VARIANTS: list[DataFrameQuery] = build_result_replay_variants(
    20,
    result_columns=["s_name", "s_address"],
    sort_columns=["s_name"],
)
