"""Tests for TPC-Havoc DataFrame variant registration."""

from __future__ import annotations

from datetime import date

import pytest

try:
    import polars as pl
    from polars.testing import assert_frame_equal

    from benchbox.platforms.dataframe.polars_df import POLARS_AVAILABLE, PolarsDataFrameAdapter
except ImportError:  # pragma: no cover - dependency-gated tests
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]
    assert_frame_equal = None  # type: ignore[assignment]
    PolarsDataFrameAdapter = None  # type: ignore[assignment]

from benchbox.core.benchmark_registry import BENCHMARK_METADATA
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory
from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.dataframe_queries import get_dataframe_queries, get_query, list_query_ids

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

Q1_COLUMNS = [
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
]


class TestTPCHavocDataFrameRegistry:
    """DataFrame registry metadata coverage."""

    def test_all_220_variants_registered(self) -> None:
        registry = get_dataframe_queries()
        assert len(registry) == 220

    def test_registry_returns_singleton(self) -> None:
        assert get_dataframe_queries() is get_dataframe_queries()

    @pytest.mark.parametrize("query_number", range(1, 23))
    def test_each_query_has_10_variants(self, query_number: int) -> None:
        ids = list_query_ids()
        expected = {f"Q{query_number}v{variant}" for variant in range(1, 11)}
        assert expected.issubset(ids)

    def test_all_variants_have_both_families_and_categories(self) -> None:
        for query in get_dataframe_queries().get_all_queries():
            assert isinstance(query, DataFrameQuery)
            assert query.has_expression_impl(), f"{query.query_id} missing expression_impl"
            assert query.has_pandas_impl(), f"{query.query_id} missing pandas_impl"
            assert query.categories, f"{query.query_id} missing categories"

    def test_query_lookup(self) -> None:
        query = get_query("Q1v1")
        assert query.query_id == "Q1v1"
        assert QueryCategory.AGGREGATE in query.categories

    def test_benchmark_registry_supports_dataframe(self) -> None:
        assert BENCHMARK_METADATA["tpchavoc"]["supports_dataframe"] is True

    def test_benchmark_class_exposes_dataframe_registry(self) -> None:
        benchmark = TPCHavocBenchmark(scale_factor=0.01)
        assert benchmark.supports_dataframe_mode() is True
        assert len(benchmark.get_dataframe_queries()) == 220


@pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
class TestQ1Equivalence:
    """Q1 variants should preserve canonical TPC-H output."""

    @pytest.fixture
    def q1_context(self):
        ctx = PolarsDataFrameAdapter().create_context()
        ctx.register_table(
            "lineitem",
            pl.DataFrame(
                {
                    "l_orderkey": [1, 2, 3, 4],
                    "l_quantity": [5.0, 10.0, 7.0, 9.0],
                    "l_extendedprice": [100.0, 200.0, 150.0, 300.0],
                    "l_discount": [0.05, 0.10, 0.00, 0.02],
                    "l_tax": [0.02, 0.05, 0.03, 0.01],
                    "l_returnflag": ["A", "A", "N", "R"],
                    "l_linestatus": ["F", "F", "O", "F"],
                    "l_shipdate": [
                        date(1994, 1, 1),
                        date(1995, 1, 1),
                        date(1996, 1, 1),
                        date(1997, 1, 1),
                    ],
                }
            ).lazy(),
        )
        return ctx

    def test_q1_equivalence_expression_variants(self, q1_context) -> None:
        base = _collect_q1(get_query("Q1v1").expression_impl(q1_context))
        for variant_id in range(2, 11):
            query = get_query(f"Q1v{variant_id}")
            result = _collect_q1(query.expression_impl(q1_context))
            assert_frame_equal(result, base)


def _collect_q1(result) -> pl.DataFrame:
    if hasattr(result, "native"):
        result = result.native
    if hasattr(result, "collect"):
        result = result.collect()
    return result.select(Q1_COLUMNS).sort(["l_returnflag", "l_linestatus"])


