"""NL2SQL query definitions and management.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NL2SQLQueryCategory(Enum):
    """Categories of NL2SQL queries."""

    AGGREGATION = "aggregation"
    FILTERING = "filtering"
    JOINING = "joining"
    GROUPING = "grouping"
    SORTING = "sorting"
    WINDOW = "window"
    SUBQUERY = "subquery"
    DATE_TIME = "date_time"
    STRING_MANIPULATION = "string_manipulation"
    COMPLEX = "complex"


class QueryDifficulty(Enum):
    """Difficulty levels for NL2SQL queries."""

    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


@dataclass
class NL2SQLQuery:
    """A natural language to SQL test case."""

    query_id: str
    natural_language: str
    expected_sql: str
    category: NL2SQLQueryCategory
    difficulty: QueryDifficulty
    description: str = ""
    schema_context: str = ""
    expected_columns: list[str] = field(default_factory=list)
    expected_row_count: int | None = None
    validation_sql: str | None = None
    timeout_seconds: int = 60
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": self.query_id,
            "natural_language": self.natural_language,
            "expected_sql": self.expected_sql,
            "category": self.category.value,
            "difficulty": self.difficulty.value,
            "description": self.description,
            "schema_context": self.schema_context,
            "expected_columns": self.expected_columns,
            "expected_row_count": self.expected_row_count,
            "timeout_seconds": self.timeout_seconds,
            "tags": self.tags,
        }


# Default schema context for TPC-H style tables
TPCH_SCHEMA_CONTEXT = """
Tables:
- customer (c_custkey, c_name, c_address, c_nationkey, c_phone, c_acctbal, c_mktsegment, c_comment)
- orders (o_orderkey, o_custkey, o_orderstatus, o_totalprice, o_orderdate, o_orderpriority, o_clerk, o_shippriority, o_comment)
- lineitem (l_orderkey, l_partkey, l_suppkey, l_linenumber, l_quantity, l_extendedprice, l_discount, l_tax, l_returnflag, l_linestatus, l_shipdate, l_commitdate, l_receiptdate, l_shipinstruct, l_shipmode, l_comment)
- part (p_partkey, p_name, p_mfgr, p_brand, p_type, p_size, p_container, p_retailprice, p_comment)
- supplier (s_suppkey, s_name, s_address, s_nationkey, s_phone, s_acctbal, s_comment)
- nation (n_nationkey, n_name, n_regionkey, n_comment)
- region (r_regionkey, r_name, r_comment)
- partsupp (ps_partkey, ps_suppkey, ps_availqty, ps_supplycost, ps_comment)
"""


class NL2SQLQueryManager:
    """Manager for NL2SQL test queries."""

    def __init__(self) -> None:
        """Initialize the query manager."""
        self._queries: dict[str, NL2SQLQuery] = {}
        self._build_queries()

    def _build_queries(self) -> None:
        """Build the test query set."""
        # Easy - Simple Aggregation
        self._queries["agg_total_revenue"] = NL2SQLQuery(
            query_id="agg_total_revenue",
            natural_language="What is the total revenue from all orders?",
            expected_sql="""
SELECT SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
FROM lineitem
""",
            category=NL2SQLQueryCategory.AGGREGATION,
            difficulty=QueryDifficulty.EASY,
            description="Simple sum with calculated field",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["total_revenue"],
            tags=["sum", "calculation"],
        )

        self._queries["agg_order_count"] = NL2SQLQuery(
            query_id="agg_order_count",
            natural_language="How many orders are there in total?",
            expected_sql="""
SELECT COUNT(*) AS order_count
FROM orders
""",
            category=NL2SQLQueryCategory.AGGREGATION,
            difficulty=QueryDifficulty.EASY,
            description="Simple count",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["order_count"],
            tags=["count"],
        )

        self._queries["agg_avg_balance"] = NL2SQLQuery(
            query_id="agg_avg_balance",
            natural_language="What is the average customer account balance?",
            expected_sql="""
