"""SSB DataFrame query implementations."""

from __future__ import annotations

from csv import reader
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

from .parameters import get_parameters
from .registry import register_query

_JOIN_KEYS = {
    "date": ("lo_orderdate", "d_datekey"),
    "customer": ("lo_custkey", "c_custkey"),
    "supplier": ("lo_suppkey", "s_suppkey"),
    "part": ("lo_partkey", "p_partkey"),
}


def _items(value: str) -> list[str]:
    """Split a comma-separated token list into non-empty entries."""
    return [item for item in value.split(",") if item]


def _query_params(query_id: str) -> dict[str, Any]:
    """Return cached default parameter values for a query."""
    return get_parameters(query_id).params


def _expr_join(ctx: DataFrameContext, joins: str) -> Any:
    """Build an expression-table join chain from compact join descriptors."""
    frame = ctx.get_table("lineorder")
    for table in _items(joins):
        left_on, right_on = _JOIN_KEYS[table]
        frame = frame.join(ctx.get_table(table), left_on=left_on, right_on=right_on)
    return frame


def _pandas_join(ctx: DataFrameContext, joins: str) -> Any:
    """Build a pandas join chain from compact join descriptors."""
    frame = ctx.get_table("lineorder")
    for table in _items(joins):
        left_on, right_on = _JOIN_KEYS[table]
        frame = frame.merge(ctx.get_table(table), left_on=left_on, right_on=right_on)
    return frame


def _expr_filter(ctx: DataFrameContext, filters: str, params: dict[str, Any]) -> Any:
    """Apply compact filter descriptors against the expression query plan."""
    col, lit = ctx.col, ctx.lit
    condition = None
    for column, op, names in (item.split(":") for item in filters.split(";") if item):
        values = [params[name] for name in names.split(",")]
        if op == "eq":
            part = col(column) == lit(values[0])
        elif op == "lt":
            part = col(column) < lit(values[0])
        elif op == "ge":
            part = col(column) >= lit(values[0])
        elif op == "le":
            part = col(column) <= lit(values[0])
        elif op == "in2":
            part = (col(column) == lit(values[0])) | (col(column) == lit(values[1]))
        else:
            raise ValueError(f"Unsupported SSB filter operator: {op}")
        condition = part if condition is None else condition & part
    return condition


def _pandas_filter(frame: Any, filters: str, params: dict[str, Any]) -> Any:
    """Apply compact filter descriptors against a pandas merge chain."""
    mask = None
    for column, op, names in (item.split(":") for item in filters.split(";") if item):
        values = [params[name] for name in names.split(",")]
        if op == "eq":
            part = frame[column] == values[0]
        elif op == "lt":
            part = frame[column] < values[0]
        elif op == "ge":
            part = frame[column] >= values[0]
        elif op == "le":
            part = frame[column] <= values[0]
        elif op == "in2":
            part = (frame[column] == values[0]) | (frame[column] == values[1])
        else:
            raise ValueError(f"Unsupported SSB filter operator: {op}")
        mask = part if mask is None else mask & part
    return frame[mask]


def _sort_kwargs(sort: str, descending: str, *, pandas: bool) -> dict[str, Any]:
    """Convert compact sort metadata into backend-specific sort kwargs."""
    columns = _items(sort)
    flags = [item == "True" for item in _items(descending)]
    if pandas:
        return {"by": columns, "ascending": [not flag for flag in flags] if flags else True}
    return {"by": columns, "descending": flags} if flags else {"by": columns}


def _query_doc(query_id: str, family: str) -> str:
    """Build a short docstring for a generated query implementation."""
    descriptions = globals().get("_QUERY_DESCRIPTIONS", {})
    description = descriptions.get(query_id, "SSB DataFrame query.")
    family_label = "Expression" if family == "expression" else "Pandas"
    return f"SSB {query_id} ({family_label}): {description}\n\nGenerated implementation from compact query metadata."


