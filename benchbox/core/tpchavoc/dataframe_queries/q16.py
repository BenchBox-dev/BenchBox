"""TPC-Havoc DataFrame variants for Q16."""

from __future__ import annotations

from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.tpchavoc.dataframe_queries._delegating_variants import build_result_replay_variants

Q16_VARIANTS: list[DataFrameQuery] = build_result_replay_variants(
    16,
    result_columns=["p_brand", "p_type", "p_size", "supplier_cnt"],
    sort_columns=["supplier_cnt", "p_brand", "p_type", "p_size"],
    descending=[True, False, False, False],
)
