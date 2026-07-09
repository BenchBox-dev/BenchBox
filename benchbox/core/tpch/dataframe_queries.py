"""TPC-H DataFrame queries for Expression and Pandas families.

This module provides DataFrame implementations of TPC-H benchmark queries
that can run on both expression-based (Polars, PySpark, DataFusion) and
Pandas-like (Pandas, Modin, Dask) platforms.

Each query is implemented using the DataFrameQuery class with separate
implementations for each family:
- expression_impl: Uses ctx.col(), ctx.lit() for lazy expression building
- pandas_impl: Uses string column access and boolean indexing

The queries follow the official TPC-H specification v3.0.0 with:
- Parameterized dates for SF-based substitutions
- Standard aggregation and sorting requirements
- Correct column naming and ordering

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from datetime import date
from typing import Any

from benchbox.core.dataframe.compat import _to_list
from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

# TPC-H Default Parameters per query (keyed by query_id 1-22).
# These match the inline values currently used by each query function and serve
# as the fallback when no seed-derived overrides are active.
TPCH_DEFAULT_PARAMS: dict[int, dict[str, Any]] = {
    1: {"cutoff_date": date(1998, 9, 2)},
    2: {"size": 15, "type_suffix": "BRASS", "region_name": "EUROPE"},
    3: {"segment": "BUILDING", "order_date": date(1995, 3, 15)},
    4: {"start_date": date(1993, 7, 1), "end_date": date(1993, 10, 1)},
    5: {"region_name": "ASIA", "start_date": date(1994, 1, 1), "end_date": date(1995, 1, 1)},
    6: {
        "start_date": date(1994, 1, 1),
        "end_date": date(1995, 1, 1),
        "discount_low": 0.05,
        "discount_high": 0.07,
        "quantity_limit": 24,
    },
    7: {"nation1": "FRANCE", "nation2": "GERMANY", "start_date": date(1995, 1, 1), "end_date": date(1996, 12, 31)},
    8: {
        "target_nation": "BRAZIL",
        "target_region": "AMERICA",
        "target_type": "ECONOMY ANODIZED STEEL",
        "start_date": date(1995, 1, 1),
        "end_date": date(1996, 12, 31),
    },
    9: {"color": "green"},
    10: {"start_date": date(1993, 10, 1), "end_date": date(1994, 1, 1)},
    11: {"nation_name": "GERMANY", "fraction": 0.0001},
    12: {
        "shipmode1": "MAIL",
        "shipmode2": "SHIP",
        "start_date": date(1994, 1, 1),
        "end_date": date(1995, 1, 1),
    },
    13: {"word1": "special", "word2": "requests"},
    14: {"start_date": date(1995, 9, 1), "end_date": date(1995, 10, 1)},
    15: {"start_date": date(1996, 1, 1), "end_date": date(1996, 4, 1)},
    16: {"brand": "Brand#45", "type_prefix": "MEDIUM POLISHED", "sizes": [49, 14, 23, 45, 19, 3, 36, 9]},
    17: {"brand": "Brand#23", "container": "MED BOX"},
    18: {"quantity_threshold": 300},
    19: {
        "brand1": "Brand#12",
        "brand2": "Brand#23",
        "brand3": "Brand#34",
        "quantity1": 1,
        "quantity2": 10,
        "quantity3": 20,
    },
    20: {
        "color_prefix": "forest",
        "nation_name": "CANADA",
        "start_date": date(1994, 1, 1),
        "end_date": date(1995, 1, 1),
    },
    21: {"nation_name": "SAUDI ARABIA"},
    22: {"country_codes": ["13", "31", "23", "29", "30", "18", "17"]},
}

# Module-level parameter overrides. When set by the dataframe_runner before
# query execution, get_tpch_parameters() merges these into the defaults.
_parameter_overrides: dict[int, dict[str, Any]] | None = None

# Module-level scale factor for scale-dependent parameter defaults. Canonical
# TPC-H Q11 renders its value threshold as 0.0001 / SF (qgen does this); the
# value in TPCH_DEFAULT_PARAMS is the SF=1 rendering. get_tpch_parameters()
# scales it by this factor so unseeded DataFrame runs stay scale-faithful at
# every scale, mirroring the SQL run path's {q11_fraction} rendering. Set by the
# dataframe_runner (and the TPC-Havoc equivalence gate) before execution;
# defaults to 1.0 (the qgen SF=1 rendering).
_scale_factor: float = 1.0


def set_parameter_overrides(overrides: dict[int, dict[str, Any]] | None) -> None:
    """Set parameter overrides for the current benchmark run.

    Called by the dataframe_runner before query execution to inject seed-derived
    parameters. Pass None to clear overrides and revert to static defaults.

    Args:
        overrides: Dict mapping query_id (1-22) to param dict, or None to clear.
    """
    global _parameter_overrides
    _parameter_overrides = overrides


def set_scale_factor(scale_factor: float | None) -> None:
    """Set the scale factor used for scale-dependent parameter defaults.

    Canonical TPC-H Q11 renders its value threshold as ``0.0001 / SF``. The
    dataframe_runner calls this before query execution so unseeded runs derive
    the scale-correct Q11 fraction (mirroring the SQL run path) instead of
    always using the SF=1 default. Pass ``None`` (or ``1.0``) to reset to the
    SF=1 rendering.

    Seed-derived overrides (see :func:`set_parameter_overrides`) take precedence
    over the scaled default, so seeded runs are unaffected.

    Args:
        scale_factor: The run's scale factor, or None to reset to 1.0.
    """
    global _scale_factor
    _scale_factor = 1.0 if scale_factor is None else float(scale_factor)


# Benchmark ids whose DataFrame queries reuse this module's parameter seam
# (get_tpch_parameters / the scale-dependent Q11 default). TPC-H Skew
# re-registers the TPC-H DataFrame queries verbatim and TPC-Havoc's variants
# read the same seam, so all three derive Q11's 0.0001/SF threshold from the
# run's scale factor the same way.
TPCH_FAMILY_DATAFRAME_IDS = frozenset({"tpch", "tpch_skew", "tpchavoc"})


def set_scale_factor_for_benchmark(benchmark_id: str, scale_factor: float | None) -> None:
    """Apply :func:`set_scale_factor` for TPC-H-family DataFrame benchmarks.

    A no-op for any benchmark whose DataFrame queries do not share this module's
    parameter seam (see :data:`TPCH_FAMILY_DATAFRAME_IDS`). Pass
    ``scale_factor=None`` to reset to the SF=1 rendering. Both the production
    DataFrame execution path (``BenchmarkExecutionMixin``) and the compatibility
    runner call this so unseeded runs derive Q11's 0.0001/SF threshold at every
    scale.

    Args:
        benchmark_id: Normalized benchmark id (e.g. from normalize_benchmark_id).
        scale_factor: The run's scale factor, or None to reset to 1.0.
    """
    if benchmark_id in TPCH_FAMILY_DATAFRAME_IDS:
        set_scale_factor(scale_factor)


def get_tpch_parameters(query_id: int) -> dict[str, Any]:
    """Get parameters for a TPC-H query.

    Q11's value threshold is scale-dependent: canonical qgen renders it as
    ``0.0001 / SF``. The default in TPCH_DEFAULT_PARAMS is the SF=1 value, so it
    is scaled by the active scale factor (set via :func:`set_scale_factor`) to
    keep unseeded DataFrame runs aligned with the SQL run path at every scale.

    If parameter overrides are active (set via :func:`set_parameter_overrides`),
    override values are merged on top, so seed-derived parameters win over the
    scaled default.

    Args:
        query_id: Query number (1-22)

    Returns:
        Dict of parameter values for this query.
    """
    params = dict(TPCH_DEFAULT_PARAMS.get(query_id, {}))
    if query_id == 11 and "fraction" in params and _scale_factor > 0:
        # Mirror canonical qgen's `0.0001 / SF` rendering exactly - including its
        # 10-decimal literal - so the unseeded default matches both the SQL run
        # path's {q11_fraction} token and the seeded extraction (which parses
        # that same literal). TPCH_DEFAULT_PARAMS holds the SF=1 base value.
        params["fraction"] = float(f"{params['fraction'] / _scale_factor:.10f}")
    if _parameter_overrides is not None and query_id in _parameter_overrides:
        params.update(_parameter_overrides[query_id])
    return params


# =============================================================================
# Expression Family Implementations (Polars, PySpark, DataFusion)
# =============================================================================


def q1_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q1: Pricing Summary Report (Expression Family).

    Reports pricing summary statistics for all lineitems shipped before
    a specific date, grouped by return flag and line status.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Filter: l_shipdate <= date '1998-12-01' - interval '90' day
    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    return (
        lineitem.filter(col("l_shipdate") <= lit(cutoff_date))
        .group_by("l_returnflag", "l_linestatus")
        .agg(
            col("l_quantity").sum().alias("sum_qty"),
            col("l_extendedprice").sum().alias("sum_base_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("sum_disc_price"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).sum().alias("sum_charge"),
            col("l_quantity").mean().alias("avg_qty"),
            col("l_extendedprice").mean().alias("avg_price"),
            col("l_discount").mean().alias("avg_disc"),
            col("l_orderkey").count().alias("count_order"),
        )
        .sort("l_returnflag", "l_linestatus")
    )


def q3_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q3: Shipping Priority (Expression Family).

    Retrieves the 10 unshipped orders with the highest value, ordered by
    value and order date.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    # Join customer -> orders -> lineitem
    # Filter by segment, order date, and ship date
    return (
        customer.filter(col("c_mktsegment") == lit(segment))
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter(col("o_orderdate") < lit(order_date))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") > lit(order_date))
        .group_by("o_orderkey", "o_orderdate", "o_shippriority")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .select("o_orderkey", "revenue", "o_orderdate", "o_shippriority")
        .sort(["revenue", "o_orderdate"], descending=[True, False])
        .limit(10)
    )


def q4_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q4: Order Priority Checking (Expression Family).

    Counts orders by priority where at least one lineitem was received
    late (after commit date).
    """
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Find orders with late lineitems using semi-join pattern
    late_orders = lineitem.filter(col("l_commitdate") < col("l_receiptdate")).select("l_orderkey").unique()

    return (
        orders.filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(late_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .group_by("o_orderpriority")
        .agg(col("o_orderkey").count().alias("order_count"))
        .sort("o_orderpriority")
    )


def q5_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q5: Local Supplier Volume (Expression Family).

    Lists revenue from orders where customer and supplier are in the
    same nation within a specific region.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        region.filter(col("r_name") == lit(region_name))
        .join(nation, left_on="r_regionkey", right_on="n_regionkey")
        .join(customer, left_on="n_nationkey", right_on="c_nationkey")
        .join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .join(
            supplier,
            left_on=["l_suppkey", "n_nationkey"],
            right_on=["s_suppkey", "s_nationkey"],
        )
        .group_by("n_name")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .sort("revenue", descending=True)
    )


