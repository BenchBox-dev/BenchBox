"""Tests for query plan comparison summary functionality."""

from __future__ import annotations

import pytest

from benchbox.core.query_plans.comparison import (
    PerformanceCorrelation,
    PlanComparisonSummary,
    QueryPlanChange,
    generate_plan_comparison_summary,
)
from benchbox.core.results.query_plan_models import (
    LogicalOperator,
    LogicalOperatorType,
    QueryPlanDAG,
)
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _qr(query_id: str, execution_time_ms: float = 100.0, query_plan: QueryPlanDAG | None = None) -> dict:
    """Build a query_results dict matching the real BenchmarkResults.query_results shape."""
    return {"query_id": query_id, "execution_time_ms": execution_time_ms, "query_plan": query_plan}


def _create_simple_plan(query_id: str, table_name: str = "orders") -> QueryPlanDAG:
    """Create a simple query plan for testing."""
    root = LogicalOperator(
        operator_id="1",
        operator_type=LogicalOperatorType.SCAN,
        table_name=table_name,
        children=[],
    )
    return QueryPlanDAG(
        query_id=query_id,
        platform="test",
        logical_root=root,
        plan_fingerprint=f"fp_{query_id}_{table_name}",
        raw_explain_output="test",
    )


def _create_join_plan(query_id: str) -> QueryPlanDAG:
    """Create a join query plan for testing."""
    left_scan = LogicalOperator(
        operator_id="2",
        operator_type=LogicalOperatorType.SCAN,
        table_name="orders",
        children=[],
    )
    right_scan = LogicalOperator(
        operator_id="3",
        operator_type=LogicalOperatorType.SCAN,
        table_name="customers",
        children=[],
    )
    root = LogicalOperator(
        operator_id="1",
        operator_type=LogicalOperatorType.JOIN,
        children=[left_scan, right_scan],
    )
    return QueryPlanDAG(
        query_id=query_id,
        platform="test",
        logical_root=root,
        plan_fingerprint=f"fp_join_{query_id}",
        raw_explain_output="test",
    )


class TestPlanComparisonSummary:
    """Tests for PlanComparisonSummary dataclass."""

    def test_to_dict_basic(self) -> None:
        """Test basic to_dict conversion."""
        summary = PlanComparisonSummary(
            baseline_run_id="run1",
            current_run_id="run2",
            plans_compared=5,
            plans_unchanged=3,
            plans_changed=2,
            structural_differences=[],
            performance_correlations=[],
        )

        result = summary.to_dict()

        assert result["baseline_run_id"] == "run1"
        assert result["current_run_id"] == "run2"
        assert result["plans_compared"] == 5
        assert result["plans_unchanged"] == 3
        assert result["plans_changed"] == 2
        assert result["structural_differences"] == []
        assert result["performance_correlations"] == []

    def test_to_dict_with_differences(self) -> None:
        """Test to_dict with structural differences."""
        summary = PlanComparisonSummary(
            baseline_run_id="run1",
            current_run_id="run2",
            plans_compared=2,
            plans_unchanged=1,
            plans_changed=1,
            structural_differences=[
                QueryPlanChange(
                    query_id="q1",
                    change_type="type_change",
                    similarity=0.75,
                    details="Operator type changed",
                ),
            ],
            performance_correlations=[
                PerformanceCorrelation(
                    query_id="q1",
                    plan_changed=True,
                    baseline_time_ms=100.0,
                    current_time_ms=150.0,
                    perf_change_pct=50.0,
                    is_regression=True,
                ),
            ],
        )

        result = summary.to_dict()

        assert len(result["structural_differences"]) == 1
        assert result["structural_differences"][0]["query_id"] == "q1"
        assert result["structural_differences"][0]["change_type"] == "type_change"
        assert result["structural_differences"][0]["similarity"] == 0.75

        assert len(result["performance_correlations"]) == 1
        assert result["performance_correlations"][0]["query_id"] == "q1"
        assert result["performance_correlations"][0]["is_regression"] is True
        assert result["performance_correlations"][0]["perf_change_pct"] == 50.0