SELECT AVG(c_acctbal) AS avg_balance
FROM customer
""",
            category=NL2SQLQueryCategory.AGGREGATION,
            difficulty=QueryDifficulty.EASY,
            description="Simple average",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["avg_balance"],
            tags=["avg"],
        )

        # Easy - Simple Filtering
        self._queries["filter_high_value_orders"] = NL2SQLQuery(
            query_id="filter_high_value_orders",
            natural_language="Show all orders with total price greater than 100000",
            expected_sql="""
SELECT *
FROM orders
WHERE o_totalprice > 100000
""",
            category=NL2SQLQueryCategory.FILTERING,
            difficulty=QueryDifficulty.EASY,
            description="Simple numeric comparison filter",
            schema_context=TPCH_SCHEMA_CONTEXT,
            tags=["comparison", "numeric"],
        )

        self._queries["filter_urgent_orders"] = NL2SQLQuery(
            query_id="filter_urgent_orders",
            natural_language="Find all orders with urgent priority",
            expected_sql="""
SELECT *
FROM orders
WHERE o_orderpriority = '1-URGENT'
""",
            category=NL2SQLQueryCategory.FILTERING,
            difficulty=QueryDifficulty.EASY,
            description="Simple string equality filter",
            schema_context=TPCH_SCHEMA_CONTEXT,
            tags=["string", "equality"],
        )

        # Medium - Grouping
        self._queries["group_orders_by_status"] = NL2SQLQuery(
            query_id="group_orders_by_status",
            natural_language="Count orders grouped by order status",
            expected_sql="""
SELECT o_orderstatus, COUNT(*) AS order_count
FROM orders
GROUP BY o_orderstatus
ORDER BY order_count DESC
""",
            category=NL2SQLQueryCategory.GROUPING,
            difficulty=QueryDifficulty.MEDIUM,
            description="Group by with count and ordering",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["o_orderstatus", "order_count"],
            tags=["group by", "count", "order by"],
        )

        self._queries["group_revenue_by_segment"] = NL2SQLQuery(
            query_id="group_revenue_by_segment",
            natural_language="Calculate total revenue by customer market segment",
            expected_sql="""
SELECT c.c_mktsegment, SUM(l.l_extendedprice * (1 - l.l_discount)) AS total_revenue
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
JOIN lineitem l ON o.o_orderkey = l.l_orderkey
GROUP BY c.c_mktsegment
ORDER BY total_revenue DESC
""",
            category=NL2SQLQueryCategory.GROUPING,
            difficulty=QueryDifficulty.MEDIUM,
            description="Group by with joins and calculation",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["c_mktsegment", "total_revenue"],
            tags=["group by", "join", "sum", "calculation"],
        )

        # Medium - Simple Join
        self._queries["join_customer_orders"] = NL2SQLQuery(
            query_id="join_customer_orders",
            natural_language="List customer names with their order dates",
            expected_sql="""
SELECT c.c_name, o.o_orderdate
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
ORDER BY o.o_orderdate DESC
LIMIT 100
""",
            category=NL2SQLQueryCategory.JOINING,
            difficulty=QueryDifficulty.MEDIUM,
            description="Simple two-table join",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["c_name", "o_orderdate"],
            tags=["join", "order by"],
        )

        # Medium - Date Filtering
        self._queries["date_orders_year"] = NL2SQLQuery(
            query_id="date_orders_year",
            natural_language="Show all orders from 1995",
            expected_sql="""
SELECT *
FROM orders
WHERE EXTRACT(YEAR FROM o_orderdate) = 1995
""",
            category=NL2SQLQueryCategory.DATE_TIME,
            difficulty=QueryDifficulty.MEDIUM,
            description="Date extraction and filtering",
            schema_context=TPCH_SCHEMA_CONTEXT,
            tags=["date", "extract", "year"],
        )

        self._queries["date_recent_shipments"] = NL2SQLQuery(
            query_id="date_recent_shipments",
            natural_language="Find line items shipped in the last quarter of 1997",
            expected_sql="""
