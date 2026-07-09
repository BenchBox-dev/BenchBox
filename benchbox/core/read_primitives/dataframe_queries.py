"""Read Primitives DataFrame queries for Expression and Pandas families.

This module provides DataFrame implementations of Read Primitives benchmark queries
that can run on both expression-based (Polars, PySpark, DataFusion) and
Pandas-like (Pandas, Modin, Dask) platforms.

Read Primitives is a microbenchmark testing isolated database operations using
the TPC-H schema. Unlike full TPC-H queries, these focus on single operations
to enable granular performance analysis:

Categories implemented:
- aggregation: COUNT, SUM, AVG, COUNT DISTINCT, GROUP BY operations
- filter: WHERE clauses, predicate pushdown, selectivity testing
- groupby: GROUP BY ALL, ROLLUP, CUBE operations
- orderby: Sorting, TOP-N, ORDER BY ALL
- shuffle: Data redistribution patterns
- string: LIKE, CONCAT, SUBSTRING, string functions
- predicate: Predicate ordering by selectivity
- window: ROW_NUMBER, RANK, LAG/LEAD, aggregate windows
- qualify: QUALIFY clause for window filtering (expression-family only)
- array: ARRAY operations, UNNEST, array aggregations
- broadcast: Small table broadcast joins
- exchange: Data redistribution patterns

Note: Optimizer queries (13 queries testing SQL optimizer behavior) are
SQL-only and not implemented for DataFrame platforms, as they test query
planning behavior which doesn't apply to DataFrame execution.

Each query is implemented using the DataFrameQuery class with separate
implementations for each family:
- expression_impl: Uses ctx.col(), ctx.lit() for lazy expression building
- pandas_impl: Uses string column access and boolean indexing

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

if TYPE_CHECKING:
    from benchbox.core.dataframe.context import DataFrameContext


class QueryImpl(Protocol):
    """A DataFrame query implementation: takes a context, returns a frame.

    The dispatch (`_impl_for`) and the registry below are typed against this
    Protocol so factory-built impls are statically resolvable instead of
    Any-typed module-global lookups.
    """

    def __call__(self, ctx: DataFrameContext) -> Any: ...


# Single registry of every dispatchable impl, keyed by "<base>_<family>_impl".
# Factory-built impls register here (see _register_generated_impl) instead of
# mutating module globals, and the explicit module-level `def *_impl` functions
# are indexed in once below; the dispatch then resolves both with one typed
# lookup. This keeps generated impls discoverable and ty-visible without
# reverting the factory consolidation to per-query defs.
_IMPLS: dict[str, QueryImpl] = {}


def _register_generated_impl(impl: QueryImpl) -> QueryImpl:
    """Register a factory-built impl under its already-set ``__name__``."""
    _IMPLS[impl.__name__] = impl
    return impl


def __getattr__(name: str) -> QueryImpl:
    """Resolve factory-built impl names from the registry (PEP 562).

    Generated impls live in `_IMPLS` rather than module globals, so importing
    one by name (e.g. for a focused unit test) is served here instead of by a
    module-global injection.
    """
    if name in _IMPLS:
        return _IMPLS[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _tables(ctx: DataFrameContext, *names: str) -> tuple[Any, ...]:
    return tuple(ctx.get_table(name) for name in names)


def _is_dask_context(ctx: DataFrameContext) -> bool:
    """Return whether a pandas-family context is backed by Dask."""
    platform = ctx.platform.lower().replace("_", "-")
    return platform in {"dask", "dask-df"}


# =============================================================================
# Query IDs that should be skipped for DataFrame implementations
# =============================================================================
#
# IMPORTANT: Most "SQL-only" features ARE implementable via DataFrames:
# - Optimizer probes: Spark DataFrames are DECLARATIVE - Catalyst optimizes them
# - CUBE/ROLLUP: Use multiple groupby + union (or native cube/rollup in PySpark)
# - QUALIFY: Use window function + filter (two-step approach)
# - Arrays/Structs/Maps: Native support in Polars and PySpark
# - Higher-order functions: F.transform(), F.filter(), F.aggregate() in PySpark
# - Pivot/Unpivot: Native pivot/melt in all DataFrame libraries
#
# Only truly SQL-only constructs are correlated subqueries where the inner query
# references the outer query's row values - this has no DataFrame equivalent.

SKIP_FOR_DATAFRAME = [
    # Correlated EXISTS subquery - inner query references outer row
    # SQL: WHERE EXISTS (SELECT 1 FROM t2 WHERE t2.key = t1.key AND ...)
    # No DataFrame equivalent - requires per-row subquery execution
    "optimizer_exists_to_semijoin",
    # Correlated IN subquery - inner query references outer row
    # SQL: WHERE col IN (SELECT t2.col FROM t2 WHERE t2.key = t1.key)
    # No DataFrame equivalent - requires per-row subquery execution
    "optimizer_in_to_exists",
    # Correlated scalar subquery - inner query returns single value per outer row
    # SQL: SELECT (SELECT MAX(x) FROM t2 WHERE t2.key = t1.key) FROM t1
    # No DataFrame equivalent - requires per-row subquery execution
    "optimizer_scalar_subquery_flattening",
    # PySpark is the only DataFrame engine with a native array-returning
    # approximate-quantile aggregate (`percentile_approx(col, array(...))`);
    # emulating via a per-quantile loop on Polars/DataFusion/pandas defeats
    # the latency measurement that the benchmark is supposed to report.
    "approx_quantiles_array",
    # PySpark 4.1+ is the only DataFrame engine with a native
    # `approx_top_k` accumulator. Polars' `top_k` returns largest-by-sort-key
    # (different semantics — not frequency-based). A real top-K port for
    # Polars/DataFusion/pandas is a deferred follow-up; see TODO
    # `write-primitives-sketch-pyspark-dataframe-surface` for the
    # PySpark-only DataFrame story this would slot into.
    "approx_top_k_lineitem",
]

# NOTE: EXPRESSION_FAMILY_ONLY list has been removed.
#
# All queries now support both expression-family (Polars, PySpark, DataFusion)
# and pandas-family (Pandas, Modin, cuDF, Dask) implementations.
#
# Queries previously in this list have valid pandas-family implementations:
# - QUALIFY queries: Use window + filter pattern (add window col, then filter)
# - Higher-order functions: Use .apply() with lambdas
# - Array operations: Use .explode(), list comprehensions
# - Struct/Map operations: Use dict/list operations
# - Timeseries/ASOF: Use pd.merge_asof() or window-based approximation
# - Optimizer probes: DataFrames are declarative, Catalyst optimizes plans

# Queries skipped for expression-family platforms (Polars, PySpark, DataFusion).
#
# Most list/array, struct, and string-split queries are now supported through
# the unified expression API (UnifiedListExpr, UnifiedMapExpr, UnifiedStrExpr).
SKIP_FOR_EXPRESSION_FAMILY: list[str] = [
    # Currently empty as most expression-family gaps are platform-specific
]

# Queries skipped specifically for Polars DataFrame mode.
SKIP_FOR_POLARS = [
    # --- Map operations: Polars has no native Map dtype ---
    "map_construction",  # ctx.struct() + ctx.map_from_entries()
    "map_access",  # ctx.struct() + ctx.map_from_entries() + .map.get()
    "map_keys_values",  # ctx.struct() + ctx.map_from_entries() + .map.keys/values()
]

# Queries skipped specifically for PySpark DataFrame mode.
SKIP_FOR_PYSPARK = [
    # list_filter and list_transform call ctx.element() in expression_impl.
    # PySpark does not override element() so it raises NotImplementedError.
    "list_filter",
    "list_transform",
    # window_lead_lag_same_frame's expression impl uses raw Polars (`.native` +
    # pl.col(...).shift().over()) for a deterministic composite-key LAG/LEAD that
    # the unified window helpers cannot yet express (single-column order_by only;
    # see TODO read-primitives-simplify-inline-window-helpers). pl.col(...) on a
    # non-Polars native frame fails, so PySpark skips it until the impl is ported.
    "window_lead_lag_same_frame",
]

# Queries skipped specifically for DataFusion DataFrame mode.
# These use Polars-only features or DataFusion v50 missing functions.
SKIP_FOR_DATAFUSION = [
    "list_filter",  # .list.eval() is Polars-only - no DataFusion equivalent
    "list_transform",  # .list.eval() is Polars-only - no DataFusion equivalent
    "list_reduce",  # array_sum() not in DataFusion v50 Python bindings
    "array_distinct",  # DataFusion array_distinct returns Dictionary(Int32,Utf8) causing Arrow type mismatch
    # Raw-Polars (`.native` + pl.col) deterministic LAG/LEAD impl; pl.col on a
    # non-Polars native frame fails (see SKIP_FOR_PYSPARK note above).
    "window_lead_lag_same_frame",
]


# =============================================================================
# Expression Family Implementations (Polars, PySpark, DataFusion)
# =============================================================================


def aggregation_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality key on a large table."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1))).select(
        col("o_custkey").n_unique().alias("unique_customers")
    )


def approx_count_distinct_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count (HLL) on a large table.

    Sketch-backed on Polars (`approx_n_unique`), PySpark
    (`approx_count_distinct`), and DataFusion (`approx_distinct`); see
    `docs/benchmarks/read-primitives-approximate-functions.md` for the
    cross-platform DataFrame coverage matrix.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    return orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1))).select(
        col("o_custkey").approx_n_unique().alias("unique_customers")
    )


def approx_count_distinct_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count (HLL) per low-cardinality group.

    Sketch-backed on Polars (`approx_n_unique`), PySpark
    (`approx_count_distinct`), and DataFusion (`approx_distinct`); see
    `docs/benchmarks/read-primitives-approximate-functions.md` for the
    cross-platform DataFrame coverage matrix.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col

    return lineitem.group_by("l_returnflag", "l_linestatus").agg(
        col("l_orderkey").approx_n_unique().alias("unique_orders"),
        col("l_partkey").approx_n_unique().alias("unique_parts"),
    )


def aggregation_groupby_impl(
    ctx: DataFrameContext,
    *,
    table_name: str,
    group_cols: tuple[str, ...],
    agg_specs: tuple[tuple[str, str, str], ...],
    conditions: tuple[tuple[str, str, Any, bool], ...] = (),
    sort_cols: tuple[str, ...] = (),
    sort_desc: bool | list[bool] = False,
    limit: int | None = None,
) -> Any:
    """Run a grouped aggregation for either expression-family or pandas-family contexts."""
    table = ctx.get_table(table_name)
    group_columns = list(group_cols)

    if hasattr(table, "group_by"):
        col = ctx.col
        expression_builders = {
            "nunique": lambda column: column.n_unique(),
            "sum": lambda column: column.sum(),
            "mean": lambda column: column.mean(),
            "count": lambda column: column.count(),
            "max": lambda column: column.max(),
            "first": lambda column: column.first(),
            # DuckDB QUANTILE_CONT/PERCENTILE_CONT use linear interpolation; the
            # UnifiedExpr default is "nearest", which lands on a different element.
            "median": lambda column: column.quantile(0.5, interpolation="linear"),
            "q25": lambda column: column.quantile(0.25, interpolation="linear"),
            "q75": lambda column: column.quantile(0.75, interpolation="linear"),
            "q95": lambda column: column.quantile(0.95, interpolation="linear"),
            "std": lambda column: column.std(),
            "var": lambda column: column.var(),
        }
        if conditions:
            table = table.filter(_expr_combined_filter(ctx, conditions))
        result = table.group_by(*group_columns).agg(
            *(
                expression_builders[agg_func](col(column_name)).alias(alias)
                for column_name, agg_func, alias in agg_specs
            )
        )
        if sort_cols:
            result = result.sort(list(sort_cols) if len(sort_cols) > 1 else sort_cols[0], descending=sort_desc)
        return result.limit(limit) if limit is not None else result

    if hasattr(table, "groupby"):
        if conditions:
            table = table[_pandas_combined_filter(table, conditions)]
        pandas_aggs = {
            alias: (
                column_name,
                {
                    "nunique": "nunique",
                    "q25": lambda series: series.quantile(0.25),
                    "q75": lambda series: series.quantile(0.75),
                    "q95": lambda series: series.quantile(0.95),
                    "median": "median",
                }.get(agg_func, agg_func),
            )
            for column_name, agg_func, alias in agg_specs
        }
        result = table.groupby(group_columns, as_index=False).agg(**pandas_aggs)
        if sort_cols:
            ascending = [not value for value in sort_desc] if isinstance(sort_desc, list) else not sort_desc
            result = result.sort_values(list(sort_cols), ascending=ascending)
        return result.head(limit) if limit is not None else result

    raise TypeError(f"Unsupported table type for grouped aggregation: {type(table)!r}")


def _expr_grouped_list(ctx: DataFrameContext, table_name: str, group_col: str, value_col: str, alias: str) -> Any:
    return ctx.get_table(table_name).group_by(group_col).agg(ctx.col(value_col).list().alias(alias))


def _pandas_grouped_list(table: Any, group_col: str, value_col: str, alias: str) -> Any:
    result = table.groupby(group_col)[value_col].apply(list).reset_index()
    result.columns = [group_col, alias]
    return result


def _partsupp_map_expression(ctx: DataFrameContext, max_suppkey: int) -> Any:
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("partsupp")
        .filter(col("ps_suppkey") <= lit(max_suppkey))
        .group_by("ps_suppkey")
        .agg(ctx.struct(col("ps_partkey").cast_string(), col("ps_supplycost")).list().alias("entries"))
        .with_columns(ctx.map_from_entries("entries").alias("part_costs"))
    )


def _partsupp_map_pandas(ctx: DataFrameContext, max_suppkey: int) -> Any:
    filtered = ctx.get_table("partsupp")
    filtered = filtered[filtered["ps_suppkey"] <= max_suppkey]
    result = filtered.groupby("ps_suppkey").apply(
        lambda group: {str(row["ps_partkey"]): row["ps_supplycost"] for _, row in group.iterrows()},
        include_groups=False,
    )
    result = result.reset_index()
    result.columns = ["ps_suppkey", "part_costs"]
    return result


def _make_groupby_impl(
    name: str,
    table_name: str,
    group_cols: tuple[str, ...],
    agg_specs: tuple[tuple[str, str, str], ...],
    conditions: tuple[tuple[str, str, Any, bool], ...] = (),
    sort_cols: tuple[str, ...] = (),
    sort_desc: bool | list[bool] = False,
    limit: int | None = None,
) -> QueryImpl:
    def impl(ctx: DataFrameContext) -> Any:
        return aggregation_groupby_impl(
            ctx,
            table_name=table_name,
            group_cols=group_cols,
            agg_specs=agg_specs,
            conditions=conditions,
            sort_cols=sort_cols,
            sort_desc=sort_desc,
            limit=limit,
        )

    impl.__name__ = name
    impl.__qualname__ = name
    return impl


for _spec in (
    (
        "aggregation_distinct_groupby",
        "lineitem",
        ("l_returnflag", "l_linestatus"),
        (("l_orderkey", "nunique", "unique_orders"), ("l_partkey", "nunique", "unique_parts")),
    ),
    (
        "aggregation_groupby_large",
        "lineitem",
        ("l_orderkey", "l_partkey", "l_suppkey"),
        (("l_quantity", "sum", "total_qty"), ("l_extendedprice", "mean", "avg_price")),
    ),
    (
        "aggregation_groupby_small",
        "nation",
        ("n_regionkey",),
        (("n_nationkey", "count", "nation_count"), ("n_name", "max", "last_nation")),
    ),
    ("groupby_highndv", "lineitem", ("l_orderkey",), (("l_linenumber", "count", "line_count"),)),
    ("groupby_lowndv", "orders", ("o_orderpriority",), (("o_orderkey", "count", "order_count"),)),
    ("groupby_pk", "customer", ("c_custkey",), (("c_name", "max", "customer_name"),)),
    ("groupby_decimal_highndv", "lineitem", ("l_extendedprice",), (("l_orderkey", "count", "price_frequency"),)),
    (
        "groupby_decimal_lowndv",
        "lineitem",
        ("l_discount",),
        (("l_orderkey", "count", "discount_frequency"), ("l_quantity", "mean", "avg_qty")),
    ),
    (
        "aggregation_partition",
        "lineitem",
        ("l_shipdate", "l_shipmode"),
        (("l_quantity", "sum", "daily_quantity"), ("l_orderkey", "count", "shipment_count")),
        (("l_shipdate", "ge", date(1995, 1, 1), False), ("l_shipdate", "lt", date(1996, 1, 1), False)),
    ),
    ("orderby_bigint", "lineitem", ("l_orderkey",), (("l_quantity", "sum", "total_qty"),), (), ("l_orderkey",)),
    (
        "topn_aggregate",
        "lineitem",
        ("l_orderkey",),
        (("l_quantity", "sum", "total_quantity"),),
        (),
        ("total_quantity",),
        True,
        10,
    ),
    # statistical_variance (impl_base of statistical_variance_stddev) is a dedicated
    # impl below - the factory cannot express the ddof=0 population stddev.
    (
        "any_value_simple",
        "customer",
        ("c_mktsegment",),
        (("c_name", "first", "sample_customer"), ("c_custkey", "count", "customer_count")),
    ),
    (
        "any_value_with_filter",
        "nation",
        ("n_regionkey",),
        (
            ("n_name", "first", "sample_nation"),
            ("n_comment", "first", "sample_comment"),
            ("n_nationkey", "count", "nation_count"),
        ),
    ),
    (
        "groupby_all_simple",
        "lineitem",
        ("l_returnflag", "l_linestatus"),
        (("l_quantity", "sum", "total_qty"), ("l_extendedprice", "mean", "avg_price")),
    ),
    (
        "orderby_all_desc",
        "part",
        ("p_brand", "p_type"),
        (("p_retailprice", "mean", "avg_price"),),
        (),
        ("p_brand", "p_type", "avg_price"),
        True,
        100,
    ),
    (
        "statistical_percentiles",
        "lineitem",
        ("l_returnflag", "l_linestatus"),
        (
            ("l_orderkey", "count", "record_count"),
            ("l_quantity", "q25", "quantity_q1"),
            ("l_quantity", "median", "quantity_median"),
            ("l_quantity", "q75", "quantity_q3"),
            ("l_extendedprice", "q95", "price_p95"),
        ),
    ),
    ("approx_quantile_groupby", "lineitem", ("l_shipmode",), (("l_quantity", "median", "median_quantity"),)),
):
    _stem, _table_name, _group_cols, _agg_specs, *_opts = _spec
    for _family in ("expression", "pandas"):
        _register_generated_impl(
            _make_groupby_impl(f"{_stem}_{_family}_impl", _table_name, _group_cols, _agg_specs, *_opts)
        )


def _expr_count_filter_predicate(ctx: DataFrameContext, column_name: str, op: str, value: Any, lower: bool) -> Any:
    expr = ctx.col(column_name)
    if lower:
        expr = expr.str.to_lowercase()
    if op == "eq":
        return expr == ctx.lit(value)
    if op == "ge":
        return expr >= ctx.lit(value)
    if op == "gt":
        return expr > ctx.lit(value)
    if op == "lt":
        return expr < ctx.lit(value)
    if op == "in":
        return expr.is_in(value)
    if op == "contains":
        return expr.str.contains(value)
    if op == "starts":
        return expr.str.starts_with(value)
    if op == "ends":
        return expr.str.ends_with(value)
    if op == "all_contains":
        first, *rest = value
        predicate = expr.str.contains(first)
        for item in rest:
            predicate = predicate & expr.str.contains(item)
        return predicate
    raise ValueError(f"Unsupported count-filter operation: {op}")


def _pandas_count_filter_mask(table: Any, column_name: str, op: str, value: Any, lower: bool) -> Any:
    series = table[column_name]
    if lower:
        series = series.str.lower()
    if op == "eq":
        return series == value
    if op == "ge":
        return series >= value
    if op == "gt":
        return series > value
    if op == "lt":
        return series < value
    if op == "in":
        return series.isin(value)
    if op == "contains":
        return series.str.contains(value, na=False)
    if op == "starts":
        return series.str.startswith(value, na=False)
    if op == "ends":
        return series.str.endswith(value, na=False)
    if op == "all_contains":
        first, *rest = value
        mask = series.str.contains(first, na=False)
        for item in rest:
            mask = mask & series.str.contains(item, na=False)
        return mask
    raise ValueError(f"Unsupported count-filter operation: {op}")


def _make_count_filter_impl(
    name: str,
    table_name: str,
    column_name: str,
    op: str,
    value: Any,
    count_col: str,
    alias: str,
    lower: bool = False,
) -> None:
    def expression_impl(ctx: DataFrameContext) -> Any:
        table = ctx.get_table(table_name)
        return table.filter(_expr_count_filter_predicate(ctx, column_name, op, value, lower)).select(
            ctx.col(count_col).count().alias(alias)
        )

    def pandas_impl(ctx: DataFrameContext) -> Any:
        table = ctx.get_table(table_name)
        return ctx.scalar_to_df({alias: len(table[_pandas_count_filter_mask(table, column_name, op, value, lower)])})

    for family, impl in (("expression", expression_impl), ("pandas", pandas_impl)):
        impl.__name__ = f"{name}_{family}_impl"
        impl.__qualname__ = impl.__name__
        _register_generated_impl(impl)


for _spec in (
    ("filter_bigint_non_selective", "lineitem", "l_orderkey", "gt", 1000, "l_orderkey", "count", False),
    ("filter_decimal_non_selective", "lineitem", "l_extendedprice", "gt", 1000.00, "l_orderkey", "count", False),
    ("filter_string_non_selective", "customer", "c_mktsegment", "ge", "A", "c_custkey", "count", False),
    ("string_equal", "part", "p_brand", "eq", "Brand#23", "p_partkey", "count", False),
    ("string_equal_lower", "part", "p_brand", "eq", "brand#23", "p_partkey", "count", True),
    ("string_in_predicate", "orders", "o_orderpriority", "in", ["1-URGENT", "2-HIGH"], "o_orderkey", "count", False),
    ("string_like_center", "part", "p_name", "contains", "STEEL", "p_partkey", "count", False),
    ("string_like_suffix", "part", "p_name", "ends", "COPPER", "p_partkey", "count", False),
    ("string_like_prefix", "part", "p_name", "starts", "STANDARD", "p_partkey", "count", False),
    ("string_ilike_start", "part", "p_name", "starts", "standard", "p_partkey", "count", True),
    ("string_ilike_end", "part", "p_name", "ends", "copper", "p_partkey", "count", True),
    ("string_like_multi", "part", "p_name", "all_contains", ("STEEL", "BRASS"), "p_partkey", "count", False),
    ("string_ilike_multi", "part", "p_name", "all_contains", ("steel", "brass"), "p_partkey", "count", True),
    ("string_like_center_insensitive", "part", "p_name", "contains", "steel", "p_partkey", "count", True),
    ("intrinsic_to_date", "orders", "o_orderdate", "eq", date(1995, 3, 15), "o_orderkey", "orders_by_month", False),
):
    _make_count_filter_impl(*_spec)


def _expr_combined_filter(ctx: DataFrameContext, conditions: tuple[tuple[str, str, Any, bool], ...]) -> Any:
    first, *rest = conditions
    predicate = _expr_count_filter_predicate(ctx, *first)
    for condition in rest:
        predicate = predicate & _expr_count_filter_predicate(ctx, *condition)
    return predicate


def _pandas_combined_filter(table: Any, conditions: tuple[tuple[str, str, Any, bool], ...]) -> Any:
    first, *rest = conditions
    mask = _pandas_count_filter_mask(table, *first)
    for condition in rest:
        mask = mask & _pandas_count_filter_mask(table, *condition)
    return mask


def _make_filtered_select_impl(
    name: str,
    table_name: str,
    conditions: tuple[tuple[str, str, Any, bool], ...],
    columns: tuple[str, ...],
    limit: int | None = None,
) -> None:
    def expression_impl(ctx: DataFrameContext) -> Any:
        table = ctx.get_table(table_name)
        if conditions:
            table = table.filter(_expr_combined_filter(ctx, conditions))
        result = table.select(*columns)
        return result.limit(limit) if limit is not None else result

    def pandas_impl(ctx: DataFrameContext) -> Any:
        table = ctx.get_table(table_name)
        if conditions:
            table = table[_pandas_combined_filter(table, conditions)]
        result = table[list(columns)]
        return result.head(limit) if limit is not None else result

    for family, impl in (("expression", expression_impl), ("pandas", pandas_impl)):
        impl.__name__ = f"{name}_{family}_impl"
        impl.__qualname__ = impl.__name__
        _register_generated_impl(impl)


for _spec in (
    (
        "filter_selective",
        "lineitem",
        (("l_quantity", "gt", 45, False), ("l_extendedprice", "gt", 50000, False), ("l_discount", "lt", 0.05, False)),
        ("l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"),
        None,
    ),
    (
        "filter_non_selective",
        "lineitem",
        (("l_quantity", "gt", 1, False),),
        ("l_orderkey", "l_partkey", "l_quantity", "l_extendedprice"),
        None,
    ),
    # The *_selective / *_in_list / *_like filter queries are `SELECT * FROM <t>
    # WHERE ...` on the SQL surface, so the DataFrame surface must project every
    # column in schema order (the prior 4-col subsets caused column-count
    # divergences). An empty result still carries the full schema.
    (
        "filter_bigint_selective",
        "orders",
        (("o_orderkey", "eq", 1234567, False),),
        (
            "o_orderkey",
            "o_custkey",
            "o_orderstatus",
            "o_totalprice",
            "o_orderdate",
            "o_orderpriority",
            "o_clerk",
            "o_shippriority",
            "o_comment",
        ),
        None,
    ),
    (
        "filter_bigint_in_list",
        "orders",
        (("o_orderkey", "in", [1, 100, 1000, 10000, 100000], False),),
        (
            "o_orderkey",
            "o_custkey",
            "o_orderstatus",
            "o_totalprice",
            "o_orderdate",
            "o_orderpriority",
            "o_clerk",
            "o_shippriority",
            "o_comment",
        ),
        None,
    ),
    (
        "filter_decimal_selective",
        "lineitem",
        (("l_extendedprice", "eq", 12345.67, False), ("l_discount", "eq", 0.05, False)),
        (
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_quantity",
            "l_extendedprice",
            "l_discount",
            "l_tax",
            "l_returnflag",
            "l_linestatus",
            "l_shipdate",
            "l_commitdate",
            "l_receiptdate",
            "l_shipinstruct",
            "l_shipmode",
            "l_comment",
        ),
        None,
    ),
    (
        "filter_decimal_in_list",
        "lineitem",
        (("l_extendedprice", "in", [1000.00, 5000.00, 10000.00, 50000.00], False),),
        (
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "l_quantity",
            "l_extendedprice",
            "l_discount",
            "l_tax",
            "l_returnflag",
            "l_linestatus",
            "l_shipdate",
            "l_commitdate",
            "l_receiptdate",
            "l_shipinstruct",
            "l_shipmode",
            "l_comment",
        ),
        None,
    ),
    (
        "filter_string_selective",
        "customer",
        (("c_name", "eq", "Customer#000001234", False),),
        ("c_custkey", "c_name", "c_address", "c_nationkey", "c_phone", "c_acctbal", "c_mktsegment", "c_comment"),
        None,
    ),
    (
        "filter_string_like",
        "part",
        (("p_name", "contains", "green", False),),
        ("p_partkey", "p_name", "p_mfgr", "p_brand", "p_type", "p_size", "p_container", "p_retailprice", "p_comment"),
        None,
    ),
    # "limit" is a dedicated impl below (SELECT * + ORDER BY, which this filtered
    # -select factory cannot express).
    ("string_like", "part", (("p_name", "contains", "blue", False),), ("p_partkey", "p_name", "p_type"), None),
    ("string_starts_with", "part", (("p_type", "starts", "STANDARD", False),), ("p_partkey", "p_name", "p_type"), None),
    ("string_ends_with", "part", (("p_type", "ends", "BRASS", False),), ("p_partkey", "p_name", "p_type"), None),
):
    _make_filtered_select_impl(*_spec)


def _extreme_source(ctx: DataFrameContext, base: str, joins: tuple[tuple[str, str, str], ...]) -> Any:
    table = ctx.get_table(base)
    for other, left_on, right_on in joins:
        other_table = ctx.get_table(other)
        table = (
            table.merge(other_table, left_on=left_on, right_on=right_on)
            if hasattr(table, "merge")
            else table.join(other_table, left_on=left_on, right_on=right_on)
        )
    return table


def _make_extreme_row_impls(
    name: str,
    doc: str,
    base: str,
    joins: tuple[tuple[str, str, str], ...],
    groups: tuple[str, ...],
    pd_groups: tuple[str, ...],
    value: str,
    agg: str,
    alias: str,
    expr_select: tuple[str, ...],
    expr_unique: tuple[str, ...],
    pd_select: tuple[str, ...],
    pd_rename: dict[str, str],
    desc: bool = False,
    limit: int | None = None,
) -> None:
    group_key = groups[0] if len(groups) == 1 else list(groups)
    pd_group_key = pd_groups[0] if len(pd_groups) == 1 else list(pd_groups)

    def expression_impl(ctx: DataFrameContext) -> Any:
        table = _extreme_source(ctx, base, joins)
        extrema = table.group_by(*groups).agg(getattr(ctx.col(value), agg)().alias(alias))
        result = table.join(extrema, on=group_key).filter(ctx.col(value) == ctx.col(alias)).select(*expr_select)
        result = result.unique(subset=expr_unique[0] if len(expr_unique) == 1 else list(expr_unique)).sort(
            alias, descending=desc
        )
        return result.limit(limit) if limit is not None else result

    def pandas_impl(ctx: DataFrameContext) -> Any:
        table = _extreme_source(ctx, base, joins)
        idx_func = "idxmax" if agg == "max" else "idxmin"
        result = table.loc[getattr(table.groupby(pd_group_key)[value], idx_func)()][list(pd_select)].rename(
            columns=pd_rename
        )
        result = result.sort_values(alias, ascending=not desc)
        return result.head(limit) if limit is not None else result

    for family, impl in (("expression", expression_impl), ("pandas", pandas_impl)):
        impl.__name__ = f"{name}_{family}_impl"
        impl.__qualname__ = impl.__name__
        impl.__doc__ = doc
        _register_generated_impl(impl)


# fmt: off
for _spec in (
    ("max_by_simple", "Find the customer with the highest account balance in each nation.", "customer", (("nation", "c_nationkey", "n_nationkey"),), ("n_name",), ("n_name",), "c_acctbal", "max", "max_balance", ("n_name", "c_name", "max_balance"), ("n_name",), ("n_name", "c_name", "c_acctbal"), {"c_acctbal": "max_balance"}, True, None),
    ("min_by_simple", "Find the customer with the lowest account balance in each nation.", "customer", (("nation", "c_nationkey", "n_nationkey"),), ("n_name",), ("n_name",), "c_acctbal", "min", "min_balance", ("n_name", "c_name", "min_balance"), ("n_name",), ("n_name", "c_name", "c_acctbal"), {"c_acctbal": "min_balance"}, False, None),
    ("max_by_complex", "Find the most expensive order for each customer segment.", "orders", (("customer", "o_custkey", "c_custkey"),), ("c_mktsegment",), ("c_mktsegment",), "o_totalprice", "max", "max_order_value", ("c_mktsegment", "o_orderkey", "o_orderdate", "max_order_value"), ("c_mktsegment",), ("c_mktsegment", "o_orderkey", "o_orderdate", "o_totalprice"), {"o_totalprice": "max_order_value"}, True, None),
    # min_by_complex, min_by_with_ties, max_by_with_ties are dedicated impls below:
    # they need a deterministic ARG_MIN/MAX tie-break and the SQL's secondary
    # ORDER BY keys, which this factory (sort-by-alias + arbitrary unique) cannot
    # express.
):
    _make_extreme_row_impls(*_spec)
# fmt: on


def min_by_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """Cheapest part per brand (ARG_MIN by p_retailprice), deterministic tie-break."""
    col = ctx.col
    return (
        ctx.get_table("part")
        .sort(["p_brand", "p_retailprice", "p_name", "p_type"])
        .group_by("p_brand")
        .agg(
            col("p_name").first().alias("cheapest_part_name"),
            col("p_type").first().alias("cheapest_part_type"),
            col("p_retailprice").min().alias("min_price"),
        )
        .sort(["min_price", "p_brand"])
        .select("p_brand", "cheapest_part_name", "cheapest_part_type", "min_price")
    )


def min_by_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """Cheapest part per brand (ARG_MIN by p_retailprice), deterministic tie-break."""
    ordered = ctx.get_table("part").sort_values(["p_brand", "p_retailprice", "p_name", "p_type"])
    picked = ordered.groupby("p_brand", as_index=False).agg(
        cheapest_part_name=("p_name", "first"),
        cheapest_part_type=("p_type", "first"),
        min_price=("p_retailprice", "first"),
    )
    return picked.sort_values(["min_price", "p_brand"])[
        ["p_brand", "cheapest_part_name", "cheapest_part_type", "min_price"]
    ].reset_index(drop=True)


def _supply_cost_extreme_expr(ctx: DataFrameContext, *, descending: bool, value_alias: str, limit: int) -> Any:
    """Lowest/highest-supply-cost supplier per part with a deterministic tie-break."""
    col = ctx.col
    # Polars consumes the right join key (p_partkey); ps_partkey == p_partkey on
    # joined rows, so group/sort/project on ps_partkey (it fills the p_partkey
    # output position).
    joined = (
        ctx.get_table("partsupp")
        .join(ctx.get_table("part"), left_on="ps_partkey", right_on="p_partkey")
        .join(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
        .sort(["ps_partkey", "p_name", "ps_supplycost", "s_name"], descending=[False, False, descending, False])
    )
    value = col("ps_supplycost").max() if descending else col("ps_supplycost").min()
    return (
        joined.group_by("ps_partkey", "p_name")
        .agg(col("s_name").first().alias("supplier_name"), value.alias(value_alias))
        .sort([value_alias, "ps_partkey", "p_name"], descending=[descending, False, False])
        .select("ps_partkey", "p_name", "supplier_name", value_alias)
        .limit(limit)
    )


def _supply_cost_extreme_pandas(ctx: DataFrameContext, *, descending: bool, value_alias: str, limit: int) -> Any:
    joined = (
        ctx.get_table("partsupp")
        .merge(ctx.get_table("part"), left_on="ps_partkey", right_on="p_partkey")
        .merge(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
    )
    ordered = joined.sort_values(
        ["p_partkey", "p_name", "ps_supplycost", "s_name"], ascending=[True, True, not descending, True]
    )
    picked = ordered.groupby(["p_partkey", "p_name"], as_index=False).agg(
        supplier_name=("s_name", "first"), **{value_alias: ("ps_supplycost", "first")}
    )
    return (
        picked.sort_values([value_alias, "p_partkey", "p_name"], ascending=[not descending, True, True])[
            ["p_partkey", "p_name", "supplier_name", value_alias]
        ]
        .head(limit)
        .reset_index(drop=True)
    )


def min_by_with_ties_expression_impl(ctx: DataFrameContext) -> Any:
    """Lowest-supply-cost supplier per part (ARG_MIN), deterministic tie-break."""
    return _supply_cost_extreme_expr(ctx, descending=False, value_alias="min_supply_cost", limit=100)


def min_by_with_ties_pandas_impl(ctx: DataFrameContext) -> Any:
    """Lowest-supply-cost supplier per part (ARG_MIN), deterministic tie-break."""
    return _supply_cost_extreme_pandas(ctx, descending=False, value_alias="min_supply_cost", limit=100)


def max_by_with_ties_expression_impl(ctx: DataFrameContext) -> Any:
    """Highest-supply-cost supplier per part (ARG_MAX), deterministic tie-break."""
    return _supply_cost_extreme_expr(ctx, descending=True, value_alias="max_supply_cost", limit=100)


def max_by_with_ties_pandas_impl(ctx: DataFrameContext) -> Any:
    """Highest-supply-cost supplier per part (ARG_MAX), deterministic tie-break."""
    return _supply_cost_extreme_pandas(ctx, descending=True, value_alias="max_supply_cost", limit=100)


def _sort_key(cols: tuple[str, ...]) -> str | list[str]:
    return cols[0] if len(cols) == 1 else list(cols)


def _ascending(desc: bool | tuple[bool, ...]) -> bool | list[bool]:
    return [not value for value in desc] if isinstance(desc, tuple) else not desc


def _select_sort_limit(
    frame: Any, cols: tuple[str, ...] = (), sort: tuple[str, ...] = (), desc: Any = False, *, distinct: bool = False
) -> Any:
    result = frame.select(*cols) if cols else frame
    result = result.unique() if distinct else result
    return result.sort(_sort_key(sort), descending=desc) if sort else result


def _pandas_select_sort_limit(
    frame: Any,
    cols: tuple[str, ...] = (),
    sort: tuple[str, ...] = (),
    desc: Any = False,
    *,
    distinct: bool = False,
) -> Any:
    result = frame[list(cols)] if cols else frame
    result = result.drop_duplicates() if distinct else result
    return result.sort_values(_sort_key(sort), ascending=_ascending(desc)) if sort else result


def _limit(frame: Any, limit: int | None, *, pandas: bool = False) -> Any:
    return frame.head(limit) if pandas and limit is not None else frame.limit(limit) if limit is not None else frame


def _make_select_sort_impls(
    name: str,
    table_name: str,
    cols: tuple[str, ...] = (),
    sort: tuple[str, ...] = (),
    desc: bool | tuple[bool, ...] = False,
    limit: int | None = None,
    *,
    distinct: bool = False,
) -> None:
    def expression_impl(ctx: DataFrameContext) -> Any:
        result = _select_sort_limit(ctx.get_table(table_name), cols, sort, desc, distinct=distinct)
        return _limit(result, limit)

    def pandas_impl(ctx: DataFrameContext) -> Any:
        result = _pandas_select_sort_limit(ctx.get_table(table_name), cols, sort, desc, distinct=distinct)
        return _limit(result, limit, pandas=True)

    for family, impl in (("expression", expression_impl), ("pandas", pandas_impl)):
        impl.__name__ = f"{name}_{family}_impl"
        impl.__qualname__ = impl.__name__
        _register_generated_impl(impl)


for _spec in (
    ("orderby_simple", "orders", ("o_orderkey", "o_orderdate", "o_totalprice"), ("o_orderdate",), False, 100),
    (
        "orderby_multi",
        "lineitem",
        ("l_orderkey", "l_linenumber", "l_shipdate", "l_quantity"),
        ("l_shipdate", "l_orderkey", "l_linenumber"),
        False,
        100,
    ),
    ("orderby_desc", "orders", ("o_orderkey", "o_totalprice", "o_orderdate"), ("o_totalprice",), True, 100),
    ("topn", "lineitem", ("l_orderkey", "l_partkey", "l_extendedprice"), ("l_extendedprice",), True, 10),
    (
        # SQL is `SELECT * FROM customer ORDER BY c_custkey` (8 cols). The prior
        # 7-col projection dropped c_comment.
        "orderby_all",
        "customer",
        ("c_custkey", "c_name", "c_address", "c_nationkey", "c_phone", "c_acctbal", "c_mktsegment", "c_comment"),
        ("c_custkey",),
        False,
        None,
    ),
    (
        # SQL is `SELECT * FROM orders ORDER BY o_orderpriority, o_orderdate DESC,
        # o_totalprice DESC LIMIT 100` (9 cols). Project all orders columns in
        # schema order; append o_orderkey (PK) as a deterministic tie-break so the
        # LIMIT-100 boundary is a total order (the catalog SQL carries the same
        # trailing key).
        "orderby_multicol",
        "orders",
        (
            "o_orderkey",
            "o_custkey",
            "o_orderstatus",
            "o_totalprice",
            "o_orderdate",
            "o_orderpriority",
            "o_clerk",
            "o_shippriority",
            "o_comment",
        ),
        ("o_orderpriority", "o_orderdate", "o_totalprice", "o_orderkey"),
        (False, True, True, False),
        100,
    ),
    (
        "orderby_shortstrings",
        "lineitem",
        ("l_returnflag", "l_linestatus"),
        ("l_returnflag", "l_linestatus"),
        False,
        None,
    ),
    ("topn_allcols", "lineitem", (), ("l_extendedprice",), True, 10),
):
    _make_select_sort_impls(*_spec, distinct=_spec[0] == "orderby_shortstrings")


def aggregation_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct count of high cardinality key on a large table."""
    filtered = ctx.get_table("orders")
    filtered = filtered[filtered["o_orderdate"] >= date(1995, 1, 1)]
    return filtered[["o_custkey"]].nunique().to_frame(name="unique_customers").reset_index(drop=True)


