"""Star Schema Benchmark (SSB) query management.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.

Provides functionality to load and parameterize the 13 standard SSB queries, which are organized into 4 flights:

Flight 1 (Q1.1-Q1.3): Drill-down queries
Flight 2 (Q2.1-Q2.3): Drill-down queries with joins
Flight 3 (Q3.1-Q3.4): Drill-down queries with multiple joins
Flight 4 (Q4.1-Q4.3): Join queries with aggregation

For more information see:
- "Star Schema Benchmark" by O'Neil et al.
- https://www.cs.umb.edu/~poneil/StarSchemaB.PDF
"""

from typing import Any

from benchbox.core.query_manager import ParameterizedQueryManager


class SSBQueryManager(ParameterizedQueryManager):
    """Manager for Star Schema Benchmark queries."""

    def __init__(self) -> None:
        """Initialize SSB query manager."""
        self._queries = self._load_queries()

    def _load_queries(self) -> dict[str, str]:
        """Load all SSB queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        queries = {}

        # Flight 1: Drill-down queries
        queries["Q1.1"] = """
SELECT sum(lo_extendedprice*lo_discount) as revenue
FROM lineorder, date
WHERE lo_orderdate = d_datekey
  AND d_year = {year}
  AND lo_discount between {discount_min} and {discount_max}
  AND lo_quantity < {quantity};
"""

        queries["Q1.2"] = """
SELECT sum(lo_extendedprice*lo_discount) as revenue
FROM lineorder, date
WHERE lo_orderdate = d_datekey
  AND d_yearmonthnum = {year_month}
  AND lo_discount between {discount_min} and {discount_max}
  AND lo_quantity between {quantity_min} and {quantity_max};
"""

        queries["Q1.3"] = """
SELECT sum(lo_extendedprice*lo_discount) as revenue
FROM lineorder, date
WHERE lo_orderdate = d_datekey
  AND d_weeknuminyear = {week}
  AND d_year = {year}
  AND lo_discount between {discount_min} and {discount_max}
  AND lo_quantity between {quantity_min} and {quantity_max};
"""

        # Flight 2: Drill-down queries with joins
        queries["Q2.1"] = """
SELECT d_year, p_brand1, sum(lo_revenue) as revenue
FROM lineorder, date, part, supplier
WHERE lo_orderdate = d_datekey
  AND lo_partkey = p_partkey
  AND lo_suppkey = s_suppkey
  AND p_category = '{category}'
  AND s_region = '{region}'
GROUP BY d_year, p_brand1
ORDER BY d_year, p_brand1;
"""

        queries["Q2.2"] = """
SELECT d_year, p_brand1, sum(lo_revenue) as revenue
FROM lineorder, date, part, supplier
WHERE lo_orderdate = d_datekey
  AND lo_partkey = p_partkey
  AND lo_suppkey = s_suppkey
  AND p_brand1 between '{brand_min}' and '{brand_max}'
  AND s_region = '{region}'
GROUP BY d_year, p_brand1
ORDER BY d_year, p_brand1;
"""

        queries["Q2.3"] = """
SELECT d_year, p_brand1, sum(lo_revenue) as revenue
FROM lineorder, date, part, supplier
WHERE lo_orderdate = d_datekey
  AND lo_partkey = p_partkey
  AND lo_suppkey = s_suppkey
  AND p_brand1 = '{brand}'
  AND s_region = '{region}'
GROUP BY d_year, p_brand1
ORDER BY d_year, p_brand1;
"""

        # Flight 3: Drill-down queries with multiple joins
        queries["Q3.1"] = """
SELECT c_nation, s_nation, d_year, sum(lo_revenue) as revenue
FROM customer, lineorder, supplier, date
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_orderdate = d_datekey
  AND c_region = '{c_region}'
  AND s_region = '{s_region}'
  AND d_year >= {year_min} and d_year <= {year_max}
GROUP BY c_nation, s_nation, d_year
ORDER BY d_year asc, revenue desc;
"""

        queries["Q3.2"] = """
SELECT c_city, s_city, d_year, sum(lo_revenue) as revenue
FROM customer, lineorder, supplier, date
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_orderdate = d_datekey
  AND c_nation = '{c_nation}'
  AND s_nation = '{s_nation}'
  AND d_year >= {year_min} and d_year <= {year_max}
GROUP BY c_city, s_city, d_year
ORDER BY d_year asc, revenue desc;
"""

        queries["Q3.3"] = """