class TestGeneratePlanComparisonSummary:
    """Tests for generate_plan_comparison_summary function."""

    def test_identical_plans(self) -> None:
        """Test comparison when all plans are identical."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_simple_plan("q1", "orders")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1)],
        )
        current = make_benchmark_results(
            run_id="current",
            query_results=[_qr("q1", 100.0, plan2)],
        )

        summary = generate_plan_comparison_summary(baseline, current)

        assert summary.baseline_run_id == "baseline"
        assert summary.current_run_id == "current"
        assert summary.plans_compared == 1
        assert summary.plans_unchanged == 1
        assert summary.plans_changed == 0

    def test_different_plans(self) -> None:
        """Test comparison when plans differ."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_simple_plan("q1", "customers")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1)],
        )
        current = make_benchmark_results(
            run_id="current",
            query_results=[_qr("q1", 100.0, plan2)],
        )

        summary = generate_plan_comparison_summary(baseline, current)

        assert summary.plans_compared == 1
        assert summary.plans_unchanged == 0
        assert summary.plans_changed == 1
        assert len(summary.structural_differences) == 1
        assert summary.structural_differences[0].query_id == "q1"
        assert summary.structural_differences[0].change_type != "unchanged"

    def test_multiple_queries(self) -> None:
        """Test comparison with multiple queries."""
        plan1a = _create_simple_plan("q1", "orders")
        plan1b = _create_simple_plan("q1", "orders")  # Same
        plan2a = _create_simple_plan("q2", "customers")
        plan2b = _create_simple_plan("q2", "products")  # Different

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1a), _qr("q2", 200.0, plan2a)],
        )
        current = make_benchmark_results(
            run_id="current",
            query_results=[_qr("q1", 100.0, plan1b), _qr("q2", 200.0, plan2b)],
        )

        summary = generate_plan_comparison_summary(baseline, current)

        assert summary.plans_compared == 2
        assert summary.plans_unchanged == 1
        assert summary.plans_changed == 1

    def test_regression_detection(self) -> None:
        """Test regression detection with performance degradation."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_join_plan("q1")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1)],
        )
        current = make_benchmark_results(
            run_id="current",
            # 150% slower (from 100ms to 250ms)
            query_results=[_qr("q1", 250.0, plan2)],
        )

        summary = generate_plan_comparison_summary(baseline, current, regression_threshold_pct=20.0)

        assert summary.plans_changed == 1
        assert len(summary.performance_correlations) == 1
        corr = summary.performance_correlations[0]
        assert corr.query_id == "q1"
        assert corr.plan_changed is True
        assert corr.baseline_time_ms == 100.0
        assert corr.current_time_ms == 250.0
        assert corr.perf_change_pct == 150.0
        assert corr.is_regression is True

    def test_no_regression_if_plan_unchanged(self) -> None:
        """Test that unchanged plans don't count as regressions even if slower."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_simple_plan("q1", "orders")  # Same plan

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1)],
        )
        current = make_benchmark_results(
            run_id="current",
            # Slower but plan unchanged
            query_results=[_qr("q1", 200.0, plan2)],
        )

        summary = generate_plan_comparison_summary(baseline, current, regression_threshold_pct=20.0)

        assert summary.plans_unchanged == 1
        assert len(summary.performance_correlations) == 1
        corr = summary.performance_correlations[0]
        assert corr.plan_changed is False
        assert corr.is_regression is False

    def test_custom_regression_threshold(self) -> None:
        """Test custom regression threshold."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_join_plan("q1")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1)],
        )
        current = make_benchmark_results(
            run_id="current",
            # 15% slower - below 20% threshold but above 10%
            query_results=[_qr("q1", 115.0, plan2)],
        )

        # With 20% threshold - not a regression
        summary20 = generate_plan_comparison_summary(baseline, current, regression_threshold_pct=20.0)
        assert summary20.performance_correlations[0].is_regression is False

        # With 10% threshold - is a regression
        summary10 = generate_plan_comparison_summary(baseline, current, regression_threshold_pct=10.0)
        assert summary10.performance_correlations[0].is_regression is True

    def test_missing_plans_skipped(self) -> None:
        """Test that queries without plans are skipped."""
        plan = _create_simple_plan("q1", "orders")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan), _qr("q2", 100.0, None)],  # q2: no plan
        )
        current = make_benchmark_results(
            run_id="current",
            query_results=[_qr("q1", 100.0, plan), _qr("q2", 100.0, None)],
        )

        summary = generate_plan_comparison_summary(baseline, current)

        assert summary.plans_compared == 1  # Only q1 with plans

    def test_non_common_queries_skipped(self) -> None:
        """Test that queries not in both runs are skipped."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_simple_plan("q2", "customers")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1)],
        )
        current = make_benchmark_results(
            run_id="current",
            query_results=[_qr("q2", 100.0, plan2)],
        )

        summary = generate_plan_comparison_summary(baseline, current)

        assert summary.plans_compared == 0  # No common queries

    def test_multiple_phases(self) -> None:
        """Test that all queries in query_results are collected regardless of phase."""
        plan1 = _create_simple_plan("q1", "orders")
        plan2 = _create_simple_plan("q2", "customers")

        baseline = make_benchmark_results(
            run_id="baseline",
            query_results=[_qr("q1", 100.0, plan1), _qr("q2", 200.0, plan2)],
        )
        current = make_benchmark_results(
            run_id="current",
            query_results=[_qr("q1", 100.0, plan1), _qr("q2", 200.0, plan2)],
        )

        summary = generate_plan_comparison_summary(baseline, current)

        assert summary.plans_compared == 2


class TestQueryPlanChange:
    """Tests for QueryPlanChange dataclass."""

    def test_creation(self) -> None:
        """Test QueryPlanChange creation."""
        change = QueryPlanChange(
            query_id="q1",
            change_type="structure_change",
            similarity=0.5,
            details="Major structural differences",
        )

        assert change.query_id == "q1"
        assert change.change_type == "structure_change"
        assert change.similarity == 0.5
        assert change.details == "Major structural differences"


class TestPerformanceCorrelation:
    """Tests for PerformanceCorrelation dataclass."""

    def test_creation(self) -> None:
        """Test PerformanceCorrelation creation."""
        corr = PerformanceCorrelation(
            query_id="q1",
            plan_changed=True,
            baseline_time_ms=100.0,
            current_time_ms=200.0,
            perf_change_pct=100.0,
            is_regression=True,
        )

        assert corr.query_id == "q1"
        assert corr.plan_changed is True
        assert corr.baseline_time_ms == 100.0
        assert corr.current_time_ms == 200.0
        assert corr.perf_change_pct == 100.0
        assert corr.is_regression is True