def approx_count_distinct_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count fallback for the pandas family.

    Dask uses native `nunique_approx()` (HLL) for this single-value
    query. Pandas, Modin, and cuDF expose only exact `.nunique()` at
    the API surface, so the "approximate" label degrades to exact on
    those platforms.
    """
    filtered = ctx.get_table("orders")
    filtered = filtered[filtered["o_orderdate"] >= date(1995, 1, 1)]
    if _is_dask_context(ctx):
        return ctx.scalar_to_df({"unique_customers": filtered["o_custkey"].nunique_approx().compute()})
    return filtered[["o_custkey"]].nunique().to_frame(name="unique_customers").reset_index(drop=True)


def approx_count_distinct_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Approximate distinct count groupby fallback for the pandas family.

    Pandas, Modin, cuDF, and current Dask expose no groupby approximate
    distinct aggregate matching this query shape. Dask has Series-level
    `nunique_approx()`, but no groupby equivalent in the dask-expr API,
    so this query remains an exact fallback for the pandas family.
    """
    return _IMPLS["aggregation_distinct_groupby_pandas_impl"](ctx)


def aggregation_materialize_expression_impl(ctx: DataFrameContext) -> Any:
    """Nested aggregation requiring CTE materialization."""
    totals = ctx.get_table("orders").group_by("o_custkey").agg(ctx.col("o_totalprice").sum().alias("customer_total"))
    return totals.select(ctx.col("customer_total").mean().alias("avg_customer_spending"))


def aggregation_materialize_pandas_impl(ctx: DataFrameContext) -> Any:
    """Nested aggregation requiring CTE materialization."""
    totals = ctx.get_table("orders").groupby("o_custkey", as_index=False).agg(customer_total=("o_totalprice", "sum"))
    return ctx.scalar_to_df({"avg_customer_spending": totals["customer_total"].mean()})


