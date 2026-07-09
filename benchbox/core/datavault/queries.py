"""Data Vault query definitions adapted from TPC-H.

This module provides 22 queries adapted from TPC-H to work with
the Data Vault 2.0 schema (Hub-Link-Satellite model).

Query parameters follow TPC-H specification for reproducible benchmarking.
Parameters can be generated deterministically based on seed and scale factor.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional, Union

import yaml

logger = logging.getLogger(__name__)


def _load_query_parameter_specs() -> dict[str, list[str]]:
    with (Path(__file__).with_name("query_parameter_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


# TPC-H reference data for parameter generation
_QUERY_PARAMETER_SPECS = _load_query_parameter_specs()
REGIONS = _QUERY_PARAMETER_SPECS["regions"]
NATIONS = _QUERY_PARAMETER_SPECS["nations"]
SEGMENTS = _QUERY_PARAMETER_SPECS["segments"]
TYPES_SYLLABLE1 = _QUERY_PARAMETER_SPECS["types_syllable1"]
TYPES_SYLLABLE2 = _QUERY_PARAMETER_SPECS["types_syllable2"]
TYPES_SYLLABLE3 = _QUERY_PARAMETER_SPECS["types_syllable3"]
CONTAINERS = _QUERY_PARAMETER_SPECS["containers"]
SHIPMODES = _QUERY_PARAMETER_SPECS["shipmodes"]
COLORS = _QUERY_PARAMETER_SPECS["colors"]
BRAND_NUMBERS = _QUERY_PARAMETER_SPECS["brand_numbers"]


@dataclass
class QueryParameters:
    """Parameters for a specific query execution."""

    query_id: int
    params: dict[str, Any]
    seed: Optional[int] = None
    scale_factor: float = 1.0

    def as_dict(self) -> dict[str, Any]:
        """Return the query parameters as a dictionary."""
        return self.params.copy()


class DataVaultParameterGenerator:
    """Generates TPC-H-compliant parameters for Data Vault queries.

    Parameters are generated deterministically based on seed and scale factor,
    following TPC-H specification 2.1.3 for substitution parameters.
    """

    def __init__(self, seed: Optional[int] = None, scale_factor: float = 1.0) -> None:
        """Initialize parameter generator.

        Args:
            seed: Random seed for reproducible parameter generation.
                  If None, uses current time.
            scale_factor: TPC-H scale factor (affects some parameter ranges).
        """
        self.scale_factor = scale_factor
        self._seed = seed if seed is not None else int(random.random() * 100000)
        self._rng = random.Random(self._seed)

    @property
    def seed(self) -> int:
        """Get the current seed."""
        return self._seed

    def _reset_rng(self, query_id: int, stream_id: int = 0) -> None:
        """Reset RNG with query-specific seed for reproducibility."""
        # Combine base seed, query_id, and stream_id for unique but reproducible params
        combined_seed = (self._seed * 7919 + query_id * 3037 + stream_id * 1009) % 2147483647
        self._rng.seed(combined_seed)

    def generate_parameters(self, query_id: int, stream_id: int = 0) -> QueryParameters:
        """Generate parameters for a specific query.

        Args:
            query_id: Query number (1-22)
            stream_id: Stream ID for multi-stream execution (affects randomization)

        Returns:
            QueryParameters containing all parameters for the query
        """
        self._reset_rng(query_id, stream_id)
        params = self._generate_query_params(query_id)
        return QueryParameters(query_id=query_id, params=params, seed=self._seed, scale_factor=self.scale_factor)

    def _generate_query_params(self, query_id: int) -> dict[str, Any]:
        """Generate parameters for a specific query ID."""
        generators = {
            1: self._q1_params,
            2: self._q2_params,
            3: self._q3_params,
            4: self._q4_params,
            5: self._q5_params,
            6: self._q6_params,
            7: self._q7_params,
            8: self._q8_params,
            9: self._q9_params,
            10: self._q10_params,
            11: self._q11_params,
            12: self._q12_params,
            13: self._q13_params,
            14: self._q14_params,
            15: self._q15_params,
            16: self._q16_params,
            17: self._q17_params,
            18: self._q18_params,
            19: self._q19_params,
            20: self._q20_params,
            21: self._q21_params,
            22: self._q22_params,
        }
        return generators.get(query_id, dict)()

    def _random_date(self, start_year: int, end_year: int) -> date:
        """Generate a random date within range."""
        start = date(start_year, 1, 1)
        end = date(end_year, 12, 31)
        delta = (end - start).days
        return start + timedelta(days=self._rng.randint(0, delta))

    def _q1_params(self) -> dict[str, Any]:
        """Q1: DELTA between 60 and 120 inclusive."""
        delta = self._rng.randint(60, 120)
        return {"delta": delta}

    def _q2_params(self) -> dict[str, Any]:
        """Q2: SIZE (1-50), TYPE suffix, REGION."""
        size = self._rng.randint(1, 50)
        type_suffix = self._rng.choice(TYPES_SYLLABLE3)
        region = self._rng.choice(REGIONS)
        return {"size": size, "type_suffix": type_suffix, "region": region}

    def _q3_params(self) -> dict[str, Any]:
        """Q3: SEGMENT, DATE (first 5 years of TPC-H data range)."""
        segment = self._rng.choice(SEGMENTS)
        # TPC-H dates range from 1992-01-01 to 1998-12-31
        # Q3 uses a date in 1995 (middle of range)
        dt = date(1995, self._rng.randint(1, 3), self._rng.randint(1, 28))
        return {"segment": segment, "date": dt.isoformat()}

    def _q4_params(self) -> dict[str, Any]:
        """Q4: DATE (any month in 1993-1997)."""
        year = self._rng.randint(1993, 1997)
        month = self._rng.randint(1, 10)  # Max month 10 to allow 3-month interval
        dt = date(year, month, 1)
        return {"date": dt.isoformat()}

    def _q5_params(self) -> dict[str, Any]:
        """Q5: REGION, DATE (first day of year in 1993-1997)."""
        region = self._rng.choice(REGIONS)
        year = self._rng.randint(1993, 1997)
        return {"region": region, "date": date(year, 1, 1).isoformat()}

    def _q6_params(self) -> dict[str, Any]:
        """Q6: DATE, DISCOUNT (0.02-0.09), QUANTITY (24-25)."""
        year = self._rng.randint(1993, 1997)
        discount = round(self._rng.uniform(0.02, 0.09), 2)
        quantity = self._rng.randint(24, 25)
        return {"date": date(year, 1, 1).isoformat(), "discount": discount, "quantity": quantity}

    def _q7_params(self) -> dict[str, Any]:
        """Q7: Two nations from TPC-H nation list."""
        nations = self._rng.sample(NATIONS, 2)
        return {"nation1": nations[0], "nation2": nations[1]}

    def _q8_params(self) -> dict[str, Any]:
        """Q8: NATION, REGION, TYPE (full type string)."""
        nation = self._rng.choice(NATIONS)
        region = self._rng.choice(REGIONS)
        part_type = f"{self._rng.choice(TYPES_SYLLABLE1)} {self._rng.choice(TYPES_SYLLABLE2)} {self._rng.choice(TYPES_SYLLABLE3)}"
        return {"nation": nation, "region": region, "type": part_type}

    def _q9_params(self) -> dict[str, Any]:
        """Q9: COLOR (any color from P_NAME generation)."""
        color = self._rng.choice(COLORS)
        return {"color": color}

    def _q10_params(self) -> dict[str, Any]:
        """Q10: DATE (first day of month in 1993-1995)."""
        year = self._rng.randint(1993, 1995)
        month = self._rng.randint(1, 10)  # Max month 10 for 3-month interval
        return {"date": date(year, month, 1).isoformat()}

    def _q11_params(self) -> dict[str, Any]:
        """Q11: NATION, FRACTION (0.0001/SF)."""
        nation = self._rng.choice(NATIONS)
        # Fraction is always 0.0001/SF per TPC-H spec
        fraction = 0.0001 / self.scale_factor
        return {"nation": nation, "fraction": fraction}

    def _q12_params(self) -> dict[str, Any]:
        """Q12: Two ship modes, DATE."""
        modes = self._rng.sample(SHIPMODES, 2)
        year = self._rng.randint(1993, 1997)
        return {"shipmode1": modes[0], "shipmode2": modes[1], "date": date(year, 1, 1).isoformat()}

    def _q13_params(self) -> dict[str, Any]:
        """Q13: WORD1, WORD2 for comment filtering."""
        words = ["special", "pending", "unusual", "express", "furious", "sly", "careful", "unusual"]
        word1 = self._rng.choice(words)
        word2 = self._rng.choice(["requests", "packages", "accounts", "deposits"])
        return {"word1": word1, "word2": word2}

    def _q14_params(self) -> dict[str, Any]:
        """Q14: DATE (first day of month in 1993-1997)."""
        year = self._rng.randint(1993, 1997)
        month = self._rng.randint(1, 12)
        return {"date": date(year, month, 1).isoformat()}

    def _q15_params(self) -> dict[str, Any]:
        """Q15: DATE (first day of month, with 3-month interval)."""
        year = self._rng.randint(1993, 1997)
        month = self._rng.randint(1, 10)  # Max month 10 for 3-month interval
        return {"date": date(year, month, 1).isoformat()}

    def _q16_params(self) -> dict[str, Any]:
        """Q16: BRAND, TYPE, SIZE list (8 sizes)."""
        # Brand to exclude (Brand#45 in default)
        brand = self._rng.choice(BRAND_NUMBERS)
        # Type prefix to exclude
        type_prefix = f"{self._rng.choice(TYPES_SYLLABLE2[:3])} {self._rng.choice(TYPES_SYLLABLE2)}"
        # 8 distinct sizes from 1-50
        sizes = sorted(self._rng.sample(range(1, 51), 8))
        return {"brand": brand, "type_prefix": type_prefix, "sizes": sizes}

    def _q17_params(self) -> dict[str, Any]:
        """Q17: BRAND, CONTAINER."""
        brand = self._rng.choice(BRAND_NUMBERS)
        container = self._rng.choice(CONTAINERS)
        return {"brand": brand, "container": container}

    def _q18_params(self) -> dict[str, Any]:
        """Q18: QUANTITY threshold (312-315)."""
        quantity = self._rng.randint(312, 315)
        return {"quantity": quantity}

    def _q19_params(self) -> dict[str, Any]:
        """Q19: Three brands, three quantities."""
        brands = self._rng.sample(BRAND_NUMBERS, 3)
        quantities = [self._rng.randint(1, 10), self._rng.randint(10, 20), self._rng.randint(20, 30)]
        return {
            "brand1": brands[0],
            "brand2": brands[1],
            "brand3": brands[2],
            "quantity1": quantities[0],
            "quantity2": quantities[1],
            "quantity3": quantities[2],
        }

    def _q20_params(self) -> dict[str, Any]:
        """Q20: COLOR, DATE, NATION."""
        color = self._rng.choice(COLORS)
        year = self._rng.randint(1993, 1997)
        nation = self._rng.choice(NATIONS)
        return {"color": color, "date": date(year, 1, 1).isoformat(), "nation": nation}

    def _q21_params(self) -> dict[str, Any]:
        """Q21: NATION."""
        nation = self._rng.choice(NATIONS)
        return {"nation": nation}

    def _q22_params(self) -> dict[str, Any]:
        """Q22: 7 distinct country codes (2-digit phone prefixes)."""
        # TPC-H uses country codes 10-34 (mapped to 25 nations)
        codes = sorted(self._rng.sample(range(10, 35), 7))
        return {"country_codes": [str(c) for c in codes]}


class DataVaultQueryManager:
    """Manages Data Vault queries adapted from TPC-H.

    All 22 TPC-H queries are adapted to work with the Data Vault schema,
    using Hub→Satellite→Link join patterns and filtering for current
    records (LOAD_END_DTS IS NULL).

    Queries support parameter substitution via :param_name placeholders.
    Use get_parameterized_query() for parameterized execution.
    """

    # Query templates with :param_name placeholders
    # Each query uses Hub-Link-Satellite joins with current record filtering
    QUERY_TEMPLATES: dict[int, str] = {
        # Q1: Pricing Summary Report (LINEITEM aggregation)
        # Parameters: :delta (days to subtract from 1998-12-01)
        1: """
