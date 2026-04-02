"""Tests for query plan capture failure handling."""

from __future__ import annotations

import logging
import time
from typing import Any

import pytest

from benchbox.core.errors import PlanCaptureError
from benchbox.platforms.base.adapter import PlatformAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class DummyAdapter(PlatformAdapter):
    """Lightweight adapter for testing plan capture paths."""

    def __init__(
        self,
        explain_output: Any = "PLAN",
        parser: Any = None,
        explain_error: Exception | None = None,
        explain_delay_seconds: float = 0,
        **config,
    ):
        self._explain_output = explain_output
        self._parser = parser
        self._explain_error = explain_error
        self._explain_delay_seconds = explain_delay_seconds
        super().__init__(**config)

    @staticmethod
    def add_cli_arguments(parser) -> None:  # pragma: no cover - not used in tests
        return None

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        return cls(**config)

    def create_connection(self, **connection_config) -> Any:
        return None

    def create_schema(self, benchmark, connection: Any) -> float:
        return 0.0

    def get_target_dialect(self) -> str:
        return "generic"

    def apply_platform_optimizations(self, platform_config, connection: Any) -> None:
        return None

    def apply_constraint_configuration(self, primary_key_config, foreign_key_config, connection: Any) -> None:
        return None

    def load_data(self, benchmark, connection: Any, data_dir):
        return {}, 0.0, None

    def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
        return None

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        return {}

    def get_query_plan(self, connection: Any, query: str) -> Any:
        if self._explain_delay_seconds > 0:
            time.sleep(self._explain_delay_seconds)
        if self._explain_error:
            raise self._explain_error
        return self._explain_output

    def get_query_plan_parser(self):
        return self._parser


def test_parser_unavailable_records_warning(caplog: pytest.LogCaptureFixture) -> None:
    adapter = DummyAdapter(capture_plans=True)

    caplog.set_level(logging.WARNING)
    plan, capture_time_ms = adapter.capture_query_plan(None, "SELECT 1", "q1")

    assert plan is None
    assert capture_time_ms >= 0  # Timing is recorded even on failure
    assert adapter.query_plans_captured == 0
    assert adapter.plan_capture_failures == 1
    assert adapter.plan_capture_errors[0]["reason"] == "parser_unavailable"
    assert any("Query plan capture disabled" in record.message for record in caplog.records)


def test_strict_plan_capture_raises_error() -> None:
    adapter = DummyAdapter(
        capture_plans=True,
        strict_plan_capture=True,
        explain_error=RuntimeError("boom"),
    )

    with pytest.raises(PlanCaptureError) as excinfo:
        adapter.capture_query_plan(None, "SELECT 1", "q2")

    assert "boom" in str(excinfo.value)
    assert adapter.plan_capture_failures == 1
    assert adapter.plan_capture_errors[0]["reason"] == "explain_failed"


def test_plan_capture_failure_is_graceful_when_not_strict() -> None:
    adapter = DummyAdapter(capture_plans=True, explain_output="")

    plan, capture_time_ms = adapter.capture_query_plan(None, "SELECT 1", "q3")

    assert plan is None
    assert capture_time_ms >= 0
    assert adapter.plan_capture_failures == 1
    assert adapter.plan_capture_errors[0]["reason"] == "explain_failed"


def test_plan_capture_timeout_records_failure(caplog: pytest.LogCaptureFixture) -> None:
    """Test that slow EXPLAIN queries time out and record failure."""
    adapter = DummyAdapter(
        capture_plans=True,
        explain_delay_seconds=2.0,  # Simulate slow EXPLAIN
        plan_capture_timeout_seconds=1,  # 1 second timeout
    )

    caplog.set_level(logging.WARNING)
    plan, capture_time_ms = adapter.capture_query_plan(None, "SELECT 1", "q4")

    assert plan is None
    assert capture_time_ms >= 1000  # Should have waited at least timeout duration
    assert adapter.query_plans_captured == 0
    assert adapter.plan_capture_failures == 1
    assert adapter.plan_capture_errors[0]["reason"] == "timeout"
    assert "timed out" in adapter.plan_capture_errors[0]["message"]
    assert any("timed out" in record.message for record in caplog.records)