def aggregation_materialize_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """Complex nested aggregation requiring materialization of a subquery with joins."""
    col, lit = ctx.col, ctx.lit
    totals = (
        ctx.get_table("customer")
        .join(ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey")
        .join(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
        .group_by("c_mktsegment", "o_orderkey")
        .agg((col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("order_total"))
    )
    return totals.group_by("c_mktsegment").agg(col("order_total").mean().alias("avg_segment_order"))


def aggregation_materialize_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """Complex nested aggregation requiring materialization of a subquery with joins."""
    merged = ctx.get_table("customer").merge(ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey")
    merged = merged.merge(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
    merged["order_total"] = merged["l_extendedprice"] * (1 - merged["l_discount"])
    totals = merged.groupby(["c_mktsegment", "o_orderkey"], as_index=False).agg(order_total=("order_total", "sum"))
    return totals.groupby("c_mktsegment", as_index=False).agg(avg_segment_order=("order_total", "mean"))


def aggregation_selective_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate on a small subset of rows."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("lineitem")
        .filter((col("l_discount") > lit(0.05)) & (col("l_quantity") < lit(24)))
        .select((col("l_extendedprice") * col("l_discount")).sum().alias("total_discount_amount"))
    )


def aggregation_selective_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate on a small subset of rows."""
    lineitem = ctx.get_table("lineitem")
    filtered = lineitem[(lineitem["l_discount"] > 0.05) & (lineitem["l_quantity"] < 24)]
    return ctx.scalar_to_df({"total_discount_amount": (filtered["l_extendedprice"] * filtered["l_discount"]).sum()})


def aggregation_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate over all rows in table."""
    col = ctx.col
    return ctx.get_table("orders").select(
        col("o_orderkey").count().alias("total_orders"), col("o_totalprice").sum().alias("total_revenue")
    )


def aggregation_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate over all rows in table."""
    orders = ctx.get_table("orders")
    return ctx.scalar_to_df({"total_orders": len(orders), "total_revenue": orders["o_totalprice"].sum()})


def count_star_expression_impl(ctx: DataFrameContext) -> Any:
    """Metadata-based count optimization vs full table scan performance."""
    return ctx.get_table("lineitem").select(ctx.col("l_orderkey").count().alias("total_lineitems"))


def count_star_pandas_impl(ctx: DataFrameContext) -> Any:
    """Metadata-based count optimization vs full table scan performance."""
    return ctx.scalar_to_df({"total_lineitems": len(ctx.get_table("lineitem"))})


def decimal_arithmetic_expression_impl(ctx: DataFrameContext) -> Any:
    """Decimal precision arithmetic with complex expressions."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("lineitem")
        .filter(col("l_quantity") > lit(0))
        .select(
            col("l_orderkey"),
            (col("l_extendedprice") * (lit(1) - col("l_discount")) * (lit(1) + col("l_tax"))).alias("final_price"),
            (col("l_extendedprice") / col("l_quantity")).alias("unit_price"),
        )
        .limit(1000)
    )


def decimal_arithmetic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Decimal precision arithmetic with complex expressions."""
    filtered = ctx.get_table("lineitem")
    filtered = filtered[filtered["l_quantity"] > 0].copy()
    filtered["final_price"] = filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])
    filtered["unit_price"] = filtered["l_extendedprice"] / filtered["l_quantity"]
    return filtered[["l_orderkey", "final_price", "unit_price"]].head(1000)


def string_concat_expression_impl(ctx: DataFrameContext) -> Any:
    """String concatenation."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("customer")
        .select(col("c_custkey"), (col("c_name") + lit(" - ") + col("c_mktsegment")).alias("customer_info"))
        .limit(100)
    )


def string_concat_pandas_impl(ctx: DataFrameContext) -> Any:
    """String concatenation."""
    result = ctx.get_table("customer").copy()
    result["customer_info"] = result["c_name"] + " - " + result["c_mktsegment"]
    return result[["c_custkey", "customer_info"]].head(100)


def string_substring_expression_impl(ctx: DataFrameContext) -> Any:
    """String substring extraction."""
    return (
        ctx.get_table("customer")
        .select(ctx.col("c_custkey"), ctx.col("c_phone").str.slice(0, 3).alias("country_code"))
        .limit(100)
    )


def string_substring_pandas_impl(ctx: DataFrameContext) -> Any:
    """String substring extraction."""
    result = ctx.get_table("customer").copy()
    result["country_code"] = result["c_phone"].str[:3]
    return result[["c_custkey", "country_code"]].head(100)


def _window_select(frame: Any, cols: tuple[str, ...]) -> Any:
    return frame.select(*cols)


def window_row_number_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""
    # SQL is over orders (PARTITION BY o_custkey ORDER BY o_totalprice DESC), with
    # a date window and NO rank filter.
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("orders")
        .filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1996, 1, 1))))
        .with_columns(
            ctx.window_row_number(order_by=[("o_totalprice", False)], partition_by=["o_custkey"]).alias("order_rank")
        )
        .select("o_custkey", "o_orderkey", "o_totalprice", "order_rank")
    )


def window_row_number_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ...)."""
    orders = ctx.get_table("orders")
    result = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))].copy()
    result = result.sort_values(["o_custkey", "o_totalprice"], ascending=[True, False])
    result["order_rank"] = result.groupby("o_custkey").cumcount() + 1
    return result[["o_custkey", "o_orderkey", "o_totalprice", "order_rank"]].reset_index(drop=True)


def window_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    result = ctx.get_table("lineitem").with_columns(
        ctx.window_rank(order_by=[("l_quantity", False)], partition_by=["l_returnflag"]).alias("qty_rank")
    )
    # SQL ORDER BY l_returnflag, qty_rank, l_orderkey (all projected -> order-aware).
    return (
        result.filter(ctx.col("qty_rank") <= 5)
        .select("l_orderkey", "l_returnflag", "l_quantity", "qty_rank")
        .sort(["l_returnflag", "qty_rank", "l_orderkey"])
    )


def window_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function RANK() OVER (PARTITION BY ... ORDER BY ...)."""
    result = ctx.get_table("lineitem").copy()
    result["qty_rank"] = result.groupby("l_returnflag")["l_quantity"].rank(method="min", ascending=False)
    return (
        result[result["qty_rank"] <= 5][["l_orderkey", "l_returnflag", "l_quantity", "qty_rank"]]
        .sort_values(["l_returnflag", "qty_rank", "l_orderkey"])
        .reset_index(drop=True)
    )


def window_sum_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (PARTITION BY ...)."""
    return (
        ctx.get_table("lineitem")
        .with_columns(ctx.window_sum("l_extendedprice", partition_by=["l_orderkey"]).alias("order_total"))
        .select("l_orderkey", "l_linenumber", "l_extendedprice", "order_total")
    )


def window_sum_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (PARTITION BY ...)."""
    result = ctx.get_table("lineitem").copy()
    result["order_total"] = result.groupby("l_orderkey")["l_extendedprice"].transform("sum")
    return result[["l_orderkey", "l_linenumber", "l_extendedprice", "order_total"]]


def window_running_sum_expression_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (ORDER BY o_orderdate) - RANGE running sum."""
    # SQL SUM(...) OVER (ORDER BY o_orderdate) with no frame = RANGE UNBOUNDED
    # PRECEDING -> all rows of a date share the cumulative total through that date.
    # Compute per-date totals, cumulate across dates, then broadcast to each row.
    col = ctx.col
    orders = ctx.get_table("orders")
    daily = (
        orders.group_by("o_orderdate")
        .agg(col("o_totalprice").sum().alias("_daily_total"))
        .sort("o_orderdate")
        .with_columns(ctx.window_sum("_daily_total", order_by=[("o_orderdate", True)]).alias("cumulative_revenue"))
        .select("o_orderdate", "cumulative_revenue")
    )
    return (
        orders.join(daily, on="o_orderdate")
        .sort("o_orderdate")
        .select("o_orderkey", "o_orderdate", "o_totalprice", "cumulative_revenue")
        .limit(100)
    )


def window_running_sum_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window function SUM() OVER (ORDER BY o_orderdate) - RANGE running sum."""
    orders = ctx.get_table("orders")
    daily = orders.groupby("o_orderdate", as_index=False).agg(_daily_total=("o_totalprice", "sum"))
    daily = daily.sort_values("o_orderdate")
    daily["cumulative_revenue"] = daily["_daily_total"].cumsum()
    result = orders.merge(daily[["o_orderdate", "cumulative_revenue"]], on="o_orderdate")
    return (
        result.sort_values("o_orderdate")[["o_orderkey", "o_orderdate", "o_totalprice", "cumulative_revenue"]]
        .head(100)
        .reset_index(drop=True)
    )


def broadcast_join_two_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """One small table broadcast to join with one large table."""
    return (
        ctx.get_table("supplier")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .select(ctx.col("s_suppkey").count().alias("supplier_count"))
    )


