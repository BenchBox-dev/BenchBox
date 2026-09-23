"""TPC-Havoc DataFrame variants for Q19.

Q19 is a join plus a three-way OR of brand/container/quantity/size
conditions. The variants keep the canonical output while varying the
condition structure around union-of-branches, filter pushdown, part-side
prefiltering, column pruning, and revenue formulation.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_query as get_tpch_query,
    get_tpch_parameters,
    q19_expression_impl as _q19_expr_base,
    q19_pandas_impl as _q19_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import build_variants

VariantImpl = Callable[[DataFrameContext], Any]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q19 implementation",
    "Condition unions: one filtered branch per brand, concatenated before revenue",
    "Common pushdown: shipmode/shipinstruct filter on lineitem before the join",
    "Part-side prefilter: brand/container/size predicates applied before the join",
    "Column prune: select only needed columns before the join",
    "Per-branch joins: separate join pipeline per brand, concatenated after",
    "Chained style: maximum method chaining, no named intermediates",
    "Alternative formula: commuted (1-discount)*price revenue",
    "Materialized revenue: with_columns revenue before select and sum",
    "Branch-first ordering: branch OR filter applied before common filters",
]

_SM = ["SM CASE", "SM BOX", "SM PACK", "SM PKG"]
_MED = ["MED BAG", "MED BOX", "MED PKG", "MED PACK"]
_LG = ["LG CASE", "LG BOX", "LG PACK", "LG PKG"]
_SHIP_MODES = ["AIR", "AIR REG"]
_NEEDED_LINEITEM = ["l_partkey", "l_quantity", "l_extendedprice", "l_discount", "l_shipmode", "l_shipinstruct"]
_NEEDED_PART = ["p_partkey", "p_brand", "p_container", "p_size"]


def _q19_branches() -> tuple[tuple[str, list[str], str, int, int], ...]:
    return (
        ("brand1", _SM, "quantity1", 1, 5),
        ("brand2", _MED, "quantity2", 1, 10),
        ("brand3", _LG, "quantity3", 1, 15),
    )


def _q19_expr_common(col: Any, lit: Any) -> Any:
    return col("l_shipmode").is_in(_SHIP_MODES) & (col("l_shipinstruct") == lit("DELIVER IN PERSON"))


def _q19_expr_branch(col: Any, lit: Any, params: dict[str, Any], spec: tuple[str, list[str], str, int, int]) -> Any:
    brand_key, containers, qty_key, size_lo, size_hi = spec
    qty = params[qty_key]
    return (
        (col("p_brand") == lit(params[brand_key]))
        & col("p_container").is_in(containers)
        & (col("l_quantity") >= lit(qty))
        & (col("l_quantity") <= lit(qty + 10))
        & (col("p_size") >= lit(size_lo))
        & (col("p_size") <= lit(size_hi))
    )


def _q19_expr_revenue(col: Any, lit: Any, *, commuted: bool = False) -> Any:
    if commuted:
        return ((lit(1) - col("l_discount")) * col("l_extendedprice")).alias("revenue")
    return (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("revenue")


def _q19_expr_sum(joined: Any, col: Any, lit: Any, params: dict[str, Any], *, commuted: bool = False) -> Any:
    common = _q19_expr_common(col, lit)
    branches = [_q19_expr_branch(col, lit, params, spec) for spec in _q19_branches()]
    combined = branches[0] | branches[1] | branches[2]
    return joined.filter(common & combined).select(_q19_expr_revenue(col, lit, commuted=commuted)).sum()


def _make_q19_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q19_expr_base(ctx)

        col = ctx.col
        lit = ctx.lit
        params = get_tpch_parameters(19)
        branches = [_q19_expr_branch(col, lit, params, spec) for spec in _q19_branches()]
        combined = branches[0] | branches[1] | branches[2]
        common = _q19_expr_common(col, lit)

        if variant == 2:
            joined = ctx.get_table("lineitem").join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
            parts = [joined.filter(common & branch) for branch in branches]
            return ctx.concat(parts).select(_q19_expr_revenue(col, lit)).sum()

        if variant == 3:
            lineitem = ctx.get_table("lineitem").filter(common)
            joined = lineitem.join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
            return joined.filter(combined).select(_q19_expr_revenue(col, lit)).sum()

        if variant == 4:
            part = ctx.get_table("part")
            lineitem = ctx.get_table("lineitem")
            frames = []
            for brand_key, containers, _qty_key, size_lo, size_hi in _q19_branches():
                part_branch = part.filter(
                    (col("p_brand") == lit(params[brand_key]))
                    & col("p_container").is_in(containers)
                    & (col("p_size") >= lit(size_lo))
                    & (col("p_size") <= lit(size_hi))
                )
                frames.append(lineitem.join(part_branch, left_on="l_partkey", right_on="p_partkey"))
            joined = ctx.concat(frames) if len(frames) > 1 else frames[0]
            return _q19_expr_sum(joined, col, lit, params)

        if variant == 5:
            lineitem = ctx.get_table("lineitem").select(_NEEDED_LINEITEM)
            part = ctx.get_table("part").select(_NEEDED_PART)
            joined = lineitem.join(part, left_on="l_partkey", right_on="p_partkey")
            return joined.filter(common & combined).select(_q19_expr_revenue(col, lit)).sum()

        if variant == 6:
            lineitem = ctx.get_table("lineitem")
            part = ctx.get_table("part")
            piped = [
                lineitem.join(part, left_on="l_partkey", right_on="p_partkey").filter(common & branch)
                for branch in branches
            ]
            return ctx.concat(piped).select(_q19_expr_revenue(col, lit)).sum()

        if variant == 7:
            return (
                ctx.get_table("lineitem")
                .join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
                .filter(common & combined)
                .select(_q19_expr_revenue(col, lit))
                .sum()
            )

        if variant == 8:
            joined = ctx.get_table("lineitem").join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
            return joined.filter(common & combined).select(_q19_expr_revenue(col, lit, commuted=True)).sum()

        if variant == 9:
            joined = ctx.get_table("lineitem").join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
            return joined.filter(common & combined).with_columns(_q19_expr_revenue(col, lit)).select("revenue").sum()

        joined = ctx.get_table("lineitem").join(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
        return joined.filter(combined).filter(common).select(_q19_expr_revenue(col, lit)).sum()

    impl.__name__ = f"q19_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q19_pandas_masks(joined: Any, params: dict[str, Any]) -> Any:
    common = joined["l_shipmode"].isin(_SHIP_MODES) & (joined["l_shipinstruct"] == "DELIVER IN PERSON")
    conds = []
    for brand_key, containers, qty_key, size_lo, size_hi in _q19_branches():
        qty = params[qty_key]
        conds.append(
            (joined["p_brand"] == params[brand_key])
            & joined["p_container"].isin(containers)
            & (joined["l_quantity"] >= qty)
            & (joined["l_quantity"] <= qty + 10)
            & (joined["p_size"] >= size_lo)
            & (joined["p_size"] <= size_hi)
        )
    return common, conds[0] | conds[1] | conds[2], conds


def _q19_pandas_frame(value: Any) -> Any:
    import pandas as pd

    value = value.compute() if hasattr(value, "compute") else value
    return pd.DataFrame({"revenue": [value]})


def _q19_pandas_sum(filtered: Any, *, commuted: bool = False) -> Any:
    if commuted:
        revenue = (1 - filtered["l_discount"]) * filtered["l_extendedprice"]
    else:
        revenue = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    return _q19_pandas_frame(revenue.sum())


def _make_q19_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        import pandas as pd

        if variant == 1:
            return _q19_pandas_base(ctx)

        lineitem = ctx.get_table("lineitem")
        part = ctx.get_table("part")
        params = get_tpch_parameters(19)

        if variant == 2:
            joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")
            common, _, conds = _q19_pandas_masks(joined, params)
            parts = [joined[common & cond] for cond in conds]
            return _q19_pandas_sum(pd.concat(parts, ignore_index=True))

        if variant == 3:
            lineitem = lineitem[
                lineitem["l_shipmode"].isin(_SHIP_MODES) & (lineitem["l_shipinstruct"] == "DELIVER IN PERSON")
            ]
            joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")
            _, combined, _ = _q19_pandas_masks(joined, params)
            return _q19_pandas_sum(joined[combined])

        if variant == 4:
            frames = []
            for brand_key, containers, _qty_key, size_lo, size_hi in _q19_branches():
                part_branch = part[
                    (part["p_brand"] == params[brand_key])
                    & part["p_container"].isin(containers)
                    & (part["p_size"] >= size_lo)
                    & (part["p_size"] <= size_hi)
                ]
                frames.append(lineitem.merge(part_branch, left_on="l_partkey", right_on="p_partkey"))
            joined = pd.concat(frames, ignore_index=True)
            common, combined, _ = _q19_pandas_masks(joined, params)
            return _q19_pandas_sum(joined[common & combined])

        if variant == 5:
            joined = lineitem[_NEEDED_LINEITEM].merge(part[_NEEDED_PART], left_on="l_partkey", right_on="p_partkey")
            common, combined, _ = _q19_pandas_masks(joined, params)
            return _q19_pandas_sum(joined[common & combined])

        if variant == 6:
            joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")
            common, _, conds = _q19_pandas_masks(joined, params)
            piped = [joined[common & cond] for cond in conds]
            return _q19_pandas_sum(pd.concat(piped, ignore_index=True))

        if variant == 7:
            joined = ctx.get_table("lineitem").merge(ctx.get_table("part"), left_on="l_partkey", right_on="p_partkey")
            common, combined, _ = _q19_pandas_masks(joined, params)
            return _q19_pandas_sum(joined[common & combined])

        if variant == 8:
            joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")
            common, combined, _ = _q19_pandas_masks(joined, params)
            return _q19_pandas_sum(joined[common & combined], commuted=True)

        if variant == 9:
            joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")
            common, combined, _ = _q19_pandas_masks(joined, params)
            filtered = joined[common & combined].copy()
            filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
            return _q19_pandas_frame(filtered["revenue"].sum())

        joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")
        common, combined, _ = _q19_pandas_masks(joined, params)
        return _q19_pandas_sum(joined[combined][common])

    impl.__name__ = f"q19_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


_Q19_BASE = get_tpch_query("Q19")

Q19_VARIANTS = build_variants(
    19,
    [(_make_q19_expression_impl(v), _make_q19_pandas_impl(v)) for v in range(1, 11)],
    _DESCRIPTIONS,
    _Q19_BASE.categories,
)