def _collect_scalar(result) -> pl.DataFrame:
    """Collect any expression-family or native frame to a plain Polars DataFrame."""
    if hasattr(result, "native"):
        result = result.native
    if hasattr(result, "collect"):
        result = result.collect()
    return result


@pytest.mark.skipif(not POLARS_AVAILABLE, reason="Polars not installed")
class TestQ14v8Regression:
    """Regression tests for Q14v8 expression implementation.

    Q14v8 uses a dual-join approach (separate promo/non-promo part tables) and
    must return a native expression-family frame - not a Pandas DataFrame and
    not the result of ctx.scalar().
    """

    @pytest.fixture
    def q14_context(self):
        """Minimal synthetic Q14 context.

        Lineitem rows within the 1995-09 window:
          partkey=10, extprice=100, disc=0  → promo (PROMO ANODIZED STEEL)
          partkey=20, extprice=200, disc=0  → non-promo (STANDARD BRASS)

        Expected promo_revenue = 100 * 100 / 300 = 33.333...
        """
        ctx = PolarsDataFrameAdapter().create_context()
        ctx.register_table(
            "lineitem",
            pl.DataFrame(
                {
                    "l_orderkey": [1, 2, 3, 4],
                    "l_partkey": [10, 20, 30, 40],
                    "l_extendedprice": [100.0, 200.0, 999.0, 999.0],
                    "l_discount": [0.0, 0.0, 0.0, 0.0],
                    "l_shipdate": [
                        date(1995, 9, 2),  # within window → row included
                        date(1995, 9, 15),  # within window → row included
                        date(1994, 1, 1),  # before window → excluded
                        date(1995, 10, 1),  # at exclusive end → excluded
                    ],
                }
            ).lazy(),
        )
        ctx.register_table(
            "part",
            pl.DataFrame(
                {
                    "p_partkey": [10, 20, 30, 40],
                    "p_type": [
                        "PROMO ANODIZED STEEL",
                        "STANDARD BRASS",
                        "PROMO PLATED TIN",
                        "ECONOMY ANODIZED",
                    ],
                }
            ).lazy(),
        )
        return ctx

    def test_q14v8_expression_executes_without_error(self, q14_context) -> None:
        """Q14v8 expression_impl must not raise - specifically no ctx.scalar() or Pandas attrs."""
        query = get_query("Q14v8")
        result = _collect_scalar(query.expression_impl(q14_context))
        assert "promo_revenue" in result.columns

    def test_q14v8_expression_result_shape(self, q14_context) -> None:
        """Q14v8 must produce exactly one row with a promo_revenue column."""
        query = get_query("Q14v8")
        result = _collect_scalar(query.expression_impl(q14_context))
        assert result.shape == (1, 1)
        assert result.columns == ["promo_revenue"]

    def test_q14v8_promo_revenue_value(self, q14_context) -> None:
        """Q14v8 promo_revenue must equal 100 * promo_sum / total_sum."""
        # Only rows 1 and 2 fall in the 1995-09 window.
        # Row 1: partkey=10 → PROMO → revenue=100
        # Row 2: partkey=20 → not PROMO → revenue=200
        # promo_revenue = 100 * 100 / 300 = 33.333...
        query = get_query("Q14v8")
        result = _collect_scalar(query.expression_impl(q14_context))
        value = result["promo_revenue"][0]
        assert abs(value - 100.0 * 100.0 / 300.0) < 1e-6

    def test_q14v8_parity_with_q14v1(self, q14_context) -> None:
        """Q14v8 expression result must match Q14v1 on identical synthetic data."""
        v1 = _collect_scalar(get_query("Q14v1").expression_impl(q14_context))
        v8 = _collect_scalar(get_query("Q14v8").expression_impl(q14_context))
        assert_frame_equal(v8, v1, check_exact=False, atol=1e-6)