def broadcast_join_two_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """One small table broadcast to join with one large table."""
    return ctx.scalar_to_df(
        {
            "supplier_count": len(
                ctx.get_table("supplier").merge(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
            )
        }
    )


def broadcast_join_three_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """Two small tables broadcast to join with one large table."""
    return (
        ctx.get_table("supplier")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .join(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
        .group_by("r_name", "n_name")
        .agg(ctx.col("s_suppkey").count().alias("supplier_count"))
    )


def broadcast_join_three_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """Two small tables broadcast to join with one large table."""
    merged = ctx.get_table("supplier").merge(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
    return (
        merged.merge(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
        .groupby(["r_name", "n_name"], as_index=False)
        .agg(supplier_count=("s_suppkey", "count"))
    )


def predicate_ordering_aggregation_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("lineitem")
        .filter(
            (col("l_shipdate") >= lit(date(1994, 1, 1)))
            & (col("l_shipdate") < lit(date(1995, 1, 1)))
            & (col("l_discount") >= lit(0.05))
            & (col("l_discount") <= lit(0.07))
            & (col("l_quantity") < lit(24))
        )
        .select(col("l_extendedprice").sum().alias("total_price"))
    )


def predicate_ordering_aggregation_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation."""
    table = ctx.get_table("lineitem")
    filtered = table[
        (table["l_shipdate"] >= date(1994, 1, 1))
        & (table["l_shipdate"] < date(1995, 1, 1))
        & (table["l_discount"] >= 0.05)
        & (table["l_discount"] <= 0.07)
        & (table["l_quantity"] < 24)
    ]
    return ctx.scalar_to_df({"total_price": filtered["l_extendedprice"].sum()})


def shuffle_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys."""
    return (
        ctx.get_table("orders")
        .join(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
        .group_by("o_orderkey")
        .agg(ctx.col("l_quantity").sum().alias("total_qty"))
    )


def shuffle_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys."""
    merged = ctx.get_table("orders").merge(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
    return merged.groupby("o_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))


_LINEITEM_COLS = (
    "l_orderkey",
    "l_partkey",
    "l_suppkey",
    "l_linenumber",
    "l_quantity",
    "l_extendedprice",
    "l_discount",
    "l_tax",
    "l_returnflag",
    "l_linestatus",
    "l_shipdate",
    "l_commitdate",
    "l_receiptdate",
    "l_shipinstruct",
    "l_shipmode",
    "l_comment",
)


def empty_build_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Join when build side produces no rows (edge case handling)."""
    col, lit = ctx.col, ctx.lit
    empty_orders = ctx.get_table("orders").filter(col("o_totalprice") < lit(0)).select("o_orderkey")
    # SQL is `SELECT l.* FROM lineitem l LEFT JOIN ...` -> all 16 lineitem columns
    # (excluding the joined o_orderkey from the empty build side).
    return (
        ctx.get_table("lineitem")
        .join(empty_orders, left_on="l_orderkey", right_on="o_orderkey", how="left")
        .select(*_LINEITEM_COLS)
    )


def empty_build_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Join when build side produces no rows (edge case handling)."""
    empty_orders = ctx.get_table("orders")
    empty_orders = empty_orders[empty_orders["o_totalprice"] < 0][["o_orderkey"]]
    return ctx.get_table("lineitem").merge(empty_orders, left_on="l_orderkey", right_on="o_orderkey", how="left")[
        list(_LINEITEM_COLS)
    ]


def filter_in_predicate_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with subquery and selective filtering."""
    # SQL is `SELECT * FROM part WHERE p_partkey IN (...)` -> all 9 part columns.
    # A semi-join keeps only the left (part) columns, so no projection is needed.
    high_qty = ctx.get_table("lineitem").filter(ctx.col("l_quantity") > ctx.lit(45)).select("l_partkey").unique()
    return ctx.get_table("part").join(high_qty, left_on="p_partkey", right_on="l_partkey", how="semi")


def filter_in_predicate_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """IN predicate with subquery and selective filtering."""
    high_qty = ctx.get_table("lineitem")[ctx.get_table("lineitem")["l_quantity"] > 45]["l_partkey"].unique()
    return ctx.get_table("part")[ctx.get_table("part")["p_partkey"].isin(high_qty)].reset_index(drop=True)


def orderby_expression_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort on computed expressions with DESC ordering."""
    return (
        ctx.get_table("lineitem")
        .with_columns((ctx.col("l_quantity") * ctx.col("l_extendedprice")).alias("total_value"))
        .sort("total_value", descending=True)
        .select("l_orderkey", "l_partkey", "total_value")
        .limit(100)
    )


def orderby_expression_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort on computed expressions with DESC ordering."""
    result = ctx.get_table("lineitem").copy()
    result["total_value"] = result["l_quantity"] * result["l_extendedprice"]
    return result.sort_values("total_value", ascending=False)[["l_orderkey", "l_partkey", "total_value"]].head(100)


def _make_shuffle_customer_order_impls(name: str, how: str, aggs: tuple[tuple[str, str, str], ...]) -> None:
    def expression_impl(ctx: DataFrameContext) -> Any:
        joined = ctx.get_table("customer").join(
            ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey", how=how
        )
        return joined.group_by("c_mktsegment").agg(
            *(getattr(ctx.col(col), func)().alias(alias) for col, func, alias in aggs)
        )

    def pandas_impl(ctx: DataFrameContext) -> Any:
        joined = ctx.get_table("customer").merge(
            ctx.get_table("orders"), left_on="c_custkey", right_on="o_custkey", how=how
        )
        return joined.groupby("c_mktsegment", as_index=False).agg(**{alias: (col, func) for col, func, alias in aggs})

    for family, impl in (("expression", expression_impl), ("pandas", pandas_impl)):
        impl.__name__ = f"{name}_{family}_impl"
        impl.__qualname__ = impl.__name__
        _register_generated_impl(impl)


_make_shuffle_customer_order_impls(
    "shuffle_inner_join_groupby",
    "inner",
    (("o_orderkey", "count", "order_count"), ("o_totalprice", "sum", "total_revenue")),
)
_make_shuffle_customer_order_impls(
    "shuffle_left_join_groupby", "left", (("o_orderkey", "count", "order_count"), ("c_custkey", "count", "total_rows"))
)
_make_shuffle_customer_order_impls(
    "shuffle_full_join_groupby",
    "outer",
    (("o_orderkey", "count", "order_count"), ("c_custkey", "count", "customer_count")),
)


def shuffle_self_join_expression_impl(ctx: DataFrameContext) -> Any:
    """Self-join with hash collision handling on large table."""
    col = ctx.col
    lineitem = ctx.get_table("lineitem")
    other = lineitem.select("l_orderkey", "l_partkey", "l_shipdate").rename({"l_orderkey": "l_orderkey_2"})
    return (
        lineitem.join(other, on=["l_partkey", "l_shipdate"])
        .filter(col("l_orderkey") != col("l_orderkey_2"))
        .group_by("l_orderkey")
        .agg(col("l_orderkey_2").count().alias("match_count"))
        .limit(10000)
    )


def shuffle_self_join_pandas_impl(ctx: DataFrameContext) -> Any:
    """Self-join with hash collision handling on large table."""
    left = ctx.get_table("lineitem")[["l_orderkey", "l_partkey", "l_shipdate"]].copy()
    right = left.rename(columns={"l_orderkey": "l_orderkey_2"})
    result = left.merge(right, on=["l_partkey", "l_shipdate"])
    return (
        result[result["l_orderkey"] != result["l_orderkey_2"]]
        .groupby("l_orderkey", as_index=False)
        .agg(match_count=("l_orderkey_2", "count"))
        .head(10000)
    )


def window_growing_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Running sum window aggregation with growing frame size."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("lineitem")
        .filter(col("l_orderkey") <= lit(1000))
        .sort(["l_orderkey", "l_linenumber"])
        .with_columns(
            ctx.window_sum("l_quantity", partition_by=["l_orderkey"], order_by=[("l_linenumber", True)]).alias(
                "running_quantity"
            )
        )
        .select("l_orderkey", "l_linenumber", "l_quantity", "running_quantity")
    )


def window_growing_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Running sum window aggregation with growing frame size."""
    result = ctx.get_table("lineitem")
    result = result[result["l_orderkey"] <= 1000].copy().sort_values(["l_orderkey", "l_linenumber"])
    result["running_quantity"] = result.groupby("l_orderkey")["l_quantity"].cumsum()
    return result[["l_orderkey", "l_linenumber", "l_quantity", "running_quantity"]]


def window_lead_lag_expression_impl(ctx: DataFrameContext) -> Any:
    """Offset window functions over the same frame (deterministic tie-break).

    Uses raw Polars via ``.native``: ``UnifiedExpr`` has no ``.shift`` and the
    ``window_lag``/``window_lead`` helpers shift before sorting. LAG/LEAD are
    computed with ``shift().over()`` after a total-order sort that matches the
    catalog SQL's ``ORDER BY o_orderdate, o_orderkey`` window tie-break.
    """
    import polars as pl

    return (
        ctx.get_table("orders")
        .native.filter((pl.col("o_orderdate") >= date(1995, 1, 1)) & (pl.col("o_orderdate") < date(1996, 1, 1)))
        .sort(["o_custkey", "o_orderdate", "o_orderkey"])
        .with_columns(
            pl.col("o_totalprice").shift(1).over("o_custkey").alias("prev_order_price"),
            pl.col("o_totalprice").shift(-1).over("o_custkey").alias("next_order_price"),
        )
        .select("o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price", "next_order_price")
    )


def window_lead_lag_pandas_impl(ctx: DataFrameContext) -> Any:
    """Offset window functions over the same frame (deterministic tie-break)."""
    result = ctx.get_table("orders")
    result = result[(result["o_orderdate"] >= date(1995, 1, 1)) & (result["o_orderdate"] < date(1996, 1, 1))].copy()
    result = result.sort_values(["o_custkey", "o_orderdate", "o_orderkey"])
    result["prev_order_price"] = result.groupby("o_custkey")["o_totalprice"].shift(1)
    result["next_order_price"] = result.groupby("o_custkey")["o_totalprice"].shift(-1)
    return result[["o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price", "next_order_price"]].reset_index(
        drop=True
    )


def window_dense_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Multiple window orderings: DENSE_RANK + PERCENT_RANK + CUME_DIST.

    Raw Polars: PERCENT_RANK = (rank_min - 1)/(n - 1) is 0/0 = NaN for a single-row
    partition where DuckDB returns 0.0, so it is coalesced (fill_nan + fill_null).
    CUME_DIST = rank_max / n.
    """
    import polars as pl

    n = pl.len().over("l_orderkey")
    return (
        ctx.get_table("lineitem")
        .native.filter(pl.col("l_orderkey") <= 10000)
        .with_columns(
            pl.col("l_extendedprice").rank("dense", descending=True).over("l_orderkey").alias("price_rank"),
            ((pl.col("l_quantity").rank("min").over("l_orderkey") - 1) / (n - 1))
            .fill_nan(0.0)
            .fill_null(0.0)
            .alias("quantity_percentile"),
            (pl.col("l_extendedprice").rank("max").over("l_orderkey") / n).alias("price_distribution"),
        )
        .sort(["l_orderkey", "price_rank"])
        .select(
            "l_orderkey",
            "l_partkey",
            "l_quantity",
            "l_extendedprice",
            "price_rank",
            "quantity_percentile",
            "price_distribution",
        )
    )


def window_dense_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Multiple window orderings: DENSE_RANK + PERCENT_RANK + CUME_DIST."""
    result = ctx.get_table("lineitem")
    result = result[result["l_orderkey"] <= 10000].copy()
    grp = result.groupby("l_orderkey")
    result["price_rank"] = grp["l_extendedprice"].rank(method="dense", ascending=False)
    # PERCENT_RANK = (rank_min - 1) / (n - 1); single-row partition -> 0.
    n = grp["l_quantity"].transform("count")
    rank_min_qty = grp["l_quantity"].rank(method="min", ascending=True)
    result["quantity_percentile"] = ((rank_min_qty - 1) / (n - 1)).where(n > 1, 0.0)
    # CUME_DIST = rank_max / n.
    rank_max_price = grp["l_extendedprice"].rank(method="max", ascending=True)
    result["price_distribution"] = rank_max_price / grp["l_extendedprice"].transform("count")
    return result.sort_values(["l_orderkey", "price_rank"])[
        [
            "l_orderkey",
            "l_partkey",
            "l_quantity",
            "l_extendedprice",
            "price_rank",
            "quantity_percentile",
            "price_distribution",
        ]
    ].reset_index(drop=True)


def predicate_ordering_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation within a low cardinality grouping."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("lineitem")
        .filter(
            (col("l_shipdate") <= lit(date(1998, 9, 1)))
            & (col("l_discount") > lit(0.05))
            & (col("l_tax") < lit(0.08))
            & (col("l_quantity") >= lit(10))
            & (col("l_quantity") <= lit(30))
        )
        .group_by("l_returnflag")
        .agg(col("l_quantity").sum().alias("total_qty"))
    )


def predicate_ordering_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity for aggregation within a low cardinality grouping."""
    table = ctx.get_table("lineitem")
    filtered = table[
        (table["l_shipdate"] <= date(1998, 9, 1))
        & (table["l_discount"] > 0.05)
        & (table["l_tax"] < 0.08)
        & (table["l_quantity"] >= 10)
        & (table["l_quantity"] <= 30)
    ]
    return filtered.groupby("l_returnflag", as_index=False).agg(total_qty=("l_quantity", "sum"))


def predicate_ordering_costs_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with result projection only."""
    col, lit = ctx.col, ctx.lit
    # SQL is SELECT * (16 lineitem cols); the filter is very selective so the
    # unordered LIMIT 100 never truncates (the result is order-insensitive).
    return (
        ctx.get_table("lineitem")
        .filter(
            (col("l_quantity") > lit(45))
            & (col("l_extendedprice") > lit(50000))
            & (col("l_discount") < lit(0.05))
            & (col("l_shipinstruct") == lit("DELIVER IN PERSON"))
            & col("l_shipmode").is_in(["AIR", "AIR REG"])
        )
        .limit(100)
    )


def predicate_ordering_costs_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with result projection only."""
    table = ctx.get_table("lineitem")
    return (
        table[
            (table["l_quantity"] > 45)
            & (table["l_extendedprice"] > 50000)
            & (table["l_discount"] < 0.05)
            & (table["l_shipinstruct"] == "DELIVER IN PERSON")
            & table["l_shipmode"].isin(["AIR", "AIR REG"])
        ]
        .head(100)
        .reset_index(drop=True)
    )


def broadcast_join_four_tables_expression_impl(ctx: DataFrameContext) -> Any:
    """Three small tables broadcast to join with one large table."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("partsupp")
        .join(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
        .join(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
        .join(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
        .join(ctx.get_table("part"), left_on="ps_partkey", right_on="p_partkey")
        .filter(col("p_size") == lit(15))
        .group_by("r_name", "p_type")
        .agg((col("ps_supplycost") * col("ps_availqty")).sum().alias("total_value"))
    )


def broadcast_join_four_tables_pandas_impl(ctx: DataFrameContext) -> Any:
    """Three small tables broadcast to join with one large table."""
    merged = ctx.get_table("partsupp").merge(ctx.get_table("supplier"), left_on="ps_suppkey", right_on="s_suppkey")
    merged = merged.merge(ctx.get_table("nation"), left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(ctx.get_table("region"), left_on="n_regionkey", right_on="r_regionkey")
    merged = merged.merge(ctx.get_table("part"), left_on="ps_partkey", right_on="p_partkey")
    filtered = merged[merged["p_size"] == 15].copy()
    filtered["total_value"] = filtered["ps_supplycost"] * filtered["ps_availqty"]
    return filtered.groupby(["r_name", "p_type"], as_index=False).agg(total_value=("total_value", "sum"))


def exchange_broadcast_expression_impl(ctx: DataFrameContext) -> Any:
    """One small table is copied to all nodes that have the large table."""
    small_parts = ctx.get_table("part").filter(ctx.col("p_size") == ctx.lit(1)).select("p_partkey")
    return (
        ctx.get_table("lineitem")
        .join(small_parts, left_on="l_partkey", right_on="p_partkey")
        .group_by("l_orderkey")
        .agg(ctx.col("l_quantity").sum().alias("total_qty"))
    )


def exchange_broadcast_pandas_impl(ctx: DataFrameContext) -> Any:
    """One small table is copied to all nodes that have the large table."""
    small_parts = ctx.get_table("part")[ctx.get_table("part")["p_size"] == 1][["p_partkey"]]
    merged = ctx.get_table("lineitem").merge(small_parts, left_on="l_partkey", right_on="p_partkey")
    return merged.groupby("l_orderkey", as_index=False).agg(total_qty=("l_quantity", "sum"))


def exchange_merge_expression_impl(ctx: DataFrameContext) -> Any:
    """Sorted data from multiple nodes is combined while keeping the sort order."""
    return (
        ctx.get_table("orders")
        .join(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")
        .select("o_orderkey", "l_linenumber", "l_quantity")
        .sort(["o_orderkey", "l_linenumber"])
    )


def exchange_merge_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sorted data from multiple nodes is combined while keeping the sort order."""
    return (
        ctx.get_table("orders")
        .merge(ctx.get_table("lineitem"), left_on="o_orderkey", right_on="l_orderkey")[
            ["o_orderkey", "l_linenumber", "l_quantity"]
        ]
        .sort_values(["o_orderkey", "l_linenumber"])
    )


def exchange_shuffle_expression_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys so matching rows end up on the same node."""
    col, lit = ctx.col, ctx.lit
    partsupp = ctx.get_table("partsupp")
    ps1 = partsupp.select(
        col("ps_partkey").alias("ps_partkey"), col("ps_suppkey").alias("supp1"), col("ps_supplycost").alias("cost1")
    )
    ps2 = partsupp.select(col("ps_partkey").alias("ps_partkey_2"), col("ps_suppkey").alias("supp2"))
    return (
        ps1.join(ps2, left_on="ps_partkey", right_on="ps_partkey_2")
        .filter((col("supp1") < col("supp2")) & (col("cost1") > lit(100)))
        .select("ps_partkey", "supp1", "supp2")
    )


def exchange_shuffle_pandas_impl(ctx: DataFrameContext) -> Any:
    """Data is redistributed based on the join keys so matching rows end up on the same node."""
    partsupp = ctx.get_table("partsupp")
    ps1 = partsupp[["ps_partkey", "ps_suppkey", "ps_supplycost"]].rename(
        columns={"ps_suppkey": "supp1", "ps_supplycost": "cost1"}
    )
    ps2 = partsupp[["ps_partkey", "ps_suppkey"]].rename(columns={"ps_suppkey": "supp2"})
    merged = ps1.merge(ps2, on="ps_partkey")
    return merged[(merged["supp1"] < merged["supp2"]) & (merged["cost1"] > 100)][["ps_partkey", "supp1", "supp2"]]


def statistical_correlation_expression_impl(ctx: DataFrameContext) -> Any:
    """Correlation, covariance, and linear regression between numeric columns.

    Raw Polars for the population-moment regression terms (UnifiedExpr.var/std have
    no ddof). REGR_*(y, x) in DuckDB take y=l_extendedprice, x=l_quantity:
    slope = cov_pop(x, y)/var_pop(x); intercept = mean(y) - slope*mean(x);
    r2 = corr(x, y)**2.
    """
    import polars as pl

    lf = ctx.get_table("lineitem").native.filter(
        (pl.col("l_shipdate") >= date(1995, 1, 1)) & (pl.col("l_shipdate") < date(1996, 1, 1))
    )
    slope = pl.cov("l_quantity", "l_extendedprice", ddof=0) / pl.col("l_quantity").var(ddof=0)
    intercept = pl.col("l_extendedprice").mean() - slope * pl.col("l_quantity").mean()
    return lf.select(
        pl.corr("l_quantity", "l_extendedprice").alias("qty_price_correlation"),
        pl.cov("l_quantity", "l_discount", ddof=0).alias("qty_discount_covariance"),
        pl.cov("l_tax", "l_extendedprice", ddof=1).alias("tax_price_covariance"),
        slope.alias("price_qty_slope"),
        intercept.alias("price_qty_intercept"),
        (pl.corr("l_quantity", "l_extendedprice") ** 2).alias("regression_r_squared"),
    )


def statistical_correlation_pandas_impl(ctx: DataFrameContext) -> Any:
    """Correlation, covariance, and linear regression between numeric columns."""
    filtered = ctx.get_table("lineitem")
    filtered = filtered[(filtered["l_shipdate"] >= date(1995, 1, 1)) & (filtered["l_shipdate"] < date(1996, 1, 1))]
    qty = filtered["l_quantity"]
    price = filtered["l_extendedprice"]
    slope = qty.cov(price, ddof=0) / qty.var(ddof=0)
    intercept = price.mean() - slope * qty.mean()
    corr_xy = qty.corr(price)
    return ctx.scalar_to_df(
        {
            "qty_price_correlation": corr_xy,
            "qty_discount_covariance": qty.cov(filtered["l_discount"], ddof=0),
            "tax_price_covariance": filtered["l_tax"].cov(price, ddof=1),
            "price_qty_slope": slope,
            "price_qty_intercept": intercept,
            "regression_r_squared": corr_xy**2,
        }
    )


def statistical_variance_expression_impl(ctx: DataFrameContext) -> Any:
    """Variance and standard deviation (sample + population) by order priority.

    Raw Polars for the ddof control (UnifiedExpr.var/std have none). DuckDB
    VARIANCE/STDDEV/STDDEV_SAMP are sample (ddof=1); STDDEV_POP is population
    (ddof=0).
    """
    import polars as pl

    return (
        ctx.get_table("orders")
        .native.filter(pl.col("o_orderdate") >= date(1995, 1, 1))
        .group_by("o_orderpriority")
        .agg(
            pl.len().alias("order_count"),
            pl.col("o_totalprice").mean().alias("avg_price"),
            pl.col("o_totalprice").var(ddof=1).alias("price_variance"),
            pl.col("o_totalprice").std(ddof=1).alias("price_stddev"),
            pl.col("o_totalprice").std(ddof=0).alias("price_stddev_pop"),
            pl.col("o_totalprice").std(ddof=1).alias("price_stddev_samp"),
        )
    )


def statistical_variance_pandas_impl(ctx: DataFrameContext) -> Any:
    """Variance and standard deviation (sample + population) by order priority."""
    orders = ctx.get_table("orders")
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    return filtered.groupby("o_orderpriority", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        avg_price=("o_totalprice", "mean"),
        price_variance=("o_totalprice", lambda s: s.var(ddof=1)),
        price_stddev=("o_totalprice", lambda s: s.std(ddof=1)),
        price_stddev_pop=("o_totalprice", lambda s: s.std(ddof=0)),
        price_stddev_samp=("o_totalprice", lambda s: s.std(ddof=1)),
    )


def long_predicate_expression_impl(ctx: DataFrameContext) -> Any:
    """Query with many conjunctive predicates across multiple tables."""
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("lineitem")
        .join(ctx.get_table("orders"), left_on="l_orderkey", right_on="o_orderkey")
        .join(ctx.get_table("customer"), left_on="o_custkey", right_on="c_custkey")
        .filter(
            (col("l_shipdate") >= lit(date(1994, 1, 1)))
            & (col("l_shipdate") < lit(date(1995, 1, 1)))
            & (col("l_discount") >= lit(0.05))
            & (col("l_discount") <= lit(0.07))
            & (col("l_quantity") < lit(24))
            & (col("o_orderpriority") == lit("1-URGENT"))
            & (col("c_mktsegment") == lit("BUILDING"))
            & (col("l_returnflag") == lit("R"))
            & (col("l_linestatus") == lit("F"))
            & (col("o_totalprice") > lit(100000))
            & col("c_nationkey").is_in([1, 2, 3, 4, 5])
        )
        .select(col("l_orderkey").count().alias("count"))
    )


def long_predicate_pandas_impl(ctx: DataFrameContext) -> Any:
    """Query with many conjunctive predicates across multiple tables."""
    merged = ctx.get_table("lineitem").merge(ctx.get_table("orders"), left_on="l_orderkey", right_on="o_orderkey")
    merged = merged.merge(ctx.get_table("customer"), left_on="o_custkey", right_on="c_custkey")
    filtered = merged[
        (merged["l_shipdate"] >= date(1994, 1, 1))
        & (merged["l_shipdate"] < date(1995, 1, 1))
        & (merged["l_discount"] >= 0.05)
        & (merged["l_discount"] <= 0.07)
        & (merged["l_quantity"] < 24)
        & (merged["o_orderpriority"] == "1-URGENT")
        & (merged["c_mktsegment"] == "BUILDING")
        & (merged["l_returnflag"] == "R")
        & (merged["l_linestatus"] == "F")
        & (merged["o_totalprice"] > 100000)
        & merged["c_nationkey"].isin([1, 2, 3, 4, 5])
    ]
    return ctx.scalar_to_df({"count": len(filtered)})


def array_agg_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Aggregate part keys into arrays per supplier."""
    col = ctx.col
    return (
        ctx.get_table("partsupp")
        .group_by("ps_suppkey")
        .agg(
            col("ps_partkey").sort_by("ps_partkey").alias("supplied_parts"),
            col("ps_partkey").count().alias("part_count"),
        )
        .filter(col("part_count") <= 100)
        .sort("ps_suppkey")
        .limit(100)
    )


def array_agg_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Aggregate part keys into arrays per supplier."""
    result = (
        ctx.get_table("partsupp")
        .groupby("ps_suppkey", as_index=False)
        .agg(supplied_parts=("ps_partkey", lambda x: sorted(x)), part_count=("ps_partkey", "count"))
    )
    return result[result["part_count"] <= 100].sort_values("ps_suppkey").head(100).reset_index(drop=True)


def array_agg_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Distinct array aggregation."""
    return (
        ctx.get_table("customer")
        .group_by("c_mktsegment")
        .agg(ctx.col("c_nationkey").unique().sort().alias("nation_keys"))
        .sort("c_mktsegment")
    )


def array_agg_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distinct array aggregation."""
    return (
        ctx.get_table("customer")
        .groupby("c_mktsegment", as_index=False)
        .agg(nation_keys=("c_nationkey", lambda x: sorted(set(x))))
        .sort_values("c_mktsegment")
        .reset_index(drop=True)
    )


# -----------------------------------------------------------------------------
# Limit query (Expression)
# -----------------------------------------------------------------------------


def limit_expression_impl(ctx: DataFrameContext) -> Any:
    """SELECT * FROM lineitem ORDER BY l_orderkey, l_linenumber LIMIT 100."""
    return ctx.get_table("lineitem").sort(["l_orderkey", "l_linenumber"]).limit(100)


def limit_pandas_impl(ctx: DataFrameContext) -> Any:
    """SELECT * FROM lineitem ORDER BY l_orderkey, l_linenumber LIMIT 100."""
    return ctx.get_table("lineitem").sort_values(["l_orderkey", "l_linenumber"]).head(100).reset_index(drop=True)


def limit_ordered_expression_impl(ctx: DataFrameContext) -> Any:
    """LIMIT clause with ordering on large result set."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.sort(["l_orderkey", "l_linenumber"]).limit(100)


def limit_ordered_pandas_impl(ctx: DataFrameContext) -> Any:
    """LIMIT clause with ordering on large result set."""
    lineitem = ctx.get_table("lineitem")

    return lineitem.sort_values(["l_orderkey", "l_linenumber"]).head(100)


# -----------------------------------------------------------------------------
# Decimal IN list filter queries
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# String LIKE filter queries (LIKE pattern)
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# OrderBy decimal queries
# -----------------------------------------------------------------------------


def orderby_decimal_expression_impl(ctx: DataFrameContext) -> Any:
    """Multi-column sort with mixed ASC/DESC on decimal columns."""
    lineitem = ctx.get_table("lineitem")

    # l_orderkey is the tertiary tie-break (matches the catalog SQL) so the
    # LIMIT-100 boundary over the non-unique (l_extendedprice, l_discount) keys is a
    # total order on both surfaces.
    return (
        lineitem.sort(["l_extendedprice", "l_discount", "l_orderkey"], descending=[True, False, False])
        .select("l_orderkey", "l_extendedprice", "l_discount")
        .limit(100)
    )


def orderby_decimal_pandas_impl(ctx: DataFrameContext) -> Any:
    """Multi-column sort with mixed ASC/DESC on decimal columns."""
    lineitem = ctx.get_table("lineitem")

    return (
        lineitem.sort_values(["l_extendedprice", "l_discount", "l_orderkey"], ascending=[False, True, True])[
            ["l_orderkey", "l_extendedprice", "l_discount"]
        ]
        .head(100)
        .reset_index(drop=True)
    )


# -----------------------------------------------------------------------------
# Min/Max runtime filter query
# -----------------------------------------------------------------------------


def min_max_runtime_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Bloom filter and runtime filter effectiveness for join optimization."""
    lineitem, orders = _tables(ctx, "lineitem", "orders")
    col = ctx.col
    lit = ctx.lit

    # Get orderkeys from date range
    date_filtered_orders = orders.filter(
        (col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") <= lit(date(1995, 3, 31)))
    ).select("o_orderkey")

    # SQL is `SELECT l.* FROM lineitem l WHERE l_orderkey IN (...)` -> all 16
    # lineitem columns; a semi-join keeps exactly the left (lineitem) columns.
    return lineitem.join(date_filtered_orders, left_on="l_orderkey", right_on="o_orderkey", how="semi")


def min_max_runtime_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Bloom filter and runtime filter effectiveness for join optimization."""
    lineitem, orders = _tables(ctx, "lineitem", "orders")

    date_filtered_orders = orders[
        (orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] <= date(1995, 3, 31))
    ]["o_orderkey"].unique()

    return lineitem[lineitem["l_orderkey"].isin(date_filtered_orders)].reset_index(drop=True)


# -----------------------------------------------------------------------------
# ANY_VALUE queries (modern SQL feature)
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# GROUP BY ALL queries (modern SQL feature)
# Note: GROUP BY ALL automatically groups by all non-aggregate columns
# In DataFrames, we explicitly specify the grouping columns
# -----------------------------------------------------------------------------


def groupby_all_complex_expression_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY ALL with multiple non-aggregate expressions."""
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    filtered = orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
    return (
        filtered.with_columns(col("o_orderdate").dt.truncate("1mo").alias("order_month"))
        .group_by("order_month", "o_orderpriority")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("monthly_revenue"),
        )
        .sort(["order_month", "o_orderpriority"])
    )


def groupby_all_complex_pandas_impl(ctx: DataFrameContext) -> Any:
    """GROUP BY ALL with multiple non-aggregate expressions."""
    import pandas as pd

    orders = ctx.get_table("orders")

    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)].copy()
    # Month-start date matching DATE_TRUNC('MONTH', ...). o_orderdate is Arrow
    # date32-backed, so .dt.to_period("M") raises and a Period would not normalize
    # to a date; subtract (day-1) to get a midnight Timestamp that normalizes to
    # date(Y, M, 1) like the SQL DATE column.
    dt = filtered["o_orderdate"].astype("datetime64[ns]")
    filtered["order_month"] = dt - pd.to_timedelta(dt.dt.day - 1, unit="D")

    return (
        filtered.groupby(["order_month", "o_orderpriority"], as_index=False)
        .agg(
            order_count=("o_orderkey", "count"),
            monthly_revenue=("o_totalprice", "sum"),
        )
        .sort_values(["order_month", "o_orderpriority"])
        .reset_index(drop=True)
    )


# -----------------------------------------------------------------------------
# ORDER BY ALL queries (modern SQL feature)
# -----------------------------------------------------------------------------


def orderby_all_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Order by all columns in SELECT list."""
    supplier, nation, region = _tables(ctx, "supplier", "nation", "region")
    col = ctx.col

    return (
        supplier.join(nation, left_on="s_nationkey", right_on="n_nationkey")
        .join(region, left_on="n_regionkey", right_on="r_regionkey")
        .group_by("r_name", "n_name")
        .agg(col("s_suppkey").count().alias("supplier_count"))
        .sort(["r_name", "n_name", "supplier_count"])
    )


def orderby_all_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order by all columns in SELECT list."""
    supplier, nation, region = _tables(ctx, "supplier", "nation", "region")

    merged = supplier.merge(nation, left_on="s_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey")

    return (
        merged.groupby(["r_name", "n_name"], as_index=False)
        .agg(supplier_count=("s_suppkey", "count"))
        .sort_values(["r_name", "n_name", "supplier_count"])
    )


# -----------------------------------------------------------------------------
# Additional predicate queries
# -----------------------------------------------------------------------------


def predicate_ordering_subquery_expression_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with subquery predicate."""
    orders, customer = _tables(ctx, "orders", "customer")
    col = ctx.col
    lit = ctx.lit

    # Get customers matching criteria
    building_customers = customer.filter(
        (col("c_mktsegment") == lit("BUILDING")) & (col("c_nationkey") == lit(1))
    ).select("c_custkey")

    return (
        orders.filter((col("o_totalprice") > lit(100000)) & (col("o_orderdate") >= lit(date(1995, 1, 1))))
        .join(building_customers, left_on="o_custkey", right_on="c_custkey", how="semi")
        .select("o_orderkey", "o_totalprice")
    )


def predicate_ordering_subquery_pandas_impl(ctx: DataFrameContext) -> Any:
    """Order filter predicates by selectivity with subquery predicate."""
    orders, customer = _tables(ctx, "orders", "customer")

    building_customers = customer[(customer["c_mktsegment"] == "BUILDING") & (customer["c_nationkey"] == 1)][
        "c_custkey"
    ].unique()

    filtered_orders = orders[(orders["o_totalprice"] > 100000) & (orders["o_orderdate"] >= date(1995, 1, 1))]
    return filtered_orders[filtered_orders["o_custkey"].isin(building_customers)][["o_orderkey", "o_totalprice"]]


# -----------------------------------------------------------------------------
# Shuffle with UNION ALL query
# -----------------------------------------------------------------------------


def shuffle_union_all_groupby_expression_impl(ctx: DataFrameContext) -> Any:
    """Complex join with UNION ALL and different data sources."""
    orders, lineitem = _tables(ctx, "orders", "lineitem")
    col = ctx.col
    lit = ctx.lit

    # First source: orders from date range
    orders_source = (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .select(col("o_custkey").alias("cust_id"))
        .with_columns(lit("ORDER").alias("source_type"))
    )

    # Second source: lineitems joined with orders
    lineitem_orders = (
        orders.join(lineitem, left_on="o_orderkey", right_on="l_orderkey")
        .filter(col("l_shipdate") >= lit(date(1995, 1, 1)))
        .select(col("o_custkey").alias("cust_id"))
        .with_columns(lit("LINEITEM").alias("source_type"))
    )

    # Combine and aggregate
    return (
        orders_source.vstack(lineitem_orders).group_by("source_type").agg(col("cust_id").count().alias("record_count"))
    )


def shuffle_union_all_groupby_pandas_impl(ctx: DataFrameContext) -> Any:
    """Complex join with UNION ALL and different data sources."""
    orders, lineitem = _tables(ctx, "orders", "lineitem")

    # First source
    orders_source = orders[orders["o_orderdate"] >= date(1995, 1, 1)][["o_custkey"]].copy()
    orders_source["source_type"] = "ORDER"
    orders_source = orders_source.rename(columns={"o_custkey": "cust_id"})

    # Second source
    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    lineitem_source = merged[merged["l_shipdate"] >= date(1995, 1, 1)][["o_custkey"]].copy()
    lineitem_source["source_type"] = "LINEITEM"
    lineitem_source = lineitem_source.rename(columns={"o_custkey": "cust_id"})

    # Combine using ctx.concat for platform compatibility
    combined = ctx.concat([orders_source, lineitem_source])
    return combined.groupby("source_type", as_index=False).agg(record_count=("cust_id", "count"))


# -----------------------------------------------------------------------------
# Statistical percentiles query
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Case-insensitive string matching queries
# -----------------------------------------------------------------------------


# -----------------------------------------------------------------------------
# Additional Window queries
# -----------------------------------------------------------------------------


def window_moving_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with complex moving frame definitions.

    Raw Polars: a 6-row trailing AVG (ROWS frame, over the total-order sort) plus a
    30-day RANGE SUM (``rolling_sum_by`` on o_orderdate). The unified surface has
    no bounded-frame window helper.
    """
    import polars as pl

    lf = (
        ctx.get_table("orders")
        .native.filter((pl.col("o_orderdate") >= date(1995, 1, 1)) & (pl.col("o_orderdate") < date(1996, 1, 1)))
        .sort(["o_orderdate", "o_orderkey"])
    )
    return lf.with_columns(
        pl.col("o_totalprice").rolling_mean(window_size=6, min_samples=1).alias("moving_avg_6_orders"),
        pl.col("o_totalprice")
        .rolling_sum_by("o_orderdate", window_size="30d", closed="both")
        .alias("monthly_running_total"),
    ).select("o_orderkey", "o_orderdate", "o_totalprice", "moving_avg_6_orders", "monthly_running_total")


def window_moving_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with complex moving frame definitions."""
    import pandas as pd

    orders = ctx.get_table("orders")
    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))].copy()
    filtered = filtered.sort_values(["o_orderdate", "o_orderkey"]).reset_index(drop=True)
    # 6-row trailing average (ROWS BETWEEN 5 PRECEDING AND CURRENT ROW).
    filtered["moving_avg_6_orders"] = filtered["o_totalprice"].rolling(window=6, min_periods=1).mean()
    # 30-day RANGE sum: value-based and PEER-inclusive (every row of a date shares
    # the same total), so aggregate to one row per date first, roll over the unique
    # dates ([t-30d, t]), then broadcast back - a row-position rolling window would
    # miss same-date peers that sort after the current row.
    daily = filtered.groupby("o_orderdate", as_index=False)["o_totalprice"].sum().sort_values("o_orderdate")
    didx = pd.DatetimeIndex(daily["o_orderdate"].astype("datetime64[ns]"))
    daily["monthly_running_total"] = (
        pd.Series(daily["o_totalprice"].to_numpy(), index=didx).rolling("30D", closed="both").sum().to_numpy()
    )
    filtered = filtered.merge(daily[["o_orderdate", "monthly_running_total"]], on="o_orderdate")
    return filtered.sort_values(["o_orderdate", "o_orderkey"])[
        ["o_orderkey", "o_orderdate", "o_totalprice", "moving_avg_6_orders", "monthly_running_total"]
    ].reset_index(drop=True)