SELECT *
FROM lineitem
WHERE l_shipdate >= '1997-10-01' AND l_shipdate <= '1997-12-31'
""",
            category=NL2SQLQueryCategory.DATE_TIME,
            difficulty=QueryDifficulty.MEDIUM,
            description="Date range filtering",
            schema_context=TPCH_SCHEMA_CONTEXT,
            tags=["date", "range"],
        )

        # Hard - Multi-table Join
        self._queries["join_supplier_parts_nation"] = NL2SQLQuery(
            query_id="join_supplier_parts_nation",
            natural_language="List suppliers with their available parts and nation names",
            expected_sql="""
SELECT s.s_name, p.p_name, n.n_name, ps.ps_availqty
FROM supplier s
JOIN partsupp ps ON s.s_suppkey = ps.ps_suppkey
JOIN part p ON ps.ps_partkey = p.p_partkey
JOIN nation n ON s.s_nationkey = n.n_nationkey
ORDER BY s.s_name, p.p_name
LIMIT 100
""",
            category=NL2SQLQueryCategory.JOINING,
            difficulty=QueryDifficulty.HARD,
            description="Four-table join",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["s_name", "p_name", "n_name", "ps_availqty"],
            tags=["join", "multi-table"],
        )

        # Hard - Window Functions
        self._queries["window_customer_rank"] = NL2SQLQuery(
            query_id="window_customer_rank",
            natural_language="Rank customers by their account balance within each market segment",
            expected_sql="""
SELECT
    c_name,
    c_mktsegment,
    c_acctbal,
    RANK() OVER (PARTITION BY c_mktsegment ORDER BY c_acctbal DESC) AS balance_rank
FROM customer
""",
            category=NL2SQLQueryCategory.WINDOW,
            difficulty=QueryDifficulty.HARD,
            description="Window function with RANK and partitioning",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["c_name", "c_mktsegment", "c_acctbal", "balance_rank"],
            tags=["window", "rank", "partition"],
        )

        self._queries["window_running_total"] = NL2SQLQuery(
            query_id="window_running_total",
            natural_language="Calculate running total of order prices by customer",
            expected_sql="""
SELECT
    o.o_custkey,
    o.o_orderdate,
    o.o_totalprice,
    SUM(o.o_totalprice) OVER (
        PARTITION BY o.o_custkey
        ORDER BY o.o_orderdate
        ROWS UNBOUNDED PRECEDING
    ) AS running_total
FROM orders o
ORDER BY o.o_custkey, o.o_orderdate
""",
            category=NL2SQLQueryCategory.WINDOW,
            difficulty=QueryDifficulty.HARD,
            description="Running sum window function",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["o_custkey", "o_orderdate", "o_totalprice", "running_total"],
            tags=["window", "sum", "running total"],
        )

        # Hard - Subquery
        self._queries["subquery_above_avg_orders"] = NL2SQLQuery(
            query_id="subquery_above_avg_orders",
            natural_language="Find customers with order totals above the average order total",
            expected_sql="""
SELECT c.c_name, o.o_totalprice
FROM customer c
JOIN orders o ON c.c_custkey = o.o_custkey
WHERE o.o_totalprice > (SELECT AVG(o_totalprice) FROM orders)
ORDER BY o.o_totalprice DESC
""",
            category=NL2SQLQueryCategory.SUBQUERY,
            difficulty=QueryDifficulty.HARD,
            description="Scalar subquery comparison",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["c_name", "o_totalprice"],
            tags=["subquery", "comparison", "avg"],
        )

        self._queries["subquery_exists"] = NL2SQLQuery(
            query_id="subquery_exists",
            natural_language="Find suppliers who have supplied parts to customers in Germany",
            expected_sql="""
