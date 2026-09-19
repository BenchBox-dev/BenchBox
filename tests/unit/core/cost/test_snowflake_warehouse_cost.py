"""Tests for Snowflake warehouse runtime cost estimation.

Snowflake's QUERY_HISTORY exposes only cloud-services credits, never
warehouse compute credits, so the cost model estimates warehouse credits from
measured execution time and the warehouse size's credits/hour rate. These tests
pin the estimation math, the explicit-credits precedence, the fallback
stamping, and the end-to-end normalized gate.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from benchbox.core.cost.calculator import CostCalculator, validate_resource_usage
from benchbox.core.cost.integration import add_cost_estimation_to_results
from benchbox.core.cost.models import QueryCost
from benchbox.core.cost.pricing import (
    resolve_snowflake_credit_price,
    resolve_snowflake_warehouse_credits_per_hour,
)
from benchbox.core.results.models import BenchmarkResults

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _config(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "edition": "standard",
        "cloud": "aws",
        "region": "us-east-1",
        "warehouse_size": "Medium",
    }
    base.update(overrides)
    return base


def _results(**overrides: object) -> BenchmarkResults:
    base: dict[str, object] = {
        "benchmark_name": "TPC-H",
        "platform": "Snowflake",
        "scale_factor": 0.1,
        "execution_id": "deadbeef",
        "timestamp": datetime(2026, 9, 17, 13, 48, 51),
        "duration_seconds": 160.76,
        "total_queries": 1,
        "successful_queries": 1,
        "failed_queries": 0,
    }
    base.update(overrides)
    return BenchmarkResults(**base)  # type: ignore[arg-type]


class TestSnowflakeWarehouseCreditsPerHour:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            ("X-Small", 1.0),
            ("Small", 2.0),
            ("Medium", 4.0),
            ("Large", 8.0),
            ("X-Large", 16.0),
            ("2X-Large", 32.0),
            ("3X-Large", 64.0),
            ("4X-Large", 128.0),
            ("5X-Large", 256.0),
            ("6X-Large", 512.0),
        ],
    )
    def test_all_documented_sizes_resolve(self, size: str, expected: float) -> None:
        resolution = resolve_snowflake_warehouse_credits_per_hour(size)
        assert resolution.value == expected
        assert resolution.fallback_used is False

    @pytest.mark.parametrize("size", ["MEDIUM", "medium", "XSMALL", "x-small", "  Large  ", "2x-large"])
    def test_label_variants_normalize(self, size: str) -> None:
        resolution = resolve_snowflake_warehouse_credits_per_hour(size)
        assert resolution.fallback_used is False
        assert resolution.value is not None

    def test_unknown_size_keeps_a_flagged_estimate(self) -> None:
        resolution = resolve_snowflake_warehouse_credits_per_hour("11X-Colossal")
        assert resolution.value == 4.0
        assert resolution.fallback_used is True
        assert resolution.reason is not None


class TestSnowflakeEstimation:
    def test_one_hour_on_medium_matches_four_metered_credits(self) -> None:
        """1 hour on Medium burns 4 credits; estimation must equal metering."""
        calculator = CostCalculator()
        estimated = calculator.calculate_query_cost("snowflake", {"execution_time_seconds": 3600.0}, _config())
        metered = calculator.calculate_query_cost("snowflake", {"credits_used": 4.0}, _config())
        assert isinstance(estimated, QueryCost)
        assert isinstance(metered, QueryCost)
        assert estimated.compute_cost == pytest.approx(metered.compute_cost)
        assert estimated.compute_cost == pytest.approx(
            4.0 * resolve_snowflake_credit_price("standard", "aws", "us-east-1").value
        )
        assert estimated.pricing_details["credits_used_estimated"] is True
        assert estimated.pricing_details["credits_per_hour"] == 4.0

    def test_explicit_credits_win_over_runtime(self) -> None:
        calculator = CostCalculator()
        cost = calculator.calculate_query_cost(
            "snowflake",
            {"credits_used": 0.5, "execution_time_seconds": 3600.0},
            _config(),
        )
        assert isinstance(cost, QueryCost)
        assert "credits_used_estimated" not in cost.pricing_details
        assert cost.compute_cost == pytest.approx(
            0.5 * resolve_snowflake_credit_price("standard", "aws", "us-east-1").value
        )

    def test_millisecond_timings_are_accepted(self) -> None:
        calculator = CostCalculator()
        from_ms = calculator.calculate_query_cost("snowflake", {"execution_time_ms": 3_600_000}, _config())
        from_elapsed = calculator.calculate_query_cost("snowflake", {"total_elapsed_time_ms": 3_600_000}, _config())
        assert isinstance(from_ms, QueryCost)
        assert isinstance(from_elapsed, QueryCost)
        assert from_ms.compute_cost == pytest.approx(from_elapsed.compute_cost)

    def test_seconds_beat_server_side_milliseconds(self) -> None:
        calculator = CostCalculator()
        cost = calculator.calculate_query_cost(
            "snowflake",
            {"execution_time_seconds": 60.0, "execution_time_ms": 3_600_000},
            _config(),
        )
        assert isinstance(cost, QueryCost)
        assert cost.pricing_details["execution_time_seconds"] == 60.0

    def test_per_query_size_overrides_config(self) -> None:
        calculator = CostCalculator()
        cost = calculator.calculate_query_cost(
            "snowflake",
            {"execution_time_seconds": 3600.0, "warehouse_size": "Large"},
            _config(warehouse_size="Medium"),
        )
        assert isinstance(cost, QueryCost)
        assert cost.pricing_details["warehouse_size"] == "Large"
        assert cost.pricing_details["credits_per_hour"] == 8.0

    def test_runtime_without_any_size_returns_none(self) -> None:
        """Runtime alone is not enough when neither usage nor config names a size."""
        resource_usage: dict[str, object] = {"execution_time_seconds": 60.0}
        config = _config()
        del config["warehouse_size"]
        assert CostCalculator().calculate_query_cost("snowflake", resource_usage, config) is None

    def test_config_size_backs_estimation(self) -> None:
        """A config-level size still yields a per-query estimate (never normalized)."""
        cost = CostCalculator().calculate_query_cost("snowflake", {"execution_time_seconds": 60.0}, _config())
        assert isinstance(cost, QueryCost)
        assert cost.pricing_details["credits_per_hour"] == 4.0

    @pytest.mark.parametrize(
        "resource_usage",
        [
            {},
            {"warehouse_size": "Medium"},
            {"execution_time_seconds": "sixty", "warehouse_size": "Medium"},
            {"credits_used_cloud_services": 0.01, "warehouse_size": "Medium"},
        ],
    )
    def test_no_estimable_signal_returns_none(self, resource_usage: dict[str, object]) -> None:
        """Cloud-services credits alone must never price as warehouse compute."""
        assert CostCalculator().calculate_query_cost("snowflake", resource_usage, _config()) is None

    def test_unknown_size_stamps_price_unavailable(self) -> None:
        calculator = CostCalculator()
        cost = calculator.calculate_query_cost(
            "snowflake",
            {"execution_time_seconds": 60.0, "warehouse_size": "11X-Colossal"},
            _config(),
        )
        assert isinstance(cost, QueryCost)
        marker = cost.pricing_details["price_unavailable"]
        assert marker["table"] == "snowflake_warehouse_credits_per_hour"


class TestSnowflakeNormalizedGate:
    def test_observed_run_with_edition_publishes(self) -> None:
        results = _results(
            platform_info={
                "platform_type": "snowflake",
                "edition": "standard",
                "cloud_provider": "aws",
                "region": "us-east-1",
            },
            platform_compute={
                "warehouse_size": "X-Small",
                "warehouse_state": "STARTED",
                "source": "observed",
                "collection_status": "available",
            },
            query_results=[
                {
                    "query_id": "Q1",
                    "execution_time_seconds": 60.0,
                    "resource_usage": {
                        "execution_time_seconds": 60.0,
                        "execution_time_ms": 60_000,
                        "total_elapsed_time_ms": 61_000,
                        "credits_used_cloud_services": 0.0,
                        "warehouse_size": "X-Small",
                    },
                }
            ],
        )
        add_cost_estimation_to_results(results)

        normalized = (results.cost_summary or {})["normalized_cost"]
        assert normalized["cost_status"] == "normalized"
        expected = (60.0 / 3600.0) * 1.0 * resolve_snowflake_credit_price("standard", "aws", "us-east-1").value
        assert float(normalized["normalized_cost_usd"]) == pytest.approx(expected)
        assert normalized["pricing_region"] == "us-east-1"
        assert normalized["deployment"]["warehouse_size"] == "X-Small"

    def test_missing_edition_stays_unavailable(self) -> None:
        """The edition is not service-observable; guessing it must not publish."""
        results = _results(
            platform_info={
                "platform_type": "snowflake",
                "cloud_provider": "aws",
                "region": "us-east-1",
            },
            platform_compute={
                "warehouse_size": "X-Small",
                "warehouse_state": "STARTED",
                "source": "observed",
                "collection_status": "available",
            },
            query_results=[
                {
                    "query_id": "Q1",
                    "resource_usage": {"execution_time_seconds": 60.0},
                }
            ],
        )
        add_cost_estimation_to_results(results)

        normalized = (results.cost_summary or {})["normalized_cost"]
        assert normalized["cost_status"] == "unavailable"
        assert normalized["normalized_cost_usd"] is None

    def test_cloud_services_credits_alone_stay_unavailable(self) -> None:
        """A live-shaped bundle with only cloud-services credits is not $0."""
        results = _results(
            platform_info={
                "platform_type": "snowflake",
                "edition": "standard",
                "cloud_provider": "aws",
                "region": "us-east-1",
            },
            platform_compute={
                "warehouse_size": "X-Small",
                "warehouse_state": "STARTED",
                "source": "observed",
                "collection_status": "available",
            },
            query_results=[
                {
                    "query_id": "Q1",
                    "resource_usage": {
                        "credits_used_cloud_services": 0.0,
                        "warehouse_size": "X-Small",
                    },
                }
            ],
        )
        add_cost_estimation_to_results(results)

        normalized = (results.cost_summary or {})["normalized_cost"]
        assert normalized["cost_status"] == "unavailable"
        assert normalized["normalized_cost_usd"] is None


class TestSnowflakeResourceValidation:
    def test_runtime_signals_satisfy_the_schema(self) -> None:
        valid, _ = validate_resource_usage("snowflake", {"execution_time_seconds": 60.0, "warehouse_size": "Medium"})
        assert valid

    def test_empty_usage_fails_the_schema(self) -> None:
        valid, warnings = validate_resource_usage("snowflake", {})
        assert not valid
        assert any("Missing at least one of" in warning for warning in warnings)
