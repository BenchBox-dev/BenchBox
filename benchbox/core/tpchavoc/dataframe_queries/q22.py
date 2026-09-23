"""TPC-Havoc DataFrame variants for Q22.

Q22 is a global-sales-opportunity query: a materialized average account
balance over selected countries, then customers above that average with
no orders. The variants keep the canonical output while varying the
average-balance materialization, the anti-join formulation, and filter
structure.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.tpch.dataframe_queries import (
    get_query as get_tpch_query,
    get_tpch_parameters,
    q22_expression_impl as _q22_expr_base,
    q22_pandas_impl as _q22_pandas_base,
)
from benchbox.core.tpchavoc.dataframe_queries.loader import build_variants

VariantImpl = Callable[[DataFrameContext], Any]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q22 implementation",
    "Average-via-sum-count: materialize the balance threshold from sum and count",
    "Anti-via-left-join: left join plus null filter instead of anti-join",
    "Filter-order swap: balance predicate before the country predicate",
    "Column prune: select only needed columns before the joins",
    "Positive-first: positive-balance filter before country-code extraction",
    "Chained style: maximum method chaining, no named intermediates",
    "Split aggregation: separate count and sum group-bys joined on country",
    "Distinct-count: n_unique customer count instead of count",
    "Unique-via-groupby: group-by aggregation instead of unique for orders",
]


def _q22_expr_coded(customer: Any, col: Any) -> Any:
    return customer.with_columns(col("c_phone").str.slice(0, 2).alias("cntrycode"))


def _q22_expr_avg(coded: Any, ctx: DataFrameContext, col: Any, lit: Any, country_codes: list[str]) -> Any:
    return ctx.scalar(
        coded.filter((col("c_acctbal") > lit(0)) & col("cntrycode").is_in(country_codes)).select(
            col("c_acctbal").mean().alias("avg_bal")
        )
    )


def _q22_expr_avg_sum_count(coded: Any, ctx: DataFrameContext, col: Any, lit: Any, country_codes: list[str]) -> Any:
    stats = (
        coded.filter((col("c_acctbal") > lit(0)) & col("cntrycode").is_in(country_codes))
        .select(col("c_acctbal"))
        .agg(col("c_acctbal").sum().alias("total"), col("c_acctbal").count().alias("n"))
    )
    total = ctx.scalar(stats.select("total"))
    count = ctx.scalar(stats.select("n"))
    return total / count


def _q22_expr_main(
    coded: Any,
    with_orders: Any,
    avg_balance: Any,
    col: Any,
    lit: Any,
    country_codes: list[str],
    *,
    left_join: bool = False,
    distinct_count: bool = False,
) -> Any:
    qualified = coded.filter(col("cntrycode").is_in(country_codes) & (col("c_acctbal") > lit(avg_balance)))
    if left_join:
        order_flag = with_orders.select(col("o_custkey").alias("has_order"), lit(1).alias("order_present"))
        joined = qualified.join(order_flag, left_on="c_custkey", right_on="has_order", how="left").filter(
            col("order_present").is_null()
        )
    else:
        joined = qualified.join(with_orders, left_on="c_custkey", right_on="o_custkey", how="anti")
    count_expr = (
        col("c_custkey").n_unique().alias("numcust") if distinct_count else col("c_custkey").count().alias("numcust")
    )
    return joined.group_by("cntrycode").agg(count_expr, col("c_acctbal").sum().alias("totacctbal")).sort("cntrycode")


def _make_q22_expression_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q22_expr_base(ctx)

        col = ctx.col
        lit = ctx.lit
        params = get_tpch_parameters(22)
        country_codes = params["country_codes"]
        customer = ctx.get_table("customer")
        orders = ctx.get_table("orders")

        if variant == 2:
            coded = _q22_expr_coded(customer, col)
            avg_balance = _q22_expr_avg_sum_count(coded, ctx, col, lit, country_codes)
            with_orders = orders.select("o_custkey").unique()
            return _q22_expr_main(coded, with_orders, avg_balance, col, lit, country_codes)

        if variant == 3:
            coded = _q22_expr_coded(customer, col)
            avg_balance = _q22_expr_avg(coded, ctx, col, lit, country_codes)
            with_orders = orders.select("o_custkey").unique()
            return _q22_expr_main(coded, with_orders, avg_balance, col, lit, country_codes, left_join=True)

        if variant == 4:
            coded = _q22_expr_coded(customer, col)
            avg_balance = _q22_expr_avg(coded, ctx, col, lit, country_codes)
            with_orders = orders.select("o_custkey").unique()
            qualified = coded.filter((col("c_acctbal") > lit(avg_balance)) & col("cntrycode").is_in(country_codes))
            return (
                qualified.join(with_orders, left_on="c_custkey", right_on="o_custkey", how="anti")
                .group_by("cntrycode")
                .agg(col("c_custkey").count().alias("numcust"), col("c_acctbal").sum().alias("totacctbal"))
                .sort("cntrycode")
            )

        if variant == 5:
            coded = _q22_expr_coded(customer.select("c_custkey", "c_phone", "c_acctbal"), col)
            avg_balance = _q22_expr_avg(coded, ctx, col, lit, country_codes)
            with_orders = orders.select("o_custkey").unique()
            return _q22_expr_main(coded, with_orders, avg_balance, col, lit, country_codes)

        if variant == 6:
            positive = customer.filter(col("c_acctbal") > lit(0))
            coded = _q22_expr_coded(positive, col)
            avg_balance = _q22_expr_avg(coded, ctx, col, lit, country_codes)
            with_orders = orders.select("o_custkey").unique()
            full_coded = _q22_expr_coded(customer, col)
            return _q22_expr_main(full_coded, with_orders, avg_balance, col, lit, country_codes)

        if variant == 7:
            coded = customer.with_columns(col("c_phone").str.slice(0, 2).alias("cntrycode"))
            avg_balance = ctx.scalar(
                coded.filter((col("c_acctbal") > lit(0)) & col("cntrycode").is_in(country_codes)).select(
                    col("c_acctbal").mean().alias("avg_bal")
                )
            )
            return (
                coded.filter(col("cntrycode").is_in(country_codes) & (col("c_acctbal") > lit(avg_balance)))
                .join(orders.select("o_custkey").unique(), left_on="c_custkey", right_on="o_custkey", how="anti")
                .group_by("cntrycode")
                .agg(col("c_custkey").count().alias("numcust"), col("c_acctbal").sum().alias("totacctbal"))
                .sort("cntrycode")
            )

        coded = _q22_expr_coded(customer, col)
        avg_balance = _q22_expr_avg(coded, ctx, col, lit, country_codes)
        with_orders = orders.select("o_custkey").unique()

        if variant == 8:
            qualified = coded.filter(col("cntrycode").is_in(country_codes) & (col("c_acctbal") > lit(avg_balance)))
            kept = qualified.join(with_orders, left_on="c_custkey", right_on="o_custkey", how="anti")
            counts = kept.group_by("cntrycode").agg(col("c_custkey").count().alias("numcust"))
            totals = kept.group_by("cntrycode").agg(col("c_acctbal").sum().alias("totacctbal"))
            return counts.join(totals, left_on="cntrycode", right_on="cntrycode").sort("cntrycode")

        if variant == 9:
            return _q22_expr_main(coded, with_orders, avg_balance, col, lit, country_codes, distinct_count=True)

        # variant 10: unique-via-groupby for the ordered-customer set
        with_orders = orders.group_by("o_custkey").agg(col("o_orderkey").count().alias("n_orders")).select("o_custkey")
        return _q22_expr_main(coded, with_orders, avg_balance, col, lit, country_codes)

    impl.__name__ = f"q22_v{variant}_expression_impl"
    impl.__qualname__ = impl.__name__
    return impl


def _q22_pandas_coded(customer: Any) -> Any:
    customer = customer.copy()
    customer["cntrycode"] = customer["c_phone"].str[:2]
    return customer


def _q22_pandas_avg(coded: Any, country_codes: list[str]) -> Any:
    positive = coded[(coded["c_acctbal"] > 0) & (coded["cntrycode"].isin(country_codes))]
    avg_balance = positive["c_acctbal"].mean()
    return avg_balance.compute() if hasattr(avg_balance, "compute") else avg_balance


def _q22_pandas_main(
    coded: Any,
    orders: Any,
    avg_balance: Any,
    country_codes: list[str],
    *,
    left_join: bool = False,
    distinct_count: bool = False,
) -> Any:
    from benchbox.core.dataframe.compat import _to_list

    with_orders = _to_list(orders["o_custkey"].unique())
    qualified = coded[(coded["cntrycode"].isin(country_codes)) & (coded["c_acctbal"] > avg_balance)]
    if left_join:
        order_frame = orders[["o_custkey"]].drop_duplicates()
        joined = qualified.merge(order_frame, left_on="c_custkey", right_on="o_custkey", how="left")
        kept = joined[joined["o_custkey"].isna()]
    else:
        kept = qualified[~qualified["c_custkey"].isin(with_orders)]
    if distinct_count:
        return (
            kept.groupby("cntrycode", as_index=False)
            .agg(numcust=("c_custkey", "nunique"), totacctbal=("c_acctbal", "sum"))
            .sort_values("cntrycode")
        )
    return (
        kept.groupby("cntrycode", as_index=False)
        .agg(numcust=("c_custkey", "count"), totacctbal=("c_acctbal", "sum"))
        .sort_values("cntrycode")
    )


def _make_q22_pandas_impl(variant: int) -> VariantImpl:
    def impl(ctx: DataFrameContext) -> Any:
        if variant == 1:
            return _q22_pandas_base(ctx)

        customer = ctx.get_table("customer")
        orders = ctx.get_table("orders")
        params = get_tpch_parameters(22)
        country_codes = params["country_codes"]

        if variant == 2:
            coded = _q22_pandas_coded(customer)
            eligible = coded[(coded["c_acctbal"] > 0) & (coded["cntrycode"].isin(country_codes))]
            total = eligible["c_acctbal"].sum()
            count = eligible["c_acctbal"].count()
            total = total.compute() if hasattr(total, "compute") else total
            count = count.compute() if hasattr(count, "compute") else count
            return _q22_pandas_main(coded, orders, total / count, country_codes)

        if variant == 3:
            coded = _q22_pandas_coded(customer)
            return _q22_pandas_main(coded, orders, _q22_pandas_avg(coded, country_codes), country_codes, left_join=True)

        if variant == 4:
            coded = _q22_pandas_coded(customer)
            avg_balance = _q22_pandas_avg(coded, country_codes)
            from benchbox.core.dataframe.compat import _to_list

            with_orders = _to_list(orders["o_custkey"].unique())
            kept = coded[(coded["c_acctbal"] > avg_balance) & (coded["cntrycode"].isin(country_codes))]
            kept = kept[~kept["c_custkey"].isin(with_orders)]
            return (
                kept.groupby("cntrycode", as_index=False)
                .agg(numcust=("c_custkey", "count"), totacctbal=("c_acctbal", "sum"))
                .sort_values("cntrycode")
            )

        if variant == 5:
            coded = _q22_pandas_coded(customer[["c_custkey", "c_phone", "c_acctbal"]])
            return _q22_pandas_main(coded, orders, _q22_pandas_avg(coded, country_codes), country_codes)

        if variant == 6:
            positive = customer[customer["c_acctbal"] > 0]
            avg_balance = _q22_pandas_avg(_q22_pandas_coded(positive), country_codes)
            return _q22_pandas_main(_q22_pandas_coded(customer), orders, avg_balance, country_codes)

        if variant == 7:
            coded = customer.copy()
            coded["cntrycode"] = coded["c_phone"].str[:2]
            avg_balance = _q22_pandas_avg(coded, country_codes)
            return _q22_pandas_main(coded, orders, avg_balance, country_codes)

        coded = _q22_pandas_coded(customer)
        avg_balance = _q22_pandas_avg(coded, country_codes)

        if variant == 8:
            from benchbox.core.dataframe.compat import _to_list

            with_orders = _to_list(orders["o_custkey"].unique())
            kept = coded[(coded["cntrycode"].isin(country_codes)) & (coded["c_acctbal"] > avg_balance)]
            kept = kept[~kept["c_custkey"].isin(with_orders)]
            counts = kept.groupby("cntrycode", as_index=False).agg(numcust=("c_custkey", "count"))
            totals = kept.groupby("cntrycode", as_index=False).agg(totacctbal=("c_acctbal", "sum"))
            return counts.merge(totals, on="cntrycode").sort_values("cntrycode")

        if variant == 9:
            return _q22_pandas_main(coded, orders, avg_balance, country_codes, distinct_count=True)

        # variant 10: ordered-customer set via groupby instead of unique
        from benchbox.core.dataframe.compat import _to_list

        grouped_orders = orders.groupby("o_custkey").size().index
        with_orders = _to_list(grouped_orders)
        kept = coded[(coded["cntrycode"].isin(country_codes)) & (coded["c_acctbal"] > avg_balance)]
        kept = kept[~kept["c_custkey"].isin(with_orders)]
        return (
            kept.groupby("cntrycode", as_index=False)
            .agg(numcust=("c_custkey", "count"), totacctbal=("c_acctbal", "sum"))
            .sort_values("cntrycode")
        )

    impl.__name__ = f"q22_v{variant}_pandas_impl"
    impl.__qualname__ = impl.__name__
    return impl


_Q22_BASE = get_tpch_query("Q22")

Q22_VARIANTS = build_variants(
    22,
    [(_make_q22_expression_impl(v), _make_q22_pandas_impl(v)) for v in range(1, 11)],
    _DESCRIPTIONS,
    _Q22_BASE.categories,
)