def test_plan_capture_completes_within_timeout() -> None:
    """Test that fast EXPLAIN queries complete within timeout."""

    class QuickParser:
        """Simple parser that returns a minimal plan."""

        platform_name = "test"

        def parse_explain_output(self, query_id: str, explain_output: str):
            from benchbox.core.results.query_plan_models import (
                LogicalOperator,
                LogicalOperatorType,
                QueryPlanDAG,
            )

            return QueryPlanDAG(
                query_id=query_id,
                platform="test",
                logical_root=LogicalOperator(
                    operator_type=LogicalOperatorType.SCAN,
                    operator_id="scan_1",
                ),
            )

    adapter = DummyAdapter(
        capture_plans=True,
        explain_output="EXPLAIN PLAN",
        explain_delay_seconds=0.1,  # Fast EXPLAIN
        plan_capture_timeout_seconds=5,  # 5 second timeout
        parser=QuickParser(),
    )

    plan, capture_time_ms = adapter.capture_query_plan(None, "SELECT 1", "q5")

    assert plan is not None
    assert capture_time_ms >= 100  # Should have at least the delay time
    assert adapter.query_plans_captured == 1
    assert adapter.plan_capture_failures == 0


def test_plan_capture_returns_zero_time_when_disabled() -> None:
    """Test that disabled capture returns None and 0.0 time."""
    adapter = DummyAdapter(capture_plans=False)

    plan, capture_time_ms = adapter.capture_query_plan(None, "SELECT 1", "q6")

    assert plan is None
    assert capture_time_ms == 0.0


def test_plan_query_filter_only_captures_specified_queries() -> None:
    """Test that plan_queries filter only captures specified queries."""

    class SimpleParser:
        """Simple parser that returns a minimal plan."""

        platform_name = "test"

        def parse_explain_output(self, query_id: str, explain_output: str):
            from benchbox.core.results.query_plan_models import (
                LogicalOperator,
                LogicalOperatorType,
                QueryPlanDAG,
            )

            return QueryPlanDAG(
                query_id=query_id,
                platform="test",
                logical_root=LogicalOperator(
                    operator_type=LogicalOperatorType.SCAN,
                    operator_id="scan_1",
                ),
            )

    adapter = DummyAdapter(
        capture_plans=True,
        explain_output="EXPLAIN PLAN",
        parser=SimpleParser(),
        plan_queries="q01,q02",
    )

    # q01 should be captured
    plan1, time1 = adapter.capture_query_plan(None, "SELECT 1", "q01")
    assert plan1 is not None

    # q03 should be skipped (not in filter)
    plan3, time3 = adapter.capture_query_plan(None, "SELECT 1", "q03")
    assert plan3 is None
    assert time3 == 0.0


def test_plan_first_n_only_captures_first_iterations() -> None:
    """Test that plan_first_n only captures first N iterations per query."""

    class SimpleParser:
        """Simple parser that returns a minimal plan."""

        platform_name = "test"

        def parse_explain_output(self, query_id: str, explain_output: str):
            from benchbox.core.results.query_plan_models import (
                LogicalOperator,
                LogicalOperatorType,
                QueryPlanDAG,
            )

            return QueryPlanDAG(
                query_id=query_id,
                platform="test",
                logical_root=LogicalOperator(
                    operator_type=LogicalOperatorType.SCAN,
                    operator_id="scan_1",
                ),
            )

    adapter = DummyAdapter(
        capture_plans=True,
        explain_output="EXPLAIN PLAN",
        parser=SimpleParser(),
        plan_first_n=2,
    )

    # First iteration - should capture
    plan1, _ = adapter.capture_query_plan(None, "SELECT 1", "q01")
    assert plan1 is not None

    # Second iteration - should capture
    plan2, _ = adapter.capture_query_plan(None, "SELECT 1", "q01")
    assert plan2 is not None

    # Third iteration - should skip
    plan3, time3 = adapter.capture_query_plan(None, "SELECT 1", "q01")
    assert plan3 is None
    assert time3 == 0.0

    # Different query, first iteration - should capture
    plan4, _ = adapter.capture_query_plan(None, "SELECT 1", "q02")
    assert plan4 is not None