def _make_expression_impl(spec: dict[str, str]) -> Any:
    def impl(ctx: DataFrameContext) -> Any:
        col = ctx.col
        filtered = _expr_join(ctx, spec["joins"]).filter(_expr_filter(ctx, spec["filters"], _query_params(spec["id"])))
        if spec["metric"] == "scalar_revenue":
            return filtered.select((col("lo_extendedprice") * col("lo_discount")).sum().alias("revenue"))
        metric = (
            (col("lo_revenue") - col("lo_supplycost")).sum().alias("profit")
            if spec["metric"] == "profit"
            else col("lo_revenue").sum().alias("revenue")
        )
        return (
            filtered.group_by(*_items(spec["group"]))
            .agg(metric)
            .sort(**_sort_kwargs(spec["sort"], spec["desc"], pandas=False))
        )

    impl.__name__ = f"{spec['stem']}_expression_impl"
    impl.__qualname__ = impl.__name__
    impl.__doc__ = _query_doc(spec["id"], "expression")
    return impl


def _make_pandas_impl(spec: dict[str, str]) -> Any:
    def impl(ctx: DataFrameContext) -> Any:
        import pandas as pd

        filtered = _pandas_filter(_pandas_join(ctx, spec["joins"]), spec["filters"], _query_params(spec["id"]))
        if spec["metric"] == "scalar_revenue":
            revenue = (filtered["lo_extendedprice"] * filtered["lo_discount"]).sum()
            return pd.DataFrame({"revenue": [revenue.compute() if hasattr(revenue, "compute") else revenue]})
        output, source = ("profit", "profit") if spec["metric"] == "profit" else ("revenue", "lo_revenue")
        if source == "profit":
            filtered = filtered.copy()
            filtered["profit"] = filtered["lo_revenue"] - filtered["lo_supplycost"]
        return (
            filtered.groupby(_items(spec["group"]), as_index=False)
            .agg(**{output: (source, "sum")})
            .sort_values(**_sort_kwargs(spec["sort"], spec["desc"], pandas=True))
        )

    impl.__name__ = f"{spec['stem']}_pandas_impl"
    impl.__qualname__ = impl.__name__
    impl.__doc__ = _query_doc(spec["id"], "pandas")
    return impl


_QUERY_SPECS = """\
Q1.1|q1_1|scalar_revenue|date|d_year:eq:year;lo_discount:ge:discount_min;lo_discount:le:discount_max;lo_quantity:lt:quantity|||
Q1.2|q1_2|scalar_revenue|date|d_yearmonthnum:eq:year_month;lo_discount:ge:discount_min;lo_discount:le:discount_max;lo_quantity:ge:quantity_min;lo_quantity:le:quantity_max|||
Q1.3|q1_3|scalar_revenue|date|d_weeknuminyear:eq:week;d_year:eq:year;lo_discount:ge:discount_min;lo_discount:le:discount_max;lo_quantity:ge:quantity_min;lo_quantity:le:quantity_max|||
Q2.1|q2_1|revenue|date,part,supplier|p_category:eq:category;s_region:eq:region|d_year,p_brand1|d_year,p_brand1|
Q2.2|q2_2|revenue|date,part,supplier|p_brand1:ge:brand_min;p_brand1:le:brand_max;s_region:eq:region|d_year,p_brand1|d_year,p_brand1|
Q2.3|q2_3|revenue|date,part,supplier|p_brand1:eq:brand;s_region:eq:region|d_year,p_brand1|d_year,p_brand1|
Q3.1|q3_1|revenue|customer,supplier,date|c_region:eq:c_region;s_region:eq:s_region;d_year:ge:year_min;d_year:le:year_max|c_nation,s_nation,d_year|d_year,revenue|False,True
Q3.2|q3_2|revenue|customer,supplier,date|c_nation:eq:c_nation;s_nation:eq:s_nation;d_year:ge:year_min;d_year:le:year_max|c_city,s_city,d_year|d_year,revenue|False,True
Q3.3|q3_3|revenue|customer,supplier,date|c_city:in2:c_city1,c_city2;s_city:in2:s_city1,s_city2;d_year:ge:year_min;d_year:le:year_max|c_city,s_city,d_year|d_year,revenue|False,True
Q3.4|q3_4|revenue|customer,supplier,date|c_city:in2:c_city1,c_city2;s_city:in2:s_city1,s_city2;d_yearmonth:eq:year_month|c_city,s_city,d_year|d_year,revenue|False,True
Q4.1|q4_1|profit|date,customer,supplier,part|c_region:eq:region;s_region:eq:region;p_mfgr:in2:mfgr1,mfgr2|d_year,c_nation|d_year,c_nation|
Q4.2|q4_2|profit|date,customer,supplier,part|c_region:eq:region;s_region:eq:region;d_year:in2:year1,year2;p_mfgr:in2:mfgr1,mfgr2|d_year,s_nation,p_category|d_year,s_nation,p_category|
Q4.3|q4_3|profit|date,customer,supplier,part|c_region:eq:region;s_region:eq:region;d_year:in2:year1,year2;p_category:eq:category|d_year,s_city,p_brand1|d_year,s_city,p_brand1|
"""