SELECT DISTINCT s.s_name, s.s_phone
FROM supplier s
WHERE EXISTS (
    SELECT 1
    FROM lineitem l
    JOIN orders o ON l.l_orderkey = o.o_orderkey
    JOIN customer c ON o.o_custkey = c.c_custkey
    JOIN nation n ON c.c_nationkey = n.n_nationkey
    WHERE l.l_suppkey = s.s_suppkey
    AND n.n_name = 'GERMANY'
)
ORDER BY s.s_name
""",
            category=NL2SQLQueryCategory.SUBQUERY,
            difficulty=QueryDifficulty.HARD,
            description="EXISTS subquery with multiple joins",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["s_name", "s_phone"],
            tags=["subquery", "exists", "join"],
        )

        # Expert - Complex Analytical
        self._queries["complex_top_customers"] = NL2SQLQuery(
            query_id="complex_top_customers",
            natural_language="Find the top 10 customers by total spending and show their percentage of total revenue",
            expected_sql="""
WITH customer_totals AS (
    SELECT
        c.c_custkey,
        c.c_name,
        SUM(l.l_extendedprice * (1 - l.l_discount)) AS customer_revenue
    FROM customer c
    JOIN orders o ON c.c_custkey = o.o_custkey
    JOIN lineitem l ON o.o_orderkey = l.l_orderkey
    GROUP BY c.c_custkey, c.c_name
),
total_revenue AS (
    SELECT SUM(customer_revenue) AS total FROM customer_totals
)
SELECT
    ct.c_name,
    ct.customer_revenue,
    ROUND(ct.customer_revenue * 100.0 / tr.total, 2) AS revenue_percentage
FROM customer_totals ct, total_revenue tr
ORDER BY ct.customer_revenue DESC
LIMIT 10
""",
            category=NL2SQLQueryCategory.COMPLEX,
            difficulty=QueryDifficulty.EXPERT,
            description="CTEs with percentage calculation",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["c_name", "customer_revenue", "revenue_percentage"],
            tags=["cte", "percentage", "top-n"],
        )

        self._queries["complex_yoy_growth"] = NL2SQLQuery(
            query_id="complex_yoy_growth",
            natural_language="Calculate year-over-year revenue growth by region",
            expected_sql="""
WITH yearly_revenue AS (
    SELECT
        r.r_name AS region,
        EXTRACT(YEAR FROM o.o_orderdate) AS year,
        SUM(l.l_extendedprice * (1 - l.l_discount)) AS revenue
    FROM region r
    JOIN nation n ON r.r_regionkey = n.n_regionkey
    JOIN customer c ON n.n_nationkey = c.c_nationkey
    JOIN orders o ON c.c_custkey = o.o_custkey
    JOIN lineitem l ON o.o_orderkey = l.l_orderkey
    GROUP BY r.r_name, EXTRACT(YEAR FROM o.o_orderdate)
)
SELECT
    region,
    year,
    revenue,
    LAG(revenue) OVER (PARTITION BY region ORDER BY year) AS prev_year_revenue,
    ROUND(
        (revenue - LAG(revenue) OVER (PARTITION BY region ORDER BY year)) * 100.0
        / NULLIF(LAG(revenue) OVER (PARTITION BY region ORDER BY year), 0),
        2
    ) AS yoy_growth_pct
FROM yearly_revenue
ORDER BY region, year
""",
            category=NL2SQLQueryCategory.COMPLEX,
            difficulty=QueryDifficulty.EXPERT,
            description="Year-over-year growth with LAG window function",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["region", "year", "revenue", "prev_year_revenue", "yoy_growth_pct"],
            tags=["cte", "window", "lag", "growth"],
        )

        self._queries["complex_market_basket"] = NL2SQLQuery(
            query_id="complex_market_basket",
            natural_language="Find pairs of parts that are frequently ordered together",
            expected_sql="""
WITH order_parts AS (
    SELECT DISTINCT l_orderkey, l_partkey
    FROM lineitem
)
SELECT
    p1.p_name AS part1,
    p2.p_name AS part2,
    COUNT(*) AS co_occurrence