SELECT
    sl.l_returnflag,
    sl.l_linestatus,
    SUM(sl.l_quantity) AS sum_qty,
    SUM(sl.l_extendedprice) AS sum_base_price,
    SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS sum_disc_price,
    SUM(sl.l_extendedprice * (1 - sl.l_discount) * (1 + sl.l_tax)) AS sum_charge,
    AVG(sl.l_quantity) AS avg_qty,
    AVG(sl.l_extendedprice) AS avg_price,
    AVG(sl.l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link
    AND sl.load_end_dts IS NULL
WHERE sl.l_shipdate <= DATE '1998-12-01' - INTERVAL ':delta days'
GROUP BY sl.l_returnflag, sl.l_linestatus
ORDER BY sl.l_returnflag, sl.l_linestatus
        """,
        # Q2: Minimum Cost Supplier
        # Parameters: :size, :type_suffix, :region
        2: """
SELECT
    ss.s_acctbal,
    ss.s_name,
    sn.n_name,
    hp.p_partkey,
    sp.p_mfgr,
    ss.s_address,
    ss.s_phone,
    ss.s_comment
FROM hub_part hp
JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
JOIN link_part_supplier lps ON hp.hk_part = lps.hk_part
JOIN hub_supplier hs ON lps.hk_supplier = hs.hk_supplier
JOIN sat_supplier ss ON hs.hk_supplier = ss.hk_supplier AND ss.load_end_dts IS NULL
JOIN sat_partsupp sps ON lps.hk_part_supplier = sps.hk_part_supplier AND sps.load_end_dts IS NULL
JOIN link_supplier_nation lsn ON hs.hk_supplier = lsn.hk_supplier
JOIN hub_nation hn ON lsn.hk_nation = hn.hk_nation
JOIN sat_nation sn ON hn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
JOIN link_nation_region lnr ON hn.hk_nation = lnr.hk_nation
JOIN hub_region hr ON lnr.hk_region = hr.hk_region
JOIN sat_region sr ON hr.hk_region = sr.hk_region AND sr.load_end_dts IS NULL
WHERE sp.p_size = :size
  AND sp.p_type LIKE '%:type_suffix'
  AND sr.r_name = ':region'
  AND sps.ps_supplycost = (
      SELECT MIN(sps2.ps_supplycost)
      FROM link_part_supplier lps2
      JOIN sat_partsupp sps2 ON lps2.hk_part_supplier = sps2.hk_part_supplier AND sps2.load_end_dts IS NULL
      JOIN hub_supplier hs2 ON lps2.hk_supplier = hs2.hk_supplier
      JOIN link_supplier_nation lsn2 ON hs2.hk_supplier = lsn2.hk_supplier
      JOIN hub_nation hn2 ON lsn2.hk_nation = hn2.hk_nation
      JOIN link_nation_region lnr2 ON hn2.hk_nation = lnr2.hk_nation
      JOIN hub_region hr2 ON lnr2.hk_region = hr2.hk_region
      JOIN sat_region sr2 ON hr2.hk_region = sr2.hk_region AND sr2.load_end_dts IS NULL
      WHERE lps2.hk_part = hp.hk_part
        AND sr2.r_name = ':region'
  )
ORDER BY ss.s_acctbal DESC, sn.n_name, ss.s_name, hp.p_partkey
LIMIT 100
        """,
        # Q3: Shipping Priority
        # Parameters: :segment, :date
        3: """
SELECT
    hl.l_orderkey,
    SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS revenue,
    so.o_orderdate,
    so.o_shippriority
FROM hub_customer hc
JOIN sat_customer sc ON hc.hk_customer = sc.hk_customer AND sc.load_end_dts IS NULL
JOIN link_order_customer loc ON hc.hk_customer = loc.hk_customer
JOIN hub_order ho ON loc.hk_order = ho.hk_order
JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
JOIN link_lineitem ll ON ho.hk_order = ll.hk_order
JOIN hub_lineitem hl ON ll.hk_lineitem = hl.hk_lineitem
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
WHERE sc.c_mktsegment = ':segment'
  AND so.o_orderdate < DATE ':date'
  AND sl.l_shipdate > DATE ':date'
GROUP BY hl.l_orderkey, so.o_orderdate, so.o_shippriority
ORDER BY revenue DESC, so.o_orderdate
LIMIT 10
        """,
        # Q4: Order Priority Checking
        # Parameters: :date
        4: """
SELECT
    so.o_orderpriority,
    COUNT(*) AS order_count
FROM hub_order ho
JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
WHERE so.o_orderdate >= DATE ':date'
  AND so.o_orderdate < DATE ':date' + INTERVAL '3' MONTH
  AND EXISTS (
      SELECT 1
      FROM link_lineitem ll
      JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
      WHERE ll.hk_order = ho.hk_order
        AND sl.l_commitdate < sl.l_receiptdate
  )
GROUP BY so.o_orderpriority
ORDER BY so.o_orderpriority
        """,
        # Q5: Local Supplier Volume
        # Parameters: :region, :date
        5: """
SELECT
    sn.n_name,
    SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS revenue
FROM hub_region hr
JOIN sat_region sr ON hr.hk_region = sr.hk_region AND sr.load_end_dts IS NULL
JOIN link_nation_region lnr ON hr.hk_region = lnr.hk_region
JOIN hub_nation hn ON lnr.hk_nation = hn.hk_nation
JOIN sat_nation sn ON hn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
JOIN link_customer_nation lcn ON hn.hk_nation = lcn.hk_nation
JOIN hub_customer hc ON lcn.hk_customer = hc.hk_customer
JOIN link_order_customer loc ON hc.hk_customer = loc.hk_customer
JOIN hub_order ho ON loc.hk_order = ho.hk_order
JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
JOIN link_lineitem ll ON ho.hk_order = ll.hk_order
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
JOIN link_supplier_nation lsn ON hn.hk_nation = lsn.hk_nation
JOIN hub_supplier hs ON lsn.hk_supplier = hs.hk_supplier AND ll.hk_supplier = hs.hk_supplier
WHERE sr.r_name = ':region'
  AND so.o_orderdate >= DATE ':date'
  AND so.o_orderdate < DATE ':date' + INTERVAL '1' YEAR
GROUP BY sn.n_name
ORDER BY revenue DESC
        """,
        # Q6: Forecasting Revenue Change
        # Parameters: :date, :discount, :quantity
        6: """
SELECT
    SUM(sl.l_extendedprice * sl.l_discount) AS revenue
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
WHERE sl.l_shipdate >= DATE ':date'
  AND sl.l_shipdate < DATE ':date' + INTERVAL '1' YEAR
  AND sl.l_discount BETWEEN :discount - 0.01 AND :discount + 0.01
  AND sl.l_quantity < :quantity
        """,
        # Q7: Volume Shipping
        # Parameters: :nation1, :nation2
        7: """
SELECT
    supp_nation,
    cust_nation,
    l_year,
    SUM(volume) AS revenue
FROM (
    SELECT
        n1.n_name AS supp_nation,
        n2.n_name AS cust_nation,
        EXTRACT(YEAR FROM sl.l_shipdate) AS l_year,
        sl.l_extendedprice * (1 - sl.l_discount) AS volume
    FROM link_lineitem ll
    JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
    JOIN hub_supplier hs ON ll.hk_supplier = hs.hk_supplier
    JOIN link_supplier_nation lsn ON hs.hk_supplier = lsn.hk_supplier
    JOIN hub_nation hn1 ON lsn.hk_nation = hn1.hk_nation
    JOIN sat_nation n1 ON hn1.hk_nation = n1.hk_nation AND n1.load_end_dts IS NULL
    JOIN hub_order ho ON ll.hk_order = ho.hk_order
    JOIN link_order_customer loc ON ho.hk_order = loc.hk_order
    JOIN hub_customer hc ON loc.hk_customer = hc.hk_customer
    JOIN link_customer_nation lcn ON hc.hk_customer = lcn.hk_customer
    JOIN hub_nation hn2 ON lcn.hk_nation = hn2.hk_nation
    JOIN sat_nation n2 ON hn2.hk_nation = n2.hk_nation AND n2.load_end_dts IS NULL
    WHERE ((n1.n_name = ':nation1' AND n2.n_name = ':nation2')
        OR (n1.n_name = ':nation2' AND n2.n_name = ':nation1'))
      AND sl.l_shipdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'
) AS shipping
GROUP BY supp_nation, cust_nation, l_year
ORDER BY supp_nation, cust_nation, l_year
        """,
        # Q8: National Market Share
        # Parameters: :nation, :region, :type
        8: """
SELECT
    o_year,
    SUM(CASE WHEN nation = ':nation' THEN volume ELSE 0 END) / SUM(volume) AS mkt_share
FROM (
    SELECT
        EXTRACT(YEAR FROM so.o_orderdate) AS o_year,
        sl.l_extendedprice * (1 - sl.l_discount) AS volume,
        sn2.n_name AS nation
    FROM link_lineitem ll
    JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
    JOIN hub_part hp ON ll.hk_part = hp.hk_part
    JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
    JOIN hub_supplier hs ON ll.hk_supplier = hs.hk_supplier
    JOIN link_supplier_nation lsn ON hs.hk_supplier = lsn.hk_supplier
    JOIN hub_nation hn2 ON lsn.hk_nation = hn2.hk_nation
    JOIN sat_nation sn2 ON hn2.hk_nation = sn2.hk_nation AND sn2.load_end_dts IS NULL
    JOIN hub_order ho ON ll.hk_order = ho.hk_order
    JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
    JOIN link_order_customer loc ON ho.hk_order = loc.hk_order
    JOIN hub_customer hc ON loc.hk_customer = hc.hk_customer
    JOIN link_customer_nation lcn ON hc.hk_customer = lcn.hk_customer
    JOIN hub_nation hn ON lcn.hk_nation = hn.hk_nation
    JOIN link_nation_region lnr ON hn.hk_nation = lnr.hk_nation
    JOIN hub_region hr ON lnr.hk_region = hr.hk_region
    JOIN sat_region sr ON hr.hk_region = sr.hk_region AND sr.load_end_dts IS NULL
    WHERE sr.r_name = ':region'
      AND so.o_orderdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'
      AND sp.p_type = ':type'
) AS all_nations
GROUP BY o_year
ORDER BY o_year
        """,
        # Q9: Product Type Profit Measure
        # Parameters: :color
        9: """
SELECT
    nation,
    o_year,
    SUM(amount) AS sum_profit
FROM (
    SELECT
        sn.n_name AS nation,
        EXTRACT(YEAR FROM so.o_orderdate) AS o_year,
        sl.l_extendedprice * (1 - sl.l_discount) - sps.ps_supplycost * sl.l_quantity AS amount
    FROM link_lineitem ll
    JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
    JOIN hub_part hp ON ll.hk_part = hp.hk_part
    JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
    JOIN hub_supplier hs ON ll.hk_supplier = hs.hk_supplier
    JOIN link_part_supplier lps ON hp.hk_part = lps.hk_part AND hs.hk_supplier = lps.hk_supplier
    JOIN sat_partsupp sps ON lps.hk_part_supplier = sps.hk_part_supplier AND sps.load_end_dts IS NULL
    JOIN link_supplier_nation lsn ON hs.hk_supplier = lsn.hk_supplier
    JOIN hub_nation hn ON lsn.hk_nation = hn.hk_nation
    JOIN sat_nation sn ON hn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
    JOIN hub_order ho ON ll.hk_order = ho.hk_order
    JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
    WHERE sp.p_name LIKE '%:color%'
) AS profit
GROUP BY nation, o_year
ORDER BY nation, o_year DESC
        """,
        # Q10: Returned Item Reporting
        # Parameters: :date
        10: """
SELECT
    hc.c_custkey,
    sc.c_name,
    SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS revenue,
    sc.c_acctbal,
    sn.n_name,
    sc.c_address,
    sc.c_phone,
    sc.c_comment
FROM hub_customer hc
JOIN sat_customer sc ON hc.hk_customer = sc.hk_customer AND sc.load_end_dts IS NULL
JOIN link_order_customer loc ON hc.hk_customer = loc.hk_customer
JOIN hub_order ho ON loc.hk_order = ho.hk_order
JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
JOIN link_lineitem ll ON ho.hk_order = ll.hk_order
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
JOIN link_customer_nation lcn ON hc.hk_customer = lcn.hk_customer
JOIN hub_nation hn ON lcn.hk_nation = hn.hk_nation
JOIN sat_nation sn ON hn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
WHERE so.o_orderdate >= DATE ':date'
  AND so.o_orderdate < DATE ':date' + INTERVAL '3' MONTH
  AND sl.l_returnflag = 'R'
GROUP BY hc.c_custkey, sc.c_name, sc.c_acctbal, sc.c_phone, sn.n_name, sc.c_address, sc.c_comment
ORDER BY revenue DESC
LIMIT 20
        """,
        # Q11: Important Stock Identification
        # Parameters: :nation, :fraction
        11: """
SELECT
    hp.p_partkey,
    SUM(sps.ps_supplycost * sps.ps_availqty) AS value
FROM link_part_supplier lps
JOIN hub_part hp ON lps.hk_part = hp.hk_part
JOIN sat_partsupp sps ON lps.hk_part_supplier = sps.hk_part_supplier AND sps.load_end_dts IS NULL
JOIN hub_supplier hs ON lps.hk_supplier = hs.hk_supplier
JOIN link_supplier_nation lsn ON hs.hk_supplier = lsn.hk_supplier
JOIN hub_nation hn ON lsn.hk_nation = hn.hk_nation
JOIN sat_nation sn ON hn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
WHERE sn.n_name = ':nation'
GROUP BY hp.p_partkey
HAVING SUM(sps.ps_supplycost * sps.ps_availqty) > (
    SELECT SUM(sps2.ps_supplycost * sps2.ps_availqty) * :fraction
    FROM link_part_supplier lps2
    JOIN sat_partsupp sps2 ON lps2.hk_part_supplier = sps2.hk_part_supplier AND sps2.load_end_dts IS NULL
    JOIN hub_supplier hs2 ON lps2.hk_supplier = hs2.hk_supplier
    JOIN link_supplier_nation lsn2 ON hs2.hk_supplier = lsn2.hk_supplier
    JOIN hub_nation hn2 ON lsn2.hk_nation = hn2.hk_nation
    JOIN sat_nation sn2 ON hn2.hk_nation = sn2.hk_nation AND sn2.load_end_dts IS NULL
    WHERE sn2.n_name = ':nation'
)
ORDER BY value DESC
        """,
        # Q12: Shipping Modes and Order Priority
        # Parameters: :shipmode1, :shipmode2, :date
        12: """
SELECT
    sl.l_shipmode,
    SUM(CASE
        WHEN so.o_orderpriority = '1-URGENT' OR so.o_orderpriority = '2-HIGH'
        THEN 1 ELSE 0 END) AS high_line_count,
    SUM(CASE
        WHEN so.o_orderpriority <> '1-URGENT' AND so.o_orderpriority <> '2-HIGH'
        THEN 1 ELSE 0 END) AS low_line_count
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
JOIN sat_order so ON ll.hk_order = so.hk_order AND so.load_end_dts IS NULL
WHERE sl.l_shipmode IN (':shipmode1', ':shipmode2')
  AND sl.l_commitdate < sl.l_receiptdate
  AND sl.l_shipdate < sl.l_commitdate
  AND sl.l_receiptdate >= DATE ':date'
  AND sl.l_receiptdate < DATE ':date' + INTERVAL '1' YEAR
GROUP BY sl.l_shipmode
ORDER BY sl.l_shipmode
        """,
        # Q13: Customer Distribution
        # Parameters: :word1, :word2
        13: """
SELECT
    c_count,
    COUNT(*) AS custdist
FROM (
    SELECT
        hc.c_custkey,
        COUNT(so.hk_order) AS c_count
    FROM hub_customer hc
    LEFT JOIN link_order_customer loc ON hc.hk_customer = loc.hk_customer
    LEFT JOIN hub_order ho ON loc.hk_order = ho.hk_order
    LEFT JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
        AND so.o_comment NOT LIKE '%:word1%:word2%'
    GROUP BY hc.c_custkey
) AS c_orders
GROUP BY c_count
ORDER BY custdist DESC, c_count DESC
        """,
        # Q14: Promotion Effect
        # Parameters: :date
        14: """
SELECT
    100.00 * SUM(CASE WHEN sp.p_type LIKE 'PROMO%'
        THEN sl.l_extendedprice * (1 - sl.l_discount) ELSE 0 END)
    / SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS promo_revenue
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
JOIN hub_part hp ON ll.hk_part = hp.hk_part
JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
WHERE sl.l_shipdate >= DATE ':date'
  AND sl.l_shipdate < DATE ':date' + INTERVAL '1' MONTH
        """,
        # Q15: Top Supplier (using CTE instead of VIEW)
        # Parameters: :date
        15: """
WITH revenue AS (
    SELECT
        ll.hk_supplier AS supplier_no,
        SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS total_revenue
    FROM link_lineitem ll
    JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
    WHERE sl.l_shipdate >= DATE ':date'
      AND sl.l_shipdate < DATE ':date' + INTERVAL '3' MONTH
    GROUP BY ll.hk_supplier
)
SELECT
    hs.s_suppkey,
    ss.s_name,
    ss.s_address,
    ss.s_phone,
    r.total_revenue
FROM hub_supplier hs
JOIN sat_supplier ss ON hs.hk_supplier = ss.hk_supplier AND ss.load_end_dts IS NULL
JOIN revenue r ON hs.hk_supplier = r.supplier_no
WHERE r.total_revenue = (SELECT MAX(total_revenue) FROM revenue)
ORDER BY hs.s_suppkey
        """,
        # Q16: Parts/Supplier Relationship
        # Parameters: :brand, :type_prefix, :sizes (list)
        16: """
SELECT
    sp.p_brand,
    sp.p_type,
    sp.p_size,
    COUNT(DISTINCT lps.hk_supplier) AS supplier_cnt
FROM hub_part hp
JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
JOIN link_part_supplier lps ON hp.hk_part = lps.hk_part
JOIN hub_supplier hs ON lps.hk_supplier = hs.hk_supplier
JOIN sat_supplier ss ON hs.hk_supplier = ss.hk_supplier AND ss.load_end_dts IS NULL
WHERE sp.p_brand <> ':brand'
  AND sp.p_type NOT LIKE ':type_prefix%'
  AND sp.p_size IN (:sizes)
  AND ss.s_comment NOT LIKE '%Customer%Complaints%'
GROUP BY sp.p_brand, sp.p_type, sp.p_size
ORDER BY supplier_cnt DESC, sp.p_brand, sp.p_type, sp.p_size
        """,
        # Q17: Small-Quantity-Order Revenue
        # Parameters: :brand, :container
        17: """
SELECT
    SUM(sl.l_extendedprice) / 7.0 AS avg_yearly
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
JOIN hub_part hp ON ll.hk_part = hp.hk_part
JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
WHERE sp.p_brand = ':brand'
  AND sp.p_container = ':container'
  AND sl.l_quantity < (
      SELECT 0.2 * AVG(sl2.l_quantity)
      FROM link_lineitem ll2
      JOIN sat_lineitem sl2 ON ll2.hk_lineitem_link = sl2.hk_lineitem_link AND sl2.load_end_dts IS NULL
      WHERE ll2.hk_part = hp.hk_part
  )
        """,
        # Q18: Large Volume Customer
        # Parameters: :quantity
        18: """
SELECT
    sc.c_name,
    hc.c_custkey,
    ho.o_orderkey,
    so.o_orderdate,
    so.o_totalprice,
    large_orders.total_qty
FROM hub_customer hc
JOIN sat_customer sc ON hc.hk_customer = sc.hk_customer AND sc.load_end_dts IS NULL
JOIN link_order_customer loc ON hc.hk_customer = loc.hk_customer
JOIN hub_order ho ON loc.hk_order = ho.hk_order
JOIN sat_order so ON ho.hk_order = so.hk_order AND so.load_end_dts IS NULL
JOIN (
    SELECT
        ll2.hk_order,
        SUM(sl2.l_quantity) AS total_qty
    FROM link_lineitem ll2
    JOIN sat_lineitem sl2 ON ll2.hk_lineitem_link = sl2.hk_lineitem_link AND sl2.load_end_dts IS NULL
    GROUP BY ll2.hk_order
    HAVING SUM(sl2.l_quantity) > :quantity
) large_orders ON ho.hk_order = large_orders.hk_order
ORDER BY so.o_totalprice DESC, so.o_orderdate
LIMIT 100
        """,
        # Q19: Discounted Revenue
        # Parameters: :brand1, :brand2, :brand3, :quantity1, :quantity2, :quantity3
        19: """
SELECT
    SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS revenue
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
JOIN hub_part hp ON ll.hk_part = hp.hk_part
JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
WHERE (
    sp.p_brand = ':brand1'
    AND sp.p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
    AND sl.l_quantity >= :quantity1 AND sl.l_quantity <= :quantity1 + 10
    AND sp.p_size BETWEEN 1 AND 5
    AND sl.l_shipmode IN ('AIR', 'AIR REG')
    AND sl.l_shipinstruct = 'DELIVER IN PERSON'
) OR (
    sp.p_brand = ':brand2'
    AND sp.p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
    AND sl.l_quantity >= :quantity2 AND sl.l_quantity <= :quantity2 + 10
    AND sp.p_size BETWEEN 1 AND 10
    AND sl.l_shipmode IN ('AIR', 'AIR REG')
    AND sl.l_shipinstruct = 'DELIVER IN PERSON'
) OR (
    sp.p_brand = ':brand3'
    AND sp.p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
    AND sl.l_quantity >= :quantity3 AND sl.l_quantity <= :quantity3 + 10
    AND sp.p_size BETWEEN 1 AND 15
    AND sl.l_shipmode IN ('AIR', 'AIR REG')
    AND sl.l_shipinstruct = 'DELIVER IN PERSON'
)
        """,
        # Q20: Potential Part Promotion
        # Parameters: :color, :date, :nation
        20: """
SELECT
    ss.s_name,
    ss.s_address
FROM hub_supplier hs
JOIN sat_supplier ss ON hs.hk_supplier = ss.hk_supplier AND ss.load_end_dts IS NULL
JOIN link_supplier_nation lsn ON hs.hk_supplier = lsn.hk_supplier
JOIN hub_nation hn ON lsn.hk_nation = hn.hk_nation
JOIN sat_nation sn ON hn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
WHERE sn.n_name = ':nation'
  AND hs.hk_supplier IN (
      SELECT lps.hk_supplier
      FROM link_part_supplier lps
      JOIN sat_partsupp sps ON lps.hk_part_supplier = sps.hk_part_supplier AND sps.load_end_dts IS NULL
      JOIN hub_part hp ON lps.hk_part = hp.hk_part
      JOIN sat_part sp ON hp.hk_part = sp.hk_part AND sp.load_end_dts IS NULL
      WHERE sp.p_name LIKE ':color%'
        AND sps.ps_availqty > (
            SELECT 0.5 * SUM(sl.l_quantity)
            FROM link_lineitem ll
            JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
            WHERE ll.hk_part = hp.hk_part
              AND ll.hk_supplier = lps.hk_supplier
              AND sl.l_shipdate >= DATE ':date'
              AND sl.l_shipdate < DATE ':date' + INTERVAL '1' YEAR
        )
  )
ORDER BY ss.s_name
        """,
        # Q21: Suppliers Who Kept Orders Waiting
        # Parameters: :nation
        21: """
SELECT
    ss.s_name,
    COUNT(*) AS numwait
FROM sat_supplier ss
JOIN link_supplier_nation lsn ON ss.hk_supplier = lsn.hk_supplier
JOIN sat_nation sn ON lsn.hk_nation = sn.hk_nation AND sn.load_end_dts IS NULL
JOIN link_lineitem ll1 ON ss.hk_supplier = ll1.hk_supplier
JOIN sat_lineitem sl1 ON ll1.hk_lineitem_link = sl1.hk_lineitem_link AND sl1.load_end_dts IS NULL
JOIN sat_order so ON ll1.hk_order = so.hk_order AND so.load_end_dts IS NULL
WHERE ss.load_end_dts IS NULL
  AND so.o_orderstatus = 'F'
  AND sl1.l_receiptdate > sl1.l_commitdate
  AND sn.n_name = ':nation'
  AND EXISTS (
      SELECT 1
      FROM link_lineitem ll2
      WHERE ll2.hk_order = ll1.hk_order
        AND ll2.hk_supplier <> ll1.hk_supplier
  )
  AND NOT EXISTS (
      SELECT 1
      FROM link_lineitem ll3
      JOIN sat_lineitem sl3 ON ll3.hk_lineitem_link = sl3.hk_lineitem_link AND sl3.load_end_dts IS NULL
      WHERE ll3.hk_order = ll1.hk_order
        AND ll3.hk_supplier <> ll1.hk_supplier
        AND sl3.l_receiptdate > sl3.l_commitdate
  )
GROUP BY ss.s_name
ORDER BY numwait DESC, ss.s_name
LIMIT 100
        """,
        # Q22: Global Sales Opportunity
        # Parameters: :country_codes (list of 7 codes)
        22: """
SELECT
    cntrycode,
    COUNT(*) AS numcust,
    SUM(c_acctbal) AS totacctbal
FROM (
    SELECT
        SUBSTRING(sc.c_phone FROM 1 FOR 2) AS cntrycode,
        sc.c_acctbal
    FROM hub_customer hc
    JOIN sat_customer sc ON hc.hk_customer = sc.hk_customer AND sc.load_end_dts IS NULL
    WHERE SUBSTRING(sc.c_phone FROM 1 FOR 2) IN (:country_codes)
      AND sc.c_acctbal > (
          SELECT AVG(sc2.c_acctbal)
          FROM hub_customer hc2
          JOIN sat_customer sc2 ON hc2.hk_customer = sc2.hk_customer AND sc2.load_end_dts IS NULL
          WHERE sc2.c_acctbal > 0.00
            AND SUBSTRING(sc2.c_phone FROM 1 FOR 2) IN (:country_codes)
      )
      AND NOT EXISTS (
          SELECT 1
          FROM link_order_customer loc
          WHERE loc.hk_customer = hc.hk_customer
      )
) AS custsale
GROUP BY cntrycode
ORDER BY cntrycode
        """,
    }

    # Default parameters for deterministic query generation.
    DEFAULT_PARAMS: dict[int, dict[str, Any]] = {
        1: {"delta": 90},
        2: {"size": 15, "type_suffix": "BRASS", "region": "EUROPE"},
        3: {"segment": "BUILDING", "date": "1995-03-15"},
        4: {"date": "1993-07-01"},
        5: {"region": "ASIA", "date": "1994-01-01"},
        6: {"date": "1994-01-01", "discount": 0.06, "quantity": 24},
        7: {"nation1": "FRANCE", "nation2": "GERMANY"},
        8: {"nation": "BRAZIL", "region": "AMERICA", "type": "ECONOMY ANODIZED STEEL"},
        9: {"color": "green"},
        10: {"date": "1993-10-01"},
        11: {"nation": "GERMANY", "fraction": 0.0001},
        12: {"shipmode1": "MAIL", "shipmode2": "SHIP", "date": "1994-01-01"},
        13: {"word1": "special", "word2": "requests"},
        14: {"date": "1995-09-01"},
        15: {"date": "1996-01-01"},
        16: {"brand": "Brand#45", "type_prefix": "MEDIUM POLISHED", "sizes": [49, 14, 23, 45, 19, 3, 36, 9]},
        17: {"brand": "Brand#23", "container": "MED BOX"},
        18: {"quantity": 300},
        19: {
            "brand1": "Brand#12",
            "brand2": "Brand#23",
            "brand3": "Brand#34",
            "quantity1": 1,
            "quantity2": 10,
            "quantity3": 20,
        },
        20: {"color": "forest", "date": "1994-01-01", "nation": "CANADA"},
        21: {"nation": "SAUDI ARABIA"},
        22: {"country_codes": ["13", "31", "23", "29", "30", "18", "17"]},
    }

    def __init__(self, seed: Optional[int] = None, scale_factor: float = 1.0) -> None:
        """Initialize the query manager.

        Args:
            seed: Random seed for parameter generation (for reproducibility)
            scale_factor: Scale factor (affects some parameter ranges)
        """
        self._param_generator = DataVaultParameterGenerator(seed=seed, scale_factor=scale_factor)
        self._query_cache: dict[tuple[int, int], str] = {}

    def _substitute_parameters(self, template: str, params: dict[str, Any]) -> str:
        """Substitute parameters into a query template.

        Args:
            template: Query template with :param_name placeholders
            params: Dictionary of parameter values

        Returns:
            SQL with parameters substituted
        """
        result = template

        for name, value in params.items():
            if isinstance(value, list):
                # Handle list parameters (e.g., sizes, country_codes)
                if all(isinstance(v, str) for v in value):
                    # String list: quote each value
                    list_str = ", ".join(f"'{v}'" for v in value)
                else:
                    # Numeric list: no quotes
                    list_str = ", ".join(str(v) for v in value)
                result = result.replace(f":{name}", list_str)
            elif isinstance(value, (int, float)):
                # Numeric values: no quotes (handle both quoted and unquoted contexts)
                result = result.replace(f"':{name}'", str(value))  # For quoted context
                result = result.replace(f":{name}", str(value))
            else:
                # String values: already quoted in template for most cases
                result = result.replace(f":{name}", str(value))

        return result

    def get_query(self, query_id: Union[int, str], params: Optional[dict[str, Any]] = None) -> str:
        """Get a query by ID with parameter substitution.

        Args:
            query_id: Query identifier (1-22)
            params: Optional parameter overrides. If None, uses DEFAULT_PARAMS.

        Returns:
            SQL query text with parameters substituted

        Raises:
            ValueError: If query_id is not valid
        """
        qid = int(query_id) if isinstance(query_id, str) else query_id

        if qid not in self.QUERY_TEMPLATES:
            raise ValueError(f"Invalid query ID: {query_id}. Valid IDs: 1-22")

        # Use default params if none provided
        if params is None:
            params = self.DEFAULT_PARAMS[qid]

        return self._substitute_parameters(self.QUERY_TEMPLATES[qid], params).strip()

    def get_parameterized_query(self, query_id: Union[int, str], stream_id: int = 0) -> tuple[str, QueryParameters]:
        """Get a query with randomly generated parameters.

        Uses the parameter generator with the configured seed to generate
        TPC-H-compliant parameters deterministically.

        Args:
            query_id: Query identifier (1-22)
            stream_id: Stream ID for multi-stream execution

        Returns:
            Tuple of (SQL query text, QueryParameters metadata)

        Raises:
            ValueError: If query_id is not valid
        """
        qid = int(query_id) if isinstance(query_id, str) else query_id

        if qid not in self.QUERY_TEMPLATES:
            raise ValueError(f"Invalid query ID: {query_id}. Valid IDs: 1-22")

        # Generate parameters
        query_params = self._param_generator.generate_parameters(qid, stream_id)

        # Substitute into template
        sql = self._substitute_parameters(self.QUERY_TEMPLATES[qid], query_params.params).strip()

        return sql, query_params

    def get_all_queries(self, params: Optional[dict[int, dict[str, Any]]] = None) -> dict[Union[int, str], str]:
        """Get all queries with parameter substitution.

        Args:
            params: Optional dict mapping query IDs to parameter dicts.
                   If None, uses DEFAULT_PARAMS for all queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        result: dict[Union[int, str], str] = {}
        for qid in self.QUERY_TEMPLATES:
            query_params = params.get(qid) if params else None
            result[qid] = self.get_query(qid, query_params)
        return result

    def get_all_parameterized_queries(self, stream_id: int = 0) -> dict[int, tuple[str, QueryParameters]]:
        """Get all queries with randomly generated parameters.

        Args:
            stream_id: Stream ID for multi-stream execution

        Returns:
            Dictionary mapping query IDs to (SQL, QueryParameters) tuples
        """
        result: dict[int, tuple[str, QueryParameters]] = {}
        for qid in self.QUERY_TEMPLATES:
            result[qid] = self.get_parameterized_query(qid, stream_id)
        return result

    def get_query_count(self) -> int:
        """Get the total number of queries.

        Returns:
            Number of queries (22)
        """
        return len(self.QUERY_TEMPLATES)

    def get_template(self, query_id: Union[int, str]) -> str:
        """Get the raw query template without parameter substitution.

        Args:
            query_id: Query identifier (1-22)

        Returns:
            Query template with :param_name placeholders

        Raises:
            ValueError: If query_id is not valid
        """
        qid = int(query_id) if isinstance(query_id, str) else query_id

        if qid not in self.QUERY_TEMPLATES:
            raise ValueError(f"Invalid query ID: {query_id}. Valid IDs: 1-22")

        return self.QUERY_TEMPLATES[qid].strip()

    def get_default_params(self, query_id: Union[int, str]) -> dict[str, Any]:
        """Get the default parameters for a query.

        Args:
            query_id: Query identifier (1-22)

        Returns:
            Dictionary of default parameter values

        Raises:
            ValueError: If query_id is not valid
        """
        qid = int(query_id) if isinstance(query_id, str) else query_id

        if qid not in self.DEFAULT_PARAMS:
            raise ValueError(f"Invalid query ID: {query_id}. Valid IDs: 1-22")

        return self.DEFAULT_PARAMS[qid].copy()
