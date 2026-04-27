"""TPC-Havoc DataFrame variants for Q13.

Implements 10 structurally diverse variants of TPC-H Q13 (Customer Distribution).
Q13 uses a LEFT OUTER JOIN to count orders per customer (excluding special requests),
then counts customers per order count, ordered by custdist DESC, c_count DESC.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpch.dataframe_queries import (
    get_tpch_parameters,
    q13_expression_impl as _q13_expr_base,
    q13_pandas_impl as _q13_pandas_base,
)

# ---------------------------------------------------------------------------
# v1: baseline - delegate directly to TPC-H base implementation
# ---------------------------------------------------------------------------


def q13_v1_expression_impl(ctx: DataFrameContext) -> Any:
    return _q13_expr_base(ctx)


def q13_v1_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q13_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v2: pre-filter - filter orders before the left join
# ---------------------------------------------------------------------------


def q13_v2_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Pre-filter orders to exclude special requests before joining
    filtered_orders = orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}"))

    customer_orders = (
        customer.join(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")
        .group_by("c_custkey")
        .agg(col("o_orderkey").count().alias("c_count"))
    )

    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v2_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Pre-filter orders before left join
    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    customer_orders = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))

    return (
        order_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# v3: column prune - select only needed columns before join
# ---------------------------------------------------------------------------


def q13_v3_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    customer_orders = (
        customer.select("c_custkey")
        .join(
            orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}")).select("o_custkey", "o_orderkey"),
            left_on="c_custkey",
            right_on="o_custkey",
            how="left",
        )
        .group_by("c_custkey")
        .agg(col("o_orderkey").count().alias("c_count"))
    )

    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v3_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    c = customer[["c_custkey"]]
    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    o = filtered_orders[["o_custkey", "o_orderkey"]]

    customer_orders = c.merge(o, left_on="c_custkey", right_on="o_custkey", how="left")
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))

    return (
        order_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# v4: intermediate vars - explicit DataFrames for each step
# ---------------------------------------------------------------------------


def q13_v4_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Step 1: filter orders
    filtered_orders = orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}"))
    # Step 2: left join
    joined = customer.join(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")
    # Step 3: count orders per customer
    customer_orders = joined.group_by("c_custkey").agg(col("o_orderkey").count().alias("c_count"))
    # Step 4: count customers per order count
    dist = customer_orders.group_by("c_count").agg(col("c_custkey").count().alias("custdist"))
    # Step 5: sort
    return dist.sort(["custdist", "c_count"], descending=[True, True])


def q13_v4_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Step 1: filter
    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    # Step 2: join
    customer_orders = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")
    # Step 3: count
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))
    # Step 4: distribute and sort
    dist = order_counts.groupby("c_count", as_index=False).agg(custdist=("c_custkey", "count"))
    return dist.sort_values(["custdist", "c_count"], ascending=[False, False])


# ---------------------------------------------------------------------------
# v5: pre-compute derived - add order count directly from filtered set
# ---------------------------------------------------------------------------


def q13_v5_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Filter before building the distribution
    valid_orders = orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}"))

    customer_orders = (
        customer.join(valid_orders, left_on="c_custkey", right_on="o_custkey", how="left")
        .group_by("c_custkey")
        .agg(col("o_orderkey").count().alias("c_count"))
    )

    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v5_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    valid_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    customer_orders = customer.merge(valid_orders, left_on="c_custkey", right_on="o_custkey", how="left")

    # Derive c_count in a separate step
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))

    return (
        order_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# v6: chained style - maximum method chaining
# ---------------------------------------------------------------------------


def q13_v6_expression_impl(ctx: DataFrameContext) -> Any:
    col = ctx.col
    p = get_tpch_parameters(13)
    return (
        ctx.get_table("customer")
        .join(
            ctx.get_table("orders").filter(~col("o_comment").str.contains(f"{p['word1']}.*{p['word2']}")),
            left_on="c_custkey",
            right_on="o_custkey",
            how="left",
        )
        .group_by("c_custkey")
        .agg(col("o_orderkey").count().alias("c_count"))
        .group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _q13_pandas_base(ctx)


# ---------------------------------------------------------------------------
# v7: join reorder - use customer as right table (orders left join customer)
#     Note: semantically equivalent because we're counting per customer
# ---------------------------------------------------------------------------


def q13_v7_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Filter orders before grouping, then join with customer info
    filtered_orders = orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}"))

    # Count orders per customer from filtered set, then outer-apply to all customers
    orders_per_cust = filtered_orders.group_by("o_custkey").agg(col("o_orderkey").count().alias("order_cnt"))

    # Left join from customer to order counts (so customers with 0 orders get null -> 0)
    customer_orders = customer.join(
        orders_per_cust, left_on="c_custkey", right_on="o_custkey", how="left"
    ).with_columns(col("order_cnt").fill_null(0).alias("c_count"))

    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v7_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    orders_per_cust = filtered_orders.groupby("o_custkey", as_index=False).agg(order_cnt=("o_orderkey", "count"))

    customer_orders = customer.merge(orders_per_cust, left_on="c_custkey", right_on="o_custkey", how="left")
    customer_orders = customer_orders.copy()
    customer_orders["c_count"] = customer_orders["order_cnt"].fillna(0).astype(int)

    return (
        customer_orders.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# v8: filter combination - use different regex pattern form
# ---------------------------------------------------------------------------


def q13_v8_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Same logic, just filter stored in variable for clarity
    special_request_pattern = f"{word1}.*{word2}"
    non_special = orders.filter(~col("o_comment").str.contains(special_request_pattern))

    customer_orders = (
        customer.join(non_special, left_on="c_custkey", right_on="o_custkey", how="left")
        .group_by("c_custkey")
        .agg(col("o_orderkey").count().alias("c_count"))
    )

    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v8_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    pattern = f"{word1}.*{word2}"
    # Different combination: negate the pattern match first, store separately
    non_special_mask = ~orders["o_comment"].str.contains(pattern, regex=True, na=False)
    filtered_orders = orders[non_special_mask]

    customer_orders = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))

    return (
        order_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# v9: explicit sort - pass descending flags explicitly
# ---------------------------------------------------------------------------


def q13_v9_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    customer_orders = (
        customer.join(
            orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}")),
            left_on="c_custkey",
            right_on="o_custkey",
            how="left",
        )
        .group_by("c_custkey")
        .agg(col("o_orderkey").count().alias("c_count"))
    )

    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v9_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    customer_orders = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))

    return (
        order_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# v10: alternative formula - use value_counts-style aggregation for distribution
# ---------------------------------------------------------------------------


def q13_v10_expression_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Two-step: first build order counts per customer, then distribution
    filtered_orders = orders.filter(~col("o_comment").str.contains(f"{word1}.*{word2}"))

    # Aggregate order counts per customer directly
    order_cnts = filtered_orders.group_by("o_custkey").agg(col("o_orderkey").count().alias("cnt"))

    # Right join so all customers appear (those with no orders get null -> 0)
    customer_counts = customer.join(order_cnts, left_on="c_custkey", right_on="o_custkey", how="left").with_columns(
        col("cnt").fill_null(0).alias("c_count")
    )

    return (
        customer_counts.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q13_v10_pandas_impl(ctx: DataFrameContext) -> Any:
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]
    order_cnts = filtered_orders.groupby("o_custkey", as_index=False).agg(cnt=("o_orderkey", "count"))

    customer_counts = customer.merge(order_cnts, left_on="c_custkey", right_on="o_custkey", how="left").copy()
    customer_counts["c_count"] = customer_counts["cnt"].fillna(0).astype(int)

    return (
        customer_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_IMPL_PAIRS = [
    (q13_v1_expression_impl, q13_v1_pandas_impl),
    (q13_v2_expression_impl, q13_v2_pandas_impl),
    (q13_v3_expression_impl, q13_v3_pandas_impl),
    (q13_v4_expression_impl, q13_v4_pandas_impl),
    (q13_v5_expression_impl, q13_v5_pandas_impl),
    (q13_v6_expression_impl, q13_v6_pandas_impl),
    (q13_v7_expression_impl, q13_v7_pandas_impl),
    (q13_v8_expression_impl, q13_v8_pandas_impl),
    (q13_v9_expression_impl, q13_v9_pandas_impl),
    (q13_v10_expression_impl, q13_v10_pandas_impl),
]

_DESCRIPTIONS = [
    "Baseline: direct delegation to TPC-H Q13 implementation",
    "Pre-filter: filter orders to exclude special requests before left join",
    "Column prune: select only needed columns before joining",
    "Intermediate vars: explicit DataFrames for filter, join, count, distribute steps",
    "Pre-compute derived: filter valid orders before building distribution",
    "Chained style: maximum method chaining, no named intermediates",
    "Join reorder: pre-aggregate order counts then left join to all customers",
    "Filter combination: pattern stored in variable, mask applied separately",
    "Explicit sort: descending=[True, True] passed explicitly",
    "Alternative formula: pre-aggregate order counts with fill_null(0) for zero-order customers",
]

Q13_VARIANTS: list[DataFrameQuery] = [
    DataFrameQuery(
        query_id=f"Q13v{v}",
        query_name=f"TPC-H Q13 Variant {v}",
        description=_DESCRIPTIONS[v - 1],
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=expr_impl,
        pandas_impl=pandas_impl,
    )
    for v, (expr_impl, pandas_impl) in enumerate(_IMPL_PAIRS, start=1)
]