_SPECS = {}
for _row in reader(_QUERY_SPECS.splitlines(), delimiter="|"):
    _spec = dict(zip(("id", "stem", "metric", "joins", "filters", "group", "sort", "desc"), _row))
    _SPECS[_spec["id"]] = _spec
    globals()[f"{_spec['stem']}_expression_impl"] = _make_expression_impl(_spec)
    globals()[f"{_spec['stem']}_pandas_impl"] = _make_pandas_impl(_spec)

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "FI": QueryCategory.FILTER,
    "GB": QueryCategory.GROUP_BY,
    "JO": QueryCategory.JOIN,
    "MJ": QueryCategory.MULTI_JOIN,
    "SO": QueryCategory.SORT,
}

_QUERY_METADATA = """\
Q1.1|Revenue by Year|Revenue aggregation filtered by year, discount range, and quantity threshold|JO,FI,AG|q1_1
Q1.2|Revenue by Year-Month|Revenue drill-down from year to year-month with quantity range filter|JO,FI,AG|q1_2
Q1.3|Revenue by Week|Revenue drill-down from year-month to week with quantity range filter|JO,FI,AG|q1_3
Q2.1|Revenue by Year/Brand (Category)|Revenue by year and brand filtered by part category and supplier region|MJ,FI,GB,SO|q2_1
Q2.2|Revenue by Year/Brand (Brand Range)|Revenue by year and brand filtered by brand range and supplier region|MJ,FI,GB,SO|q2_2
Q2.3|Revenue by Year/Brand (Single Brand)|Revenue by year and brand filtered by single brand and supplier region|MJ,FI,GB,SO|q2_3
Q3.1|Revenue by Nation/Year|Revenue by customer/supplier nation and year filtered by region|MJ,FI,GB,SO|q3_1
Q3.2|Revenue by City/Year (Nation)|Revenue by city and year filtered by nation (drill-down from region)|MJ,FI,GB,SO|q3_2
Q3.3|Revenue by City/Year (City Pairs)|Revenue by city and year filtered by specific city pairs (OR conditions)|MJ,FI,GB,SO|q3_3
Q3.4|Revenue by City/Year-Month|Revenue by city filtered by city pairs and specific year-month|MJ,FI,GB,SO|q3_4
Q4.1|Profit by Year/Nation|Profit (revenue - supply cost) by year and nation filtered by region and manufacturer|MJ,FI,GB,SO|q4_1
Q4.2|Profit by Year/Nation/Category|Profit by year, supplier nation, and part category with year and manufacturer filters|MJ,FI,GB,SO|q4_2
Q4.3|Profit by Year/City/Brand|Profit by year, supplier city, and brand with category filter (deepest drill-down)|MJ,FI,GB,SO|q4_3
"""


_QUERY_DESCRIPTIONS = {
    query_id: description
    for query_id, _query_name, description, *_ in (row.split("|") for row in _QUERY_METADATA.splitlines())
}

for _spec in _SPECS.values():
    impl_name = f"{_spec['stem']}_expression_impl"
    pandas_impl_name = f"{_spec['stem']}_pandas_impl"
    globals()[impl_name].__doc__ = _query_doc(_spec["id"], "expression")
    globals()[pandas_impl_name].__doc__ = _query_doc(_spec["id"], "pandas")


def _impl_for(stem: str, family: str) -> Any:
    return globals()[f"{stem}_{family}_impl"]


def _register_all_queries() -> None:
    for query_id, query_name, description, category_codes, impl_stem in reader(
        _QUERY_METADATA.splitlines(), delimiter="|"
    ):
        register_query(
            DataFrameQuery(
                query_id=query_id,
                query_name=query_name,
                description=description,
                categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
                expression_impl=_impl_for(impl_stem, "expression"),
                pandas_impl=_impl_for(impl_stem, "pandas"),
            )
        )


_register_all_queries()