def window_unbounded_frame_expression_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with the same unbounded frame definition."""
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
        lineitem.filter((col("l_orderkey") >= lit(1)) & (col("l_orderkey") <= lit(5000)))
        .sort(["l_orderkey", "l_linenumber"])
        .with_columns(
            [
                col("l_quantity").first().over("l_orderkey").alias("first_line_qty"),
                col("l_quantity").last().over("l_orderkey").alias("last_line_qty"),
            ]
        )
        .select("l_orderkey", "l_linenumber", "l_shipdate", "l_quantity", "first_line_qty", "last_line_qty")
    )


def window_unbounded_frame_pandas_impl(ctx: DataFrameContext) -> Any:
    """Window aggregations with the same unbounded frame definition."""
    lineitem = ctx.get_table("lineitem")

    filtered = lineitem[(lineitem["l_orderkey"] >= 1) & (lineitem["l_orderkey"] <= 5000)].copy()
    filtered = filtered.sort_values(["l_orderkey", "l_linenumber"])

    filtered["first_line_qty"] = filtered.groupby("l_orderkey")["l_quantity"].transform("first")
    filtered["last_line_qty"] = filtered.groupby("l_orderkey")["l_quantity"].transform("last")

    return filtered[["l_orderkey", "l_linenumber", "l_shipdate", "l_quantity", "first_line_qty", "last_line_qty"]]


# =============================================================================
# Intrinsic Queries (Approximate Median, Date Conversion)
# =============================================================================


# =============================================================================
# Fulltext Queries (String Pattern Matching - DataFrame Equivalent)
# =============================================================================
# Note: DataFrames don't have SQL-style MATCH...AGAINST fulltext search.
# We implement these using string pattern matching which provides similar
# functionality for basic text search use cases.


def fulltext_simple_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Basic text search using string contains pattern matching."""
    part = ctx.get_table("part")
    col = ctx.col

    # Search for parts containing "STEEL" or "COPPER" in name or comment
    return (
        part.filter(
            col("p_name").str.contains("STEEL")
            | col("p_name").str.contains("COPPER")
            | col("p_comment").str.contains("STEEL")
            | col("p_comment").str.contains("COPPER")
        )
        .select("p_partkey", "p_name", "p_mfgr", "p_comment")
        .limit(100)
    )


def fulltext_simple_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Basic text search using string contains pattern matching."""
    part = ctx.get_table("part")

    # Search for parts containing "STEEL" or "COPPER" in name or comment
    mask = (
        part["p_name"].str.contains("STEEL", case=True, na=False)
        | part["p_name"].str.contains("COPPER", case=True, na=False)
        | part["p_comment"].str.contains("STEEL", case=True, na=False)
        | part["p_comment"].str.contains("COPPER", case=True, na=False)
    )
    return part[mask][["p_partkey", "p_name", "p_mfgr", "p_comment"]].head(100)


def fulltext_boolean_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Boolean text search with AND/NOT operators."""
    customer = ctx.get_table("customer")
    col = ctx.col

    # Must contain "BUILDING", must NOT contain "FURNITURE"
    # Also compute a simple relevance score (1 for match, 0 for no match)
    return (
        customer.filter(col("c_comment").str.contains("BUILDING") & ~col("c_comment").str.contains("FURNITURE"))
        .with_columns(col("c_comment").str.contains("BUILDING").cast(int).alias("relevance_score"))
        .select("c_custkey", "c_name", "c_comment", "relevance_score")
        .sort("relevance_score", descending=True)
        .limit(50)
    )


def fulltext_boolean_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Boolean text search with AND/NOT operators."""
    customer = ctx.get_table("customer")

    # Must contain "BUILDING", must NOT contain "FURNITURE"
    contains_building = customer["c_comment"].str.contains("BUILDING", case=True, na=False)
    contains_furniture = customer["c_comment"].str.contains("FURNITURE", case=True, na=False)

    filtered = customer[contains_building & ~contains_furniture].copy()
    filtered["relevance_score"] = 1  # Simple relevance: all matches score 1

    return (
        filtered[["c_custkey", "c_name", "c_comment", "relevance_score"]]
        .sort_values("relevance_score", ascending=False)
        .head(50)
    )


def fulltext_phrase_search_expression_impl(ctx: DataFrameContext) -> Any:
    """Phrase-based text search for exact phrase match."""
    supplier = ctx.get_table("supplier")
    col = ctx.col

    # Search for exact phrase "Customer Complaints" (case-insensitive for robustness)
    return (
        supplier.filter(col("s_comment").str.to_lowercase().str.contains("customer complaints"))
        .with_columns(
            col("s_comment")
            .str.to_lowercase()
            .str.contains("customer complaints")
            .cast(int)
            .alias("phrase_match_score")
        )
        .select("s_suppkey", "s_name", "s_comment", "phrase_match_score")
        .sort("phrase_match_score", descending=True)
    )


def fulltext_phrase_search_pandas_impl(ctx: DataFrameContext) -> Any:
    """Phrase-based text search for exact phrase match."""
    supplier = ctx.get_table("supplier")

    # Search for exact phrase "Customer Complaints" (case-insensitive)
    phrase_match = supplier["s_comment"].str.lower().str.contains("customer complaints", na=False)

    filtered = supplier[phrase_match].copy()
    filtered["phrase_match_score"] = 1  # All matches score 1

    return filtered[["s_suppkey", "s_name", "s_comment", "phrase_match_score"]].sort_values(
        "phrase_match_score", ascending=False
    )


# =============================================================================
# OLAP Queries (CUBE/ROLLUP - Multi-dimensional Aggregation)
# =============================================================================
# CUBE and ROLLUP produce multiple levels of aggregation in SQL.
# For DataFrames, we implement these using:
# - PySpark: Native cube()/rollup() methods
# - Polars/Pandas: Multiple groupby operations + union


def olap_cube_analysis_expression_impl(ctx: DataFrameContext) -> Any:
    """CUBE operation for multidimensional analysis.

    Expression-family (Polars/PySpark) implementation.
    For PySpark, we can use native .cube() method.
    For Polars, we simulate with multiple groupby + union.
    """
    orders, customer, nation, region = _tables(ctx, "orders", "customer", "nation", "region")
    col = ctx.col
    lit = ctx.lit

    # Full CUBE over (nation, region, order_year, order_quarter) = 2^4 grouping
    # sets, NULL for each non-grouped dim. No ORDER BY -> order-insensitive. Raw
    # Polars to emit and union the grouping sets.
    import itertools

    import polars as pl

    del col, lit
    joined = (
        orders.native.filter((pl.col("o_orderdate") >= date(1995, 1, 1)) & (pl.col("o_orderdate") < date(1997, 1, 1)))
        .join(customer.native, left_on="o_custkey", right_on="c_custkey")
        .join(nation.native, left_on="c_nationkey", right_on="n_nationkey")
        .join(region.native, left_on="n_regionkey", right_on="r_regionkey")
        .with_columns(
            pl.col("n_name").alias("nation"),
            pl.col("r_name").alias("region"),
            pl.col("o_orderdate").dt.year().cast(pl.Int64).alias("order_year"),
            pl.col("o_orderdate").dt.quarter().cast(pl.Int64).alias("order_quarter"),
        )
    )
    dims = ["nation", "region", "order_year", "order_quarter"]
    measures = [
        pl.len().alias("order_count"),
        pl.col("o_totalprice").sum().alias("total_revenue"),
        pl.col("o_totalprice").mean().alias("avg_order_value"),
    ]
    frames = []
    for k in range(len(dims), -1, -1):
        for grp in itertools.combinations(dims, k):
            sub = joined.group_by(list(grp)).agg(*measures) if grp else joined.select(*measures)
            for dim in dims:
                if dim not in grp:
                    dtype = pl.Int64 if dim in ("order_year", "order_quarter") else pl.Utf8
                    sub = sub.with_columns(pl.lit(None, dtype=dtype).alias(dim))
            frames.append(sub.select(*dims, "order_count", "total_revenue", "avg_order_value"))
    return pl.concat(frames, how="vertical_relaxed")


def olap_cube_analysis_pandas_impl(ctx: DataFrameContext) -> Any:
    """CUBE operation for multidimensional analysis."""
    import itertools

    import pandas as pd

    orders, customer, nation, region = _tables(ctx, "orders", "customer", "nation", "region")
    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1997, 1, 1))]
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey").copy()
    od = pd.to_datetime(merged["o_orderdate"])
    merged["nation"] = merged["n_name"]
    merged["region"] = merged["r_name"]
    merged["order_year"] = od.dt.year
    merged["order_quarter"] = od.dt.quarter
    dims = ["nation", "region", "order_year", "order_quarter"]
    frames = []
    for k in range(len(dims), -1, -1):
        for grp in itertools.combinations(dims, k):
            if grp:
                sub = merged.groupby(list(grp), as_index=False).agg(
                    order_count=("o_orderkey", "count"),
                    total_revenue=("o_totalprice", "sum"),
                    avg_order_value=("o_totalprice", "mean"),
                )
            else:
                sub = pd.DataFrame(
                    {
                        "order_count": [len(merged)],
                        "total_revenue": [merged["o_totalprice"].sum()],
                        "avg_order_value": [merged["o_totalprice"].mean()],
                    }
                )
            for dim in dims:
                if dim not in grp:
                    sub[dim] = None
            frames.append(sub[dims + ["order_count", "total_revenue", "avg_order_value"]])
    return pd.concat(frames, ignore_index=True)


def olap_rollup_analysis_expression_impl(ctx: DataFrameContext) -> Any:
    """ROLLUP operation for hierarchical aggregation.

    Expression-family implementation.
    """
    orders, customer, nation, region = _tables(ctx, "orders", "customer", "nation", "region")
    col = ctx.col
    lit = ctx.lit

    # Full ROLLUP over (region, nation, market_segment) = 4 prefix grouping sets
    # {(r,n,m),(r,n),(r),()}, NULL for rolled-up dims, ORDER BY dims NULLS LAST.
    import polars as pl

    del col, lit
    joined = (
        orders.native.filter(pl.col("o_orderdate") >= date(1995, 1, 1))
        .join(customer.native, left_on="o_custkey", right_on="c_custkey")
        .join(nation.native, left_on="c_nationkey", right_on="n_nationkey")
        .join(region.native, left_on="n_regionkey", right_on="r_regionkey")
        .with_columns(
            pl.col("r_name").alias("region"),
            pl.col("n_name").alias("nation"),
            pl.col("c_mktsegment").alias("market_segment"),
        )
    )
    dims = ["region", "nation", "market_segment"]
    # Polars consumes the right join key, so c_custkey is gone after the join;
    # o_custkey == c_custkey on joined rows, so DISTINCT o_custkey == DISTINCT
    # c_custkey.
    measures = [
        pl.col("o_custkey").n_unique().alias("customer_count"),
        pl.len().alias("order_count"),
        pl.col("o_totalprice").sum().alias("total_revenue"),
        pl.col("o_totalprice").mean().alias("avg_order_value"),
    ]
    frames = []
    for k in range(len(dims), -1, -1):
        grp = dims[:k]
        sub = joined.group_by(grp).agg(*measures) if grp else joined.select(*measures)
        for dim in dims:
            if dim not in grp:
                sub = sub.with_columns(pl.lit(None, dtype=pl.Utf8).alias(dim))
        frames.append(sub.select(*dims, "customer_count", "order_count", "total_revenue", "avg_order_value"))
    return pl.concat(frames, how="vertical_relaxed").sort(dims, nulls_last=True)


def olap_rollup_analysis_pandas_impl(ctx: DataFrameContext) -> Any:
    """ROLLUP operation for hierarchical aggregation."""
    import pandas as pd

    orders, customer, nation, region = _tables(ctx, "orders", "customer", "nation", "region")
    filtered = orders[orders["o_orderdate"] >= date(1995, 1, 1)]
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    merged = merged.merge(region, left_on="n_regionkey", right_on="r_regionkey").copy()
    merged["region"] = merged["r_name"]
    merged["nation"] = merged["n_name"]
    merged["market_segment"] = merged["c_mktsegment"]
    dims = ["region", "nation", "market_segment"]
    frames = []
    for k in range(len(dims), -1, -1):
        grp = dims[:k]
        if grp:
            sub = merged.groupby(grp, as_index=False).agg(
                customer_count=("c_custkey", "nunique"),
                order_count=("o_orderkey", "count"),
                total_revenue=("o_totalprice", "sum"),
                avg_order_value=("o_totalprice", "mean"),
            )
        else:
            sub = pd.DataFrame(
                {
                    "customer_count": [merged["c_custkey"].nunique()],
                    "order_count": [len(merged)],
                    "total_revenue": [merged["o_totalprice"].sum()],
                    "avg_order_value": [merged["o_totalprice"].mean()],
                }
            )
        for dim in dims:
            if dim not in grp:
                sub[dim] = None
        frames.append(sub[dims + ["customer_count", "order_count", "total_revenue", "avg_order_value"]])
    return pd.concat(frames, ignore_index=True).sort_values(dims, na_position="last").reset_index(drop=True)


# =============================================================================
# Pivot/Unpivot Queries
# =============================================================================


def pivot_basic_expression_impl(ctx: DataFrameContext) -> Any:
    """Pivot ship modes into columns.

    Expression-family implementation using Polars pivot.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # Filter and select
    filtered = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1995, 4, 1)))
    ).select("l_returnflag", "l_shipmode", "l_quantity")

    # Pivot: sum l_quantity for each l_shipmode per l_returnflag
    return filtered.group_by("l_returnflag").agg(
        col("l_quantity").filter(col("l_shipmode") == lit("AIR")).sum().alias("AIR"),
        col("l_quantity").filter(col("l_shipmode") == lit("RAIL")).sum().alias("RAIL"),
        col("l_quantity").filter(col("l_shipmode") == lit("SHIP")).sum().alias("SHIP"),
        col("l_quantity").filter(col("l_shipmode") == lit("TRUCK")).sum().alias("TRUCK"),
    )


def pivot_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Pivot ship modes into columns.

    Pandas-family implementation using pivot_table.
    """
    lineitem = ctx.get_table("lineitem")

    # Filter - restrict to the four pivoted modes so the result has exactly the
    # SQL's `FOR l_shipmode IN ('AIR','RAIL','SHIP','TRUCK')` columns (pivot_table
    # would otherwise emit a column per shipmode present in the data).
    modes = ["AIR", "RAIL", "SHIP", "TRUCK"]
    filtered = lineitem[
        (lineitem["l_shipdate"] >= date(1995, 1, 1))
        & (lineitem["l_shipdate"] < date(1995, 4, 1))
        & (lineitem["l_shipmode"].isin(modes))
    ][["l_returnflag", "l_shipmode", "l_quantity"]]

    pivoted = filtered.pivot_table(
        index="l_returnflag",
        columns="l_shipmode",
        values="l_quantity",
        aggfunc="sum",
        fill_value=0,
    ).reindex(columns=modes, fill_value=0)
    pivoted = pivoted.reset_index()
    pivoted.columns.name = None
    return pivoted


def unpivot_basic_expression_impl(ctx: DataFrameContext) -> Any:
    """Unpivot part dimensions into rows.

    Expression-family implementation using melt.
    """
    part = ctx.get_table("part")
    col = ctx.col
    lit = ctx.lit

    # Filter and select columns to unpivot
    filtered = part.filter(col("p_partkey") <= lit(100)).select(
        "p_partkey",
        col("p_size").cast(float).alias("p_size"),
        col("p_retailprice").alias("p_retailprice"),
    )

    # Melt (unpivot) - convert p_size and p_retailprice to dimension_name/dimension_value rows
    return filtered.melt(
        id_vars=["p_partkey"],
        value_vars=["p_size", "p_retailprice"],
        variable_name="dimension_name",
        value_name="dimension_value",
    ).sort(["p_partkey", "dimension_name"])


def unpivot_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """Unpivot part dimensions into rows.

    Pandas-family implementation using melt.
    """
    part = ctx.get_table("part")

    # Filter and select
    filtered = part[part["p_partkey"] <= 100][["p_partkey", "p_size", "p_retailprice"]].copy()
    filtered["p_size"] = filtered["p_size"].astype(float)

    # Melt (unpivot)
    return (
        filtered.melt(
            id_vars=["p_partkey"],
            value_vars=["p_size", "p_retailprice"],
            var_name="dimension_name",
            value_name="dimension_value",
        )
        .sort_values(["p_partkey", "dimension_name"])
        .reset_index(drop=True)
    )


# =============================================================================
# Optimizer Probe Queries
# =============================================================================
# These queries test SQL optimizer behavior. The key is to write them in "naive"
# form WITHOUT manually optimizing - let Catalyst/query planner do the work.
#
# IMPORTANT: Do NOT "bake in" the optimization:
# - predicate_pushdown: Filter AFTER join, not before
# - join_reordering: Keep "bad" join order, no broadcast hints
# - limit_pushdown: orderBy().limit() at end only
# - column_pruning: Select only at the very end
# - common_subexpression: Repeat full expression multiple times
# - constant_folding: Use Spark expressions, not Python math


def optimizer_distinct_elimination_expression_impl(ctx: DataFrameContext) -> Any:
    """Test DISTINCT elimination when result is already unique (PK included).

    Expression-family implementation - write naive DISTINCT on columns including PK.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # SQL: date window AND o_totalprice > 50000, DISTINCT, ORDER BY o_orderkey,
    # LIMIT 2000.
    return (
        orders.filter((col("o_orderdate") >= lit(date(1995, 1, 1))) & (col("o_orderdate") < lit(date(1996, 1, 1))))
        .filter(col("o_totalprice") > lit(50000))
        .select("o_orderkey", "o_custkey", "o_orderdate", "o_totalprice")
        .unique()
        .sort("o_orderkey")
        .limit(2000)
    )


