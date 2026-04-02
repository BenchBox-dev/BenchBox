"""Execution tests for TPC-H DataFrame query implementations using Polars.

Tests each TPC-H query (Q1-Q22) against small test DataFrames with correct
TPC-H table schemas, using the expression_impl family via the real Polars
ExpressionFamilyContext.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date

import pytest

try:
    import polars as pl

    from benchbox.platforms.dataframe.polars_df import (
        POLARS_AVAILABLE,
        PolarsDataFrameAdapter,
    )
except ImportError:
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]

from benchbox.core.tpch.dataframe_queries import get_query, list_query_ids

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed"),
]


# ---------------------------------------------------------------------------
# Minimal TPC-H table fixtures (5-10 rows each with correct column names)
# ---------------------------------------------------------------------------


def _build_region() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "r_regionkey": [0, 1, 2, 3, 4],
            "r_name": ["AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST"],
            "r_comment": ["c0", "c1", "c2", "c3", "c4"],
        }
    ).lazy()


def _build_nation() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "n_nationkey": [0, 1, 2, 3, 4, 5, 6],
            "n_name": [
                "BRAZIL",
                "CANADA",
                "FRANCE",
                "GERMANY",
                "SAUDI ARABIA",
                "UNITED STATES",
                "JAPAN",
            ],
            "n_regionkey": [1, 1, 3, 3, 4, 1, 2],
            "n_comment": ["", "", "", "", "", "", ""],
        }
    ).lazy()


def _build_supplier() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "s_suppkey": [1, 2, 3, 4, 5],
            "s_name": ["Supp-A", "Supp-B", "Supp-C", "Supp-D", "Supp-E"],
            "s_address": ["Addr1", "Addr2", "Addr3", "Addr4", "Addr5"],
            "s_nationkey": [3, 2, 0, 4, 1],  # GERMANY, FRANCE, BRAZIL, SAUDI ARABIA, CANADA
            "s_phone": ["17-000-0001", "13-000-0002", "23-000-0003", "30-000-0004", "29-000-0005"],
            "s_acctbal": [5000.0, 3000.0, 7000.0, 2000.0, 4000.0],
            "s_comment": [
                "Reliable supplier",
                "Customer and no Complaints at all",
                "Fast delivery",
                "Average",
                "Good",
            ],
        }
    ).lazy()


def _build_customer() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "c_custkey": [1, 2, 3, 4, 5, 6],
            "c_name": ["Cust-A", "Cust-B", "Cust-C", "Cust-D", "Cust-E", "Cust-F"],
            "c_address": ["CA1", "CA2", "CA3", "CA4", "CA5", "CA6"],
            "c_nationkey": [3, 2, 0, 4, 1, 3],  # GERMANY, FRANCE, BRAZIL, SAUDI ARABIA, CANADA, GERMANY
            "c_phone": ["17-100", "13-200", "23-300", "30-400", "29-500", "17-600"],
            "c_acctbal": [1000.0, 2500.0, 500.0, 8000.0, 100.0, 3000.0],
            "c_mktsegment": ["BUILDING", "AUTOMOBILE", "BUILDING", "HOUSEHOLD", "BUILDING", "BUILDING"],
            "c_comment": ["ok", "good", "special requests noted", "fine", "standard", "premium"],
        }
    ).lazy()


def _build_orders() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "o_orderkey": [1, 2, 3, 4, 5, 6, 7, 8],
            "o_custkey": [1, 2, 3, 1, 4, 5, 6, 2],
            "o_orderstatus": ["F", "O", "F", "F", "F", "O", "F", "F"],
            "o_totalprice": [10000.0, 15000.0, 8000.0, 12000.0, 7500.0, 9000.0, 11000.0, 6000.0],
            "o_orderdate": [
                date(1993, 8, 15),
                date(1995, 4, 20),
                date(1994, 6, 10),
                date(1996, 2, 28),
                date(1993, 12, 1),
                date(1995, 11, 15),
                date(1994, 3, 22),
                date(1996, 7, 14),
            ],
            "o_orderpriority": [
                "1-URGENT",
                "2-HIGH",
                "3-MEDIUM",
                "5-LOW",
                "1-URGENT",
                "4-NOT SPECIFIED",
                "2-HIGH",
                "3-MEDIUM",
            ],
            "o_clerk": ["C001", "C002", "C003", "C004", "C001", "C002", "C003", "C004"],
            "o_shippriority": [0, 0, 0, 0, 0, 0, 0, 0],
            "o_comment": [
                "regular order",
                "special requests please",
                "standard",
                "rush",
                "normal",
                "express",
                "standard",
                "regular",
            ],
        }
    ).lazy()


def _build_part() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "p_partkey": [1, 2, 3, 4, 5, 6],
            "p_name": [
                "forest green widget",
                "promo polished steel rod",
                "blue metallic tin",
                "economy anodized steel bar",
                "forest brown copper plate",
                "medium polished brass screw",
            ],
            "p_mfgr": ["Mfgr#1", "Mfgr#2", "Mfgr#3", "Mfgr#4", "Mfgr#5", "Mfgr#1"],
            "p_brand": ["Brand#12", "Brand#23", "Brand#34", "Brand#45", "Brand#12", "Brand#23"],
            "p_type": [
                "PROMO POLISHED STEEL",
                "ECONOMY ANODIZED STEEL",
                "MEDIUM POLISHED TIN",
                "STANDARD BRUSHED BRASS",
                "PROMO POLISHED COPPER",
                "ECONOMY ANODIZED BRASS",
            ],
            "p_size": [3, 15, 9, 25, 5, 10],
            "p_container": ["SM CASE", "MED BOX", "LG PACK", "WRAP BULK", "SM CASE", "MED BOX"],
            "p_retailprice": [100.0, 200.0, 150.0, 300.0, 120.0, 180.0],
            "p_comment": ["", "", "", "", "", ""],
        }
    ).lazy()


def _build_partsupp() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "ps_partkey": [1, 1, 2, 3, 4, 5, 6, 2],
            "ps_suppkey": [1, 2, 3, 4, 5, 1, 2, 1],
            "ps_availqty": [500, 300, 200, 400, 100, 600, 350, 450],
            "ps_supplycost": [10.0, 15.0, 20.0, 25.0, 30.0, 12.0, 18.0, 22.0],
            "ps_comment": ["", "", "", "", "", "", "", ""],
        }
    ).lazy()


def _build_lineitem() -> pl.LazyFrame:
    return pl.DataFrame(
        {
            "l_orderkey": [1, 1, 2, 3, 4, 5, 6, 7, 8, 3],
            "l_partkey": [1, 2, 3, 4, 5, 1, 2, 3, 4, 1],
            "l_suppkey": [1, 3, 4, 5, 1, 2, 3, 4, 5, 1],
            "l_linenumber": [1, 2, 1, 1, 1, 1, 1, 1, 1, 2],
            "l_quantity": [5.0, 15.0, 3.0, 8.0, 20.0, 10.0, 12.0, 7.0, 25.0, 4.0],
            "l_extendedprice": [
                500.0,
                3000.0,
                450.0,
                2400.0,
                2400.0,
                1200.0,
                2160.0,
                1050.0,
                7500.0,
                480.0,
            ],
            "l_discount": [0.06, 0.04, 0.05, 0.07, 0.03, 0.08, 0.02, 0.06, 0.04, 0.05],
            "l_tax": [0.02, 0.03, 0.01, 0.02, 0.05, 0.04, 0.03, 0.01, 0.02, 0.06],
            "l_returnflag": ["R", "N", "R", "N", "A", "R", "N", "A", "R", "N"],
            "l_linestatus": ["F", "O", "F", "F", "F", "O", "O", "F", "F", "F"],
            "l_shipdate": [
                date(1994, 2, 1),
                date(1995, 5, 10),
                date(1994, 7, 20),
                date(1994, 8, 15),
                date(1996, 4, 1),
                date(1995, 12, 20),
                date(1995, 6, 5),
                date(1994, 5, 10),
                date(1996, 8, 30),
                date(1994, 9, 12),
            ],
            "l_commitdate": [
                date(1994, 1, 25),
                date(1995, 4, 28),
                date(1994, 7, 10),
                date(1994, 7, 30),
                date(1996, 3, 15),
                date(1995, 12, 10),
                date(1995, 5, 20),
                date(1994, 4, 25),
                date(1996, 8, 10),
                date(1994, 8, 20),
            ],
            "l_receiptdate": [
                date(1994, 2, 10),
                date(1995, 5, 20),
                date(1994, 7, 25),
                date(1994, 9, 1),
                date(1996, 4, 10),
                date(1996, 1, 5),
                date(1995, 6, 15),
                date(1994, 5, 15),
                date(1996, 9, 5),
                date(1994, 9, 25),
            ],
            "l_shipmode": ["MAIL", "AIR", "SHIP", "RAIL", "AIR REG", "MAIL", "AIR", "SHIP", "RAIL", "MAIL"],
            "l_shipinstruct": [
                "DELIVER IN PERSON",
                "DELIVER IN PERSON",
                "NONE",
                "COLLECT COD",
                "DELIVER IN PERSON",
                "DELIVER IN PERSON",
                "NONE",
                "DELIVER IN PERSON",
                "NONE",
                "DELIVER IN PERSON",
            ],
            "l_comment": ["", "", "", "", "", "", "", "", "", ""],
        }
    ).lazy()


@pytest.fixture(scope="session")
def polars_adapter() -> PolarsDataFrameAdapter:
    """Create a Polars adapter for tests."""
    return PolarsDataFrameAdapter()


@pytest.fixture(scope="session")
def tpch_context(polars_adapter):
    """Create and populate an ExpressionFamilyContext with TPC-H test data.

    Session-scoped so the context is shared across all tests for performance.
    """
    ctx = polars_adapter.create_context()
    ctx.register_table("region", _build_region())
    ctx.register_table("nation", _build_nation())
    ctx.register_table("supplier", _build_supplier())
    ctx.register_table("customer", _build_customer())
    ctx.register_table("orders", _build_orders())
    ctx.register_table("part", _build_part())
    ctx.register_table("partsupp", _build_partsupp())
    ctx.register_table("lineitem", _build_lineitem())
    return ctx


# ---------------------------------------------------------------------------
# Expected output columns for each TPC-H query
# ---------------------------------------------------------------------------

EXPECTED_COLUMNS: dict[str, list[str]] = {
    "Q1": [
        "l_returnflag",
        "l_linestatus",
        "sum_qty",
        "sum_base_price",
        "sum_disc_price",
        "sum_charge",
        "avg_qty",
        "avg_price",
        "avg_disc",
        "count_order",
    ],
    "Q2": ["s_acctbal", "s_name", "n_name", "p_partkey", "p_mfgr", "s_address", "s_phone", "s_comment"],
    "Q3": ["o_orderkey", "o_orderdate", "o_shippriority", "revenue"],
    "Q4": ["o_orderpriority", "order_count"],
    "Q5": ["n_name", "revenue"],
    "Q6": ["revenue"],
    "Q7": ["supp_nation", "cust_nation", "l_year", "revenue"],
    "Q8": ["o_year", "mkt_share"],
    "Q9": ["nation", "o_year", "sum_profit"],
    "Q10": ["c_custkey", "c_name", "c_acctbal", "c_phone", "n_name", "c_address", "c_comment", "revenue"],
    "Q11": ["ps_partkey", "value"],
    "Q12": ["l_shipmode", "high_line_count", "low_line_count"],
    "Q13": ["c_count", "custdist"],
    "Q14": ["promo_revenue"],
    "Q15": ["s_suppkey", "s_name", "s_address", "s_phone", "total_revenue"],
    "Q16": ["p_brand", "p_type", "p_size", "supplier_cnt"],
    "Q17": ["avg_yearly"],
    "Q18": ["c_name", "c_custkey", "o_orderkey", "o_orderdate", "o_totalprice", "sum_qty"],
    "Q19": ["revenue"],
    "Q20": ["s_name", "s_address"],
    "Q21": ["s_name", "numwait"],
    "Q22": ["cntrycode", "numcust", "totacctbal"],
}


def _collect_result(result):
    """Collect a query result to a Polars DataFrame.

    Handles UnifiedLazyFrame, LazyFrame, and DataFrame transparently.
    """
    if hasattr(result, "native"):
        result = result.native
    if hasattr(result, "collect"):
        return result.collect()
    return result


class TestTPCHContextSetup:
    """Verify the test context is correctly populated."""

    def test_all_tables_registered(self, tpch_context):
        """Test that all 8 TPC-H tables are registered."""
        tables = tpch_context.list_tables()
        expected = ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"]
        assert sorted(tables) == expected

    def test_table_access(self, tpch_context):
        """Test that tables can be accessed and collected."""
        lineitem = tpch_context.get_table("lineitem")
        assert lineitem is not None
        df = _collect_result(lineitem)
        assert len(df) == 10  # 10 lineitem rows


class TestTPCHExpressionQueries:
    """Execute each TPC-H expression_impl query against test data.

    For each query, verify:
    1. The query executes without error
    2. The result can be collected to a DataFrame
    3. The result has the expected column names
    """

    def test_q1_pricing_summary(self, tpch_context):
        """Q1: Pricing Summary Report."""
        query = get_query("Q1")
        result = _collect_result(query.expression_impl(tpch_context))

        assert len(result) > 0
        assert set(EXPECTED_COLUMNS["Q1"]).issubset(set(result.columns))
        # Should have groups by returnflag x linestatus
        assert "l_returnflag" in result.columns
        assert "sum_qty" in result.columns

    def test_q2_minimum_cost_supplier(self, tpch_context):
        """Q2: Minimum Cost Supplier."""
        query = get_query("Q2")
        result = _collect_result(query.expression_impl(tpch_context))

        # May be empty with tiny data if no parts match size=15 + type BRASS in EUROPE
        assert set(EXPECTED_COLUMNS["Q2"]).issubset(set(result.columns))

    def test_q3_shipping_priority(self, tpch_context):
        """Q3: Shipping Priority."""
        query = get_query("Q3")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q3"]).issubset(set(result.columns))

    def test_q4_order_priority(self, tpch_context):
        """Q4: Order Priority Checking."""
        query = get_query("Q4")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q4"]).issubset(set(result.columns))

    def test_q5_local_supplier_volume(self, tpch_context):
        """Q5: Local Supplier Volume."""
        query = get_query("Q5")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q5"]).issubset(set(result.columns))

    def test_q6_forecasting_revenue(self, tpch_context):
        """Q6: Forecasting Revenue Change."""
        query = get_query("Q6")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q6"]).issubset(set(result.columns))

    def test_q7_volume_shipping(self, tpch_context):
        """Q7: Volume Shipping."""
        query = get_query("Q7")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q7"]).issubset(set(result.columns))

    def test_q8_national_market_share(self, tpch_context):
        """Q8: National Market Share."""
        query = get_query("Q8")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q8"]).issubset(set(result.columns))

    def test_q9_product_type_profit(self, tpch_context):
        """Q9: Product Type Profit Measure."""
        query = get_query("Q9")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q9"]).issubset(set(result.columns))

    def test_q10_returned_items(self, tpch_context):
        """Q10: Returned Item Reporting."""
        query = get_query("Q10")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q10"]).issubset(set(result.columns))

    def test_q11_important_stock(self, tpch_context):
        """Q11: Important Stock Identification."""
        query = get_query("Q11")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q11"]).issubset(set(result.columns))

    def test_q12_shipping_modes(self, tpch_context):
        """Q12: Shipping Modes and Order Priority."""
        query = get_query("Q12")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q12"]).issubset(set(result.columns))

    def test_q13_customer_distribution(self, tpch_context):
        """Q13: Customer Distribution."""
        query = get_query("Q13")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q13"]).issubset(set(result.columns))

    def test_q14_promotion_effect(self, tpch_context):
        """Q14: Promotion Effect."""
        query = get_query("Q14")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q14"]).issubset(set(result.columns))

    def test_q15_top_supplier(self, tpch_context):
        """Q15: Top Supplier."""
        query = get_query("Q15")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q15"]).issubset(set(result.columns))

    def test_q16_parts_supplier_relationship(self, tpch_context):
        """Q16: Parts/Supplier Relationship."""
        query = get_query("Q16")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q16"]).issubset(set(result.columns))

    def test_q17_small_quantity_order_revenue(self, tpch_context):
        """Q17: Small-Quantity-Order Revenue."""
        query = get_query("Q17")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q17"]).issubset(set(result.columns))

    def test_q18_large_volume_customer(self, tpch_context):
        """Q18: Large Volume Customer."""
        query = get_query("Q18")
        result = _collect_result(query.expression_impl(tpch_context))

        # May be empty if no orders exceed quantity_threshold=300
        assert set(EXPECTED_COLUMNS["Q18"]).issubset(set(result.columns))

    def test_q19_discounted_revenue(self, tpch_context):
        """Q19: Discounted Revenue."""
        query = get_query("Q19")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q19"]).issubset(set(result.columns))

    def test_q20_potential_part_promotion(self, tpch_context):
        """Q20: Potential Part Promotion."""
        query = get_query("Q20")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q20"]).issubset(set(result.columns))

    def test_q21_suppliers_kept_waiting(self, tpch_context):
        """Q21: Suppliers Who Kept Orders Waiting."""
        query = get_query("Q21")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q21"]).issubset(set(result.columns))

    def test_q22_global_sales_opportunity(self, tpch_context):
        """Q22: Global Sales Opportunity."""
        query = get_query("Q22")
        result = _collect_result(query.expression_impl(tpch_context))

        assert set(EXPECTED_COLUMNS["Q22"]).issubset(set(result.columns))


class TestTPCHParameterizedExecution:
    """Parametrized execution of all Q1-Q22 for comprehensive coverage."""

    @pytest.mark.parametrize("query_id", list_query_ids())
    def test_expression_impl_executes(self, tpch_context, query_id: str):
        """Every expression_impl should execute without error and produce a DataFrame."""
        query = get_query(query_id)
        assert query.expression_impl is not None, f"{query_id} has no expression_impl"

        result = query.expression_impl(tpch_context)
        assert result is not None

        df = _collect_result(result)
        assert hasattr(df, "columns"), f"{query_id} result is not a DataFrame"
        assert hasattr(df, "shape"), f"{query_id} result is not a DataFrame"

    @pytest.mark.parametrize("query_id", list_query_ids())
    def test_expression_impl_column_structure(self, tpch_context, query_id: str):
        """Every expression_impl should return the expected columns."""
        query = get_query(query_id)
        result = _collect_result(query.expression_impl(tpch_context))

        expected = EXPECTED_COLUMNS.get(query_id)
        if expected is not None:
            actual_cols = set(result.columns)
            missing = set(expected) - actual_cols
            assert not missing, f"{query_id}: missing columns {missing}, got {sorted(actual_cols)}"


class TestTPCHQueryResultValues:
    """Spot-check result values for queries that reliably produce data with tiny tables."""

    def test_q1_has_multiple_groups(self, tpch_context):
        """Q1 should produce at least 2 returnflag x linestatus groups."""
        query = get_query("Q1")
        result = _collect_result(query.expression_impl(tpch_context))
        assert len(result) >= 2

    def test_q6_returns_single_row(self, tpch_context):
        """Q6 returns a single revenue scalar."""
        query = get_query("Q6")
        result = _collect_result(query.expression_impl(tpch_context))
        assert len(result) == 1

    def test_q13_produces_distribution(self, tpch_context):
        """Q13 should produce customer-order count distribution."""
        query = get_query("Q13")
        result = _collect_result(query.expression_impl(tpch_context))
        assert len(result) >= 1
        assert "c_count" in result.columns
        assert "custdist" in result.columns

    def test_q14_returns_single_row(self, tpch_context):
        """Q14 returns a single promo_revenue value."""
        query = get_query("Q14")
        result = _collect_result(query.expression_impl(tpch_context))
        assert len(result) == 1
        assert result["promo_revenue"][0] is not None
