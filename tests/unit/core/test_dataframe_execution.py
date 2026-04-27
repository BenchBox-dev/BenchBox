"""Execution tests for DataFrame query implementations.

Validates that Expression and Pandas family implementations:
1. Execute without errors on real data
2. Produce non-empty results with expected schemas
3. Return equivalent results (same row counts and column values)

Uses Polars (expression family) and Pandas (pandas family) as reference
platforms with small in-memory fixture datasets.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from unittest.mock import patch

import pytest

try:
    import pandas as pd
    import polars as pl

    from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter
    from benchbox.platforms.dataframe.polars_df import PolarsDataFrameAdapter

    DEPS_AVAILABLE = True
except ImportError:
    DEPS_AVAILABLE = False

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(not DEPS_AVAILABLE, reason="Polars and/or Pandas not installed"),
]


# =============================================================================
# Helpers
# =============================================================================


def _to_pandas(result: Any) -> pd.DataFrame:
    """Normalize any result to a pandas DataFrame for comparison."""
    from benchbox.platforms.dataframe.unified_frame import UnifiedLazyFrame
    from benchbox.platforms.dataframe.unified_pandas_frame import UnifiedPandasFrame

    if isinstance(result, UnifiedLazyFrame):
        result = result.native
    if isinstance(result, UnifiedPandasFrame):
        result = result.native
    if isinstance(result, pl.LazyFrame):
        result = result.collect()
    if isinstance(result, pl.DataFrame):
        return result.to_pandas()
    if isinstance(result, pd.DataFrame):
        return result
    raise TypeError(f"Cannot convert {type(result)} to pandas DataFrame")


def _compare_results(expr_result: pd.DataFrame, pandas_result: pd.DataFrame, *, rtol: float = 1e-5) -> None:
    """Assert that expression and pandas results are equivalent.

    Compares:
    - Column names (sorted, order-independent)
    - Row counts
    - Values (numeric columns compared with tolerance, others exact)
    """
    # Column names must match
    expr_cols = sorted(expr_result.columns.tolist())
    pandas_cols = sorted(pandas_result.columns.tolist())
    assert expr_cols == pandas_cols, f"Column mismatch: expr={expr_cols}, pandas={pandas_cols}"

    # Row counts must match
    assert len(expr_result) == len(pandas_result), (
        f"Row count mismatch: expr={len(expr_result)}, pandas={len(pandas_result)}"
    )

    if len(expr_result) == 0:
        return

    # Align columns and sort both DataFrames identically for row-by-row comparison
    common_cols = sorted(expr_result.columns.tolist())
    expr_sorted = expr_result[common_cols].reset_index(drop=True)
    pandas_sorted = pandas_result[common_cols].reset_index(drop=True)

    # Sort by all columns for deterministic comparison
    sort_cols = common_cols
    expr_sorted = expr_sorted.sort_values(sort_cols, ignore_index=True)
    pandas_sorted = pandas_sorted.sort_values(sort_cols, ignore_index=True)

    for col_name in common_cols:
        e_col = expr_sorted[col_name]
        p_col = pandas_sorted[col_name]

        if pd.api.types.is_numeric_dtype(e_col) and pd.api.types.is_numeric_dtype(p_col):
            pd.testing.assert_series_equal(
                e_col.astype(float),
                p_col.astype(float),
                check_names=False,
                rtol=rtol,
                atol=1e-10,
            )
        else:
            pd.testing.assert_series_equal(
                e_col.astype(str),
                p_col.astype(str),
                check_names=False,
            )


def _create_polars_context():
    """Create a Polars expression-family context."""
    adapter = PolarsDataFrameAdapter()
    return adapter.create_context()


def _create_pandas_context():
    """Create a Pandas family context."""
    adapter = PandasDataFrameAdapter()
    return adapter.create_context()


# =============================================================================
# H2ODB Fixture Data (single "trips" table)
# =============================================================================


def _h2odb_trips_polars() -> pl.LazyFrame:
    """Create a small H2ODB-compatible trips table as Polars LazyFrame."""
    return pl.DataFrame(
        {
            "vendor_id": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "passenger_count": [1, 1, 2, 2, 3, 3, 1, 2, 3, 1],
            "fare_amount": [10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 8.0, 35.0],
            "pickup_datetime": [
                datetime(2024, 1, 1, 8, 0),
                datetime(2024, 1, 1, 9, 30),
                datetime(2024, 1, 1, 14, 15),
                datetime(2024, 1, 2, 8, 0),
                datetime(2024, 1, 2, 17, 45),
                datetime(2024, 1, 3, 10, 0),
                datetime(2024, 1, 3, 22, 0),
                datetime(2024, 2, 1, 8, 0),
                datetime(2024, 2, 1, 12, 30),
                datetime(2024, 2, 2, 15, 0),
            ],
            "pickup_location_id": [100, 200, 100, 300, 200, None, 100, 300, 200, 100],
        }
    ).lazy()


def _h2odb_trips_pandas() -> pd.DataFrame:
    """Create a small H2ODB-compatible trips table as Pandas DataFrame."""
    return pd.DataFrame(
        {
            "vendor_id": [1, 2, 1, 2, 1, 2, 1, 2, 1, 2],
            "passenger_count": [1, 1, 2, 2, 3, 3, 1, 2, 3, 1],
            "fare_amount": [10.0, 20.0, 15.0, 25.0, 30.0, 12.0, 18.0, 22.0, 8.0, 35.0],
            "pickup_datetime": pd.to_datetime(
                [
                    "2024-01-01 08:00",
                    "2024-01-01 09:30",
                    "2024-01-01 14:15",
                    "2024-01-02 08:00",
                    "2024-01-02 17:45",
                    "2024-01-03 10:00",
                    "2024-01-03 22:00",
                    "2024-02-01 08:00",
                    "2024-02-01 12:30",
                    "2024-02-02 15:00",
                ]
            ),
            "pickup_location_id": [100.0, 200.0, 100.0, 300.0, 200.0, float("nan"), 100.0, 300.0, 200.0, 100.0],
        }
    )


# =============================================================================
# SSB Fixture Data (lineorder + date tables)
# =============================================================================


def _ssb_lineorder_polars() -> pl.LazyFrame:
    """Create a small SSB lineorder table as Polars LazyFrame."""
    return pl.DataFrame(
        {
            "lo_orderdate": [19930101, 19930115, 19930201, 19940101, 19940215, 19930310],
            "lo_extendedprice": [1000.0, 2000.0, 1500.0, 2500.0, 3000.0, 500.0],
            "lo_discount": [2, 1, 3, 2, 4, 2],
            "lo_quantity": [10, 20, 15, 5, 30, 24],
            "lo_revenue": [980.0, 1980.0, 1455.0, 2450.0, 2880.0, 490.0],
            "lo_supplycost": [100.0, 200.0, 150.0, 250.0, 300.0, 50.0],
            "lo_custkey": [1, 2, 1, 3, 2, 1],
            "lo_partkey": [10, 20, 10, 30, 20, 10],
            "lo_suppkey": [100, 200, 100, 300, 200, 100],
        }
    ).lazy()


def _ssb_date_polars() -> pl.LazyFrame:
    """Create a small SSB date table as Polars LazyFrame."""
    return pl.DataFrame(
        {
            "d_datekey": [19930101, 19930115, 19930201, 19930310, 19940101, 19940215],
            "d_year": [1993, 1993, 1993, 1993, 1994, 1994],
            "d_yearmonthnum": [199301, 199301, 199302, 199303, 199401, 199402],
            "d_weeknuminyear": [1, 3, 5, 10, 1, 7],
        }
    ).lazy()


def _ssb_lineorder_pandas() -> pd.DataFrame:
    """Create a small SSB lineorder table as Pandas DataFrame."""
    return pd.DataFrame(
        {
            "lo_orderdate": [19930101, 19930115, 19930201, 19940101, 19940215, 19930310],
            "lo_extendedprice": [1000.0, 2000.0, 1500.0, 2500.0, 3000.0, 500.0],
            "lo_discount": [2, 1, 3, 2, 4, 2],
            "lo_quantity": [10, 20, 15, 5, 30, 24],
            "lo_revenue": [980.0, 1980.0, 1455.0, 2450.0, 2880.0, 490.0],
            "lo_supplycost": [100.0, 200.0, 150.0, 250.0, 300.0, 50.0],
            "lo_custkey": [1, 2, 1, 3, 2, 1],
            "lo_partkey": [10, 20, 10, 30, 20, 10],
            "lo_suppkey": [100, 200, 100, 300, 200, 100],
        }
    )


def _ssb_date_pandas() -> pd.DataFrame:
    """Create a small SSB date table as Pandas DataFrame."""
    return pd.DataFrame(
        {
            "d_datekey": [19930101, 19930115, 19930201, 19930310, 19940101, 19940215],
            "d_year": [1993, 1993, 1993, 1993, 1994, 1994],
            "d_yearmonthnum": [199301, 199301, 199302, 199303, 199401, 199402],
            "d_weeknuminyear": [1, 3, 5, 10, 1, 7],
        }
    )


# =============================================================================
# H2ODB Execution Tests - Expression Family (Polars)
# =============================================================================


class TestH2ODBExpressionExecution:
    """Execute all H2ODB queries against Polars and verify results."""

    @pytest.fixture(autouse=True)
    def setup_context(self):
        """Set up a Polars context with H2ODB test data."""
        self.ctx = _create_polars_context()
        self.ctx.register_table("trips", _h2odb_trips_polars())

    def _execute(self, query_id: str) -> pd.DataFrame:
        from benchbox.core.h2odb.dataframe_queries import get_h2odb_query

        query = get_h2odb_query(query_id)
        result = query.expression_impl(self.ctx)
        return _to_pandas(result)

    def test_q1_count(self):
        result = self._execute("Q1")
        assert "count" in result.columns
        assert result["count"].iloc[0] == 10

    def test_q2_sum_mean(self):
        result = self._execute("Q2")
        assert "sum_fare_amount" in result.columns
        assert "mean_fare_amount" in result.columns
        assert abs(result["sum_fare_amount"].iloc[0] - 195.0) < 0.01
        assert abs(result["mean_fare_amount"].iloc[0] - 19.5) < 0.01

    def test_q3_sum_by_passenger(self):
        result = self._execute("Q3")
        assert len(result) == 3  # 3 distinct passenger_counts
        assert "passenger_count" in result.columns
        assert "sum_fare_amount" in result.columns

    def test_q4_sum_mean_by_passenger(self):
        result = self._execute("Q4")
        assert len(result) == 3
        assert "sum_fare_amount" in result.columns
        assert "mean_fare_amount" in result.columns

    def test_q5_sum_by_passenger_vendor(self):
        result = self._execute("Q5")
        assert "passenger_count" in result.columns
        assert "vendor_id" in result.columns
        assert "sum_fare_amount" in result.columns
        assert len(result) == 6  # 3 passengers x 2 vendors

    def test_q6_sum_mean_by_passenger_vendor(self):
        result = self._execute("Q6")
        assert len(result) == 6
        assert "sum_fare_amount" in result.columns
        assert "mean_fare_amount" in result.columns

    def test_q7_sum_by_hour(self):
        result = self._execute("Q7")
        assert "hour" in result.columns
        assert "sum_fare_amount" in result.columns
        assert len(result) > 0

    def test_q8_sum_by_year_hour(self):
        result = self._execute("Q8")
        assert "year" in result.columns
        assert "hour" in result.columns
        assert "sum_fare_amount" in result.columns

    def test_q9_percentiles(self):
        result = self._execute("Q9")
        assert "median_fare_amount" in result.columns
        assert "p90_fare_amount" in result.columns
        assert len(result) == 3

    def test_q10_top_locations(self):
        result = self._execute("Q10")
        assert "pickup_location_id" in result.columns
        assert "trip_count" in result.columns
        # NULL location filtered out, so 3 distinct locations
        assert len(result) == 3


# =============================================================================
# H2ODB Execution Tests - Pandas Family
# =============================================================================


class TestH2ODBPandasExecution:
    """Execute all H2ODB queries against Pandas and verify results."""

    @pytest.fixture(autouse=True)
    def setup_context(self):
        """Set up a Pandas context with H2ODB test data."""
        self.ctx = _create_pandas_context()
        self.ctx.register_table("trips", _h2odb_trips_pandas())

    def _execute(self, query_id: str) -> pd.DataFrame:
        from benchbox.core.h2odb.dataframe_queries import get_h2odb_query

        query = get_h2odb_query(query_id)
        result = query.pandas_impl(self.ctx)
        return _to_pandas(result)

    def test_q1_count(self):
        result = self._execute("Q1")
        assert "count" in result.columns
        assert result["count"].iloc[0] == 10

    def test_q2_sum_mean(self):
        result = self._execute("Q2")
        assert abs(result["sum_fare_amount"].iloc[0] - 195.0) < 0.01

    def test_q3_sum_by_passenger(self):
        result = self._execute("Q3")
        assert len(result) == 3

    def test_q4_sum_mean_by_passenger(self):
        result = self._execute("Q4")
        assert len(result) == 3

    def test_q5_sum_by_passenger_vendor(self):
        result = self._execute("Q5")
        assert len(result) == 6

    def test_q6_sum_mean_by_passenger_vendor(self):
        result = self._execute("Q6")
        assert len(result) == 6

    def test_q7_sum_by_hour(self):
        result = self._execute("Q7")
        assert "hour" in result.columns
        assert len(result) > 0

    def test_q8_sum_by_year_hour(self):
        result = self._execute("Q8")
        assert "year" in result.columns
        assert "hour" in result.columns

    def test_q9_percentiles(self):
        result = self._execute("Q9")
        assert "median_fare_amount" in result.columns
        assert len(result) == 3

    def test_q10_top_locations(self):
        result = self._execute("Q10")
        assert len(result) == 3


# =============================================================================
# H2ODB Cross-Family Comparison (Expression vs Pandas)
# =============================================================================

H2ODB_QUERY_IDS = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10"]


class TestH2ODBCrossFamilyComparison:
    """Verify Expression and Pandas implementations produce equivalent results."""

    @pytest.fixture(autouse=True)
    def setup_contexts(self):
        """Set up both Polars and Pandas contexts with identical data."""
        self.expr_ctx = _create_polars_context()
        self.expr_ctx.register_table("trips", _h2odb_trips_polars())

        self.pandas_ctx = _create_pandas_context()
        self.pandas_ctx.register_table("trips", _h2odb_trips_pandas())

    @pytest.mark.parametrize("query_id", H2ODB_QUERY_IDS)
    def test_expression_vs_pandas(self, query_id: str):
        """Verify expression and pandas implementations return equivalent results."""
        from benchbox.core.h2odb.dataframe_queries import get_h2odb_query

        query = get_h2odb_query(query_id)

        expr_result = _to_pandas(query.expression_impl(self.expr_ctx))
        pandas_result = _to_pandas(query.pandas_impl(self.pandas_ctx))

        # Q9 (percentile): Polars uses "nearest" interpolation for quantile
        # while Pandas uses "linear".  On small datasets this causes large
        # relative differences (e.g., p90 of [10,20] → 20 vs 19).  We still
        # validate column names and row counts but skip numeric comparison.
        if query_id == "Q9":
            assert sorted(expr_result.columns) == sorted(pandas_result.columns)
            assert len(expr_result) == len(pandas_result)
        else:
            _compare_results(expr_result, pandas_result)


# =============================================================================
# SSB Execution Tests - Cross-Family for Q1.1 (join + filter + scalar agg)
# =============================================================================


class TestSSBQ11Execution:
    """Execute SSB Q1.1 on both families and verify cross-family equivalence.

    Q1.1 tests: 2-table join -> multi-column filter -> scalar aggregation.
    This covers a fundamentally different pattern than H2ODB (single-table).
    """

    @pytest.fixture(autouse=True)
    def setup_contexts(self):
        """Set up Polars and Pandas contexts with SSB fixture data."""
        self.expr_ctx = _create_polars_context()
        self.expr_ctx.register_table("lineorder", _ssb_lineorder_polars())
        self.expr_ctx.register_table("date", _ssb_date_polars())

        self.pandas_ctx = _create_pandas_context()
        self.pandas_ctx.register_table("lineorder", _ssb_lineorder_pandas())
        self.pandas_ctx.register_table("date", _ssb_date_pandas())

    def test_q1_1_expression_executes(self):
        """Q1.1 expression impl produces a result."""
        from benchbox.core.ssb.dataframe_queries import get_ssb_query

        query = get_ssb_query("Q1.1")
        result = _to_pandas(query.expression_impl(self.expr_ctx))
        assert "revenue" in result.columns
        assert len(result) == 1  # scalar aggregation

    def test_q1_1_pandas_executes(self):
        """Q1.1 pandas impl produces a result."""
        from benchbox.core.ssb.dataframe_queries import get_ssb_query

        query = get_ssb_query("Q1.1")
        result = _to_pandas(query.pandas_impl(self.pandas_ctx))
        assert "revenue" in result.columns
        assert len(result) == 1

    def test_q1_1_cross_family_equivalence(self):
        """Q1.1 expression and pandas produce the same revenue."""
        from benchbox.core.ssb.dataframe_queries import get_ssb_query

        query = get_ssb_query("Q1.1")
        expr_result = _to_pandas(query.expression_impl(self.expr_ctx))
        pandas_result = _to_pandas(query.pandas_impl(self.pandas_ctx))

        _compare_results(expr_result, pandas_result)

    def test_q1_1_revenue_value_correct(self):
        """Q1.1 revenue matches hand-calculated expected value.

        SSB Q1.1 params: year=1993, discount_min=1, discount_max=3, quantity<25.
        Matching rows after join (d_year==1993 AND 1<=lo_discount<=3 AND lo_quantity<25):
          - lo_orderdate=19930101: price=1000, disc=2, qty=10 -> 1000*2 = 2000
          - lo_orderdate=19930115: price=2000, disc=1, qty=20 -> 2000*1 = 2000
          - lo_orderdate=19930201: price=1500, disc=3, qty=15 -> 1500*3 = 4500
          - lo_orderdate=19930310: price=500,  disc=2, qty=24 -> 500*2  = 1000
        Total revenue = 2000 + 2000 + 4500 + 1000 = 9500
        """
        from benchbox.core.ssb.dataframe_queries import get_ssb_query

        query = get_ssb_query("Q1.1")
        result = _to_pandas(query.expression_impl(self.expr_ctx))
        assert abs(result["revenue"].iloc[0] - 9500.0) < 0.01


# =============================================================================
# CoffeeShop Fixture Data (order_lines + dim_locations)
# =============================================================================


def _coffeeshop_order_lines_polars() -> pl.LazyFrame:
    """Create a small CoffeeShop order_lines table as Polars LazyFrame."""
    return pl.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "order_date": [
                date(2023, 1, 5),
                date(2023, 2, 10),
                date(2023, 4, 15),
                date(2023, 7, 20),
                date(2023, 10, 25),
                date(2024, 1, 5),
                date(2024, 4, 10),
                date(2024, 7, 15),
            ],
            "total_price": [50.0, 75.0, 100.0, 120.0, 90.0, 60.0, 80.0, 110.0],
            "location_record_id": [1, 2, 1, 2, 1, 2, 1, 2],
        }
    ).lazy()


def _coffeeshop_dim_locations_polars() -> pl.LazyFrame:
    """Create a small CoffeeShop dim_locations table as Polars LazyFrame."""
    return pl.DataFrame(
        {
            "record_id": [1, 2],
            "region": ["North", "South"],
        }
    ).lazy()


def _coffeeshop_order_lines_pandas() -> pd.DataFrame:
    """Create a small CoffeeShop order_lines table as Pandas DataFrame."""
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4, 5, 6, 7, 8],
            "order_date": pd.to_datetime(
                [
                    "2023-01-05",
                    "2023-02-10",
                    "2023-04-15",
                    "2023-07-20",
                    "2023-10-25",
                    "2024-01-05",
                    "2024-04-10",
                    "2024-07-15",
                ]
            ),
            "total_price": [50.0, 75.0, 100.0, 120.0, 90.0, 60.0, 80.0, 110.0],
            "location_record_id": [1, 2, 1, 2, 1, 2, 1, 2],
        }
    )


def _coffeeshop_dim_locations_pandas() -> pd.DataFrame:
    """Create a small CoffeeShop dim_locations table as Pandas DataFrame."""
    return pd.DataFrame(
        {
            "record_id": [1, 2],
            "region": ["North", "South"],
        }
    )


# =============================================================================
# CoffeeShop SA4 Execution Tests (zero-division guard + scalar extraction)
# =============================================================================


class TestCoffeeShopSA4Execution:
    """Execute CoffeeShop SA4 to verify the scalar extraction and zero-division fixes."""

    # Patch CoffeeShop parameters to use datetime objects instead of strings.
    # Polars rejects string-to-Date comparison, and Pandas rejects date-to-datetime64
    # comparison, but both accept datetime objects.
    SA4_PARAMS = {"start_date": datetime(2023, 1, 1), "end_date": datetime(2024, 12, 31)}

    @pytest.fixture(autouse=True)
    def setup_contexts(self):
        """Set up both contexts with CoffeeShop data."""
        self.expr_ctx = _create_polars_context()
        self.expr_ctx.register_table("order_lines", _coffeeshop_order_lines_polars())
        self.expr_ctx.register_table("dim_locations", _coffeeshop_dim_locations_polars())

        self.pandas_ctx = _create_pandas_context()
        self.pandas_ctx.register_table("order_lines", _coffeeshop_order_lines_pandas())
        self.pandas_ctx.register_table("dim_locations", _coffeeshop_dim_locations_pandas())

    def _patched_get_params(self, query_id: str):
        from benchbox.core.coffeeshop.dataframe_queries.parameters import CoffeeShopParameters

        return CoffeeShopParameters(query_id=query_id, params=self.SA4_PARAMS.copy())

    def test_sa4_expression_executes(self):
        """SA4 expression impl produces results with revenue_share column."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("SA4")
        with patch("benchbox.core.coffeeshop.dataframe_queries.queries.get_parameters", self._patched_get_params):
            result = _to_pandas(query.expression_impl(self.expr_ctx))
        assert "revenue_share" in result.columns
        assert "revenue" in result.columns
        assert len(result) == 2  # 2 regions

    def test_sa4_pandas_executes(self):
        """SA4 pandas impl produces results with revenue_share column."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("SA4")
        with patch("benchbox.core.coffeeshop.dataframe_queries.queries.get_parameters", self._patched_get_params):
            result = _to_pandas(query.pandas_impl(self.pandas_ctx))
        assert "revenue_share" in result.columns
        assert len(result) == 2

    def test_sa4_revenue_shares_sum_to_one(self):
        """SA4 revenue shares across regions should sum to ~1.0."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("SA4")
        with patch("benchbox.core.coffeeshop.dataframe_queries.queries.get_parameters", self._patched_get_params):
            result = _to_pandas(query.expression_impl(self.expr_ctx))
        total_share = result["revenue_share"].sum()
        assert abs(total_share - 1.0) < 0.01

    def test_sa4_cross_family_equivalence(self):
        """SA4 expression and pandas produce equivalent results."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("SA4")
        with patch("benchbox.core.coffeeshop.dataframe_queries.queries.get_parameters", self._patched_get_params):
            expr_result = _to_pandas(query.expression_impl(self.expr_ctx))
            pandas_result = _to_pandas(query.pandas_impl(self.pandas_ctx))
        _compare_results(expr_result, pandas_result)


# =============================================================================
# CoffeeShop TR1 Execution Tests (quarter column alias fix)
# =============================================================================


class TestCoffeeShopTR1Execution:
    """Execute CoffeeShop TR1 to verify the quarter column alias fix."""

    @pytest.fixture(autouse=True)
    def setup_contexts(self):
        """Set up both contexts with CoffeeShop data."""
        self.expr_ctx = _create_polars_context()
        self.expr_ctx.register_table("order_lines", _coffeeshop_order_lines_polars())

        self.pandas_ctx = _create_pandas_context()
        self.pandas_ctx.register_table("order_lines", _coffeeshop_order_lines_pandas())

    def test_tr1_expression_has_quarter_column(self):
        """TR1 expression impl should have a 'quarter' column (not 'month')."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("TR1")
        result = _to_pandas(query.expression_impl(self.expr_ctx))
        assert "quarter" in result.columns
        assert "year" in result.columns
        assert "month" not in result.columns

    def test_tr1_quarter_values_correct(self):
        """TR1 quarter values should be 1-4, computed from month."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("TR1")
        result = _to_pandas(query.expression_impl(self.expr_ctx))
        quarters = sorted(result["quarter"].unique().tolist())
        # Our fixture data spans Jan, Feb, Apr, Jul, Oct (2023) + Jan, Apr, Jul (2024)
        # Q1=Jan/Feb, Q2=Apr, Q3=Jul, Q4=Oct
        assert all(q in [1, 2, 3, 4] for q in quarters)

    def test_tr1_cross_family_equivalence(self):
        """TR1 expression and pandas produce equivalent results."""
        from benchbox.core.coffeeshop.dataframe_queries import get_coffeeshop_query

        query = get_coffeeshop_query("TR1")
        expr_result = _to_pandas(query.expression_impl(self.expr_ctx))
        pandas_result = _to_pandas(query.pandas_impl(self.pandas_ctx))
        _compare_results(expr_result, pandas_result)


# =============================================================================
# Data Vault Q5 Fixture Data (8 hub/link/satellite tables)
# =============================================================================


def _datavault_tables_polars() -> dict[str, pl.LazyFrame]:
    """Create minimal Data Vault tables for Q5 testing (Polars)."""
    from datetime import date as d

    sat_region = pl.DataFrame({"hk_region": [1], "r_name": ["ASIA"], "load_end_dts": [None]}).lazy()
    link_nation_region = pl.DataFrame({"hk_region": [1, 1], "hk_nation": [10, 11]}).lazy()
    sat_nation = pl.DataFrame(
        {"hk_nation": [10, 11], "n_name": ["CHINA", "JAPAN"], "load_end_dts": [None, None]}
    ).lazy()
    link_customer_nation = pl.DataFrame({"hk_nation": [10, 11], "hk_customer": [100, 101]}).lazy()
    link_order_customer = pl.DataFrame({"hk_customer": [100, 101], "hk_order": [1000, 1001]}).lazy()
    sat_order = pl.DataFrame(
        {
            "hk_order": [1000, 1001],
            "o_orderdate": [d(1994, 6, 1), d(1994, 8, 15)],
            "load_end_dts": [None, None],
        }
    ).lazy()
    link_lineitem = pl.DataFrame({"hk_order": [1000, 1001], "hk_lineitem_link": [5000, 5001]}).lazy()
    sat_lineitem = pl.DataFrame(
        {
            "hk_lineitem_link": [5000, 5001],
            "l_extendedprice": [1000.0, 2000.0],
            "l_discount": [0.1, 0.05],
            "hk_supplier": [200, 201],
            "load_end_dts": [None, None],
        }
    ).lazy()
    # link_supplier_nation: supplier 200 is in nation 10, supplier 201 is in nation 11
    link_supplier_nation = pl.DataFrame({"hk_nation": [10, 11], "hk_supplier": [200, 201]}).lazy()
    return {
        "sat_region": sat_region,
        "link_nation_region": link_nation_region,
        "sat_nation": sat_nation,
        "link_customer_nation": link_customer_nation,
        "link_order_customer": link_order_customer,
        "sat_order": sat_order,
        "link_lineitem": link_lineitem,
        "sat_lineitem": sat_lineitem,
        "link_supplier_nation": link_supplier_nation,
    }


def _datavault_tables_pandas() -> dict[str, pd.DataFrame]:
    """Create minimal Data Vault tables for Q5 testing (Pandas)."""
    from datetime import date as d

    sat_region = pd.DataFrame({"hk_region": [1], "r_name": ["ASIA"], "load_end_dts": [None]})
    link_nation_region = pd.DataFrame({"hk_region": [1, 1], "hk_nation": [10, 11]})
    sat_nation = pd.DataFrame({"hk_nation": [10, 11], "n_name": ["CHINA", "JAPAN"], "load_end_dts": [None, None]})
    link_customer_nation = pd.DataFrame({"hk_nation": [10, 11], "hk_customer": [100, 101]})
    link_order_customer = pd.DataFrame({"hk_customer": [100, 101], "hk_order": [1000, 1001]})
    sat_order = pd.DataFrame(
        {
            "hk_order": [1000, 1001],
            "o_orderdate": [d(1994, 6, 1), d(1994, 8, 15)],
            "load_end_dts": [None, None],
        }
    )
    link_lineitem = pd.DataFrame({"hk_order": [1000, 1001], "hk_lineitem_link": [5000, 5001]})
    sat_lineitem = pd.DataFrame(
        {
            "hk_lineitem_link": [5000, 5001],
            "l_extendedprice": [1000.0, 2000.0],
            "l_discount": [0.1, 0.05],
            "hk_supplier": [200, 201],
            "load_end_dts": [None, None],
        }
    )
    link_supplier_nation = pd.DataFrame({"hk_nation": [10, 11], "hk_supplier": [200, 201]})
    return {
        "sat_region": sat_region,
        "link_nation_region": link_nation_region,
        "sat_nation": sat_nation,
        "link_customer_nation": link_customer_nation,
        "link_order_customer": link_order_customer,
        "sat_order": sat_order,
        "link_lineitem": link_lineitem,
        "sat_lineitem": sat_lineitem,
        "link_supplier_nation": link_supplier_nation,
    }


# =============================================================================
# Data Vault Q5 Execution Tests (explicit suffix fix)
# =============================================================================


class TestDataVaultQ5Execution:
    """Execute Data Vault Q5 to verify the explicit suffix fix for join disambiguation."""

    @pytest.fixture(autouse=True)
    def setup_contexts(self):
        """Set up both contexts with Data Vault fixture data."""
        self.expr_ctx = _create_polars_context()
        for name, df in _datavault_tables_polars().items():
            self.expr_ctx.register_table(name, df)

        self.pandas_ctx = _create_pandas_context()
        for name, df in _datavault_tables_pandas().items():
            self.pandas_ctx.register_table(name, df)

    def test_q5_expression_executes(self):
        """Q5 expression impl executes without errors on the suffix-fixed join chain."""
        from benchbox.core.datavault.dataframe_queries import get_datavault_query

        query = get_datavault_query("Q5")
        result = _to_pandas(query.expression_impl(self.expr_ctx))
        assert "n_name" in result.columns
        assert "revenue" in result.columns
        assert len(result) > 0

    def test_q5_pandas_executes(self):
        """Q5 pandas impl executes without errors."""
        from benchbox.core.datavault.dataframe_queries import get_datavault_query

        query = get_datavault_query("Q5")
        result = _to_pandas(query.pandas_impl(self.pandas_ctx))
        assert "n_name" in result.columns
        assert "revenue" in result.columns
        assert len(result) > 0

    def test_q5_revenue_values_correct(self):
        """Q5 revenue is correctly computed as extendedprice * (1 - discount).

        Fixture data:
          - CHINA:  supplier 200 matches nation 10 → 1000 * (1 - 0.1) = 900
          - JAPAN:  supplier 201 matches nation 11 → 2000 * (1 - 0.05) = 1900
        """
        from benchbox.core.datavault.dataframe_queries import get_datavault_query

        query = get_datavault_query("Q5")
        result = _to_pandas(query.expression_impl(self.expr_ctx))
        result_sorted = result.sort_values("n_name").reset_index(drop=True)
        assert abs(result_sorted.loc[0, "revenue"] - 900.0) < 0.01  # CHINA
        assert abs(result_sorted.loc[1, "revenue"] - 1900.0) < 0.01  # JAPAN

    def test_q5_cross_family_equivalence(self):
        """Q5 expression and pandas produce equivalent results."""
        from benchbox.core.datavault.dataframe_queries import get_datavault_query

        query = get_datavault_query("Q5")
        expr_result = _to_pandas(query.expression_impl(self.expr_ctx))
        pandas_result = _to_pandas(query.pandas_impl(self.pandas_ctx))
        _compare_results(expr_result, pandas_result)