def q6_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q6: Forecasting Revenue Change (Expression Family).

    Quantifies revenue increase from eliminating certain discounts.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    return (
        lineitem.filter(
            (col("l_shipdate") >= lit(start_date))
            & (col("l_shipdate") < lit(end_date))
            & (col("l_discount") >= lit(discount_low))
            & (col("l_discount") <= lit(discount_high))
            & (col("l_quantity") < lit(quantity_limit))
        )
        .select((col("l_extendedprice") * col("l_discount")).alias("revenue"))
        .sum()
    )


def q10_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q10: Returned Item Reporting (Expression Family).

    Identifies customers who have returned parts and their revenue impact.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") < lit(end_date)))
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_returnflag") == lit("R"))
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .group_by(
            "c_custkey",
            "c_name",
            "c_acctbal",
            "c_phone",
            "n_name",
            "c_address",
            "c_comment",
        )
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"))
        .select("c_custkey", "c_name", "revenue", "c_acctbal", "n_name", "c_address", "c_phone", "c_comment")
        .sort("revenue", descending=True)
        .limit(20)
    )


def q12_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q12: Shipping Modes and Order Priority (Expression Family).

    Determines whether selecting less expensive shipping modes affects
    the priority of orders.
    """
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.filter(
            (col("l_shipmode").is_in([shipmode1, shipmode2]))
            & (col("l_commitdate") < col("l_receiptdate"))
            & (col("l_shipdate") < col("l_commitdate"))
            & (col("l_receiptdate") >= lit(start_date))
            & (col("l_receiptdate") < lit(end_date))
        )
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .group_by("l_shipmode")
        .agg(
            col("o_orderpriority")
            .filter(col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("high_line_count"),
            col("o_orderpriority")
            .filter(~col("o_orderpriority").is_in(["1-URGENT", "2-HIGH"]))
            .count()
            .alias("low_line_count"),
        )
        .sort("l_shipmode")
    )


def q14_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q14: Promotion Effect (Expression Family).

    Monitors the effect of promotions on revenue.
    """
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    return (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .join(part, left_on="l_partkey", right_on="p_partkey")
        .select(
            (
                lit(100.0)
                * (col("l_extendedprice") * (lit(1) - col("l_discount")))
                .filter(col("p_type").str.starts_with("PROMO"))
                .sum()
                / (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum()
            ).alias("promo_revenue")
        )
    )


def q7_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q7: Volume Shipping (Expression Family).

    Determines the value of goods shipped between certain nations.
    """
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Alias nation table for supplier and customer nations
    n1 = nation.select(col("n_nationkey").alias("n1_nationkey"), col("n_name").alias("supp_nation"))
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("cust_nation"))

    return (
        supplier.join(n1, left_on="s_nationkey", right_on="n1_nationkey")
        .join(lineitem, left_on="s_suppkey", right_on="l_suppkey")
        .filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") <= lit(end_date)))
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(n2, left_on="c_nationkey", right_on="n2_nationkey")
        .filter(
            ((col("supp_nation") == lit(nation1)) & (col("cust_nation") == lit(nation2)))
            | ((col("supp_nation") == lit(nation2)) & (col("cust_nation") == lit(nation1)))
        )
        .with_columns(
            col("l_shipdate").dt.year().alias("l_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("supp_nation", "cust_nation", "l_year")
        .agg(col("volume").sum().alias("revenue"))
        .sort("supp_nation", "cust_nation", "l_year")
    )


def q8_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q8: National Market Share (Expression Family).

    Determines market share of a given nation within a given region.
    """
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Alias nation for supplier nation
    n2 = nation.select(col("n_nationkey").alias("n2_nationkey"), col("n_name").alias("nation"))

    return (
        part.filter(col("p_type") == lit(target_type))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(n2, left_on="s_nationkey", right_on="n2_nationkey")
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter((col("o_orderdate") >= lit(start_date)) & (col("o_orderdate") <= lit(end_date)))
        .join(customer, left_on="o_custkey", right_on="c_custkey")
        .join(nation, left_on="c_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(target_region))
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("volume"),
        )
        .group_by("o_year")
        .agg(
            col("volume").filter(col("nation") == lit(target_nation)).sum().alias("nation_volume"),
            col("volume").sum().alias("total_volume"),
        )
        .with_columns((col("nation_volume") / col("total_volume")).alias("mkt_share"))
        .select("o_year", "mkt_share")
        .sort("o_year")
    )


def q9_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q9: Product Type Profit Measure (Expression Family).

    Determines how much profit is made on a given line of parts.
    """
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(9)
    color = params["color"]

    return (
        part.filter(col("p_name").str.contains(color))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(supplier, left_on="l_suppkey", right_on="s_suppkey")
        .join(
            partsupp,
            left_on=["l_suppkey", "p_partkey"],
            right_on=["ps_suppkey", "ps_partkey"],
        )
        .join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .with_columns(
            col("o_orderdate").dt.year().alias("o_year"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) - col("ps_supplycost") * col("l_quantity")).alias(
                "amount"
            ),
        )
        .group_by(col("n_name").alias("nation"), "o_year")
        .agg(col("amount").sum().alias("sum_profit"))
        .sort(["nation", "o_year"], descending=[False, True])
    )


def q13_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q13: Customer Distribution (Expression Family).

    Determines the distribution of customers by order count.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Left outer join customers to orders (excluding special requests)
    # Count orders per customer
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

    # Count customers per order count
    return (
        customer_orders.group_by("c_count")
        .agg(col("c_custkey").count().alias("custdist"))
        .sort(["custdist", "c_count"], descending=[True, True])
    )


def q18_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q18: Large Volume Customer (Expression Family).

    Ranks customers based on large orders.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(18)
    quantity_threshold = params["quantity_threshold"]

    # Find orders with large total quantity
    large_orders = (
        lineitem.group_by("l_orderkey")
        .agg(col("l_quantity").sum().alias("total_qty"))
        .filter(col("total_qty") > lit(quantity_threshold))
        .select("l_orderkey")
    )

    return (
        customer.join(orders, left_on="c_custkey", right_on="o_custkey")
        .join(large_orders, left_on="o_orderkey", right_on="l_orderkey", how="semi")
        .join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .group_by("c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice")
        .agg(col("l_quantity").sum().alias("sum_qty"))
        .sort(["o_totalprice", "o_orderdate"], descending=[True, False])
        .limit(100)
    )


def q19_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q19: Discounted Revenue (Expression Family).

    Computes revenue for certain parts with specific conditions.
    """
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(19)
    brand1 = params["brand1"]
    brand2 = params["brand2"]
    brand3 = params["brand3"]
    quantity1 = params["quantity1"]
    quantity2 = params["quantity2"]
    quantity3 = params["quantity3"]

    sm_containers = ["SM CASE", "SM BOX", "SM PACK", "SM PKG"]
    med_containers = ["MED BAG", "MED BOX", "MED PKG", "MED PACK"]
    lg_containers = ["LG CASE", "LG BOX", "LG PACK", "LG PKG"]
    ship_modes = ["AIR", "AIR REG"]

    # Join and apply complex OR conditions
    return (
        lineitem.join(part, left_on="l_partkey", right_on="p_partkey")
        .filter(
            col("l_shipmode").is_in(ship_modes)
            & (col("l_shipinstruct") == lit("DELIVER IN PERSON"))
            & (
                (
                    (col("p_brand") == lit(brand1))
                    & col("p_container").is_in(sm_containers)
                    & (col("l_quantity") >= lit(quantity1))
                    & (col("l_quantity") <= lit(quantity1 + 10))
                    & (col("p_size") >= lit(1))
                    & (col("p_size") <= lit(5))
                )
                | (
                    (col("p_brand") == lit(brand2))
                    & col("p_container").is_in(med_containers)
                    & (col("l_quantity") >= lit(quantity2))
                    & (col("l_quantity") <= lit(quantity2 + 10))
                    & (col("p_size") >= lit(1))
                    & (col("p_size") <= lit(10))
                )
                | (
                    (col("p_brand") == lit(brand3))
                    & col("p_container").is_in(lg_containers)
                    & (col("l_quantity") >= lit(quantity3))
                    & (col("l_quantity") <= lit(quantity3 + 10))
                    & (col("p_size") >= lit(1))
                    & (col("p_size") <= lit(15))
                )
            )
        )
        .select((col("l_extendedprice") * (lit(1) - col("l_discount"))).alias("revenue"))
        .sum()
    )


def q2_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q2: Minimum Cost Supplier (Expression Family).

    Finds the supplier with minimum cost for a given part size and type
    within a region.
    """
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Find minimum supply cost per part in the region
    min_cost_per_part = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .group_by("ps_partkey")
        .agg(col("ps_supplycost").min().alias("min_cost"))
    )

    # Main query joining with minimum costs
    return (
        part.filter((col("p_size") == lit(size)) & col("p_type").str.ends_with(type_suffix))
        .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .filter(col("r_name") == lit(region_name))
        .join(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
        .filter(col("ps_supplycost") == col("min_cost"))
        .select(
            "s_acctbal",
            "s_name",
            "n_name",
            "p_partkey",
            "p_mfgr",
            "s_address",
            "s_phone",
            "s_comment",
        )
        .sort(["s_acctbal", "n_name", "s_name", "p_partkey"], descending=[True, False, False, False])
        .limit(100)
    )


def q11_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q11: Important Stock Identification (Expression Family).

    Finds the most important subset of suppliers' stock in a nation.
    """
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Calculate total value for the nation
    nation_stock = (
        partsupp.join(supplier, left_on="ps_suppkey", right_on="s_suppkey")
        .join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .filter(col("n_name") == lit(nation_name))
        .with_columns((col("ps_supplycost") * col("ps_availqty")).alias("value"))
    )

    # Calculate threshold using optimized scalar extraction
    total_value = ctx.scalar(nation_stock.select(col("value").sum().alias("total")))
    threshold = total_value * fraction

    # Find parts above threshold
    return (
        nation_stock.group_by("ps_partkey")
        .agg(col("value").sum().alias("value"))
        .filter(col("value") > lit(threshold))
        .sort("value", descending=True)
    )


def q15_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q15: Top Supplier (Expression Family).

    Determines the top supplier based on revenue from lineitems.
    """
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Calculate revenue per supplier (CTE-like pattern)
    revenue = (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by(col("l_suppkey").alias("supplier_no"))
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("total_revenue"))
    )

    # Find maximum revenue using optimized scalar extraction
    max_revenue = ctx.scalar(revenue.select(col("total_revenue").max().alias("max_rev")))

    # Join with suppliers having maximum revenue
    return (
        supplier.join(revenue, left_on="s_suppkey", right_on="supplier_no")
        .filter(col("total_revenue") == lit(max_revenue))
        .select("s_suppkey", "s_name", "s_address", "s_phone", "total_revenue")
        .sort("s_suppkey")
    )


def q16_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q16: Parts/Supplier Relationship (Expression Family).

    Counts suppliers for parts matching certain criteria, excluding
    suppliers with complaints.
    """
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(16)
    brand = params["brand"]
    type_prefix = params["type_prefix"]
    sizes = params["sizes"]

    # Find suppliers with complaints (to exclude)
    complaint_suppliers = supplier.filter(col("s_comment").str.contains("Customer.*Complaints")).select("s_suppkey")

    # Main query
    return (
        part.filter(
            (col("p_brand") != lit(brand)) & ~col("p_type").str.starts_with(type_prefix) & col("p_size").is_in(sizes)
        )
        .join(partsupp, left_on="p_partkey", right_on="ps_partkey")
        .join(complaint_suppliers, left_on="ps_suppkey", right_on="s_suppkey", how="anti")
        .group_by("p_brand", "p_type", "p_size")
        .agg(col("ps_suppkey").n_unique().alias("supplier_cnt"))
        .sort(["supplier_cnt", "p_brand", "p_type", "p_size"], descending=[True, False, False, False])
    )


def q17_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q17: Small-Quantity-Order Revenue (Expression Family).

    Determines potential revenue increase from eliminating small quantity orders.
    """
    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(17)
    brand = params["brand"]
    container = params["container"]

    # Calculate average quantity per part
    avg_qty_per_part = lineitem.group_by("l_partkey").agg((col("l_quantity").mean() * lit(0.2)).alias("avg_qty"))

    # Main query
    return (
        part.filter((col("p_brand") == lit(brand)) & (col("p_container") == lit(container)))
        .join(lineitem, left_on="p_partkey", right_on="l_partkey")
        .join(avg_qty_per_part, left_on="p_partkey", right_on="l_partkey")
        .filter(col("l_quantity") < col("avg_qty"))
        .select((col("l_extendedprice").sum() / lit(7.0)).alias("avg_yearly"))
    )


def q20_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q20: Potential Part Promotion (Expression Family).

    Identifies suppliers with excess inventory of specific parts.
    """
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(20)
    color_prefix = params["color_prefix"]
    nation_name = params["nation_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Find parts with color prefix
    forest_parts = part.filter(col("p_name").str.starts_with(color_prefix)).select("p_partkey")

    # Calculate half the quantity shipped per part-supplier combo
    shipped_qty = (
        lineitem.filter((col("l_shipdate") >= lit(start_date)) & (col("l_shipdate") < lit(end_date)))
        .group_by("l_partkey", "l_suppkey")
        .agg((col("l_quantity").sum() * lit(0.5)).alias("threshold"))
    )

    # Find partsupps with availability above threshold
    excess_partsupps = (
        partsupp.join(forest_parts, left_on="ps_partkey", right_on="p_partkey", how="semi")
        .join(shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"])
        .filter(col("ps_availqty") > col("threshold"))
        .select("ps_suppkey")
        .unique()
    )

    # Main query
    return (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .filter(col("n_name") == lit(nation_name))
        .join(excess_partsupps, left_on="s_suppkey", right_on="ps_suppkey", how="semi")
        .select("s_name", "s_address")
        .sort("s_name")
    )


def q21_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q21: Suppliers Who Kept Orders Waiting (Expression Family).

    Identifies suppliers who delayed orders they could have filled.

    Optimized using filter pushdown to compute expensive aggregates
    only for relevant orders, avoiding the costly unique() + join pattern.
    """
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(21)
    nation_name = params["nation_name"]

    # Step 1: Target suppliers from the specified nation (small set ~400)
    target_suppliers = (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .filter(col("n_name") == lit(nation_name))
        .select(col("s_suppkey").alias("target_suppkey"), col("s_name"))
    )

    # Step 2: Valid orders with status 'F'
    valid_orders = orders.filter(col("o_orderstatus") == lit("F")).select(col("o_orderkey").alias("valid_orderkey"))

    # Step 3: Candidates - late lineitems from target suppliers on valid orders
    # This is our candidate set - much smaller than full lineitem table
    candidates = (
        lineitem.filter(col("l_receiptdate") > col("l_commitdate"))
        .join(target_suppliers, left_on="l_suppkey", right_on="target_suppkey")
        .join(valid_orders, left_on="l_orderkey", right_on="valid_orderkey")
        .select("l_orderkey", "l_suppkey", "s_name")
    )

    # Step 4: Get candidate order keys for semi-join filtering
    candidate_orders = candidates.select(col("l_orderkey").alias("cand_orderkey")).unique()

    # Count distinct suppliers per order (only for candidate orders)
    # This implements the EXISTS check: order has multiple suppliers
    suppliers_per_order = (
        lineitem.join(candidate_orders, left_on="l_orderkey", right_on="cand_orderkey", how="semi")
        .group_by("l_orderkey")
        .agg(col("l_suppkey").n_unique().alias("num_suppliers"))
        .select(col("l_orderkey").alias("supp_orderkey"), col("num_suppliers"))
    )

    # Count distinct LATE suppliers per order (only for candidate orders)
    # This implements the NOT EXISTS check: no other supplier was late
    late_suppliers_per_order = (
        lineitem.filter(col("l_receiptdate") > col("l_commitdate"))
        .join(candidate_orders, left_on="l_orderkey", right_on="cand_orderkey", how="semi")
        .group_by("l_orderkey")
        .agg(col("l_suppkey").n_unique().alias("num_late_suppliers"))
        .select(col("l_orderkey").alias("late_orderkey"), col("num_late_suppliers"))
    )

    # Step 5: Join candidates with counts and apply EXISTS/NOT EXISTS as filters
    return (
        candidates.join(suppliers_per_order, left_on="l_orderkey", right_on="supp_orderkey")
        .join(late_suppliers_per_order, left_on="l_orderkey", right_on="late_orderkey")
        # EXISTS: order has multiple suppliers
        .filter(col("num_suppliers") > lit(1))
        # NOT EXISTS: only this supplier was late (no other late suppliers)
        # If num_late_suppliers == 1, and we're a late supplier, no one else was late
        .filter(col("num_late_suppliers") == lit(1))
        # Final aggregation
        .group_by("s_name")
        .agg(col("l_orderkey").count().alias("numwait"))
        .sort(["numwait", "s_name"], descending=[True, False])
        .limit(100)
    )


def q22_expression_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q22: Global Sales Opportunity (Expression Family).

    Identifies geographic areas with customers likely to make purchases.
    """
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    params = get_tpch_parameters(22)
    country_codes = params["country_codes"]

    # Extract country code from phone
    customer_with_code = customer.with_columns(col("c_phone").str.slice(0, 2).alias("cntrycode"))

    # Calculate average account balance for positive accounts in selected countries
    # Using optimized scalar extraction
    avg_balance = ctx.scalar(
        customer_with_code.filter((col("c_acctbal") > lit(0)) & col("cntrycode").is_in(country_codes)).select(
            col("c_acctbal").mean().alias("avg_bal")
        )
    )

    # Find customers without orders
    customers_with_orders = orders.select("o_custkey").unique()

    # Main query
    return (
        customer_with_code.filter(col("cntrycode").is_in(country_codes) & (col("c_acctbal") > lit(avg_balance)))
        .join(customers_with_orders, left_on="c_custkey", right_on="o_custkey", how="anti")
        .group_by("cntrycode")
        .agg(col("c_custkey").count().alias("numcust"), col("c_acctbal").sum().alias("totacctbal"))
        .sort("cntrycode")
    )


# =============================================================================
# Pandas Family Implementations (Pandas, Modin, Dask)
# =============================================================================


def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q1: Pricing Summary Report (Pandas Family)."""
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(1)
    cutoff_date = params["cutoff_date"]

    # Filter
    filtered = lineitem[lineitem["l_shipdate"] <= cutoff_date]

    # Calculate derived columns
    filtered = filtered.copy()
    filtered["disc_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])
    filtered["charge"] = filtered["disc_price"] * (1 + filtered["l_tax"])

    # Aggregate
    return (
        filtered.groupby(["l_returnflag", "l_linestatus"], as_index=False)
        .agg(
            sum_qty=("l_quantity", "sum"),
            sum_base_price=("l_extendedprice", "sum"),
            sum_disc_price=("disc_price", "sum"),
            sum_charge=("charge", "sum"),
            avg_qty=("l_quantity", "mean"),
            avg_price=("l_extendedprice", "mean"),
            avg_disc=("l_discount", "mean"),
            count_order=("l_orderkey", "count"),
        )
        .sort_values(["l_returnflag", "l_linestatus"])
    )


def q6_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q6: Forecasting Revenue Change (Pandas Family)."""
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(6)
    start_date = params["start_date"]
    end_date = params["end_date"]
    discount_low = params["discount_low"]
    discount_high = params["discount_high"]
    quantity_limit = params["quantity_limit"]

    # Filter
    filtered = lineitem[
        (lineitem["l_shipdate"] >= start_date)
        & (lineitem["l_shipdate"] < end_date)
        & (lineitem["l_discount"] >= discount_low)
        & (lineitem["l_discount"] <= discount_high)
        & (lineitem["l_quantity"] < quantity_limit)
    ]

    # Calculate revenue
    revenue = (filtered["l_extendedprice"] * filtered["l_discount"]).sum()

    # Return as DataFrame with single value
    # Note: compute() handles both lazy (Dask) and eager (Pandas) values
    import pandas as pd

    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue
    return pd.DataFrame({"revenue": [revenue_val]})


def q3_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q3: Shipping Priority (Pandas Family)."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(3)
    segment = params["segment"]
    order_date = params["order_date"]

    # Filter customer by segment
    filtered_customer = customer[customer["c_mktsegment"] == segment]

    # Join customer -> orders
    customer_orders = filtered_customer.merge(orders, left_on="c_custkey", right_on="o_custkey")

    # Filter orders by date
    customer_orders = customer_orders[customer_orders["o_orderdate"] < order_date]

    # Join with lineitem
    joined = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")

    # Filter by ship date
    joined = joined[joined["l_shipdate"] > order_date]

    # Calculate revenue
    joined = joined.copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    # Aggregate
    return (
        joined.groupby(["l_orderkey", "o_orderdate", "o_shippriority"], as_index=False)
        .agg(revenue=("revenue", "sum"))[["l_orderkey", "revenue", "o_orderdate", "o_shippriority"]]
        .sort_values(["revenue", "o_orderdate"], ascending=[False, True])
        .head(10)
    )


def q4_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q4: Order Priority Checking (Pandas Family)."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(4)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Find orders with late lineitems
    late_lineitems = lineitem[lineitem["l_commitdate"] < lineitem["l_receiptdate"]]
    late_orderkeys = _to_list(late_lineitems["l_orderkey"].unique())

    # Filter orders by date range
    filtered_orders = orders[(orders["o_orderdate"] >= start_date) & (orders["o_orderdate"] < end_date)]

    # Keep only orders with late lineitems (semi-join)
    filtered_orders = filtered_orders[filtered_orders["o_orderkey"].isin(late_orderkeys)]

    # Count by priority
    return (
        filtered_orders.groupby("o_orderpriority", as_index=False)
        .agg(order_count=("o_orderkey", "count"))
        .sort_values("o_orderpriority")
    )


def q5_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q5: Local Supplier Volume (Pandas Family)."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(5)
    region_name = params["region_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Filter region
    asia_region = region[region["r_name"] == region_name]

    # Join region -> nation
    asia_nations = asia_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")

    # Join nation -> customer
    asia_customers = asia_nations.merge(customer, left_on="n_nationkey", right_on="c_nationkey")

    # Join customer -> orders, filter by date
    customer_orders = asia_customers.merge(orders, left_on="c_custkey", right_on="o_custkey")
    customer_orders = customer_orders[
        (customer_orders["o_orderdate"] >= start_date) & (customer_orders["o_orderdate"] < end_date)
    ]

    # Join orders -> lineitem
    order_lines = customer_orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")

    # Join lineitem -> supplier (same nation requirement)
    joined = order_lines.merge(supplier, left_on=["l_suppkey", "c_nationkey"], right_on=["s_suppkey", "s_nationkey"])

    # Calculate revenue
    joined = joined.copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    # Aggregate by nation
    return (
        joined.groupby("n_name", as_index=False).agg(revenue=("revenue", "sum")).sort_values("revenue", ascending=False)
    )


def q10_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q10: Returned Item Reporting (Pandas Family)."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(10)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Projection pushdown: carry only the columns each stage needs so the wide
    # string columns (c_comment, l_comment, o_comment, ...) never ride through
    # the large lineitem join. Push the l_returnflag='R' filter below the join,
    # and group by the narrow integer keys (c_custkey is the customer PK so it
    # functionally determines the other customer attributes; c_nationkey -> n_name),
    # then rejoin the small detail columns onto the aggregated result. This keeps
    # the groupby off wide string keys and is what lets the graph fit a
    # constrained local Dask envelope; the result is identical to grouping by all
    # seven output columns.
    customer_keys = customer[["c_custkey", "c_nationkey"]]
    customer_detail = customer[["c_custkey", "c_name", "c_acctbal", "c_phone", "c_address", "c_comment"]]

    orders_window = orders[["o_orderkey", "o_custkey", "o_orderdate"]]
    orders_window = orders_window[
        (orders_window["o_orderdate"] >= start_date) & (orders_window["o_orderdate"] < end_date)
    ]

    returned_lines = lineitem[["l_orderkey", "l_extendedprice", "l_discount", "l_returnflag"]]
    returned_lines = returned_lines[returned_lines["l_returnflag"] == "R"]
    returned_lines = returned_lines.assign(
        revenue=returned_lines["l_extendedprice"] * (1 - returned_lines["l_discount"])
    )[["l_orderkey", "revenue"]]

    customer_orders = customer_keys.merge(orders_window, left_on="c_custkey", right_on="o_custkey")
    order_lines = customer_orders.merge(returned_lines, left_on="o_orderkey", right_on="l_orderkey")

    revenue_by_customer = order_lines.groupby(["c_custkey", "c_nationkey"], as_index=False).agg(
        revenue=("revenue", "sum")
    )

    with_nation = revenue_by_customer.merge(
        nation[["n_nationkey", "n_name"]], left_on="c_nationkey", right_on="n_nationkey"
    )
    with_detail = with_nation.merge(customer_detail, on="c_custkey")

    return (
        with_detail[["c_custkey", "c_name", "revenue", "c_acctbal", "n_name", "c_address", "c_phone", "c_comment"]]
        .sort_values("revenue", ascending=False)
        .head(20)
    )


def q2_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q2: Minimum Cost Supplier (Pandas Family)."""
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    partsupp = ctx.get_table("partsupp")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(2)
    size = params["size"]
    type_suffix = params["type_suffix"]
    region_name = params["region_name"]

    # Filter region
    europe_region = region[region["r_name"] == region_name]

    # Join region -> nation
    europe_nations = europe_region.merge(nation, left_on="r_regionkey", right_on="n_regionkey")

    # Join nation -> supplier
    europe_suppliers = europe_nations.merge(supplier, left_on="n_nationkey", right_on="s_nationkey")

    # Join supplier -> partsupp
    supplier_parts = europe_suppliers.merge(partsupp, left_on="s_suppkey", right_on="ps_suppkey")

    # Calculate minimum supply cost per part in region
    min_cost_per_part = supplier_parts.groupby("ps_partkey", as_index=False).agg(min_cost=("ps_supplycost", "min"))

    # Filter parts by size and type
    filtered_parts = part[(part["p_size"] == size) & (part["p_type"].str.endswith(type_suffix))]

    # Join parts with partsupp
    part_supplier = filtered_parts.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")

    # Join with supplier
    part_supplier = part_supplier.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")

    # Join with nation
    part_supplier = part_supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")

    # Join with region to filter to Europe only
    part_supplier = part_supplier.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    part_supplier = part_supplier[part_supplier["r_name"] == region_name]

    # Join with minimum costs to filter to minimum cost suppliers
    part_supplier = part_supplier.merge(min_cost_per_part, left_on="p_partkey", right_on="ps_partkey")
    part_supplier = part_supplier[part_supplier["ps_supplycost"] == part_supplier["min_cost"]]

    # Select and sort
    return (
        part_supplier[["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"]]
        .sort_values(["s_acctbal", "n_name", "s_name", "p_partkey"], ascending=[False, True, True, True])
        .head(100)
    )


def q7_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q7: Volume Shipping (Pandas Family)."""
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(7)
    nation1 = params["nation1"]
    nation2 = params["nation2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Create nation aliases
    n1 = nation[["n_nationkey", "n_name"]].copy()
    n1.columns = ["n1_nationkey", "supp_nation"]
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "cust_nation"]

    # Join supplier with supplier nation
    supplier_with_nation = supplier.merge(n1, left_on="s_nationkey", right_on="n1_nationkey")

    # Join with lineitem, filter by date
    joined = supplier_with_nation.merge(lineitem, left_on="s_suppkey", right_on="l_suppkey")
    joined = joined[(joined["l_shipdate"] >= start_date) & (joined["l_shipdate"] <= end_date)]

    # Join with orders
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")

    # Join with customer
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")

    # Join with customer nation
    joined = joined.merge(n2, left_on="c_nationkey", right_on="n2_nationkey")

    # Filter for France<->Germany pairs
    joined = joined[
        ((joined["supp_nation"] == nation1) & (joined["cust_nation"] == nation2))
        | ((joined["supp_nation"] == nation2) & (joined["cust_nation"] == nation1))
    ]

    # Calculate year and volume
    # Note: .dt.year works directly on pyarrow date types (from parquet)
    # No need for pd.to_datetime which breaks Dask
    joined = joined.copy()
    joined["l_year"] = joined["l_shipdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    # Aggregate
    return (
        joined.groupby(["supp_nation", "cust_nation", "l_year"], as_index=False)
        .agg(revenue=("volume", "sum"))
        .sort_values(["supp_nation", "cust_nation", "l_year"])
    )


def q8_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q8: National Market Share (Pandas Family)."""
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    customer = ctx.get_table("customer")
    nation = ctx.get_table("nation")
    region = ctx.get_table("region")

    params = get_tpch_parameters(8)
    target_nation = params["target_nation"]
    target_region = params["target_region"]
    target_type = params["target_type"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Create nation alias for supplier
    n2 = nation[["n_nationkey", "n_name"]].copy()
    n2.columns = ["n2_nationkey", "nation"]

    # Filter part by type
    filtered_parts = part[part["p_type"] == target_type]

    # Join part -> lineitem
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")

    # Join lineitem -> supplier
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")

    # Join with supplier nation
    joined = joined.merge(n2, left_on="s_nationkey", right_on="n2_nationkey")

    # Join with orders, filter by date
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    joined = joined[(joined["o_orderdate"] >= start_date) & (joined["o_orderdate"] <= end_date)]

    # Join with customer
    joined = joined.merge(customer, left_on="o_custkey", right_on="c_custkey")

    # Join with customer nation
    joined = joined.merge(nation, left_on="c_nationkey", right_on="n_nationkey")

    # Join with region, filter by region
    joined = joined.merge(region, left_on="n_regionkey", right_on="r_regionkey")
    joined = joined[joined["r_name"] == target_region]

    # Calculate year and volume
    # Note: .dt.year works directly on pyarrow date types (from parquet)
    # No need for pd.to_datetime which breaks Dask
    joined = joined.copy()
    joined["o_year"] = joined["o_orderdate"].dt.year
    joined["volume"] = joined["l_extendedprice"] * (1 - joined["l_discount"])

    # Aggregate by year
    yearly = joined.groupby("o_year", as_index=False).agg(total_volume=("volume", "sum"))

    # Aggregate Brazil volume
    brazil_volume = (
        joined[joined["nation"] == target_nation].groupby("o_year", as_index=False).agg(nation_volume=("volume", "sum"))
    )

    # Merge and calculate market share
    result = yearly.merge(brazil_volume, on="o_year", how="left")
    result["nation_volume"] = result["nation_volume"].fillna(0)
    result["mkt_share"] = result["nation_volume"] / result["total_volume"]
    return result[["o_year", "mkt_share"]].sort_values("o_year")


def q9_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q9: Product Type Profit Measure (Pandas Family)."""
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    partsupp = ctx.get_table("partsupp")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(9)
    color = params["color"]

    # Filter parts by name containing color
    filtered_parts = part[part["p_name"].str.contains(color, case=False, na=False)]

    # Join part -> lineitem
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")

    # Join with supplier
    joined = joined.merge(supplier, left_on="l_suppkey", right_on="s_suppkey")

    # Join with partsupp
    joined = joined.merge(partsupp, left_on=["l_suppkey", "p_partkey"], right_on=["ps_suppkey", "ps_partkey"])

    # Join with orders
    joined = joined.merge(orders, left_on="l_orderkey", right_on="o_orderkey")

    # Join with nation
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")

    # Calculate year and amount
    # Note: .dt.year works directly on pyarrow date types (from parquet)
    # No need for pd.to_datetime which breaks Dask
    joined = joined.copy()
    joined["o_year"] = joined["o_orderdate"].dt.year
    joined["amount"] = (
        joined["l_extendedprice"] * (1 - joined["l_discount"]) - joined["ps_supplycost"] * joined["l_quantity"]
    )

    # Aggregate
    return (
        joined.groupby(["n_name", "o_year"], as_index=False)
        .agg(sum_profit=("amount", "sum"))
        .rename(columns={"n_name": "nation"})
        .sort_values(["nation", "o_year"], ascending=[True, False])
    )


def q11_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q11: Important Stock Identification (Pandas Family)."""
    partsupp = ctx.get_table("partsupp")
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(11)
    nation_name = params["nation_name"]
    fraction = params["fraction"]

    # Join partsupp -> supplier
    joined = partsupp.merge(supplier, left_on="ps_suppkey", right_on="s_suppkey")

    # Join with nation, filter by nation
    joined = joined.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    joined = joined[joined["n_name"] == nation_name]

    # Calculate value
    joined = joined.copy()
    joined["value"] = joined["ps_supplycost"] * joined["ps_availqty"]

    # Calculate threshold
    # Note: compute() handles both lazy (Dask) and eager (Pandas) values
    total_value = joined["value"].sum()
    total_value_computed = total_value.compute() if hasattr(total_value, "compute") else total_value
    threshold = total_value_computed * fraction

    # Aggregate by part and filter by threshold
    # Use explicit comparison instead of .query() for Dask compatibility
    aggregated = joined.groupby("ps_partkey", as_index=False).agg(value=("value", "sum"))
    return aggregated[aggregated["value"] > threshold].sort_values("value", ascending=False)


def q12_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q12: Shipping Modes and Order Priority (Pandas Family)."""
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(12)
    shipmode1 = params["shipmode1"]
    shipmode2 = params["shipmode2"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Filter lineitem
    filtered = lineitem[
        (lineitem["l_shipmode"].isin([shipmode1, shipmode2]))
        & (lineitem["l_commitdate"] < lineitem["l_receiptdate"])
        & (lineitem["l_shipdate"] < lineitem["l_commitdate"])
        & (lineitem["l_receiptdate"] >= start_date)
        & (lineitem["l_receiptdate"] < end_date)
    ]

    # Join with orders
    joined = filtered.merge(orders, left_on="l_orderkey", right_on="o_orderkey")

    # Calculate high and low priority counts
    joined = joined.copy()
    joined["high_priority"] = joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"]).astype(int)
    joined["low_priority"] = (~joined["o_orderpriority"].isin(["1-URGENT", "2-HIGH"])).astype(int)

    # Aggregate
    return (
        joined.groupby("l_shipmode", as_index=False)
        .agg(high_line_count=("high_priority", "sum"), low_line_count=("low_priority", "sum"))
        .sort_values("l_shipmode")
    )


def q13_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q13: Customer Distribution (Pandas Family)."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(13)
    word1 = params["word1"]
    word2 = params["word2"]

    # Filter orders to exclude special requests
    filtered_orders = orders[~orders["o_comment"].str.contains(f"{word1}.*{word2}", regex=True, na=False)]

    # Left join customers to filtered orders
    customer_orders = customer.merge(filtered_orders, left_on="c_custkey", right_on="o_custkey", how="left")

    # Count orders per customer (NaN for customers with no orders = 0)
    order_counts = customer_orders.groupby("c_custkey", as_index=False).agg(c_count=("o_orderkey", "count"))

    # Count customers per order count
    return (
        order_counts.groupby("c_count", as_index=False)
        .agg(custdist=("c_custkey", "count"))
        .sort_values(["custdist", "c_count"], ascending=[False, False])
    )


def q14_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q14: Promotion Effect (Pandas Family)."""
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(14)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Filter lineitem by date
    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]

    # Join with part
    joined = filtered.merge(part, left_on="l_partkey", right_on="p_partkey")

    # Calculate revenue
    joined = joined.copy()
    joined["revenue"] = joined["l_extendedprice"] * (1 - joined["l_discount"])
    joined["promo_revenue"] = joined["revenue"] * joined["p_type"].str.startswith("PROMO").astype(float)

    # Calculate promo percentage
    # Note: compute() handles both lazy (Dask) and eager (Pandas) values
    total_revenue = joined["revenue"].sum()
    promo_revenue = joined["promo_revenue"].sum()
    total_val = total_revenue.compute() if hasattr(total_revenue, "compute") else total_revenue
    promo_val = promo_revenue.compute() if hasattr(promo_revenue, "compute") else promo_revenue
    promo_percent = 100.0 * promo_val / total_val if total_val > 0 else 0

    return pd.DataFrame({"promo_revenue": [promo_percent]})


def q15_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q15: Top Supplier (Pandas Family)."""
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(15)
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Filter lineitem and calculate revenue per supplier
    filtered = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    filtered = filtered.copy()
    filtered["revenue"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"])

    revenue = (
        filtered.groupby("l_suppkey", as_index=False)
        .agg(total_revenue=("revenue", "sum"))
        .rename(columns={"l_suppkey": "supplier_no"})
    )

    # Find maximum revenue
    max_revenue = revenue["total_revenue"].max()

    # Join with suppliers having maximum revenue
    top_suppliers = revenue[revenue["total_revenue"] == max_revenue]
    return supplier.merge(top_suppliers, left_on="s_suppkey", right_on="supplier_no")[
        ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"]
    ].sort_values("s_suppkey")


def q16_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q16: Parts/Supplier Relationship (Pandas Family)."""
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    supplier = ctx.get_table("supplier")

    params = get_tpch_parameters(16)
    brand = params["brand"]
    type_prefix = params["type_prefix"]
    sizes = params["sizes"]

    # Find suppliers with complaints
    complaint_suppliers = _to_list(
        supplier[supplier["s_comment"].str.contains("Customer.*Complaints", regex=True, na=False)]["s_suppkey"]
    )

    # Filter parts
    filtered_parts = part[
        (part["p_brand"] != brand) & (~part["p_type"].str.startswith(type_prefix)) & (part["p_size"].isin(sizes))
    ]

    # Join parts with partsupp
    joined = filtered_parts.merge(partsupp, left_on="p_partkey", right_on="ps_partkey")

    # Exclude complaint suppliers
    joined = joined[~joined["ps_suppkey"].isin(complaint_suppliers)]

    # Count unique suppliers per part combination
    return (
        joined.groupby(["p_brand", "p_type", "p_size"], as_index=False)
        .agg(supplier_cnt=("ps_suppkey", "nunique"))
        .sort_values(["supplier_cnt", "p_brand", "p_type", "p_size"], ascending=[False, True, True, True])
    )


def q17_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q17: Small-Quantity-Order Revenue (Pandas Family)."""
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(17)
    brand = params["brand"]
    container = params["container"]

    # Filter parts
    filtered_parts = part[(part["p_brand"] == brand) & (part["p_container"] == container)]

    # Calculate average quantity per part (with 0.2 multiplier)
    avg_qty = lineitem.groupby("l_partkey", as_index=False).agg(avg_qty=("l_quantity", "mean"))
    avg_qty["avg_qty"] = avg_qty["avg_qty"] * 0.2

    # Join parts -> lineitem
    joined = filtered_parts.merge(lineitem, left_on="p_partkey", right_on="l_partkey")

    # Join with average quantity
    joined = joined.merge(avg_qty, on="l_partkey")

    # Filter for small quantities
    joined = joined[joined["l_quantity"] < joined["avg_qty"]]

    # Calculate result
    # Note: compute() handles both lazy (Dask) and eager (Pandas) values
    avg_yearly = joined["l_extendedprice"].sum() / 7.0
    avg_yearly_val = avg_yearly.compute() if hasattr(avg_yearly, "compute") else avg_yearly

    return pd.DataFrame({"avg_yearly": [avg_yearly_val]})


def q18_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q18: Large Volume Customer (Pandas Family)."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(18)
    quantity_threshold = params["quantity_threshold"]

    # Find orders with large total quantity
    order_qty = lineitem.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))
    large_orders = _to_list(order_qty[order_qty["total_qty"] > quantity_threshold]["l_orderkey"])

    # Join customer -> orders
    joined = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")

    # Filter to large orders
    joined = joined[joined["o_orderkey"].isin(large_orders)]

    # Join with lineitem
    joined = joined.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")

    # Aggregate
    return (
        joined.groupby(["c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice"], as_index=False)
        .agg(sum_qty=("l_quantity", "sum"))
        .sort_values(["o_totalprice", "o_orderdate"], ascending=[False, True])
        .head(100)
    )


def q19_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q19: Discounted Revenue (Pandas Family)."""
    import pandas as pd

    lineitem = ctx.get_table("lineitem")
    part = ctx.get_table("part")

    params = get_tpch_parameters(19)
    brand1 = params["brand1"]
    brand2 = params["brand2"]
    brand3 = params["brand3"]
    quantity1 = params["quantity1"]
    quantity2 = params["quantity2"]
    quantity3 = params["quantity3"]

    sm_containers = ["SM CASE", "SM BOX", "SM PACK", "SM PKG"]
    med_containers = ["MED BAG", "MED BOX", "MED PKG", "MED PACK"]
    lg_containers = ["LG CASE", "LG BOX", "LG PACK", "LG PKG"]
    ship_modes = ["AIR", "AIR REG"]

    # Join lineitem with part
    joined = lineitem.merge(part, left_on="l_partkey", right_on="p_partkey")

    # Apply common filters
    joined = joined[(joined["l_shipmode"].isin(ship_modes)) & (joined["l_shipinstruct"] == "DELIVER IN PERSON")]

    # Apply complex OR conditions
    condition1 = (
        (joined["p_brand"] == brand1)
        & (joined["p_container"].isin(sm_containers))
        & (joined["l_quantity"] >= quantity1)
        & (joined["l_quantity"] <= quantity1 + 10)
        & (joined["p_size"] >= 1)
        & (joined["p_size"] <= 5)
    )
    condition2 = (
        (joined["p_brand"] == brand2)
        & (joined["p_container"].isin(med_containers))
        & (joined["l_quantity"] >= quantity2)
        & (joined["l_quantity"] <= quantity2 + 10)
        & (joined["p_size"] >= 1)
        & (joined["p_size"] <= 10)
    )
    condition3 = (
        (joined["p_brand"] == brand3)
        & (joined["p_container"].isin(lg_containers))
        & (joined["l_quantity"] >= quantity3)
        & (joined["l_quantity"] <= quantity3 + 10)
        & (joined["p_size"] >= 1)
        & (joined["p_size"] <= 15)
    )

    filtered = joined[condition1 | condition2 | condition3]

    # Calculate revenue
    # Note: compute() handles both lazy (Dask) and eager (Pandas) values
    revenue = (filtered["l_extendedprice"] * (1 - filtered["l_discount"])).sum()
    revenue_val = revenue.compute() if hasattr(revenue, "compute") else revenue

    return pd.DataFrame({"revenue": [revenue_val]})


def q20_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q20: Potential Part Promotion (Pandas Family)."""
    supplier = ctx.get_table("supplier")
    nation = ctx.get_table("nation")
    partsupp = ctx.get_table("partsupp")
    part = ctx.get_table("part")
    lineitem = ctx.get_table("lineitem")

    params = get_tpch_parameters(20)
    color_prefix = params["color_prefix"]
    nation_name = params["nation_name"]
    start_date = params["start_date"]
    end_date = params["end_date"]

    # Find parts with color prefix
    forest_parts = _to_list(part[part["p_name"].str.startswith(color_prefix)]["p_partkey"])

    # Calculate half the quantity shipped per part-supplier combo
    filtered_lineitem = lineitem[(lineitem["l_shipdate"] >= start_date) & (lineitem["l_shipdate"] < end_date)]
    shipped_qty = filtered_lineitem.groupby(["l_partkey", "l_suppkey"], as_index=False).agg(
        threshold=("l_quantity", "sum")
    )
    shipped_qty["threshold"] = shipped_qty["threshold"] * 0.5

    # Filter partsupp to forest parts
    forest_partsupp = partsupp[partsupp["ps_partkey"].isin(forest_parts)]

    # Join with shipped quantity
    joined = forest_partsupp.merge(
        shipped_qty, left_on=["ps_partkey", "ps_suppkey"], right_on=["l_partkey", "l_suppkey"]
    )

    # Filter for excess availability
    excess_suppliers = _to_list(joined[joined["ps_availqty"] > joined["threshold"]]["ps_suppkey"].unique())

    # Join supplier -> nation, filter by nation and excess suppliers
    supplier_nation = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    return supplier_nation[
        (supplier_nation["n_name"] == nation_name) & (supplier_nation["s_suppkey"].isin(excess_suppliers))
    ][["s_name", "s_address"]].sort_values("s_name")


def q21_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q21: Suppliers Who Kept Orders Waiting (Pandas Family)."""
    supplier = ctx.get_table("supplier")
    lineitem = ctx.get_table("lineitem")
    orders = ctx.get_table("orders")
    nation = ctx.get_table("nation")

    params = get_tpch_parameters(21)
    nation_name = params["nation_name"]

    # Join supplier -> nation, filter by nation
    supplier_nation = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    supplier_nation = supplier_nation[supplier_nation["n_name"] == nation_name]

    # Find late lineitems (from this supplier)
    late_lineitems = lineitem[lineitem["l_receiptdate"] > lineitem["l_commitdate"]]

    # Join supplier with late lineitems
    supplier_late = supplier_nation.merge(late_lineitems, left_on="s_suppkey", right_on="l_suppkey")

    # Join with orders, filter for failed orders
    supplier_late_orders = supplier_late.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    supplier_late_orders = supplier_late_orders[supplier_late_orders["o_orderstatus"] == "F"]

    # Find orders with multiple suppliers (EXISTS condition)
    order_suppliers = lineitem.groupby("l_orderkey").agg(num_suppliers=("l_suppkey", "nunique"))
    multi_supplier_orders = _to_list(order_suppliers[order_suppliers["num_suppliers"] > 1].index)

    # Filter to multi-supplier orders
    supplier_late_orders = supplier_late_orders[supplier_late_orders["l_orderkey"].isin(multi_supplier_orders)]

    # Find orders where NO OTHER supplier was late (NOT EXISTS condition)
    # Get late lineitems by order
    all_late = lineitem[lineitem["l_receiptdate"] > lineitem["l_commitdate"]][["l_orderkey", "l_suppkey"]]

    # For each (order, supplier) in our result, check if another supplier was also late
    result_keys = supplier_late_orders[["l_orderkey", "s_suppkey"]].drop_duplicates()

    # Find orders where another supplier was also late
    # Use vectorized filter instead of .query() for Dask compatibility
    merged = result_keys.merge(all_late, left_on="l_orderkey", right_on="l_orderkey")
    orders_with_other_late = merged[merged["s_suppkey"] != merged["l_suppkey"]][["l_orderkey", "s_suppkey"]]
    orders_with_other_late = orders_with_other_late.drop_duplicates()

    # Exclude these orders using anti-join pattern (Dask-compatible)
    # Add marker column to identify rows to exclude
    orders_with_other_late = orders_with_other_late.copy()
    orders_with_other_late["_exclude"] = True
    supplier_late_orders = supplier_late_orders.merge(
        orders_with_other_late,
        on=["l_orderkey", "s_suppkey"],
        how="left",
    )
    supplier_late_orders = supplier_late_orders[supplier_late_orders["_exclude"].isna()]
    supplier_late_orders = supplier_late_orders.drop(columns=["_exclude"])

    # Count and return
    return (
        supplier_late_orders.groupby("s_name", as_index=False)
        .agg(numwait=("l_orderkey", "count"))
        .sort_values(["numwait", "s_name"], ascending=[False, True])
        .head(100)
    )


def q22_pandas_impl(ctx: DataFrameContext) -> Any:
    """TPC-H Q22: Global Sales Opportunity (Pandas Family)."""
    customer = ctx.get_table("customer")
    orders = ctx.get_table("orders")

    params = get_tpch_parameters(22)
    country_codes = params["country_codes"]

    # Extract country code from phone
    customer = customer.copy()
    customer["cntrycode"] = customer["c_phone"].str[:2]

    # Calculate average account balance for positive accounts in selected countries
    positive_accounts = customer[(customer["c_acctbal"] > 0) & (customer["cntrycode"].isin(country_codes))]
    avg_balance = positive_accounts["c_acctbal"].mean()
    avg_balance = avg_balance.compute() if hasattr(avg_balance, "compute") else avg_balance

    # Find customers without orders
    customers_with_orders = _to_list(orders["o_custkey"].unique())

    # Filter: in selected countries, above average balance, no orders
    result_customers = customer[
        (customer["cntrycode"].isin(country_codes))
        & (customer["c_acctbal"] > avg_balance)
        & (~customer["c_custkey"].isin(customers_with_orders))
    ]

    # Aggregate
    return (
        result_customers.groupby("cntrycode", as_index=False)
        .agg(numcust=("c_custkey", "count"), totacctbal=("c_acctbal", "sum"))
        .sort_values("cntrycode")
    )


# =============================================================================
# Query Registry
# =============================================================================

# Create the TPC-H DataFrame query registry
TPCH_DATAFRAME_QUERIES = QueryRegistry("TPC-H DataFrame")

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "FI": QueryCategory.FILTER,
    "GB": QueryCategory.GROUP_BY,
    "JO": QueryCategory.JOIN,
    "SO": QueryCategory.SORT,
    "SQ": QueryCategory.SUBQUERY,
}

_QUERY_METADATA = """\
Q1|Pricing Summary Report|Pricing summary statistics for shipped lineitems|AG,GB,FI|q1|SELECT l_returnflag, l_linestatus, sum(l_quantity)...|4
Q3|Shipping Priority|Top 10 unshipped orders with highest value|JO,AG,SO|q3||10
Q4|Order Priority Checking|Orders by priority with late lineitems|JO,AG,SQ|q4||5
Q5|Local Supplier Volume|Revenue from orders in same nation within region|JO,AG,FI|q5||
Q6|Forecasting Revenue Change|Revenue increase from eliminating discounts|AG,FI|q6||1
Q10|Returned Item Reporting|Customers with returned parts and revenue impact|JO,AG,SO|q10||20
Q12|Shipping Modes and Order Priority|Effect of shipping modes on order priority|JO,AG,FI|q12||2
Q14|Promotion Effect|Effect of promotions on revenue|JO,AG,FI|q14||1
Q7|Volume Shipping|Value of goods shipped between nations|JO,AG,FI|q7||
Q8|National Market Share|Market share of a nation within a region|JO,AG,FI|q8||
Q9|Product Type Profit Measure|Profit on a given line of parts|JO,AG,FI|q9||
Q13|Customer Distribution|Distribution of customers by order count|JO,AG,SQ|q13||
Q18|Large Volume Customer|Customers with large orders|JO,AG,SQ|q18||100
Q19|Discounted Revenue|Revenue for parts with specific conditions|JO,AG,FI|q19||1
Q2|Minimum Cost Supplier|Find supplier with minimum cost for parts in region|JO,SQ,SO|q2||100
Q11|Important Stock Identification|Find most important stock in a nation|JO,AG,SQ|q11||
Q15|Top Supplier|Determine top supplier based on revenue|JO,AG,SQ|q15||
Q16|Parts/Supplier Relationship|Count suppliers per part, excluding complaints|JO,AG,SQ|q16||
Q17|Small-Quantity-Order Revenue|Revenue from eliminating small quantity orders|JO,AG,SQ|q17||1
Q20|Potential Part Promotion|Suppliers with excess inventory of parts|JO,SQ,FI|q20||
Q21|Suppliers Who Kept Orders Waiting|Suppliers who delayed orders they could fill|JO,AG,SQ|q21||100
Q22|Global Sales Opportunity|Identify customers likely to make purchases|AG,SQ,FI|q22||
"""


def _impl_for(stem: str, family: str) -> Any:
    return globals()[f"{stem}_{family}_impl"]


for query_id, query_name, description, category_codes, impl_stem, sql_equivalent, expected_row_count in reader(
    _QUERY_METADATA.splitlines(), delimiter="|"
):
    TPCH_DATAFRAME_QUERIES.register(
        DataFrameQuery(
            query_id=query_id,
            query_name=query_name,
            description=description,
            categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
            expression_impl=_impl_for(impl_stem, "expression"),
            pandas_impl=_impl_for(impl_stem, "pandas"),
            sql_equivalent=sql_equivalent or None,
            expected_row_count=int(expected_row_count) if expected_row_count else None,
        )
    )


def get_tpch_dataframe_queries() -> QueryRegistry:
    """Get the TPC-H DataFrame query registry.

    Returns:
        QueryRegistry containing all TPC-H DataFrame queries
    """
    return TPCH_DATAFRAME_QUERIES


def get_query(query_id: str) -> DataFrameQuery:
    """Get a specific TPC-H DataFrame query by ID.

    Args:
        query_id: Query identifier (e.g., "Q1", "Q6")

    Returns:
        The DataFrameQuery for the specified ID

    Raises:
        KeyError: If query_id is not found
    """
    return TPCH_DATAFRAME_QUERIES.get_or_raise(query_id)


def list_query_ids() -> list[str]:
    """List all available TPC-H DataFrame query IDs.

    Returns:
        List of query IDs in order (Q1, Q3, Q4, ...)
    """
    return TPCH_DATAFRAME_QUERIES.get_query_ids()