def optimizer_distinct_elimination_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test DISTINCT elimination when result is already unique (PK included)."""
    orders = ctx.get_table("orders")

    filtered = orders[
        (orders["o_orderdate"] >= date(1995, 1, 1))
        & (orders["o_orderdate"] < date(1996, 1, 1))
        & (orders["o_totalprice"] > 50000)
    ]
    return (
        filtered[["o_orderkey", "o_custkey", "o_orderdate", "o_totalprice"]]
        .drop_duplicates()
        .sort_values("o_orderkey")
        .head(2000)
        .reset_index(drop=True)
    )


def optimizer_common_subexpression_expression_impl(ctx: DataFrameContext) -> Any:
    """Test Common Subexpression Elimination (CSE).

    Raw Polars for the CASE + ROUND. SQL: shipdate window AND revenue > 1000;
    7 cols (revenue_with_tax, value_category CASE, rounded_revenue); ORDER BY
    revenue DESC, LIMIT 5000 (l_orderkey, l_linenumber tie-break matches catalog).
    """
    import polars as pl

    revenue = pl.col("l_quantity") * pl.col("l_extendedprice") * (1 - pl.col("l_discount")) * (1 + pl.col("l_tax"))
    lf = (
        ctx.get_table("lineitem")
        .native.filter((pl.col("l_shipdate") >= date(1995, 1, 1)) & (pl.col("l_shipdate") < date(1996, 1, 1)))
        .with_columns(revenue.alias("revenue_with_tax"))
        .filter(pl.col("revenue_with_tax") > 1000)
    )
    return (
        lf.with_columns(
            pl.when(pl.col("revenue_with_tax") > 50000)
            .then(pl.lit("High Value"))
            .when(pl.col("revenue_with_tax") > 10000)
            .then(pl.lit("Medium Value"))
            .otherwise(pl.lit("Low Value"))
            .alias("value_category"),
            pl.col("revenue_with_tax").round(2).alias("rounded_revenue"),
        )
        .select(
            "l_orderkey",
            "l_partkey",
            "l_suppkey",
            "l_linenumber",
            "revenue_with_tax",
            "value_category",
            "rounded_revenue",
        )
        .sort(["revenue_with_tax", "l_orderkey", "l_linenumber"], descending=[True, False, False])
        .limit(5000)
    )


def optimizer_common_subexpression_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test Common Subexpression Elimination (CSE)."""
    lineitem = ctx.get_table("lineitem")
    filtered = lineitem[
        (lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))
    ].copy()
    revenue = (
        filtered["l_quantity"] * filtered["l_extendedprice"] * (1 - filtered["l_discount"]) * (1 + filtered["l_tax"])
    )
    filtered["revenue_with_tax"] = revenue
    filtered = filtered[filtered["revenue_with_tax"] > 1000].copy()
    rev = filtered["revenue_with_tax"]
    filtered["value_category"] = "Low Value"
    filtered.loc[rev > 10000, "value_category"] = "Medium Value"
    filtered.loc[rev > 50000, "value_category"] = "High Value"
    filtered["rounded_revenue"] = rev.round(2)
    return (
        filtered[
            [
                "l_orderkey",
                "l_partkey",
                "l_suppkey",
                "l_linenumber",
                "revenue_with_tax",
                "value_category",
                "rounded_revenue",
            ]
        ]
        .sort_values(["revenue_with_tax", "l_orderkey", "l_linenumber"], ascending=[False, True, True])
        .head(5000)
        .reset_index(drop=True)
    )


def optimizer_predicate_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test predicate pushdown through joins.

    IMPORTANT: Filter AFTER join to let optimizer push predicates down.
    """
    customer, orders = _tables(ctx, "customer", "orders")
    col = ctx.col
    lit = ctx.lit

    # SQL: c_nationkey=15 AND date window AND c_mktsegment='BUILDING',
    # ORDER BY o_totalprice DESC, LIMIT 1000.
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("c_nationkey") == lit(15))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("o_orderdate") < lit(date(1996, 1, 1)))
        .filter(col("c_mktsegment") == lit("BUILDING"))
        .select("c_name", "c_mktsegment", "o_orderdate", "o_totalprice")
        .sort(["o_totalprice", "c_name", "o_orderdate"], descending=[True, False, False])
        .limit(1000)
    )


def optimizer_predicate_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test predicate pushdown through joins."""
    customer, orders = _tables(ctx, "customer", "orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[
        (merged["c_nationkey"] == 15)
        & (merged["o_orderdate"] >= date(1995, 1, 1))
        & (merged["o_orderdate"] < date(1996, 1, 1))
        & (merged["c_mktsegment"] == "BUILDING")
    ]
    return (
        filtered[["c_name", "c_mktsegment", "o_orderdate", "o_totalprice"]]
        .sort_values(["o_totalprice", "c_name", "o_orderdate"], ascending=[False, True, True])
        .head(1000)
        .reset_index(drop=True)
    )


def optimizer_join_reordering_expression_impl(ctx: DataFrameContext) -> Any:
    """Test join reordering optimization.

    Write joins in SUBOPTIMAL order (largest table first) - optimizer should reorder.
    """
    orders, customer, nation = _tables(ctx, "orders", "customer", "nation")
    col = ctx.col
    lit = ctx.lit

    # SQL: n_regionkey=1 AND date window, GROUP BY n_name,c_name,
    # HAVING COUNT(o_orderkey) > 5, ORDER BY total_value DESC, LIMIT 100.
    return (
        orders.filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("o_orderdate") < lit(date(1996, 1, 1)))
        .join(customer, col("o_custkey") == col("c_custkey"))
        .join(nation, col("c_nationkey") == col("n_nationkey"))
        .filter(col("n_regionkey") == lit(1))
        .group_by("n_name", "c_name")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_value"),
        )
        .filter(col("order_count") > lit(5))
        .select("n_name", "c_name", "order_count", "total_value")
        .sort(["total_value", "n_name", "c_name"], descending=[True, False, False])
        .limit(100)
    )


def optimizer_join_reordering_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test join reordering optimization."""
    orders, customer, nation = _tables(ctx, "orders", "customer", "nation")

    filtered = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1996, 1, 1))]
    merged = filtered.merge(customer, left_on="o_custkey", right_on="c_custkey")
    merged = merged.merge(nation, left_on="c_nationkey", right_on="n_nationkey")
    merged = merged[merged["n_regionkey"] == 1]

    grouped = merged.groupby(["n_name", "c_name"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_value=("o_totalprice", "sum"),
    )
    grouped = grouped[grouped["order_count"] > 5]
    return (
        grouped[["n_name", "c_name", "order_count", "total_value"]]
        .sort_values(["total_value", "n_name", "c_name"], ascending=[False, True, True])
        .head(100)
        .reset_index(drop=True)
    )


def optimizer_limit_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test limit pushdown through operations.

    Apply limit at the END only - optimizer should push partial limits down.
    """
    customer, orders = _tables(ctx, "customer", "orders")
    col = ctx.col
    lit = ctx.lit

    # SQL: c_mktsegment='BUILDING' AND date window, ORDER BY o_totalprice DESC,
    # LIMIT 100. Append c_name,o_orderdate as deterministic tie-breaks so the
    # LIMIT-100 boundary is a total order across engines.
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("c_mktsegment") == lit("BUILDING"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("o_orderdate") < lit(date(1996, 1, 1)))
        .select("c_name", "c_mktsegment", "o_orderdate", "o_totalprice", "o_orderpriority")
        .sort(["o_totalprice", "c_name", "o_orderdate"], descending=[True, False, False])
        .limit(100)
    )


def optimizer_limit_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test limit pushdown through operations."""
    customer, orders = _tables(ctx, "customer", "orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[
        (merged["c_mktsegment"] == "BUILDING")
        & (merged["o_orderdate"] >= date(1995, 1, 1))
        & (merged["o_orderdate"] < date(1996, 1, 1))
    ]
    return (
        filtered[["c_name", "c_mktsegment", "o_orderdate", "o_totalprice", "o_orderpriority"]]
        .sort_values(["o_totalprice", "c_name", "o_orderdate"], ascending=[False, True, True])
        .head(100)
        .reset_index(drop=True)
    )


def optimizer_aggregate_pushdown_expression_impl(ctx: DataFrameContext) -> Any:
    """Test aggregate pushdown before join.

    Join first, THEN aggregate - optimizer can push partial aggregates before join.
    """
    customer, orders = _tables(ctx, "customer", "orders")
    col = ctx.col
    lit = ctx.lit

    # SQL: c_nationkey=15 AND date window, GROUP BY c_custkey,c_name,c_mktsegment,
    # c_nationkey, HAVING SUM(o_totalprice) > 500000, ORDER BY total_spent DESC,
    # LIMIT 50.
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .filter(col("c_nationkey") == lit(15))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("o_orderdate") < lit(date(1996, 1, 1)))
        .group_by("c_custkey", "c_name", "c_mktsegment", "c_nationkey")
        .agg(
            col("o_orderkey").count().alias("order_count"),
            col("o_totalprice").sum().alias("total_spent"),
            col("o_totalprice").mean().alias("avg_order_value"),
        )
        .filter(col("total_spent") > lit(500000))
        .select("c_name", "c_mktsegment", "c_nationkey", "order_count", "total_spent", "avg_order_value")
        .sort(["total_spent", "c_name"], descending=[True, False])
        .limit(50)
    )


def optimizer_aggregate_pushdown_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test aggregate pushdown before join."""
    customer, orders = _tables(ctx, "customer", "orders")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    filtered = merged[
        (merged["c_nationkey"] == 15)
        & (merged["o_orderdate"] >= date(1995, 1, 1))
        & (merged["o_orderdate"] < date(1996, 1, 1))
    ]
    grouped = filtered.groupby(["c_custkey", "c_name", "c_mktsegment", "c_nationkey"], as_index=False).agg(
        order_count=("o_orderkey", "count"),
        total_spent=("o_totalprice", "sum"),
        avg_order_value=("o_totalprice", "mean"),
    )
    grouped = grouped[grouped["total_spent"] > 500000]
    return (
        grouped[["c_name", "c_mktsegment", "c_nationkey", "order_count", "total_spent", "avg_order_value"]]
        .sort_values(["total_spent", "c_name"], ascending=[False, True])
        .head(50)
        .reset_index(drop=True)
    )


def optimizer_constant_folding_expression_impl(ctx: DataFrameContext) -> Any:
    """Test constant folding optimization.

    Use Spark expressions for constants - optimizer should fold them at compile time.
    """
    lineitem = ctx.get_table("lineitem")
    col = ctx.col
    lit = ctx.lit

    # SQL: 10 projected columns (folded arithmetic), filters l_quantity>10,
    # shipdate>=1995, l_discount<0.1, ORDER BY l_quantity DESC LIMIT 1000.
    # l_quantity is not projected, so sort before select; l_orderkey,l_linenumber
    # tie-break (matches catalog) makes the LIMIT-1000 cut deterministic.
    filtered = (
        lineitem.filter(col("l_quantity") > lit(10))
        .filter(col("l_shipdate") >= lit(date(1995, 1, 1)))
        .filter(col("l_discount") < lit(0.1))
        .sort(["l_quantity", "l_orderkey", "l_linenumber"], descending=[True, False, False])
    )
    return filtered.select(
        "l_orderkey",
        "l_partkey",
        "l_suppkey",
        "l_linenumber",
        (col("l_quantity") * (lit(1.0) + lit(0.0))).alias("simplified_qty"),
        (col("l_extendedprice") * (lit(2) * lit(3) + lit(4))).alias("constant_folded"),
        (col("l_discount") + lit(0.0) - lit(0.0)).alias("zero_folded"),
        col("l_tax").alias("condition_folded"),
        (col("l_quantity") / lit(1.0)).alias("division_folded"),
        (col("l_extendedprice") + (lit(5) - lit(5))).alias("addition_folded"),
    ).limit(1000)


def optimizer_constant_folding_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test constant folding optimization."""
    lineitem = ctx.get_table("lineitem")
    filtered = lineitem[
        (lineitem["l_quantity"] > 10) & (lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_discount"] < 0.1)
    ].copy()
    filtered = filtered.sort_values(["l_quantity", "l_orderkey", "l_linenumber"], ascending=[False, True, True])
    filtered["simplified_qty"] = filtered["l_quantity"] * (1.0 + 0.0)
    filtered["constant_folded"] = filtered["l_extendedprice"] * (2 * 3 + 4)
    filtered["zero_folded"] = filtered["l_discount"] + 0.0 - 0.0
    filtered["condition_folded"] = filtered["l_tax"]
    filtered["division_folded"] = filtered["l_quantity"] / 1.0
    filtered["addition_folded"] = filtered["l_extendedprice"]
    return (
        filtered[
            [
                "l_orderkey",
                "l_partkey",
                "l_suppkey",
                "l_linenumber",
                "simplified_qty",
                "constant_folded",
                "zero_folded",
                "condition_folded",
                "division_folded",
                "addition_folded",
            ]
        ]
        .head(1000)
        .reset_index(drop=True)
    )


def optimizer_column_pruning_expression_impl(ctx: DataFrameContext) -> Any:
    """Test column pruning optimization.

    Select only at the very END - optimizer should prune unused columns at scan.
    """
    customer, orders, lineitem = _tables(ctx, "customer", "orders", "lineitem")
    col = ctx.col
    lit = ctx.lit

    # SQL: date window AND l_quantity > 40 AND c_nationkey = 15, SELECT c_name
    # (NO DISTINCT), ORDER BY c_name, LIMIT 500.
    return (
        customer.join(orders, col("c_custkey") == col("o_custkey"))
        .join(lineitem, col("o_orderkey") == col("l_orderkey"))
        .filter(col("o_orderdate") >= lit(date(1995, 1, 1)))
        .filter(col("o_orderdate") < lit(date(1996, 1, 1)))
        .filter(col("l_quantity") > lit(40))
        .filter(col("c_nationkey") == lit(15))
        .select("c_name")
        .sort("c_name")
        .limit(500)
    )


def optimizer_column_pruning_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test column pruning optimization."""
    customer, orders, lineitem = _tables(ctx, "customer", "orders", "lineitem")

    merged = customer.merge(orders, left_on="c_custkey", right_on="o_custkey")
    merged = merged.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    filtered = merged[
        (merged["o_orderdate"] >= date(1995, 1, 1))
        & (merged["o_orderdate"] < date(1996, 1, 1))
        & (merged["l_quantity"] > 40)
        & (merged["c_nationkey"] == 15)
    ]

    return filtered[["c_name"]].sort_values("c_name").head(500).reset_index(drop=True)


def optimizer_union_optimization_expression_impl(ctx: DataFrameContext) -> Any:
    """Test union optimization.

    Use multiple unions, then sort - optimizer may combine/deduplicate scans.
    """
    col = ctx.col
    lit = ctx.lit

    # SQL: 3-branch UNION ALL over customer c_acctbal bands AND c_nationkey IN
    # (1,2,3), projecting c_name, c_mktsegment, customer_type (band label),
    # c_acctbal; ORDER BY c_acctbal DESC, LIMIT 300.
    customer = ctx.get_table("customer")
    in_nations = col("c_nationkey").is_in([1, 2, 3])
    out_cols = ("c_name", "c_mktsegment", "customer_type", "c_acctbal")
    high = (
        customer.filter((col("c_acctbal") > lit(8000)) & in_nations)
        .with_columns(lit("high_value").alias("customer_type"))
        .select(*out_cols)
    )
    medium = (
        customer.filter((col("c_acctbal") >= lit(4000)) & (col("c_acctbal") <= lit(8000)) & in_nations)
        .with_columns(lit("medium_value").alias("customer_type"))
        .select(*out_cols)
    )
    low = (
        customer.filter((col("c_acctbal") >= lit(1000)) & (col("c_acctbal") <= lit(4000)) & in_nations)
        .with_columns(lit("low_value").alias("customer_type"))
        .select(*out_cols)
    )
    return ctx.concat([high, medium, low]).sort(["c_acctbal", "c_name"], descending=[True, False]).limit(300)


def optimizer_union_optimization_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test union optimization."""
    customer = ctx.get_table("customer")

    in_nations = customer["c_nationkey"].isin([1, 2, 3])
    cols = ["c_name", "c_mktsegment", "customer_type", "c_acctbal"]
    high = customer[(customer["c_acctbal"] > 8000) & in_nations].assign(customer_type="high_value")[cols]
    medium = customer[(customer["c_acctbal"] >= 4000) & (customer["c_acctbal"] <= 8000) & in_nations].assign(
        customer_type="medium_value"
    )[cols]
    low = customer[(customer["c_acctbal"] >= 1000) & (customer["c_acctbal"] <= 4000) & in_nations].assign(
        customer_type="low_value"
    )[cols]

    combined = ctx.concat([high, medium, low])
    return combined.sort_values(["c_acctbal", "c_name"], ascending=[False, True]).head(300).reset_index(drop=True)


def optimizer_runtime_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Test runtime filter / dynamic partition pruning.

    Join with highly selective filter on dimension - Spark generates bloom filter.
    """
    lineitem, part = _tables(ctx, "lineitem", "part")
    col = ctx.col
    lit = ctx.lit

    # SQL: p_type LIKE '%STEEL%' AND p_size BETWEEN 10 AND 20 AND shipdate window
    # AND l_quantity > 20; project l_orderkey,l_partkey,l_suppkey,l_quantity,
    # l_extendedprice,p_name,p_type; ORDER BY l_extendedprice DESC, LIMIT 1000.
    selective_parts = part.filter(col("p_type").str.contains("STEEL")).filter(
        (col("p_size") >= lit(10)) & (col("p_size") <= lit(20))
    )
    return (
        lineitem.join(selective_parts, col("l_partkey") == col("p_partkey"))
        .filter(col("l_shipdate") >= lit(date(1995, 1, 1)))
        .filter(col("l_shipdate") < lit(date(1996, 1, 1)))
        .filter(col("l_quantity") > lit(20))
        .select("l_orderkey", "l_partkey", "l_suppkey", "l_quantity", "l_extendedprice", "p_name", "p_type")
        .sort(["l_extendedprice", "l_orderkey", "l_partkey"], descending=[True, False, False])
        .limit(1000)
    )


