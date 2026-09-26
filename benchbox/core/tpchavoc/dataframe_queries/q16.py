"""TPC-Havoc DataFrame variants for Q16.

Q16 filters parts, joins partsupp, excludes complaint suppliers via an
anti-join, then groups by brand/type/size with a distinct-supplier count.
The variants keep the canonical output while varying the anti-join shape,
filter pushdown, prefiltering, column pruning, and aggregation structure.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.compat import _to_list
from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_query as get_tpch_query,
    get_tpch_parameters,
    q16_expression_impl as _q16_expr_base,
    q16_pandas_impl as _q16_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import build_variants

VariantImpl = Callable[[DataFrameContext], Any]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q16 implementation",
    "Anti-join alternatives: complaint keys via distinct before the anti-join",
    "Semi-join pruning: partsupp semi-filtered to filtered part keys before the join",
    "Part-side prefilter: brand/type/size filter on part before the join",
    "Column prune: select only needed columns before the join",
    "Per-predicate branches: one filtered branch per size, concatenated after",
    "Late filtering: part predicates applied after the partsupp join instead of before",
    "Complaint-first ordering: anti-join before the part filter",
    "Two-stage aggregation: distinct group-supplier pairs counted before the final sort",
    "Group-first ordering: group keys projected before aggregation",
]

_GROUP_KEYS = ["p_brand", "p_type", "p_size"]
_SORT_KEYS = ["supplier_cnt", "p_brand", "p_type", "p_size"]
_SORT_DESC = [True, False, False, False]


def _q16_expr_parts(col: Any, lit: Any, params: dict[str, Any]) -> Any:
    return (
        (col("p_brand") != lit(params["brand"]))
        & ~col("p_type").str.starts_with(params["type_prefix"])
        & col("p_size").is_in(params["sizes"])
    )


def _q16_expr_complaint_keys(ctx: DataFrameContext, col: Any) -> Any:
    return ctx.get_table("supplier").filter(col("s_comment").str.contains("Customer.*Complaints")).select("s_suppkey")


def _q16_expr_aggregate(filtered: Any, col: Any) -> Any:
    return (
        filtered.group_by(*_GROUP_KEYS)
        .agg(col("ps_suppkey").n_unique().alias("supplier_cnt"))
        .sort(_SORT_KEYS, descending=_SORT_DESC)
    )


def _make_q16_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q16_expr_base(ctx)

        col = ctx.col
        lit = ctx.lit
        params = get_tpch_parameters(16)
        partsupp = ctx.get_table("partsupp")
        part = ctx.get_table("part")

        if variant == 2:
            complaint_keys = _q16_expr_complaint_keys(ctx, col).distinct()
            joined = part.filter(_q16_expr_parts(col, lit, params)).join(
                partsupp, left_on="p_partkey", right_on="ps_partkey"
            )
            return _q16_expr_aggregate(
                joined.join(complaint_keys, left_on="ps_suppkey", right_on="s_suppkey", how="anti"), col
            )

        if variant == 3:
            # Semi-join pruning: partsupp is first reduced to the rows whose
            # part key survives the part filter, via a distinct-key semi-join,
            # before the main part/partsupp join runs.
            filtered = part.filter(_q16_expr_parts(col, lit, params))
            part_keys = filtered.select("p_partkey").distinct()
            pruned = partsupp.join(part_keys, left_on="ps_partkey", right_on="p_partkey", how="semi")
            joined = filtered.join(pruned, left_on="p_partkey", right_on="ps_partkey")
            return _q16_expr_aggregate(
                joined.join(_q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti"),
                col,
            )

        if variant == 4:
            part_branch = part.filter(
                (col("p_brand") != lit(params["brand"])) & ~col("p_type").str.starts_with(params["type_prefix"])
            ).filter(col("p_size").is_in(params["sizes"]))
            joined = part_branch.join(partsupp, left_on="p_partkey", right_on="ps_partkey")
            return _q16_expr_aggregate(
                joined.join(_q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti"),
                col,
            )

        if variant == 5:
            part_cols = part.select("p_partkey", "p_brand", "p_type", "p_size").filter(
                _q16_expr_parts(col, lit, params)
            )
            joined = part_cols.join(partsupp, left_on="p_partkey", right_on="ps_partkey")
            return _q16_expr_aggregate(
                joined.join(_q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti"),
                col,
            )

        if variant == 6:
            branches = [
                part.filter(
                    (col("p_brand") != lit(params["brand"]))
                    & ~col("p_type").str.starts_with(params["type_prefix"])
                    & (col("p_size") == lit(size))
                )
                for size in params["sizes"]
            ]
            joined = ctx.concat(
                [branch.join(partsupp, left_on="p_partkey", right_on="ps_partkey") for branch in branches]
            )
            return _q16_expr_aggregate(
                joined.join(_q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti"),
                col,
            )

        if variant == 7:
            # Late filtering: part and partsupp join unfiltered, and the
            # brand/type/size predicates run on the joined rows instead of on
            # part before the join, swapping the canonical filter order.
            joined = part.join(partsupp, left_on="p_partkey", right_on="ps_partkey").filter(
                _q16_expr_parts(col, lit, params)
            )
            return _q16_expr_aggregate(
                joined.join(_q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti"),
                col,
            )

        if variant == 8:
            complaint_keys = _q16_expr_complaint_keys(ctx, col)
            partsupp_clean = partsupp.join(complaint_keys, left_on="ps_suppkey", right_on="s_suppkey", how="anti")
            joined = part.filter(_q16_expr_parts(col, lit, params)).join(
                partsupp_clean, left_on="p_partkey", right_on="ps_partkey"
            )
            return _q16_expr_aggregate(joined, col)

        if variant == 9:
            joined = part.filter(_q16_expr_parts(col, lit, params)).join(
                partsupp, left_on="p_partkey", right_on="ps_partkey"
            )
            clean = joined.join(
                _q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti"
            )
            pairs = clean.select(*_GROUP_KEYS, "ps_suppkey").distinct()
            return (
                pairs.group_by(*_GROUP_KEYS)
                .agg(col("ps_suppkey").count().alias("supplier_cnt"))
                .sort(_SORT_KEYS, descending=_SORT_DESC)
            )

        projected = (
            part.filter(_q16_expr_parts(col, lit, params))
            .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
            .join(_q16_expr_complaint_keys(ctx, col), left_on="ps_suppkey", right_on="s_suppkey", how="anti")
            .select(*_GROUP_KEYS, "ps_suppkey")
        )
        return _q16_expr_aggregate(projected, col)

    impl.__name__ = f"q16_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q16_pandas_complaint_keys(supplier: Any) -> Any:
    return supplier[supplier["s_comment"].str.contains("Customer.*Complaints", regex=True, na=False)][
        "s_suppkey"
    ].drop_duplicates()


def _q16_pandas_parts_mask(part: Any, params: dict[str, Any]) -> Any:
    return (
        (part["p_brand"] != params["brand"])
        & (~part["p_type"].str.startswith(params["type_prefix"]))
        & (part["p_size"].isin(params["sizes"]))
    )


def _q16_pandas_aggregate(joined: Any) -> Any:
    return (
        joined.groupby(["p_brand", "p_type", "p_size"], as_index=False)
        .agg(supplier_cnt=("ps_suppkey", "nunique"))
        .sort_values(["supplier_cnt", "p_brand", "p_type", "p_size"], ascending=[False, True, True, True])
    )


def _make_q16_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q16_pandas_base(ctx)

        partsupp = ctx.get_table("partsupp")
        part = ctx.get_table("part")
        supplier = ctx.get_table("supplier")
        params = get_tpch_parameters(16)

        if variant == 2:
            complaint_keys = _q16_pandas_complaint_keys(supplier).drop_duplicates()
            joined = part[_q16_pandas_parts_mask(part, params)].merge(
                partsupp, left_on="p_partkey", right_on="ps_partkey"
            )
            return _q16_pandas_aggregate(joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))])

        if variant == 3:
            # Semi-join pruning mirror: partsupp reduced to surviving part keys first.
            filtered = part[_q16_pandas_parts_mask(part, params)]
            part_keys = _to_list(filtered[["p_partkey"]].drop_duplicates()["p_partkey"])
            pruned = partsupp[partsupp["ps_partkey"].isin(part_keys)]
            joined = filtered.merge(pruned, left_on="p_partkey", right_on="ps_partkey")
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            return _q16_pandas_aggregate(joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))])

        if variant == 4:
            part_branch = part[
                (part["p_brand"] != params["brand"]) & (~part["p_type"].str.startswith(params["type_prefix"]))
            ]
            part_branch = part_branch[part_branch["p_size"].isin(params["sizes"])]
            joined = part_branch.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            return _q16_pandas_aggregate(joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))])

        if variant == 5:
            part_cols = part[["p_partkey", "p_brand", "p_type", "p_size"]]
            part_cols = part_cols[_q16_pandas_parts_mask(part_cols, params)]
            joined = part_cols.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            return _q16_pandas_aggregate(joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))])

        if variant == 6:
            branches = [
                part[
                    (part["p_brand"] != params["brand"])
                    & (~part["p_type"].str.startswith(params["type_prefix"]))
                    & (part["p_size"] == size)
                ]
                for size in params["sizes"]
            ]
            joined = ctx.concat(
                [branch.merge(partsupp, left_on="p_partkey", right_on="ps_partkey") for branch in branches]
            )
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            return _q16_pandas_aggregate(joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))])

        if variant == 7:
            # Late filtering mirror: join first, filter the joined rows after.
            joined = part.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
            filtered = joined[_q16_pandas_parts_mask(joined, params)]
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            return _q16_pandas_aggregate(filtered[~filtered["ps_suppkey"].isin(_to_list(complaint_keys))])

        if variant == 8:
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            partsupp_clean = partsupp[~partsupp["ps_suppkey"].isin(_to_list(complaint_keys))]
            joined = part[_q16_pandas_parts_mask(part, params)].merge(
                partsupp_clean, left_on="p_partkey", right_on="ps_partkey"
            )
            return _q16_pandas_aggregate(joined)

        if variant == 9:
            joined = part[_q16_pandas_parts_mask(part, params)].merge(
                partsupp, left_on="p_partkey", right_on="ps_partkey"
            )
            complaint_keys = _q16_pandas_complaint_keys(supplier)
            clean = joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))]
            pairs = clean[["p_brand", "p_type", "p_size", "ps_suppkey"]].drop_duplicates()
            return (
                pairs.groupby(["p_brand", "p_type", "p_size"], as_index=False)
                .agg(supplier_cnt=("ps_suppkey", "count"))
                .sort_values(["supplier_cnt", "p_brand", "p_type", "p_size"], ascending=[False, True, True, True])
            )

        joined = part[_q16_pandas_parts_mask(part, params)].merge(partsupp, left_on="p_partkey", right_on="ps_partkey")
        complaint_keys = _q16_pandas_complaint_keys(supplier)
        projected = joined[~joined["ps_suppkey"].isin(_to_list(complaint_keys))][
            ["p_brand", "p_type", "p_size", "ps_suppkey"]
        ]
        return _q16_pandas_aggregate(projected)

    impl.__name__ = f"q16_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


_Q16_BASE = get_tpch_query("Q16")

Q16_VARIANTS = build_variants(
    16,
    [(_make_q16_expression_impl(v), _make_q16_pandas_impl(v)) for v in range(1, 11)],
    _DESCRIPTIONS,
    _Q16_BASE.categories,
    expected_row_count=_Q16_BASE.expected_row_count,
    scale_factor_dependent=_Q16_BASE.scale_factor_dependent,
    timeout_seconds=_Q16_BASE.timeout_seconds,
    skip_platforms=_Q16_BASE.skip_platforms,
)