FROM order_parts op1
JOIN order_parts op2 ON op1.l_orderkey = op2.l_orderkey AND op1.l_partkey < op2.l_partkey
JOIN part p1 ON op1.l_partkey = p1.p_partkey
JOIN part p2 ON op2.l_partkey = p2.p_partkey
GROUP BY p1.p_name, p2.p_name
HAVING COUNT(*) > 10
ORDER BY co_occurrence DESC
LIMIT 20
""",
            category=NL2SQLQueryCategory.COMPLEX,
            difficulty=QueryDifficulty.EXPERT,
            description="Market basket analysis with self-join",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["part1", "part2", "co_occurrence"],
            tags=["self-join", "market basket", "having"],
        )

        # String Manipulation
        self._queries["string_search"] = NL2SQLQuery(
            query_id="string_search",
            natural_language="Find all parts with 'BRASS' in their name",
            expected_sql="""
SELECT p_partkey, p_name, p_type
FROM part
WHERE p_name LIKE '%BRASS%'
""",
            category=NL2SQLQueryCategory.STRING_MANIPULATION,
            difficulty=QueryDifficulty.EASY,
            description="Simple LIKE pattern matching",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["p_partkey", "p_name", "p_type"],
            tags=["like", "pattern"],
        )

        self._queries["string_extract"] = NL2SQLQuery(
            query_id="string_extract",
            natural_language="Extract the first word from each customer name",
            expected_sql="""
SELECT
    c_custkey,
    c_name,
    SPLIT_PART(c_name, '#', 1) AS first_part
FROM customer
LIMIT 100
""",
            category=NL2SQLQueryCategory.STRING_MANIPULATION,
            difficulty=QueryDifficulty.MEDIUM,
            description="String splitting function",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["c_custkey", "c_name", "first_part"],
            tags=["string", "split"],
        )

        # Sorting
        self._queries["sort_multi_column"] = NL2SQLQuery(
            query_id="sort_multi_column",
            natural_language="List orders sorted by priority (descending) then by date (ascending)",
            expected_sql="""
SELECT o_orderkey, o_orderpriority, o_orderdate, o_totalprice
FROM orders
ORDER BY o_orderpriority DESC, o_orderdate ASC
LIMIT 100
""",
            category=NL2SQLQueryCategory.SORTING,
            difficulty=QueryDifficulty.EASY,
            description="Multi-column sorting",
            schema_context=TPCH_SCHEMA_CONTEXT,
            expected_columns=["o_orderkey", "o_orderpriority", "o_orderdate", "o_totalprice"],
            tags=["order by", "multi-column"],
        )

    def get_query(self, query_id: str) -> NL2SQLQuery | None:
        """Get a query by ID."""
        return self._queries.get(query_id)

    def get_all_queries(self) -> dict[str, NL2SQLQuery]:
        """Get all queries."""
        return self._queries.copy()

    def get_queries_by_category(self, category: NL2SQLQueryCategory) -> list[NL2SQLQuery]:
        """Get queries for a specific category."""
        return [q for q in self._queries.values() if q.category == category]

    def get_queries_by_difficulty(self, difficulty: QueryDifficulty) -> list[NL2SQLQuery]:
        """Get queries for a specific difficulty level."""
        return [q for q in self._queries.values() if q.difficulty == difficulty]

    def get_query_ids(self) -> list[str]:
        """Get all query IDs."""
        return list(self._queries.keys())

    def get_categories(self) -> list[NL2SQLQueryCategory]:
        """Get all query categories."""
        return list(NL2SQLQueryCategory)

    def get_difficulty_levels(self) -> list[QueryDifficulty]:
        """Get all difficulty levels."""
        return list(QueryDifficulty)

    def export_queries(self) -> dict[str, Any]:
        """Export all queries as a dictionary."""
        return {query_id: query.to_dict() for query_id, query in self._queries.items()}

    def get_queries_by_tag(self, tag: str) -> list[NL2SQLQuery]:
        """Get queries with a specific tag."""
        return [q for q in self._queries.values() if tag in q.tags]