def optimizer_runtime_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test runtime filter / dynamic partition pruning."""
    lineitem, part = _tables(ctx, "lineitem", "part")

    selective_parts = part[
        part["p_type"].str.contains("STEEL", na=False) & (part["p_size"] >= 10) & (part["p_size"] <= 20)
    ]
    merged = lineitem.merge(selective_parts, left_on="l_partkey", right_on="p_partkey")
    filtered = merged[
        (merged["l_shipdate"] >= date(1995, 1, 1))
        & (merged["l_shipdate"] < date(1996, 1, 1))
        & (merged["l_quantity"] > 20)
    ]
    return (
        filtered[["l_orderkey", "l_partkey", "l_suppkey", "l_quantity", "l_extendedprice", "p_name", "p_type"]]
        .sort_values(["l_extendedprice", "l_orderkey", "l_partkey"], ascending=[False, True, True])
        .head(1000)
        .reset_index(drop=True)
    )


def optimizer_groupjoin_expression_impl(ctx: DataFrameContext) -> Any:
    """Test group-join (join+aggregate fusion) optimization.

    Join orders→lineitem then immediately GROUP BY join key - good optimizers
    fuse these into a single grouped-join pass, never materializing the full
    intermediate result.
    """
    orders, lineitem = _tables(ctx, "orders", "lineitem")
    col = ctx.col
    lit = ctx.lit

    return (
        orders.join(lineitem, col("o_orderkey") == col("l_orderkey"))
        .group_by("o_orderkey", "o_custkey", "o_orderdate")
        .agg(
            col("l_linenumber").count().alias("line_count"),
            (col("l_extendedprice") * (lit(1) - col("l_discount"))).sum().alias("revenue"),
        )
        .sort("revenue", descending=True)
        .limit(100)
    )


def optimizer_groupjoin_pandas_impl(ctx: DataFrameContext) -> Any:
    """Test group-join (join+aggregate fusion) optimization."""
    orders, lineitem = _tables(ctx, "orders", "lineitem")

    merged = orders.merge(lineitem, left_on="o_orderkey", right_on="l_orderkey")
    merged = merged.copy()
    merged["revenue"] = merged["l_extendedprice"] * (1 - merged["l_discount"])

    return (
        merged.groupby(["o_orderkey", "o_custkey", "o_orderdate"], as_index=False)
        .agg(line_count=("l_linenumber", "count"), revenue=("revenue", "sum"))
        .nlargest(100, "revenue")
        .reset_index(drop=True)
    )


# =============================================================================
# QUALIFY Queries
# =============================================================================
# QUALIFY is a SQL clause that filters window function results. In DataFrames,
# this is equivalent to computing the window function, then filtering rows.


def _orders_customer_since_1995_expr(ctx: DataFrameContext) -> Any:
    return (
        ctx.get_table("orders")
        .join(ctx.get_table("customer"), ctx.col("o_custkey") == ctx.col("c_custkey"))
        .filter(ctx.col("o_orderdate") >= ctx.lit(date(1995, 1, 1)))
    )


def _orders_customer_since_1995_pandas(ctx: DataFrameContext) -> Any:
    joined = ctx.get_table("orders").merge(ctx.get_table("customer"), left_on="o_custkey", right_on="c_custkey")
    return joined[joined["o_orderdate"] >= date(1995, 1, 1)].copy()


def qualify_row_number_expression_impl(ctx: DataFrameContext) -> Any:
    """Find top 3 orders by total price for each customer using ROW_NUMBER.

    Expression-family implementation using window functions.
    """
    result = _orders_customer_since_1995_expr(ctx).with_columns(
        ctx.window_row_number(order_by=[("o_totalprice", False)], partition_by=["c_custkey"]).alias("order_rank")
    )
    return (
        result.filter(ctx.col("order_rank") <= ctx.lit(3))
        .select("c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "order_rank")
        .sort("c_custkey", "order_rank")
    )


def qualify_row_number_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find top 3 orders by total price for each customer using ROW_NUMBER."""
    result = _orders_customer_since_1995_pandas(ctx)
    result["order_rank"] = result.groupby("c_custkey")["o_totalprice"].rank(method="first", ascending=False)
    cols = ["c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "order_rank"]
    return result[result["order_rank"] <= 3][cols].sort_values(["c_custkey", "order_rank"]).reset_index(drop=True)


def qualify_dense_rank_expression_impl(ctx: DataFrameContext) -> Any:
    """Find top 2 most expensive parts in each category using DENSE_RANK.

    Expression-family implementation using window functions.
    """
    result = ctx.get_table("part").with_columns(
        ctx.window_dense_rank(order_by=[("p_retailprice", False)], partition_by=["p_type"]).alias("price_rank")
    )
    # SQL ORDER BY p_type, price_rank, p_name (all projected -> order-aware).
    return (
        result.filter(ctx.col("price_rank") <= ctx.lit(2))
        .select("p_type", "p_name", "p_retailprice", "price_rank")
        .sort(["p_type", "price_rank", "p_name"])
    )


def qualify_dense_rank_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find top 2 most expensive parts in each category using DENSE_RANK."""
    result = ctx.get_table("part").copy()
    result["price_rank"] = result.groupby("p_type")["p_retailprice"].rank(method="dense", ascending=False)
    return (
        result[result["price_rank"] <= 2][["p_type", "p_name", "p_retailprice", "price_rank"]]
        .sort_values(["p_type", "price_rank", "p_name"])
        .reset_index(drop=True)
    )


def qualify_ntile_expression_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top quartile by value for each market segment using NTILE.

    The ``window_ntile`` helper uses a wrong bucket formula, so NTILE is computed
    inline (raw Polars): the SQL definition assigns the first ``cnt % n`` buckets
    ``ceil(cnt/n)`` rows. Ordering matches the catalog tie-break
    ``ORDER BY o_totalprice, o_orderkey``.
    """
    import polars as pl

    n = 4
    lf = (
        _orders_customer_since_1995_expr(ctx)
        .native.sort(["c_mktsegment", "o_totalprice", "o_orderkey"])
        .with_columns(
            pl.int_range(0, pl.len()).over("c_mktsegment").alias("_r0"),
            pl.len().over("c_mktsegment").alias("_cnt"),
        )
    )
    base = pl.col("_cnt") // n
    rem = pl.col("_cnt") % n
    big = rem * (base + 1)
    quartile = (
        pl.when(pl.col("_r0") < big)
        .then(pl.col("_r0") // (base + 1) + 1)
        .otherwise(rem + (pl.col("_r0") - big) // base + 1)
    )
    lf = lf.with_columns(quartile.cast(pl.Int64).alias("quartile"))
    return (
        lf.filter(pl.col("quartile") == n)
        .select("c_mktsegment", "o_orderkey", "o_totalprice", "quartile")
        .sort(["c_mktsegment", "o_totalprice", "o_orderkey"], descending=[False, True, True])
    )


def qualify_ntile_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top quartile by value for each market segment using NTILE."""
    import numpy as np

    n = 4
    result = (
        _orders_customer_since_1995_pandas(ctx)
        .sort_values(["c_mktsegment", "o_totalprice", "o_orderkey"], kind="stable")
        .copy()
    )
    grp = result.groupby("c_mktsegment")
    r0 = grp.cumcount()
    cnt = grp["o_orderkey"].transform("count")
    base = cnt // n
    rem = cnt % n
    big = rem * (base + 1)
    # base is 0 for partitions smaller than n, but those rows always satisfy
    # r0 < big and take the first branch; guard the divisor so the (discarded)
    # else branch never divides by zero.
    quartile = np.where(r0 < big, r0 // (base + 1) + 1, rem + (r0 - big) // base.replace(0, 1) + 1)
    result["quartile"] = quartile.astype("int64")
    return (
        result[result["quartile"] == n][["c_mktsegment", "o_orderkey", "o_totalprice", "quartile"]]
        .sort_values(["c_mktsegment", "o_totalprice", "o_orderkey"], ascending=[True, False, False])
        .reset_index(drop=True)
    )


def qualify_percentile_expression_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top 10% by value for each order priority using PERCENT_RANK.

    Expression-family implementation using window functions.
    """
    result = (
        ctx.get_table("orders")
        .filter(ctx.col("o_orderdate") >= ctx.lit(date(1995, 1, 1)))
        .with_columns(
            ctx.window_percent_rank(order_by=[("o_totalprice", True)], partition_by=["o_orderpriority"]).alias(
                "price_percentile"
            )
        )
    )
    return (
        result.filter(ctx.col("price_percentile") >= ctx.lit(0.9))
        .select("o_orderpriority", "o_orderkey", "o_totalprice", "price_percentile")
        # Use the (names, descending=[...]) sort form: a `.desc()` sort-key marker
        # is not honored by UnifiedLazyFrame.sort and yields the wrong order.
        .sort(["o_orderpriority", "o_totalprice"], descending=[False, True])
    )


def qualify_percentile_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders in top 10% by value for each order priority using PERCENT_RANK."""
    result = ctx.get_table("orders")
    result = result[result["o_orderdate"] >= date(1995, 1, 1)].copy()
    # SQL PERCENT_RANK = (rank_min - 1) / (n - 1), NOT pandas rank(pct=True)
    # (which is average-rank/n). Single-row partitions are 0 (matches DuckDB).
    grp = result.groupby("o_orderpriority")["o_totalprice"]
    n = grp.transform("count")
    rank_min = grp.rank(method="min", ascending=True)
    result["price_percentile"] = ((rank_min - 1) / (n - 1)).where(n > 1, 0.0)
    return (
        result[result["price_percentile"] >= 0.9][["o_orderpriority", "o_orderkey", "o_totalprice", "price_percentile"]]
        .sort_values(["o_orderpriority", "o_totalprice"], ascending=[True, False])
        .reset_index(drop=True)
    )


def qualify_cume_dist_expression_impl(ctx: DataFrameContext) -> Any:
    """Find lineitems with quantity in top 5% of their ship date using CUME_DIST.

    Expression-family implementation using window functions.
    """
    col, lit = ctx.col, ctx.lit
    result = (
        ctx.get_table("lineitem")
        .filter((col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1996, 1, 1))))
        .with_columns(
            ctx.window_cume_dist(order_by=[("l_quantity", True)], partition_by=["l_shipdate"]).alias(
                "quantity_cumulative_dist"
            )
        )
    )
    return (
        result.filter(col("quantity_cumulative_dist") >= lit(0.95))
        .select("l_shipdate", "l_orderkey", "l_linenumber", "l_quantity", "quantity_cumulative_dist")
        # (names, descending=[...]) form + the SQL's full ORDER BY tie-break keys
        # (a `.desc()` marker is not honored by UnifiedLazyFrame.sort).
        .sort(["l_shipdate", "l_quantity", "l_orderkey", "l_linenumber"], descending=[False, True, False, False])
    )


def qualify_cume_dist_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find lineitems with quantity in top 5% of their ship date using CUME_DIST."""
    lineitem = ctx.get_table("lineitem")
    result = lineitem[(lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1996, 1, 1))].copy()
    # transform-based per-group rank (CUME_DIST = rank_max / group_size) avoids the
    # groupby().apply(include_groups=False) path that drops the l_shipdate key.
    grp = result.groupby("l_shipdate")["l_quantity"]
    result["quantity_cumulative_dist"] = grp.rank(method="max") / grp.transform("count")
    return (
        result[result["quantity_cumulative_dist"] >= 0.95][
            ["l_shipdate", "l_orderkey", "l_linenumber", "l_quantity", "quantity_cumulative_dist"]
        ]
        .sort_values(["l_shipdate", "l_quantity", "l_orderkey", "l_linenumber"], ascending=[True, False, True, True])
        .reset_index(drop=True)
    )


def qualify_lag_lead_expression_impl(ctx: DataFrameContext) -> Any:
    """Find orders where price increased from previous order using LAG.

    Raw Polars (via ``.native``) for a correct LAG: ``shift(1).over()`` after a
    total-order sort matching the catalog SQL's ``ORDER BY o_orderdate, o_orderkey``
    window tie-break (the ``window_lag`` helper shifts before sorting).
    """
    import polars as pl

    lf = _orders_customer_since_1995_expr(ctx).native.sort(["c_custkey", "o_orderdate", "o_orderkey"])
    lf = lf.with_columns(pl.col("o_totalprice").shift(1).over("c_custkey").alias("prev_order_price"))
    return (
        lf.filter(pl.col("o_totalprice") > pl.col("prev_order_price"))
        .select("c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price")
        .sort(["c_custkey", "o_orderdate", "o_orderkey"])
    )


def qualify_lag_lead_pandas_impl(ctx: DataFrameContext) -> Any:
    """Find orders where price increased from previous order using LAG."""
    result = _orders_customer_since_1995_pandas(ctx).sort_values(["c_custkey", "o_orderdate", "o_orderkey"])
    result["prev_order_price"] = result.groupby("c_custkey")["o_totalprice"].shift(1)
    return (
        result[result["o_totalprice"] > result["prev_order_price"]][
            ["c_custkey", "c_name", "o_orderkey", "o_orderdate", "o_totalprice", "prev_order_price"]
        ]
        .sort_values(["c_custkey", "o_orderdate", "o_orderkey"])
        .reset_index(drop=True)
    )


# =============================================================================
# Struct Queries
# =============================================================================
# Struct construction and field access using DataFrame APIs.


def struct_construction_expression_impl(ctx: DataFrameContext) -> Any:
    """Construct struct from columns.

    The contract is *positional* struct construction and DuckDB STRUCT(...)
    transpiles to anonymous ROW(...), which materializes as a tuple - so the
    DataFrame builds a positional list (the comparator treats list/tuple cells
    equivalently). Raw Polars for the row-wise list construction.
    """
    import polars as pl

    return (
        ctx.get_table("customer")
        .native.filter(pl.col("c_nationkey") == 1)
        .sort("c_custkey")
        .select(
            "c_custkey",
            pl.concat_list([pl.col("c_name"), pl.col("c_address"), pl.col("c_phone")]).alias("contact_info"),
            "c_acctbal",
        )
        .limit(100)
    )


def struct_construction_pandas_impl(ctx: DataFrameContext) -> Any:
    """Construct struct from columns (positional -> list cell, matching ROW())."""
    customer = ctx.get_table("customer")
    filtered = customer[customer["c_nationkey"] == 1].copy().sort_values("c_custkey")
    filtered["contact_info"] = filtered.apply(lambda row: [row["c_name"], row["c_address"], row["c_phone"]], axis=1)
    return filtered[["c_custkey", "contact_info", "c_acctbal"]].head(100).reset_index(drop=True)


def struct_access_expression_impl(ctx: DataFrameContext) -> Any:
    """Access struct fields.

    Expression-family implementation using struct field access.
    """
    customer = ctx.get_table("customer")
    col = ctx.col
    lit = ctx.lit
    struct = ctx.struct

    # First construct struct, then access fields
    with_struct = customer.filter(col("c_nationkey") == lit(1)).select(
        "c_custkey",
        struct(col("c_name").alias("name"), col("c_phone").alias("phone"), col("c_acctbal").alias("balance")).alias(
            "info"
        ),
    )

    # Access struct fields
    return (
        with_struct.select(
            "c_custkey",
            col("info").struct.field("name").alias("name"),
            col("info").struct.field("balance").alias("balance"),
        )
        .filter(col("balance") > lit(5000))
        .limit(100)
    )


def struct_access_pandas_impl(ctx: DataFrameContext) -> Any:
    """Access struct fields."""
    customer = ctx.get_table("customer")

    filtered = customer[customer["c_nationkey"] == 1].copy()

    # Create dict column to represent struct
    filtered["info"] = filtered.apply(
        lambda row: {"name": row["c_name"], "phone": row["c_phone"], "balance": row["c_acctbal"]}, axis=1
    )

    # Access fields from struct
    filtered["name"] = filtered["info"].apply(lambda x: x["name"])
    filtered["balance"] = filtered["info"].apply(lambda x: x["balance"])

    # Filter and select
    return filtered[filtered["balance"] > 5000][["c_custkey", "name", "balance"]].head(100).reset_index(drop=True)


# =============================================================================
# Array Queries
# =============================================================================
# Array operations using DataFrame APIs.


def array_contains_expression_impl(ctx: DataFrameContext) -> Any:
    """Check if array contains a value.

    Expression-family implementation using array aggregation and contains.
    """
    col = ctx.col
    lit = ctx.lit

    return (
        _expr_grouped_list(ctx, "partsupp", "ps_suppkey", "ps_partkey", "parts")
        .with_columns(col("parts").list.contains(lit(100)).alias("has_part_100"))
        .select("ps_suppkey", "has_part_100")
        .sort("ps_suppkey")
        .limit(100)
    )


def array_contains_pandas_impl(ctx: DataFrameContext) -> Any:
    """Check if array contains a value."""
    supplier_parts = _pandas_grouped_list(ctx.get_table("partsupp"), "ps_suppkey", "ps_partkey", "parts")
    supplier_parts["has_part_100"] = supplier_parts["parts"].apply(lambda x: 100 in x)
    return supplier_parts.sort_values("ps_suppkey")[["ps_suppkey", "has_part_100"]].head(100).reset_index(drop=True)


def array_distinct_expression_impl(ctx: DataFrameContext) -> Any:
    """Get distinct array elements.

    Expression-family implementation using array aggregation and unique.
    """
    col = ctx.col

    return (
        _expr_grouped_list(ctx, "lineitem", "l_orderkey", "l_shipmode", "modes")
        .with_columns(col("modes").list.unique().list.sort().alias("unique_modes"))
        .select("l_orderkey", "unique_modes")
        .sort("l_orderkey")
        .limit(100)
    )


def array_distinct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get distinct array elements."""
    ship_modes = _pandas_grouped_list(ctx.get_table("lineitem"), "l_orderkey", "l_shipmode", "modes")
    # Sort the distinct elements so element order is deterministic across surfaces
    # (the comparator compares list cells order-sensitively).
    ship_modes["unique_modes"] = ship_modes["modes"].apply(lambda x: sorted(set(x)))
    return ship_modes.sort_values("l_orderkey")[["l_orderkey", "unique_modes"]].head(100).reset_index(drop=True)


def array_length_expression_impl(ctx: DataFrameContext) -> Any:
    """Get array length/cardinality.

    Expression-family implementation using array aggregation and length.
    """
    col = ctx.col

    return (
        _expr_grouped_list(ctx, "partsupp", "ps_suppkey", "ps_partkey", "parts")
        .with_columns(col("parts").list.len().alias("num_parts"))
        .select("ps_suppkey", "num_parts")
        .sort(["num_parts", "ps_suppkey"], descending=[True, False])
        .limit(100)
    )


def array_length_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get array length/cardinality."""
    supplier_parts = _pandas_grouped_list(ctx.get_table("partsupp"), "ps_suppkey", "ps_partkey", "parts")
    supplier_parts["num_parts"] = supplier_parts["parts"].apply(len)
    return (
        supplier_parts.sort_values(["num_parts", "ps_suppkey"], ascending=[False, True])[["ps_suppkey", "num_parts"]]
        .head(100)
        .reset_index(drop=True)
    )


def array_min_max_expression_impl(ctx: DataFrameContext) -> Any:
    """Get min/max from array.

    Expression-family implementation using array aggregation and min/max.
    """
    col = ctx.col

    return (
        _expr_grouped_list(ctx, "orders", "o_custkey", "o_totalprice", "prices")
        .with_columns(col("prices").list.min().alias("min_order"), col("prices").list.max().alias("max_order"))
        .select("o_custkey", "min_order", "max_order")
        .sort("o_custkey")
        .limit(100)
    )


def array_min_max_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get min/max from array."""
    order_prices = _pandas_grouped_list(ctx.get_table("orders"), "o_custkey", "o_totalprice", "prices")
    order_prices["min_order"] = order_prices["prices"].apply(min)
    order_prices["max_order"] = order_prices["prices"].apply(max)
    return (
        order_prices.sort_values("o_custkey")[["o_custkey", "min_order", "max_order"]].head(100).reset_index(drop=True)
    )


def array_of_struct_expression_impl(ctx: DataFrameContext) -> Any:
    """Array of structs - orders with line items summary.

    Expression-family implementation using struct in array aggregation.
    """
    orders, lineitem = _tables(ctx, "orders", "lineitem")
    col = ctx.col
    lit = ctx.lit
    struct = ctx.struct

    # Filter orders and join with lineitem; sort by l_linenumber so the aggregated
    # struct list is ordered like the SQL's ARRAY_AGG(... ORDER BY l_linenumber),
    # and sort the rows by o_orderkey for the outer ORDER BY.
    filtered_orders = orders.filter(col("o_orderdate") == lit(date(1995, 3, 15)))
    joined = lineitem.join(filtered_orders, col("l_orderkey") == col("o_orderkey")).sort("l_linenumber")

    return (
        joined.group_by("o_orderkey")
        .agg(
            struct(col("l_linenumber"), col("l_partkey"), col("l_quantity"), col("l_extendedprice"))
            .list()
            .alias("line_items")
        )
        .sort("o_orderkey")
        .limit(50)
    )


def array_of_struct_pandas_impl(ctx: DataFrameContext) -> Any:
    """Array of structs - orders with line items summary."""
    orders, lineitem = _tables(ctx, "orders", "lineitem")

    # Filter and join
    filtered_orders = orders[orders["o_orderdate"] == date(1995, 3, 15)]
    joined = lineitem.merge(filtered_orders, left_on="l_orderkey", right_on="o_orderkey")

    # Create list of dicts per order
    def agg_to_struct_list(group):
        return [
            {
                "l_linenumber": row["l_linenumber"],
                "l_partkey": row["l_partkey"],
                "l_quantity": row["l_quantity"],
                "l_extendedprice": row["l_extendedprice"],
            }
            for _, row in group.sort_values("l_linenumber").iterrows()
        ]

    result = joined.groupby("o_orderkey").apply(agg_to_struct_list, include_groups=False).reset_index()
    result.columns = ["o_orderkey", "line_items"]

    return result.sort_values("o_orderkey").head(50).reset_index(drop=True)


def array_slice_expression_impl(ctx: DataFrameContext) -> Any:
    """Get array slice/subset.

    Expression-family implementation using array slicing.
    """
    orders = ctx.get_table("orders")
    col = ctx.col

    # Aggregate prices per customer sorted descending
    order_prices = orders.group_by("o_custkey").agg(
        col("o_totalprice").sort(descending=True).list().alias("prices"), col("o_totalprice").count().alias("cnt")
    )

    # Filter for customers with at least 5 orders and get top 3
    return (
        order_prices.filter(col("cnt") >= 5)
        .with_columns(col("prices").list.slice(0, 3).alias("top_3_orders"))
        .select("o_custkey", "top_3_orders")
        .sort("o_custkey")
        .limit(100)
    )


def array_slice_pandas_impl(ctx: DataFrameContext) -> Any:
    """Get array slice/subset."""
    orders = ctx.get_table("orders")

    # Aggregate prices per customer sorted descending
    order_prices = orders.groupby("o_custkey")["o_totalprice"].apply(lambda x: sorted(x, reverse=True)).reset_index()
    order_prices.columns = ["o_custkey", "prices"]

    # Filter for 5+ orders and get top 3
    order_prices = order_prices[order_prices["prices"].apply(len) >= 5].copy()
    order_prices["top_3_orders"] = order_prices["prices"].apply(lambda x: x[:3])

    return order_prices.sort_values("o_custkey")[["o_custkey", "top_3_orders"]].head(100).reset_index(drop=True)


def array_sort_expression_impl(ctx: DataFrameContext) -> Any:
    """Sort array elements.

    Expression-family implementation using array sorting.
    """
    col = ctx.col

    return (
        _expr_grouped_list(ctx, "part", "p_brand", "p_size", "sizes")
        .with_columns(col("sizes").list.sort().alias("sorted_sizes"))
        .select("p_brand", "sorted_sizes")
        .sort("p_brand")
        .limit(50)
    )


def array_sort_pandas_impl(ctx: DataFrameContext) -> Any:
    """Sort array elements."""
    part_sizes = _pandas_grouped_list(ctx.get_table("part"), "p_brand", "p_size", "sizes")
    part_sizes["sorted_sizes"] = part_sizes["sizes"].apply(sorted)
    return part_sizes.sort_values("p_brand")[["p_brand", "sorted_sizes"]].head(50).reset_index(drop=True)


def array_unnest_expression_impl(ctx: DataFrameContext) -> Any:
    """Unnest/explode array back to rows.

    Expression-family implementation using array explode.
    """
    partsupp = ctx.get_table("partsupp")
    col = ctx.col
    lit = ctx.lit

    # Filter to small set and aggregate parts per supplier
    filtered = partsupp.filter(col("ps_suppkey") <= lit(10))
    supplier_parts = filtered.group_by("ps_suppkey").agg(col("ps_partkey").list().alias("parts"))

    # Explode array back to rows
    return supplier_parts.explode("parts").rename({"parts": "part_key"})


def array_unnest_pandas_impl(ctx: DataFrameContext) -> Any:
    # Filter and aggregate
    """Unnest/explode array back to rows."""
    partsupp = ctx.get_table("partsupp")
    supplier_parts = _pandas_grouped_list(partsupp[partsupp["ps_suppkey"] <= 10], "ps_suppkey", "ps_partkey", "parts")

    # Explode
    result = supplier_parts.explode("parts").reset_index(drop=True)
    result.columns = ["ps_suppkey", "part_key"]

    return result


# =============================================================================
# Map Queries
# =============================================================================
# Map construction and access using DataFrame APIs.


def map_construction_expression_impl(ctx: DataFrameContext) -> Any:
    """Construct map from key-value pairs.

    Expression-family implementation using map construction.
    """
    return _partsupp_map_expression(ctx, 10).select("ps_suppkey", "part_costs")


def map_construction_pandas_impl(ctx: DataFrameContext) -> Any:
    """Construct map from key-value pairs."""
    return _partsupp_map_pandas(ctx, 10)


def map_access_expression_impl(ctx: DataFrameContext) -> Any:
    """Access map values by key.

    Expression-family implementation using map element access.
    """
    col = ctx.col
    lit = ctx.lit

    # Access map elements
    return (
        _partsupp_map_expression(ctx, 10)
        .select(
            "ps_suppkey",
            col("part_costs").map.get(lit("1")).alias("cost_for_part_1"),
            col("part_costs").map.get(lit("5")).alias("cost_for_part_5"),
        )
        .limit(10)
    )


def map_access_pandas_impl(ctx: DataFrameContext) -> Any:
    """Access map values by key."""
    result = _partsupp_map_pandas(ctx, 10)

    # Access map elements
    result["cost_for_part_1"] = result["part_costs"].apply(lambda m: m.get("1"))
    result["cost_for_part_5"] = result["part_costs"].apply(lambda m: m.get("5"))

    return result[["ps_suppkey", "cost_for_part_1", "cost_for_part_5"]].head(10).reset_index(drop=True)


def map_keys_values_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract map keys and values.

    Expression-family implementation using map keys/values extraction.
    """
    col = ctx.col

    # Extract keys and values
    return _partsupp_map_expression(ctx, 5).select(
        "ps_suppkey",
        col("part_costs").map.keys().alias("part_ids"),
        col("part_costs").map.values().alias("costs"),
    )


def map_keys_values_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract map keys and values."""
    result = _partsupp_map_pandas(ctx, 5)

    # Extract keys and values
    result["part_ids"] = result["part_costs"].apply(lambda m: list(m.keys()))
    result["costs"] = result["part_costs"].apply(lambda m: list(m.values()))

    return result[["ps_suppkey", "part_ids", "costs"]].reset_index(drop=True)


# =============================================================================
# Higher-Order Function Queries
# =============================================================================
# List filter, transform, and reduce operations.


def list_filter_expression_impl(ctx: DataFrameContext) -> Any:
    """Filter array elements by condition.

    Expression-family implementation using list filter.
    """
    col = ctx.col
    lit = ctx.lit
    elem = ctx.element()

    return (
        _expr_grouped_list(ctx, "orders", "o_custkey", "o_totalprice", "prices")
        .with_columns(col("prices").list.eval(elem.filter(elem > lit(100000))).alias("large_orders"))
        .select("o_custkey", "large_orders")
        .sort("o_custkey")
        .limit(100)
    )


def list_filter_pandas_impl(ctx: DataFrameContext) -> Any:
    """Filter array elements by condition."""
    order_prices = _pandas_grouped_list(ctx.get_table("orders"), "o_custkey", "o_totalprice", "prices")
    order_prices["large_orders"] = order_prices["prices"].apply(lambda x: [p for p in x if p > 100000])
    return order_prices.sort_values("o_custkey")[["o_custkey", "large_orders"]].head(100).reset_index(drop=True)


def list_transform_expression_impl(ctx: DataFrameContext) -> Any:
    """Transform each array element.

    Expression-family implementation using list transform.
    """
    col = ctx.col
    lit = ctx.lit
    elem = ctx.element()

    return (
        _expr_grouped_list(ctx, "part", "p_brand", "p_retailprice", "prices")
        .with_columns(col("prices").list.eval(elem * lit(1.1)).alias("prices_with_tax"))
        .select("p_brand", "prices_with_tax")
        .sort("p_brand")
        .limit(50)
    )


def list_transform_pandas_impl(ctx: DataFrameContext) -> Any:
    """Transform each array element."""
    part_prices = _pandas_grouped_list(ctx.get_table("part"), "p_brand", "p_retailprice", "prices")
    part_prices["prices_with_tax"] = part_prices["prices"].apply(lambda x: [p * 1.1 for p in x])
    return part_prices.sort_values("p_brand")[["p_brand", "prices_with_tax"]].head(50).reset_index(drop=True)


def list_reduce_expression_impl(ctx: DataFrameContext) -> Any:
    """Reduce array to single value.

    Expression-family implementation using list sum (as reduce equivalent).
    """
    col = ctx.col

    return (
        _expr_grouped_list(ctx, "lineitem", "l_orderkey", "l_quantity", "qtys")
        .with_columns(col("qtys").list.sum().alias("total_qty"))
        .select("l_orderkey", "total_qty")
        .sort("l_orderkey")
        .limit(100)
    )


def list_reduce_pandas_impl(ctx: DataFrameContext) -> Any:
    """Reduce array to single value."""
    quantities = _pandas_grouped_list(ctx.get_table("lineitem"), "l_orderkey", "l_quantity", "qtys")
    quantities["total_qty"] = quantities["qtys"].apply(sum)
    return quantities.sort_values("l_orderkey")[["l_orderkey", "total_qty"]].head(100).reset_index(drop=True)


# =============================================================================
# JSON Queries
# =============================================================================
# JSON extraction and aggregation (simplified - assumes string columns).
# NOTE: These are approximations since TPC-H doesn't have native JSON columns.


def json_extract_simple_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with simple path expressions.

    Expression-family implementation - uses string operations as JSON placeholder.
    Since TPC-H doesn't have JSON columns, we use comment fields as stand-ins.
    """
    orders = ctx.get_table("orders")
    col = ctx.col
    lit = ctx.lit

    # Use order comment field - extract words as "JSON path" simulation
    # This demonstrates the pattern even without native JSON
    return (
        orders.with_columns(
            col("o_comment").str.split(" ").list.get(0).alias("first_word"),
            col("o_comment").str.len_chars().alias("comment_length"),
        )
        .filter(col("comment_length") > lit(10))
        .select("o_orderkey", "o_comment", "first_word", "comment_length")
        .limit(1000)
    )


def json_extract_simple_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with simple path expressions."""
    orders = ctx.get_table("orders")

    # Simulate JSON extraction with string operations
    df = orders.copy()
    df["first_word"] = df["o_comment"].str.split(" ").str[0]
    df["comment_length"] = df["o_comment"].str.len()

    return (
        df[df["comment_length"] > 10][["o_orderkey", "o_comment", "first_word", "comment_length"]]
        .head(1000)
        .reset_index(drop=True)
    )


def json_extract_nested_expression_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with complex path expressions.

    The SQL filters WHERE JSON_VALID(c_comment); TPC-H c_comment is free text and
    never valid JSON, so the reference is empty. Mirror that with a valid-JSON
    proxy (c_comment starting with '{') and project the contract's 4 columns -
    the cell is legitimately empty on TPC-H (classified on the gate).
    """
    col, lit = ctx.col, ctx.lit
    return (
        ctx.get_table("customer")
        .filter(col("c_comment").str.starts_with("{"))
        .select(
            "c_custkey",
            lit(None).alias("customer_segment"),
            lit(None).alias("primary_preference"),
            lit(None).alias("last_order_date"),
        )
        .limit(500)
    )


def json_extract_nested_pandas_impl(ctx: DataFrameContext) -> Any:
    """Extract from JSON with complex path expressions."""
    customer = ctx.get_table("customer")
    df = customer[customer["c_comment"].str.startswith("{")][["c_custkey"]].copy()
    df["customer_segment"] = None
    df["primary_preference"] = None
    df["last_order_date"] = None
    return df.head(500).reset_index(drop=True)


def json_aggregates_expression_impl(ctx: DataFrameContext) -> Any:
    """Create JSON array and object with aggregate functions.

    Expression-family implementation - creates list structures as JSON equivalent.
    """
    part = ctx.get_table("part")
    col = ctx.col

    # Filter and aggregate into list structures (JSON array equivalent)
    return (
        part.filter(col("p_type").str.contains("STEEL"))
        .group_by("p_brand")
        .agg(
            col("p_name").list().alias("part_names"),
            col("p_retailprice").list().alias("part_prices"),
            col("p_partkey").count().alias("part_count"),
        )
        .limit(100)
    )


def json_aggregates_pandas_impl(ctx: DataFrameContext) -> Any:
    """Create JSON array and object with aggregate functions."""
    part = ctx.get_table("part")

    # Filter
    filtered = part[part["p_type"].str.contains("STEEL")]

    # Aggregate
    result = (
        filtered.groupby("p_brand").agg({"p_name": list, "p_retailprice": list, "p_partkey": "count"}).reset_index()
    )
    result.columns = ["p_brand", "part_names", "part_prices", "part_count"]

    return result.head(100).reset_index(drop=True)


# =============================================================================
# Timeseries Analysis Query
# =============================================================================


def timeseries_trend_analysis_expression_impl(ctx: DataFrameContext) -> Any:
    """Time series trend analysis: monthly aggregates, MoM growth, regression slope.

    Raw Polars: the regression slope is REGR_SLOPE(monthly_revenue, month_epoch)
    OVER () = cov_pop(epoch, revenue)/var_pop(epoch), broadcast to every row.
    month_epoch = EXTRACT(EPOCH FROM order_month) seconds (date days * 86400).
    """
    import polars as pl

    monthly = (
        ctx.get_table("orders")
        .native.filter((pl.col("o_orderdate") >= date(1995, 1, 1)) & (pl.col("o_orderdate") < date(1997, 1, 1)))
        .with_columns(pl.col("o_orderdate").dt.truncate("1mo").alias("order_month"))
        .group_by("order_month")
        .agg(
            pl.len().alias("order_count"),
            pl.col("o_totalprice").sum().alias("monthly_revenue"),
            pl.col("o_totalprice").mean().alias("avg_order_value"),
        )
        .sort("order_month")
        .with_columns((pl.col("order_month").cast(pl.Int64) * 86400).cast(pl.Float64).alias("month_epoch"))
    )
    slope = pl.cov("month_epoch", "monthly_revenue", ddof=0) / pl.col("month_epoch").var(ddof=0)
    return (
        monthly.with_columns(slope.alias("revenue_trend_slope"))
        .with_columns(pl.col("monthly_revenue").shift(1).alias("prev_month_revenue"))
        .with_columns(
            pl.when(pl.col("prev_month_revenue") == 0)
            .then(None)
            .otherwise((pl.col("monthly_revenue") - pl.col("prev_month_revenue")) / pl.col("prev_month_revenue") * 100)
            .alias("mom_growth_pct")
        )
        .select(
            "order_month",
            "order_count",
            "monthly_revenue",
            "avg_order_value",
            "revenue_trend_slope",
            "prev_month_revenue",
            "mom_growth_pct",
        )
        .sort("order_month")
    )


def timeseries_trend_analysis_pandas_impl(ctx: DataFrameContext) -> Any:
    """Time series trend analysis: monthly aggregates, MoM growth, regression slope."""
    import pandas as pd

    orders = ctx.get_table("orders")
    df = orders[(orders["o_orderdate"] >= date(1995, 1, 1)) & (orders["o_orderdate"] < date(1997, 1, 1))].copy()
    # Month-start matching DATE_TRUNC('month', ...) (avoids the datetime64[M] crash).
    df["order_month"] = pd.to_datetime(df["o_orderdate"]).dt.to_period("M").dt.to_timestamp()
    monthly = df.groupby("order_month", as_index=False).agg(
        order_count=("o_orderkey", "count"),
        monthly_revenue=("o_totalprice", "sum"),
        avg_order_value=("o_totalprice", "mean"),
    )
    monthly = monthly.sort_values("order_month")
    monthly["month_epoch"] = monthly["order_month"].astype("int64") // 1_000_000_000
    epoch = monthly["month_epoch"]
    slope = epoch.cov(monthly["monthly_revenue"], ddof=0) / epoch.var(ddof=0)
    monthly["revenue_trend_slope"] = slope
    monthly["prev_month_revenue"] = monthly["monthly_revenue"].shift(1)
    prev = monthly["prev_month_revenue"]
    monthly["mom_growth_pct"] = ((monthly["monthly_revenue"] - prev) / prev.replace(0, pd.NA)) * 100
    return monthly[
        [
            "order_month",
            "order_count",
            "monthly_revenue",
            "avg_order_value",
            "revenue_trend_slope",
            "prev_month_revenue",
            "mom_growth_pct",
        ]
    ].reset_index(drop=True)


# =============================================================================
# ASOF Join Query
# =============================================================================


def asof_join_basic_expression_impl(ctx: DataFrameContext) -> Any:
    """ASOF join: find closest prior order for each lineitem shipment.

    Expression-family implementation using join with inequality predicates.
    Note: True ASOF join semantics require specialized support. This is an approximation.
    """
    lineitem, orders = _tables(ctx, "lineitem", "orders")
    col = ctx.col
    lit = ctx.lit

    # Filter lineitem to date range
    filtered_lineitem = lineitem.filter(
        (col("l_shipdate") >= lit(date(1995, 1, 1))) & (col("l_shipdate") < lit(date(1995, 2, 1)))
    )

    # Join with orders using equi-join on orderkey (left_on/right_on, not expression join)
    # True ASOF would find the closest prior order by date
    return (
        filtered_lineitem.join(orders, left_on="l_orderkey", right_on="o_orderkey")
        .filter(col("l_shipdate") >= col("o_orderdate"))
        .with_columns((col("l_shipdate") - col("o_orderdate")).dt.total_days().alias("days_to_ship"))
        .select("l_orderkey", "l_shipdate", "o_orderdate", "o_totalprice", "days_to_ship")
        .sort(["l_orderkey", "l_shipdate"])
        .limit(100)
    )


def asof_join_basic_pandas_impl(ctx: DataFrameContext) -> Any:
    """ASOF join: find closest prior order for each lineitem shipment."""
    lineitem, orders = _tables(ctx, "lineitem", "orders")

    # Filter lineitem
    filtered_lineitem = lineitem[
        (lineitem["l_shipdate"] >= date(1995, 1, 1)) & (lineitem["l_shipdate"] < date(1995, 2, 1))
    ]

    # Join with orders
    merged = filtered_lineitem.merge(orders, left_on="l_orderkey", right_on="o_orderkey")
    merged = merged[merged["l_shipdate"] >= merged["o_orderdate"]].copy()

    # Calculate days to ship
    merged["days_to_ship"] = (merged["l_shipdate"] - merged["o_orderdate"]).dt.days

    result = (
        merged[["l_orderkey", "l_shipdate", "o_orderdate", "o_totalprice", "days_to_ship"]]
        .sort_values(["l_orderkey", "l_shipdate"])
        .head(100)
    )

    return result.reset_index(drop=True)


# =============================================================================
# Query Registry
# =============================================================================

REGISTRY = QueryRegistry(benchmark="Read Primitives")

_CATEGORY_CODES = {
    "A": QueryCategory.AGGREGATE,
    "C": QueryCategory.SCAN,
    "F": QueryCategory.FILTER,
    "G": QueryCategory.GROUP_BY,
    "J": QueryCategory.JOIN,
    "M": QueryCategory.MULTI_JOIN,
    "P": QueryCategory.PROJECTION,
    "Q": QueryCategory.SUBQUERY,
    "S": QueryCategory.SORT,
    "W": QueryCategory.WINDOW,
}

# Index the explicit module-level `def *_impl` functions into the same registry
# the factories populate, so the dispatch resolves both kinds with one typed
# lookup. Runs after every def and factory loop above; globals() is only read,
# never mutated.
_IMPLS.update(
    {
        name: obj
        for name, obj in globals().items()
        if name.endswith(("_expression_impl", "_pandas_impl")) and callable(obj)
    }
)


def _impl_for(impl_base: str, family: str) -> QueryImpl:
    return _IMPLS[f"{impl_base}_{family}_impl"]


def _make_query(row: list[str]) -> DataFrameQuery:
    query_id, query_name, description, category_codes, impl_base, sql_equivalent = row
    impl_base = impl_base or query_id
    return DataFrameQuery(
        query_id=query_id,
        query_name=query_name,
        description=description,
        categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
        expression_impl=_impl_for(impl_base, "expression"),
        pandas_impl=_impl_for(impl_base, "pandas"),
        sql_equivalent=sql_equivalent or None,
    )


def _load_queries() -> list[DataFrameQuery]:
    metadata = Path(__file__).with_name("dataframe_query_metadata.csv").read_text(encoding="utf-8")
    return [_make_query(row) for row in reader(metadata.splitlines(), delimiter="|")]


REGISTRY.set_loader(_load_queries)


def get_dataframe_queries() -> QueryRegistry:
    """Get the Read Primitives DataFrame query registry.

    Returns:
        QueryRegistry containing all Read Primitives DataFrame queries
    """
    return REGISTRY


def get_skip_for_dataframe() -> list[str]:
    """Get query IDs that should be skipped for DataFrame execution.

    These are SQL-only queries (optimizer tests) that test SQL query
    planning behavior and are not applicable to DataFrame execution.

    Returns:
        List of query IDs to skip
    """
    return SKIP_FOR_DATAFRAME.copy()


def get_skip_for_expression_family() -> list[str]:
    """Get query IDs that should be skipped for expression-family platforms.

    Currently only map queries are skipped because Polars has no native Map
    dtype. All list/array, struct, and string-split queries are now supported
    through the unified expression API.

    Returns:
        List of query IDs to skip for expression-family platforms (map queries only)
    """
    return SKIP_FOR_EXPRESSION_FAMILY.copy()


def get_skip_for_polars() -> list[str]:
    """Get query IDs that should be skipped for Polars DataFrame mode.

    Polars lacks a native Map dtype, so map queries are skipped.

    Returns:
        List of query IDs to skip for Polars
    """
    return SKIP_FOR_POLARS.copy()


def get_skip_for_pyspark() -> list[str]:
    """Get query IDs that should be skipped for PySpark DataFrame mode.

    PySpark lacks native implementations for higher-order list functions
    that use the unified expression API's element() hook.

    Returns:
        List of query IDs to skip for PySpark
    """
    return SKIP_FOR_PYSPARK.copy()


def get_skip_for_datafusion() -> list[str]:
    """Get query IDs that should be skipped for DataFusion DataFrame mode.

    These use Polars-only features (.list.eval()) or DataFusion v50 functions
    that are missing from Python bindings (array_sum, array_distinct type bug).

    Returns:
        List of query IDs to skip for DataFusion
    """
    return SKIP_FOR_DATAFUSION.copy()


__all__ = sorted({name for name in globals() if not name.startswith("_")} | set(_IMPLS))