SELECT c_city, s_city, d_year, sum(lo_revenue) as revenue
FROM customer, lineorder, supplier, date
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_orderdate = d_datekey
  AND (c_city='{c_city1}' or c_city='{c_city2}')
  AND (s_city='{s_city1}' or s_city='{s_city2}')
  AND d_year >= {year_min} and d_year <= {year_max}
GROUP BY c_city, s_city, d_year
ORDER BY d_year asc, revenue desc;
"""

        queries["Q3.4"] = """
SELECT c_city, s_city, d_year, sum(lo_revenue) as revenue
FROM customer, lineorder, supplier, date
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_orderdate = d_datekey
  AND (c_city='{c_city1}' or c_city='{c_city2}')
  AND (s_city='{s_city1}' or s_city='{s_city2}')
  AND d_yearmonth = '{year_month}'
GROUP BY c_city, s_city, d_year
ORDER BY d_year asc, revenue desc;
"""

        # Flight 4: Join queries with aggregation
        queries["Q4.1"] = """
SELECT d_year, c_nation, sum(lo_revenue - lo_supplycost) as profit
FROM date, customer, supplier, part, lineorder
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_partkey = p_partkey
  AND lo_orderdate = d_datekey
  AND c_region = '{region}'
  AND s_region = '{region}'
  AND (p_mfgr = '{mfgr1}' or p_mfgr = '{mfgr2}')
GROUP BY d_year, c_nation
ORDER BY d_year, c_nation;
"""

        queries["Q4.2"] = """
SELECT d_year, s_nation, p_category, sum(lo_revenue - lo_supplycost) as profit
FROM date, customer, supplier, part, lineorder
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_partkey = p_partkey
  AND lo_orderdate = d_datekey
  AND c_region = '{region}'
  AND s_region = '{region}'
  AND (d_year = {year1} or d_year = {year2})
  AND (p_mfgr = '{mfgr1}' or p_mfgr = '{mfgr2}')
GROUP BY d_year, s_nation, p_category
ORDER BY d_year, s_nation, p_category;
"""

        queries["Q4.3"] = """
SELECT d_year, s_city, p_brand1, sum(lo_revenue - lo_supplycost) as profit
FROM date, customer, supplier, part, lineorder
WHERE lo_custkey = c_custkey
  AND lo_suppkey = s_suppkey
  AND lo_partkey = p_partkey
  AND lo_orderdate = d_datekey
  AND c_region = '{region}'
  AND s_region = '{region}'
  AND (d_year = {year1} or d_year = {year2})
  AND p_category = '{category}'
GROUP BY d_year, s_city, p_brand1
ORDER BY d_year, s_city, p_brand1;
"""

        return queries

    def _generate_default_params(self, query_id: str) -> dict[str, Any]:
        """Generate default parameters for a query.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary of parameter names to default values
        """
        # Default parameters used in SSB specification
        defaults = {
            # Years
            "year": 1993,
            "year_min": 1992,
            "year_max": 1997,
            "year1": 1997,
            "year2": 1998,
            "year_month": 199401,  # January 1994
            "week": 6,
            # Discounts and quantities
            "discount_min": 1,
            "discount_max": 3,
            "quantity": 25,
            "quantity_min": 26,
            "quantity_max": 35,
            # Regions
            "region": "AMERICA",
            "c_region": "ASIA",
            "s_region": "ASIA",
            # Nations and cities
            "c_nation": "UNITED STATES",
            "s_nation": "UNITED STATES",
            "c_city1": "UNITED KI1",
            "c_city2": "UNITED KI5",
            "s_city1": "UNITED KI1",
            "s_city2": "UNITED KI5",
            # Parts and manufacturers
            "category": "MFGR#12",
            "brand": "MFGR#2221",
            "brand_min": "MFGR#2221",
            "brand_max": "MFGR#2228",
            "mfgr1": "MFGR#1",
            "mfgr2": "MFGR#2",
        }

        # The `year_month` placeholder is overloaded across two columns: Q1.2 filters
        # the NUMERIC d_yearmonthnum (199401), while Q3.4 filters the STRING
        # d_yearmonth column whose canonical SSB value is 'Dec1997' (e.g. month-name +
        # year, as emitted by the generator). Substituting the numeric default into
        # Q3.4 never matches a string yearmonth, so resolve it per query.
        if query_id == "Q3.4":
            defaults["year_month"] = "Dec1997"

        return defaults
